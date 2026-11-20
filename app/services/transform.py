"""変換の実行: プロバイダー呼び出し → 結果の保存 → 履歴の記録。"""
import dataclasses
import logging
import sqlite3
import threading
from dataclasses import dataclass
from pathlib import Path
from typing import Optional

from app.errors import AppError, BusyError, InvalidReferenceError, ProviderNotConfiguredError
from app.providers.base import Provider, TransformResult
from app.repositories import images as image_repo
from app.repositories import prompts as prompt_repo
from app.repositories import transforms as transform_repo
from app.repositories.transforms import NewTransform
from app.services.images import ImageStore

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class TransformRequest:
    """変換 1 回分の依頼。prompt_id は保存済みプロンプトを使ったときだけ入る。"""

    input_image_id: int
    prompt_title: str
    prompt_body: str
    provider: str
    prompt_id: Optional[int] = None
    # False なら、出力の縦横比を指定せずプロバイダーに任せる
    keep_aspect: bool = True


class TransformService:
    """変換を実行する。同時に動かすのは 1 件だけ。"""

    def __init__(self, store: ImageStore, providers: dict[str, Provider]) -> None:
        self._store = store
        self._providers = providers
        # ボタンの連打や複数タブからの実行で、意図しない課金が重ならないようにする
        self._lock = threading.Lock()

    def is_busy(self) -> bool:
        """変換を実行中かどうか（窓を閉じる前の確認に使う）。"""
        return self._lock.locked()

    def run(self, conn: sqlite3.Connection, request: TransformRequest) -> dict:
        """変換を 1 回実行し、記録した履歴の行を返す。成功・失敗とも履歴に残す。

        入力の誤り（画像がない、API キー未設定など）は API を呼ぶ前に例外で返し、履歴には残さない。
        """
        image = image_repo.get_image(conn, request.input_image_id)
        input_path = self._store.file_of(image)
        provider = self._provider(request.provider)
        if request.prompt_id is not None:
            prompt_repo.get_prompt(conn, request.prompt_id)

        if not self._lock.acquire(blocking=False):
            raise BusyError("別の変換を実行中です。終わってからもう一度実行してください。")
        try:
            result = self._call(provider, input_path, request.prompt_body, request.keep_aspect)
            output_image_id, result = self._save_output(conn, result)
            return self._write_history(conn, self._record(request, result, output_image_id))
        finally:
            self._lock.release()

    @staticmethod
    def _write_history(conn: sqlite3.Connection, record: NewTransform) -> dict:
        """履歴を書く。変換の実行中にプロンプトが削除されていた場合も、履歴と料金は必ず残す。"""
        try:
            return transform_repo.create_transform(conn, record)
        except sqlite3.IntegrityError:
            # 実行中（1〜2 分）に、使ったプロンプトが削除されると、参照先がなくなり書き込めない。
            # プロンプトとの結び付きだけを外して書き直す（タイトルと本文は履歴に残る）。
            if record.prompt_id is None:
                raise
            return transform_repo.create_transform(conn, dataclasses.replace(record, prompt_id=None))

    def _provider(self, name: str) -> Provider:
        provider = self._providers.get(name)
        if provider is None:
            raise InvalidReferenceError(f"プロバイダー「{name}」は使えません。")
        if not provider.is_configured():
            raise ProviderNotConfiguredError(
                f"{provider.label} の API キーが設定されていません。設定タブで登録してください。"
            )
        return provider

    @staticmethod
    def _call(provider: Provider, input_path: Path, prompt: str, keep_aspect: bool) -> TransformResult:
        """プロバイダーを 1 回呼ぶ。想定外の例外も失敗の結果に変え、履歴に残せるようにする。"""
        try:
            return provider.transform(input_path, prompt, keep_aspect)
        except Exception as exc:  # noqa: BLE001 - プロバイダー実装の不具合で履歴が欠けるのを防ぐ
            # 例外の本文は API キーや接続先を含みうるため、ログにも種類の名前だけを残す
            logger.error("provider %s raised %s", provider.name, type(exc).__name__)
            message = f"変換中に想定外のエラーが発生しました（{type(exc).__name__}）。課金されている可能性があります。"
            return TransformResult(model=provider.model, error=message, billed_on_failure=True)

    def _save_output(self, conn: sqlite3.Connection, result: TransformResult) -> tuple[Optional[int], TransformResult]:
        """成功した結果の画像を保存する。保存できなければ失敗の結果に差し替える（料金は残す）。"""
        if not result.ok:
            return None, result
        try:
            image = self._store.add(conn, image_repo.KIND_RESULT, result.image_bytes)
        except AppError as exc:
            message = f"変換結果を画像として保存できませんでした: {exc.message}"
        except Exception as exc:  # noqa: BLE001 - 課金済みの変換が履歴から欠けるのを防ぐ
            # ディスクの空き不足や書き込み権限などで保存できなかった場合
            logger.error("saving result failed: %s", type(exc).__name__)
            message = f"変換結果を保存できませんでした（{type(exc).__name__}）。ディスクの空き容量を確認してください。"
        else:
            return image["id"], result
        failed = dataclasses.replace(result, image_bytes=None, error=message, billed_on_failure=True)
        return None, failed

    @staticmethod
    def _record(request: TransformRequest, result: TransformResult, output_image_id: Optional[int]) -> NewTransform:
        status = transform_repo.STATUS_SUCCESS if result.ok else transform_repo.STATUS_FAILED
        return NewTransform(
            input_image_id=request.input_image_id,
            output_image_id=output_image_id,
            prompt_id=request.prompt_id,
            prompt_title=request.prompt_title,
            prompt_body=request.prompt_body,
            provider=request.provider,
            model=result.model,
            status=status,
            error_message=result.error,
            cost_usd=result.cost_usd,
        )
