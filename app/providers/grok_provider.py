"""Grok（xAI）の画像編集 API（/v1/images/edits）を呼ぶプロバイダー。

API キーは環境変数から読み、ログ・エラー文・履歴のどこにも出さない。
"""
import base64
import binascii
import os
from pathlib import Path
from typing import Optional

import httpx

from app import config
from app.providers import common
from app.providers.base import Provider, TransformResult

# 応答ごとに、出力 1 枚と入力画像 1 枚の料金がかかる（入力の単価は仮の値。config を参照）
_COST_PER_CALL_USD = config.XAI_OUTPUT_PRICE_USD + config.XAI_INPUT_PRICE_USD


def aspect_ratio(width: int, height: int) -> str:
    """元画像の幅と高さにいちばん近い、指定できる縦横比を返す（例: "9:16"）。画像の中身は見ない。"""
    return common.nearest_aspect_ratio(width, height, config.XAI_ASPECT_RATIOS)


class GrokProvider(Provider):
    """xAI Grok Imagine による画像変換。"""

    name = "grok"
    label = "Grok"
    api_key_env = config.XAI_API_KEY_ENV

    def __init__(self, transport: Optional[httpx.BaseTransport] = None) -> None:
        # transport はテストで通信を差し替えるためのもの。通常は None（実際に通信する）。
        self._transport = transport

    @property
    def model(self) -> str:
        return os.environ.get(config.XAI_MODEL_ENV, "").strip() or config.XAI_IMAGE_MODEL

    def _api_key(self) -> str:
        return os.environ.get(self.api_key_env, "").strip()

    def is_configured(self) -> bool:
        return bool(self._api_key())

    def transform(self, image_path: Path, prompt: str, keep_aspect: bool = True) -> TransformResult:
        model = self.model
        response = common.send_once(
            self.label, model, config.XAI_TIMEOUT_SEC,
            lambda: self._post(image_path, prompt, model, keep_aspect),
        )
        if isinstance(response, TransformResult):
            return response
        if response.status_code != common.HTTP_OK:
            message = common.http_error_message(self.label, response.status_code, response.text)
            return TransformResult(model=model, error=message)
        return common.parse_billed(
            self.label, model, _COST_PER_CALL_USD, lambda: self._parse_success(response, model)
        )

    def _post(self, image_path: Path, prompt: str, model: str, keep_aspect: bool) -> httpx.Response:
        """画像編集 API を 1 回だけ呼ぶ。再試行はしない。"""
        encoded = base64.b64encode(image_path.read_bytes()).decode("ascii")
        payload = {
            "model": model,
            "prompt": prompt,
            "image": {"url": f"data:{common.mime_of(image_path)};base64,{encoded}", "type": "image_url"},
            "n": 1,
            "response_format": "b64_json",
            "resolution": config.XAI_IMAGE_RESOLUTION,
        }
        if keep_aspect:
            payload["aspect_ratio"] = aspect_ratio(*common.displayed_size(image_path))
        headers = {"Authorization": f"Bearer {self._api_key()}"}
        with httpx.Client(transport=self._transport, timeout=config.XAI_TIMEOUT_SEC) as client:
            return client.post(f"{config.XAI_API_BASE}/images/edits", json=payload, headers=headers)

    @staticmethod
    def _parse_success(response: httpx.Response, model: str) -> TransformResult:
        """HTTP 200 の応答から画像を取り出す。200 が返った時点で課金されているとみなす。"""
        try:
            body = response.json()
        except ValueError:
            body = None
        if not isinstance(body, dict):
            return common.billed_failure(model, _COST_PER_CALL_USD, "Grok の応答を読み取れませんでした。")
        data = body.get("data") or []
        item = data[0] if data and isinstance(data[0], dict) else {}
        # 内容の審査に通らなかった場合、画像の代わりにこの印が付いて返る
        if item.get("respect_moderation") is False:
            return common.billed_failure(model, _COST_PER_CALL_USD, "Grok のコンテンツポリシーにより拒否されました。")
        encoded = item.get("b64_json")
        if not encoded:
            return common.billed_failure(model, _COST_PER_CALL_USD, "Grok の応答に画像が含まれていませんでした。")
        try:
            image_bytes = base64.b64decode(encoded)
        except (binascii.Error, ValueError):
            message = "Grok から受け取った画像データを復元できませんでした。"
            return common.billed_failure(model, _COST_PER_CALL_USD, message)
        return TransformResult(model=model, image_bytes=image_bytes, cost_usd=_COST_PER_CALL_USD)
