"""Gemini の generateContent（画像 + テキスト入力、テキスト出力）で、画像の作風を読み取る。"""
import base64
from pathlib import Path
from typing import Optional

import httpx

from app import config
from app.analyzers import common
from app.analyzers.base import AnalysisResult, Analyzer


def _text_of(body: dict) -> str:
    """応答から、AI が書いた文章を取り出す（考える途中のメモは除く）。なければ空文字。"""
    candidates = body.get("candidates") or []
    candidate = candidates[0] if candidates and isinstance(candidates[0], dict) else {}
    content = candidate.get("content")
    parts = content.get("parts") if isinstance(content, dict) else None
    texts = [
        part["text"] for part in parts or []
        if isinstance(part, dict) and part.get("text") and not part.get("thought")
    ]
    return "\n".join(texts).strip()


class GeminiAnalyzer(Analyzer):
    """Google Gemini の文章モデル（画像入力つき）による作風の読み取り。"""

    name = "gemini"
    label = "Gemini"
    api_key_env = config.GEMINI_API_KEY_ENV
    model_env = config.GEMINI_TEXT_MODEL_ENV
    default_model = config.GEMINI_TEXT_MODEL

    def __init__(self, transport: Optional[httpx.BaseTransport] = None) -> None:
        # transport はテストで通信を差し替えるためのもの。通常は None（実際に通信する）。
        self._transport = transport

    def _prices(self, model: str) -> dict:
        return common.prices_of(config.GEMINI_TEXT_PRICES, model, config.GEMINI_TEXT_UNKNOWN_PRICE_KEY)

    def analyze(self, image_path: Path, language: str) -> AnalysisResult:
        model = self.model
        response = common.send_once(self.label, model, lambda: self._post(image_path, language, model))
        if isinstance(response, AnalysisResult):
            return response
        if response.status_code != common.HTTP_OK:
            return common.http_failure(self.label, model, response)
        fallback = common.fallback_cost_usd(self._prices(model))
        return common.parse_billed(self.label, model, fallback, lambda: self._parse(response, model, fallback))

    def _post(self, image_path: Path, language: str, model: str) -> httpx.Response:
        """generateContent を 1 回だけ呼ぶ。再試行はしない。"""
        encoded = base64.b64encode(common.prepared_image(image_path)).decode("ascii")
        payload = {
            "contents": [{
                "parts": [
                    {"text": common.instruction(language)},
                    {"inline_data": {"mime_type": common.JPEG_MIME, "data": encoded}},
                ],
            }],
            "generationConfig": {"maxOutputTokens": config.ANALYSIS_MAX_OUTPUT_TOKENS},
        }
        # キーは URL ではなくヘッダーで送る（URL は通信の記録に残りやすいため）
        headers = {"x-goog-api-key": self._api_key()}
        url = f"{config.GEMINI_API_BASE}/models/{model}:generateContent"
        with httpx.Client(transport=self._transport, timeout=config.ANALYSIS_TIMEOUT_SEC) as client:
            return client.post(url, json=payload, headers=headers)

    def _parse(self, response: httpx.Response, model: str, fallback: float) -> AnalysisResult:
        """HTTP 200 の応答から文章と料金を取り出す。"""
        body = common.json_body(response)
        if body is None:
            return common.billed_failure(model, fallback, "Gemini の応答を読み取れませんでした。")
        usage = body.get("usageMetadata")
        cost: Optional[float] = None
        if isinstance(usage, dict):
            # 出力の料金には、考える途中で使った分（thoughts）も含まれる
            output = (usage.get("candidatesTokenCount") or 0) + (usage.get("thoughtsTokenCount") or 0)
            cost = common.token_cost_usd(usage.get("promptTokenCount"), output, self._prices(model))

        feedback = body.get("promptFeedback")
        block_reason = feedback.get("blockReason") if isinstance(feedback, dict) else None
        if block_reason:
            # 入力の段階で止められた場合。使用量が返っていればその分だけを記録する
            billed = cost or 0.0
            message = f"Gemini が入力を受け付けませんでした（{block_reason}）。"
            return AnalysisResult(model=model, cost_usd=billed, error=message, billed_on_failure=billed > 0)

        cost = fallback if cost is None else cost
        text = _text_of(body)
        if not text:
            return common.billed_failure(model, cost, "Gemini の応答に文章が含まれていませんでした。")
        return AnalysisResult(model=model, text=text, cost_usd=cost)
