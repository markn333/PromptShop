"""作風の読み取りの実行と履歴の記録。

1 回の操作につき API の呼び出しは 1 回。自動の再試行はしない。
"""
import logging
import sqlite3
import threading
from dataclasses import dataclass
from pathlib import Path

from app import config
from app.analyzers.base import AnalysisResult, Analyzer
from app.errors import BusyError, InvalidReferenceError, ProviderNotConfiguredError
from app.repositories import analyses as analysis_repo
from app.repositories import images as image_repo
from app.repositories.analyses import NewAnalysis
from app.services.images import ImageStore

logger = logging.getLogger(__name__)

# AI が指示に反して付けることがある飾り（見出しの記号、引用符、「タイトル:」など）
_TITLE_PREFIXES = ("タイトル:", "タイトル：", "title:", "name:", "名前:", "名前：")
_TITLE_STRIP_CHARS = " \t#*\"'「」『』`"
_CODE_FENCE = "```"


@dataclass(frozen=True)
class AnalysisRequest:
    """読み取り 1 回分の依頼。"""

    image_id: int
    provider: str
    language: str


def split_draft(text: str) -> tuple[str, str]:
    """AI が書いた文章を、タイトル（1 行目）と本文（残り）に分ける。長すぎる分は切り詰める。

    1 行しかない場合は、タイトルなしの本文として扱う。
    """
    lines = [line for line in text.strip().splitlines() if line.strip() != _CODE_FENCE]
    while lines and not lines[0].strip():
        lines.pop(0)
    if not lines:
        return "", ""
    rest = "\n".join(lines[1:]).strip()
    if not rest:
        return "", lines[0].strip()[: config.PROMPT_BODY_MAX_LENGTH]
    title = lines[0].strip(_TITLE_STRIP_CHARS)
    for prefix in _TITLE_PREFIXES:
        if title.lower().startswith(prefix):
            title = title[len(prefix):].strip(_TITLE_STRIP_CHARS)
            break
    return title[: config.PROMPT_TITLE_MAX_LENGTH], rest[: config.PROMPT_BODY_MAX_LENGTH]


class AnalysisService:
    """作風の読み取りを実行する。同時に動かすのは 1 件だけ。"""

    def __init__(self, store: ImageStore, analyzers: dict[str, Analyzer]) -> None:
        self._store = store
        self._analyzers = analyzers
        # ボタンの連打や複数タブからの実行で、意図しない課金が重ならないようにする
        self._lock = threading.Lock()

    def is_busy(self) -> bool:
        """読み取りを実行中かどうか（窓を閉じる前の確認に使う）。"""
        return self._lock.locked()

    def run(self, conn: sqlite3.Connection, request: AnalysisRequest) -> dict:
        """読み取りを 1 回実行し、記録した履歴の行を返す。成功・失敗とも履歴に残す。

        入力の誤り（画像がない、API キー未設定など）は API を呼ぶ前に例外で返し、履歴には残さない。
        """
        image = image_repo.get_image(conn, request.image_id)
        image_path = self._store.file_of(image)
        analyzer = self._analyzer(request.provider)

        if not self._lock.acquire(blocking=False):
            raise BusyError("別の読み取りを実行中です。終わってからもう一度実行してください。")
        try:
            result = self._call(analyzer, image_path, request.language)
            return analysis_repo.create_analysis(conn, self._record(request, result))
        finally:
            self._lock.release()

    def _analyzer(self, name: str) -> Analyzer:
        analyzer = self._analyzers.get(name)
        if analyzer is None:
            raise InvalidReferenceError(f"プロバイダー「{name}」は使えません。")
        if not analyzer.is_configured():
            raise ProviderNotConfiguredError(
                f"{analyzer.label} の API キーが設定されていません。設定タブで登録してください。"
            )
        return analyzer

    @staticmethod
    def _call(analyzer: Analyzer, image_path: Path, language: str) -> AnalysisResult:
        """読み取りを 1 回呼ぶ。想定外の例外も失敗の結果に変え、履歴に残せるようにする。"""
        try:
            return analyzer.analyze(image_path, language)
        except Exception as exc:  # noqa: BLE001 - 実装の不具合で履歴が欠けるのを防ぐ
            # 例外の本文は API キーや接続先を含みうるため、ログにも種類の名前だけを残す
            logger.error("analyzer %s raised %s", analyzer.name, type(exc).__name__)
            message = f"読み取り中に想定外のエラーが発生しました（{type(exc).__name__}）。課金されている可能性があります。"
            return AnalysisResult(model=analyzer.model, error=message, billed_on_failure=True)

    @staticmethod
    def _record(request: AnalysisRequest, result: AnalysisResult) -> NewAnalysis:
        title, body = split_draft(result.text) if result.ok else ("", "")
        error = result.error
        if result.ok and not body:
            error = "AI の応答から本文を取り出せませんでした。料金はかかっています。"
        succeeded = error is None
        return NewAnalysis(
            image_id=request.image_id,
            provider=request.provider,
            model=result.model,
            language=request.language,
            status=analysis_repo.STATUS_SUCCESS if succeeded else analysis_repo.STATUS_FAILED,
            error_message=error,
            title=title if succeeded else None,
            body=body if succeeded else None,
            cost_usd=result.cost_usd,
        )
