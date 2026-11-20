"""Gemini の generateContent（画像 + テキスト入力、画像出力）を呼ぶプロバイダー。

API キーは環境変数から読み、ログ・エラー文・履歴のどこにも出さない。
Gemini は、出力が安全フィルターで止められた場合（IMAGE_SAFETY 等）でも課金される。
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

_IMAGE_MODALITY = "IMAGE"
_FINISH_NORMAL = "STOP"


def aspect_ratio(width: int, height: int) -> str:
    """元画像の幅と高さにいちばん近い、指定できる縦横比を返す（例: "2:3"）。画像の中身は見ない。"""
    return common.nearest_aspect_ratio(width, height, config.GEMINI_ASPECT_RATIOS)


def _prices(model: str) -> dict:
    return config.GEMINI_PRICES.get(model, config.GEMINI_PRICES[config.GEMINI_UNKNOWN_MODEL_PRICE_KEY])


def image_price_usd(model: str) -> float:
    """出力画像 1 枚の料金（USD）。"""
    prices = _prices(model)
    return prices["image_tokens"] * prices["image_output"] / config.TOKENS_PER_PRICE_UNIT


def usage_cost_usd(model: str, usage: Optional[dict]) -> float:
    """応答のトークン使用量から概算料金（USD）を計算する。使用量がなければ画像 1 枚分の料金を返す。"""
    if not usage:
        return image_price_usd(model)
    prices = _prices(model)
    output = usage.get("candidatesTokenCount") or 0
    details = usage.get("candidatesTokensDetails")
    if isinstance(details, list):
        image_out = sum(
            item.get("tokenCount") or 0
            for item in details
            if isinstance(item, dict) and item.get("modality") == _IMAGE_MODALITY
        )
    else:
        # 内訳がない場合は、出力をすべて単価の高い画像トークンとみなす（少なく見積もらないため）
        image_out = output
    text_out = max(output - image_out, 0) + (usage.get("thoughtsTokenCount") or 0)
    total = (
        (usage.get("promptTokenCount") or 0) * prices["input"]
        + image_out * prices["image_output"]
        + text_out * prices["text_output"]
    )
    return total / config.TOKENS_PER_PRICE_UNIT


def _first_candidate(body: dict) -> dict:
    candidates = body.get("candidates") or []
    return candidates[0] if candidates and isinstance(candidates[0], dict) else {}


def _encoded_image(candidate: dict) -> Optional[str]:
    """応答の中から、画像のデータ（base64）を探す。なければ None。"""
    content = candidate.get("content")
    parts = content.get("parts") if isinstance(content, dict) else None
    for part in parts or []:
        if not isinstance(part, dict):
            continue
        # REST の応答は inlineData。念のため inline_data の表記にも対応する
        inline = part.get("inlineData") or part.get("inline_data")
        if isinstance(inline, dict) and inline.get("data"):
            return inline["data"]
    return None


class GeminiProvider(Provider):
    """Google Gemini の画像モデルによる画像変換。"""

    name = "gemini"
    label = "Gemini"
    api_key_env = config.GEMINI_API_KEY_ENV

    def __init__(self, transport: Optional[httpx.BaseTransport] = None) -> None:
        # transport はテストで通信を差し替えるためのもの。通常は None（実際に通信する）。
        self._transport = transport

    @property
    def model(self) -> str:
        return os.environ.get(config.GEMINI_MODEL_ENV, "").strip() or config.GEMINI_IMAGE_MODEL

    def _api_key(self) -> str:
        return os.environ.get(self.api_key_env, "").strip()

    def is_configured(self) -> bool:
        return bool(self._api_key())

    def transform(self, image_path: Path, prompt: str, keep_aspect: bool = True) -> TransformResult:
        model = self.model
        response = common.send_once(
            self.label, model, config.GEMINI_TIMEOUT_SEC,
            lambda: self._post(image_path, prompt, model, keep_aspect),
        )
        if isinstance(response, TransformResult):
            return response
        if response.status_code != common.HTTP_OK:
            message = common.http_error_message(self.label, response.status_code, response.text)
            return TransformResult(model=model, error=message)
        return common.parse_billed(
            self.label, model, image_price_usd(model), lambda: self._parse_success(response, model)
        )

    def _post(self, image_path: Path, prompt: str, model: str, keep_aspect: bool) -> httpx.Response:
        """generateContent を 1 回だけ呼ぶ。再試行はしない。"""
        encoded = base64.b64encode(image_path.read_bytes()).decode("ascii")
        image_config = {"imageSize": config.GEMINI_IMAGE_SIZE}
        if keep_aspect:
            image_config["aspectRatio"] = aspect_ratio(*common.displayed_size(image_path))
        payload = {
            "contents": [{
                "parts": [
                    {"text": prompt},
                    {"inline_data": {"mime_type": common.mime_of(image_path), "data": encoded}},
                ],
            }],
            "generationConfig": {
                "responseModalities": ["TEXT", "IMAGE"],
                "imageConfig": image_config,
            },
        }
        # キーは URL ではなくヘッダーで送る（URL は通信の記録に残りやすいため）
        headers = {"x-goog-api-key": self._api_key()}
        url = f"{config.GEMINI_API_BASE}/models/{model}:generateContent"
        with httpx.Client(transport=self._transport, timeout=config.GEMINI_TIMEOUT_SEC) as client:
            return client.post(url, json=payload, headers=headers)

    @staticmethod
    def _parse_success(response: httpx.Response, model: str) -> TransformResult:
        """HTTP 200 の応答から画像と料金を取り出す。"""
        try:
            body = response.json()
        except ValueError:
            body = None
        if not isinstance(body, dict):
            return common.billed_failure(model, image_price_usd(model), "Gemini の応答を読み取れませんでした。")
        usage = body.get("usageMetadata")
        usage = usage if isinstance(usage, dict) else None

        feedback = body.get("promptFeedback")
        block_reason = feedback.get("blockReason") if isinstance(feedback, dict) else None
        if block_reason:
            # 入力の段階で止められた場合。画像は作られていないので、使用量が返っていればその分だけを記録する
            cost = usage_cost_usd(model, usage) if usage else 0.0
            message = f"Gemini が入力を受け付けませんでした（{block_reason}）。"
            return TransformResult(model=model, cost_usd=cost, error=message, billed_on_failure=cost > 0)

        candidate = _first_candidate(body)
        encoded = _encoded_image(candidate)
        if not encoded:
            # 出力が安全フィルター等で止められた場合。画像がなくても 1 枚分は課金されるものとして記録する
            cost = max(usage_cost_usd(model, usage), image_price_usd(model))
            reason = candidate.get("finishReason")
            if reason and reason != _FINISH_NORMAL:
                message = f"Gemini が画像を返しませんでした（{reason}）。画像がなくても課金されます。"
            else:
                message = "Gemini の応答に画像が含まれていませんでした。課金されている可能性があります。"
            return common.billed_failure(model, cost, message)
        cost = usage_cost_usd(model, usage)
        try:
            image_bytes = base64.b64decode(encoded)
        except (binascii.Error, ValueError):
            return common.billed_failure(model, cost, "Gemini から受け取った画像データを復元できませんでした。")
        return TransformResult(model=model, image_bytes=image_bytes, cost_usd=cost)
