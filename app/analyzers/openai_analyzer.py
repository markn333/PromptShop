"""OpenAI の Responses API（/v1/responses）で、画像の作風を読み取る。"""
from pathlib import Path
from typing import Optional

import httpx

from app import config
from app.analyzers import common
from app.analyzers.base import AnalysisResult, Analyzer


class OpenAIAnalyzer(Analyzer):
    """OpenAI の文章モデル（画像入力つき）による作風の読み取り。"""

    name = "openai"
    label = "OpenAI"
    api_key_env = config.OPENAI_API_KEY_ENV
    model_env = config.OPENAI_TEXT_MODEL_ENV
    default_model = config.OPENAI_TEXT_MODEL

    def __init__(self, transport: Optional[httpx.BaseTransport] = None) -> None:
        # transport はテストで通信を差し替えるためのもの。通常は None（実際に通信する）。
        self._transport = transport

    def _prices(self, model: str) -> dict:
        return common.prices_of(config.OPENAI_TEXT_PRICES, model, config.OPENAI_TEXT_UNKNOWN_PRICE_KEY)

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
        """API を 1 回だけ呼ぶ。再試行はしない。"""
        payload = common.responses_request(model, language, common.prepared_image(image_path))
        headers = {"Authorization": f"Bearer {self._api_key()}"}
        with httpx.Client(transport=self._transport, timeout=config.ANALYSIS_TIMEOUT_SEC) as client:
            return client.post(f"{config.OPENAI_API_BASE}/responses", json=payload, headers=headers)

    def _parse(self, response: httpx.Response, model: str, fallback: float) -> AnalysisResult:
        """HTTP 200 の応答から文章と料金を取り出す。200 が返った時点で課金されているとみなす。"""
        body = common.json_body(response)
        if body is None:
            return common.billed_failure(model, fallback, "OpenAI の応答を読み取れませんでした。")
        usage = body.get("usage")
        if isinstance(usage, dict):
            # output_tokens には、考える途中で使った分（reasoning）も含まれる
            cost = common.token_cost_usd(usage.get("input_tokens"), usage.get("output_tokens"), self._prices(model))
        else:
            cost = fallback
        text = common.responses_text(body)
        if not text:
            return common.billed_failure(model, cost, "OpenAI の応答に文章が含まれていませんでした。")
        return AnalysisResult(model=model, text=text, cost_usd=cost)
