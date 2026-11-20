"""OpenAI の画像編集 API（/v1/images/edits）を呼ぶプロバイダー。

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


def usage_cost_usd(usage: Optional[dict]) -> float:
    """応答のトークン使用量から概算料金（USD）を計算する。使用量がなければ 1 枚あたりの概算を返す。"""
    if not usage:
        return config.OPENAI_FALLBACK_COST_USD
    rates = config.OPENAI_TOKEN_PRICE_PER_M
    details = usage.get("input_tokens_details") or {}
    text_in = details.get("text_tokens")
    image_in = details.get("image_tokens")
    if text_in is None and image_in is None:
        # 内訳がない場合は、入力をすべて単価の高い画像トークンとみなす（少なく見積もらないため）
        text_in, image_in = 0, usage.get("input_tokens", 0)
    output = usage.get("output_tokens", 0)
    total = (
        (text_in or 0) * rates["text_input"]
        + (image_in or 0) * rates["image_input"]
        + (output or 0) * rates["image_output"]
    )
    return total / config.TOKENS_PER_PRICE_UNIT


def output_size(width: int, height: int) -> str:
    """元画像の幅と高さから、向きの合う出力サイズを選ぶ。画像の中身は見ない。"""
    ratio = width / height
    if ratio >= config.OPENAI_LANDSCAPE_MIN_RATIO:
        return config.OPENAI_SIZE_LANDSCAPE
    if ratio <= 1 / config.OPENAI_LANDSCAPE_MIN_RATIO:
        return config.OPENAI_SIZE_PORTRAIT
    return config.OPENAI_SIZE_SQUARE


class OpenAIProvider(Provider):
    """OpenAI GPT Image による画像変換。"""

    name = "openai"
    label = "OpenAI"
    api_key_env = config.OPENAI_API_KEY_ENV

    def __init__(self, transport: Optional[httpx.BaseTransport] = None) -> None:
        # transport はテストで通信を差し替えるためのもの。通常は None（実際に通信する）。
        self._transport = transport

    @property
    def model(self) -> str:
        return os.environ.get(config.OPENAI_MODEL_ENV, "").strip() or config.OPENAI_IMAGE_MODEL

    def _api_key(self) -> str:
        return os.environ.get(self.api_key_env, "").strip()

    def is_configured(self) -> bool:
        return bool(self._api_key())

    def transform(self, image_path: Path, prompt: str, keep_aspect: bool = True) -> TransformResult:
        model = self.model
        response = common.send_once(
            self.label, model, config.OPENAI_TIMEOUT_SEC,
            lambda: self._post(image_path, prompt, model, keep_aspect),
        )
        if isinstance(response, TransformResult):
            return response
        if response.status_code != common.HTTP_OK:
            message = common.http_error_message(self.label, response.status_code, response.text)
            return TransformResult(model=model, error=message)
        return common.parse_billed(
            self.label, model, config.OPENAI_FALLBACK_COST_USD, lambda: self._parse_success(response, model)
        )

    def _post(self, image_path: Path, prompt: str, model: str, keep_aspect: bool) -> httpx.Response:
        """画像編集 API を 1 回だけ呼ぶ。再試行はしない。"""
        mime = common.mime_of(image_path)
        fields = {
            "model": model,
            "prompt": prompt,
            "n": "1",
            "quality": config.OPENAI_IMAGE_QUALITY,
            "size": output_size(*common.displayed_size(image_path)) if keep_aspect else config.OPENAI_SIZE_AUTO,
            "output_format": config.OPENAI_OUTPUT_FORMAT,
        }
        files = {"image": (image_path.name, image_path.read_bytes(), mime)}
        headers = {"Authorization": f"Bearer {self._api_key()}"}
        with httpx.Client(transport=self._transport, timeout=config.OPENAI_TIMEOUT_SEC) as client:
            return client.post(f"{config.OPENAI_API_BASE}/images/edits", data=fields, files=files, headers=headers)

    @staticmethod
    def _parse_success(response: httpx.Response, model: str) -> TransformResult:
        """HTTP 200 の応答から画像と料金を取り出す。200 が返った時点で課金されているとみなす。"""
        try:
            body = response.json()
        except ValueError:
            body = None
        if not isinstance(body, dict):
            return common.billed_failure(model, config.OPENAI_FALLBACK_COST_USD, "OpenAI の応答を読み取れませんでした。")
        cost = usage_cost_usd(body.get("usage"))
        data = body.get("data") or []
        encoded = data[0].get("b64_json") if data and isinstance(data[0], dict) else None
        if not encoded:
            return common.billed_failure(model, cost, "OpenAI の応答に画像が含まれていませんでした。")
        try:
            image_bytes = base64.b64decode(encoded)
        except (binascii.Error, ValueError):
            return common.billed_failure(model, cost, "OpenAI から受け取った画像データを復元できませんでした。")
        return TransformResult(model=model, image_bytes=image_bytes, cost_usd=cost)
