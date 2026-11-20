"""各プロバイダーで共通に使う道具（通信の失敗の扱い、エラー文、元画像の向き）。

API キーはログ・エラー文・履歴のどこにも出さない。
"""
import json
import math
from pathlib import Path
from typing import Callable, Union

import httpx
from PIL import Image

from app import config
from app.providers.base import TransformResult

HTTP_OK = 200
_HTTP_UNAUTHORIZED = 401
_HTTP_TOO_MANY_REQUESTS = 429

_MIME_BY_SUFFIX = {".png": "image/png", ".jpg": "image/jpeg", ".jpeg": "image/jpeg", ".webp": "image/webp"}
_DEFAULT_MIME = "image/png"
# EXIF の「向き」の項目番号と、そのうち 90 度または 270 度回して表示する値
_EXIF_ORIENTATION_TAG = 0x0112
_EXIF_ROTATED_ORIENTATIONS = frozenset({5, 6, 7, 8})
# コンテンツポリシーによる拒否と判断する、エラー文中のキーワード
_BLOCK_KEYWORDS = ("moderation", "content policy", "content_policy", "safety", "violat", "not allowed", "prohibited")
# API キーの誤りと判断する、エラー文中のキーワード（401 以外で返すプロバイダーがあるため）
_BAD_KEY_KEYWORDS = ("api key not valid", "api_key_invalid", "incorrect api key", "invalid api key")


def mime_of(image_path: Path) -> str:
    """保存時に付けた拡張子から、送信時の画像の種類を決める。"""
    return _MIME_BY_SUFFIX.get(image_path.suffix.lower(), _DEFAULT_MIME)


def displayed_size(image_path: Path) -> tuple[int, int]:
    """画面に表示されるときの幅と高さを返す。

    スマホの写真などは、横向きに記録した画素に「90 度回して表示する」という情報を付けていることがある。
    その場合は見た目の向きに合わせて幅と高さを入れ替える。
    """
    with Image.open(image_path) as image:
        width, height = image.size
        orientation = image.getexif().get(_EXIF_ORIENTATION_TAG)
    if orientation in _EXIF_ROTATED_ORIENTATIONS:
        return height, width
    return width, height


def nearest_aspect_ratio(width: int, height: int, ratios: tuple[tuple[int, int], ...]) -> str:
    """幅と高さにいちばん近い縦横比を、候補の中から選んで返す（例: "2:3"）。画像の中身は見ない。

    近さは比の対数で測る（2:1 と 1:2 が、1:1 から同じだけ離れているとみなすため）。
    """
    target = math.log(width / height)
    best = min(ratios, key=lambda ratio: abs(math.log(ratio[0] / ratio[1]) - target))
    return f"{best[0]}:{best[1]}"


def send_once(
    label: str, model: str, timeout_sec: int, send: Callable[[], httpx.Response]
) -> Union[httpx.Response, TransformResult]:
    """API を 1 回だけ呼ぶ。通信できなかった場合は、失敗の結果を返す。再試行はしない。"""
    try:
        return send()
    except httpx.TimeoutException:
        message = (
            f"{label} の応答が {timeout_sec} 秒以内に返りませんでした。"
            "処理が進んでいた場合は課金されている可能性があります。"
        )
        return TransformResult(model=model, error=message, billed_on_failure=True)
    except httpx.HTTPError as exc:
        # 例外の本文には接続先などが含まれうるため、種類の名前だけを出す
        return TransformResult(model=model, error=f"{label} に接続できませんでした（{type(exc).__name__}）。")
    except OSError:
        # 元画像のファイルを読めなかった場合。API は呼んでいないので課金はない
        return TransformResult(model=model, error="元画像のファイルを読み込めませんでした。")


def error_detail(body_text: str) -> str:
    """エラー応答からコードとメッセージを取り出す。JSON でなければ本文の先頭を使う。"""
    try:
        body = json.loads(body_text)
    except ValueError:
        return body_text.strip()
    error = body.get("error", body) if isinstance(body, dict) else body
    if not isinstance(error, dict):
        return str(error)
    code = error.get("code") or ""
    message = error.get("message") or ""
    return f"{code}: {message}" if code and message else str(code or message)


def http_error_message(label: str, status: int, body_text: str) -> str:
    """HTTP エラーを利用者向けの文にする。"""
    detail = error_detail(body_text)[: config.PROVIDER_ERROR_MAX_LENGTH]
    lowered = detail.lower()
    if status == _HTTP_UNAUTHORIZED or any(keyword in lowered for keyword in _BAD_KEY_KEYWORDS):
        return f"{label} の API キーが正しくありません。設定タブで登録し直してください。"
    if status == _HTTP_TOO_MANY_REQUESTS:
        return f"{label} の利用上限に達したか、残高が不足しています（HTTP 429）: {detail}"
    if any(keyword in lowered for keyword in _BLOCK_KEYWORDS):
        return f"{label} のコンテンツポリシーにより拒否されました: {detail}"
    return f"{label} がエラーを返しました（HTTP {status}）: {detail}"


def parse_billed(
    label: str, model: str, fallback_cost_usd: float, parse: Callable[[], TransformResult]
) -> TransformResult:
    """HTTP 200 の応答を読み取る。想定外の形で読み取りに失敗しても、課金済みとして料金を残す。"""
    try:
        return parse()
    except Exception:  # noqa: BLE001 - 応答の形が変わっても、課金済みの呼び出しを料金 0 で記録しない
        return billed_failure(model, fallback_cost_usd, f"{label} の応答を読み取れませんでした。")


def billed_failure(model: str, cost_usd: float, message: str) -> TransformResult:
    """応答は返ったが画像を受け取れなかった場合の結果。課金されているとみなし、料金を残す。"""
    return TransformResult(model=model, cost_usd=cost_usd, error=message, billed_on_failure=True)
