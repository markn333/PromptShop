"""作風の読み取り役（OpenAI・Grok・Gemini）のテスト。通信は差し替え、実際の API は呼ばない。"""
import base64
import io
import json

import httpx
import pytest
from PIL import Image

from app import config
from app.analyzers import common, default_analyzers
from app.analyzers.gemini_analyzer import GeminiAnalyzer
from app.analyzers.grok_analyzer import GrokAnalyzer
from app.analyzers.openai_analyzer import OpenAIAnalyzer
from tests.fakes import image_bytes

FAKE_KEY = "test-not-a-real-key-123"
DRAFT = "淡い水彩\n\nにじみのある水彩で描き直す。"
KEY_ENVS = (config.OPENAI_API_KEY_ENV, config.XAI_API_KEY_ENV, config.GEMINI_API_KEY_ENV)


@pytest.fixture
def source(tmp_path):
    path = tmp_path / "in.png"
    path.write_bytes(image_bytes("PNG"))
    return path


@pytest.fixture(autouse=True)
def api_keys(monkeypatch):
    for name in KEY_ENVS:
        monkeypatch.setenv(name, FAKE_KEY)


def _make(analyzer_class, handler):
    requests = []

    def record(request):
        requests.append(request)
        return handler(request)

    return analyzer_class(transport=httpx.MockTransport(record)), requests


def _ok(body):
    return lambda request: httpx.Response(200, json=body)


def _responses_body(text=DRAFT, usage=None):
    body = {
        "status": "completed",
        "output": [
            {"type": "reasoning", "summary": []},
            {"type": "message", "role": "assistant", "content": [{"type": "output_text", "text": text}]},
        ],
    }
    if usage is not None:
        body["usage"] = usage
    return body


def _gemini_body(text=DRAFT, usage=None):
    body = {"candidates": [{"content": {"parts": [
        {"text": "考え中のメモ", "thought": True},
        {"text": text},
    ]}, "finishReason": "STOP"}]}
    if usage is not None:
        body["usageMetadata"] = usage
    return body


def _sent_image(payload_part: str) -> Image.Image:
    return Image.open(io.BytesIO(base64.b64decode(payload_part)))


# ---------- 共通 ----------

def test_default_analyzers_cover_the_three_providers():
    assert list(default_analyzers()) == ["openai", "grok", "gemini"]


@pytest.mark.parametrize("language, word", [("ja", "Japanese"), ("en", "English")])
def test_instruction_names_the_language_and_limits_to_style(language, word):
    text = common.instruction(language)

    assert f"in {word}" in text and "ONLY its artistic style" in text and "Do NOT describe what is depicted" in text


def test_prepared_image_is_small_upright_jpeg(tmp_path):
    """大きな画像は縮め、回転情報つきの画像は見た目の向きに直し、WebP でも JPEG にして送る。"""
    path = tmp_path / "big.webp"
    Image.new("RGB", (3000, 1500), "blue").save(path, format="WEBP")
    rotated = tmp_path / "rotated.jpg"
    exif = Image.Exif()
    exif[0x0112] = 6
    Image.new("RGB", (400, 200)).save(rotated, format="JPEG", exif=exif)

    big = Image.open(io.BytesIO(common.prepared_image(path)))
    turned = Image.open(io.BytesIO(common.prepared_image(rotated)))

    assert big.format == "JPEG" and big.size == (config.ANALYSIS_IMAGE_MAX_PX, config.ANALYSIS_IMAGE_MAX_PX // 2)
    assert turned.size == (200, 400)


# ---------- OpenAI ----------

def test_openai_success(source):
    usage = {"input_tokens": 1000, "output_tokens": 400}
    analyzer, requests = _make(OpenAIAnalyzer, _ok(_responses_body(usage=usage)))

    result = analyzer.analyze(source, "ja")

    assert result.ok and result.text == DRAFT and result.model == config.OPENAI_TEXT_MODEL
    # 既定モデル: 1000 * 1.00 + 400 * 5.00 = 3000 → 100 万トークンあたりの単価なので 0.003
    assert result.cost_usd == pytest.approx(0.003)
    request = requests[0]
    assert len(requests) == 1 and str(request.url) == "https://api.openai.com/v1/responses"
    assert request.headers["authorization"] == f"Bearer {FAKE_KEY}"
    payload = json.loads(request.content)
    assert payload["model"] == config.OPENAI_TEXT_MODEL and payload["store"] is False
    assert payload["max_output_tokens"] == config.ANALYSIS_MAX_OUTPUT_TOKENS
    text_part, image_part = payload["input"][0]["content"]
    assert text_part == {"type": "input_text", "text": common.instruction("ja")}
    assert image_part["type"] == "input_image" and image_part["image_url"].startswith("data:image/jpeg;base64,")
    assert _sent_image(image_part["image_url"].split(",", 1)[1]).format == "JPEG"


def test_openai_model_override_and_unknown_model_price(source, monkeypatch):
    monkeypatch.setenv(config.OPENAI_TEXT_MODEL_ENV, "gpt-9-unknown")
    usage = {"input_tokens": 1000, "output_tokens": 100}
    analyzer, requests = _make(OpenAIAnalyzer, _ok(_responses_body(usage=usage)))

    result = analyzer.analyze(source, "ja")

    assert json.loads(requests[0].content)["model"] == "gpt-9-unknown"
    # 単価表にないモデルは、いちばん高いモデルの単価: 1000 * 8 + 100 * 40 = 12000 → 0.012
    assert result.cost_usd == pytest.approx(0.012)


def test_openai_missing_usage_uses_fallback_cost(source):
    analyzer, _ = _make(OpenAIAnalyzer, _ok(_responses_body()))

    result = analyzer.analyze(source, "ja")

    expected = common.fallback_cost_usd(config.OPENAI_TEXT_PRICES[config.OPENAI_TEXT_MODEL])
    assert result.ok and result.cost_usd == pytest.approx(expected) and expected > 0


def test_openai_no_text_is_billed_failure(source):
    body = {"status": "incomplete", "output": [{"type": "reasoning"}], "usage": {"input_tokens": 1000, "output_tokens": 4000}}
    analyzer, _ = _make(OpenAIAnalyzer, _ok(body))

    result = analyzer.analyze(source, "ja")

    assert not result.ok and result.billed_on_failure and result.cost_usd == pytest.approx(0.021)
    assert "文章が含まれていません" in result.error


@pytest.mark.parametrize("analyzer_class", [OpenAIAnalyzer, GrokAnalyzer, GeminiAnalyzer])
def test_unreadable_200_is_billed_failure(source, analyzer_class):
    analyzer, _ = _make(analyzer_class, lambda request: httpx.Response(200, text="<html>not json</html>"))

    result = analyzer.analyze(source, "ja")

    assert not result.ok and result.billed_on_failure and result.cost_usd > 0


@pytest.mark.parametrize("analyzer_class", [OpenAIAnalyzer, GrokAnalyzer, GeminiAnalyzer])
def test_http_error_is_not_retried_and_hides_key(source, analyzer_class):
    body = {"error": {"code": "server_error", "message": f"boom {FAKE_KEY[:0]}"}}
    analyzer, requests = _make(analyzer_class, lambda request: httpx.Response(500, json=body))

    result = analyzer.analyze(source, "ja")

    assert not result.ok and "HTTP 500" in result.error and result.cost_usd == 0
    assert len(requests) == 1, "失敗しても自動でやり直さない"
    assert FAKE_KEY not in result.error


@pytest.mark.parametrize("analyzer_class", [OpenAIAnalyzer, GrokAnalyzer, GeminiAnalyzer])
def test_bad_key_message(source, analyzer_class):
    analyzer, _ = _make(analyzer_class, lambda request: httpx.Response(401, json={"error": {"message": "nope"}}))

    assert "API キーが正しくありません" in analyzer.analyze(source, "ja").error


@pytest.mark.parametrize("analyzer_class", [OpenAIAnalyzer, GrokAnalyzer, GeminiAnalyzer])
def test_timeout_and_missing_file(source, tmp_path, analyzer_class):
    def time_out(request):
        raise httpx.ReadTimeout("slow", request=request)

    analyzer, _ = _make(analyzer_class, time_out)
    timed_out = analyzer.analyze(source, "ja")
    missing = analyzer.analyze(tmp_path / "missing.png", "ja")

    assert not timed_out.ok and timed_out.billed_on_failure and "課金されている可能性" in timed_out.error
    assert not missing.ok and not missing.billed_on_failure and "読み込めません" in missing.error


@pytest.mark.parametrize(
    "analyzer_class, key_env",
    [
        (OpenAIAnalyzer, config.OPENAI_API_KEY_ENV),
        (GrokAnalyzer, config.XAI_API_KEY_ENV),
        (GeminiAnalyzer, config.GEMINI_API_KEY_ENV),
    ],
)
def test_is_configured_follows_the_shared_key(monkeypatch, analyzer_class, key_env):
    analyzer = analyzer_class()
    assert analyzer.is_configured() is True

    monkeypatch.setenv(key_env, "")

    assert analyzer.is_configured() is False


# ---------- Grok ----------

def test_grok_success_uses_reported_cost(source):
    usage = {"input_tokens": 1000, "output_tokens": 400, "cost_in_usd_ticks": 52_000_000}
    analyzer, requests = _make(GrokAnalyzer, _ok(_responses_body(usage=usage)))

    result = analyzer.analyze(source, "en")

    assert result.ok and result.text == DRAFT and result.model == config.XAI_TEXT_MODEL
    assert result.cost_usd == pytest.approx(0.0052)
    request = requests[0]
    assert str(request.url) == "https://api.x.ai/v1/responses"
    assert request.headers["authorization"] == f"Bearer {FAKE_KEY}"
    payload = json.loads(request.content)
    assert payload["model"] == config.XAI_TEXT_MODEL and payload["store"] is False
    assert payload["input"][0]["content"][0]["text"] == common.instruction("en")


def test_grok_cost_from_tokens_when_not_reported(source):
    usage = {"input_tokens": 1000, "output_tokens": 400, "output_tokens_details": {"reasoning_tokens": 100}}
    analyzer, _ = _make(GrokAnalyzer, _ok(_responses_body(usage=usage)))

    result = analyzer.analyze(source, "ja")

    # 既定モデル: 1000 * 2.00 + (400 + 100) * 6.00 = 5000 → 0.005
    assert result.cost_usd == pytest.approx(0.005)


# ---------- Gemini ----------

def test_gemini_success(source):
    usage = {"promptTokenCount": 1000, "candidatesTokenCount": 300, "thoughtsTokenCount": 100}
    analyzer, requests = _make(GeminiAnalyzer, _ok(_gemini_body(usage=usage)))

    result = analyzer.analyze(source, "ja")

    assert result.ok and result.text == DRAFT, "考える途中のメモは本文に入れない"
    # 既定モデル: 1000 * 0.75 + (300 + 100) * 3.75 = 2250 → 0.00225
    assert result.cost_usd == pytest.approx(0.00225)
    request = requests[0]
    assert str(request.url).endswith(f"/models/{config.GEMINI_TEXT_MODEL}:generateContent")
    assert request.headers["x-goog-api-key"] == FAKE_KEY and FAKE_KEY not in str(request.url)
    payload = json.loads(request.content)
    text_part, image_part = payload["contents"][0]["parts"]
    assert text_part == {"text": common.instruction("ja")}
    assert image_part["inline_data"]["mime_type"] == "image/jpeg"
    assert payload["generationConfig"] == {"maxOutputTokens": config.ANALYSIS_MAX_OUTPUT_TOKENS}


def test_gemini_blocked_input(source):
    body = {"promptFeedback": {"blockReason": "SAFETY"}}
    analyzer, _ = _make(GeminiAnalyzer, _ok(body))

    result = analyzer.analyze(source, "ja")

    assert not result.ok and "SAFETY" in result.error and result.cost_usd == 0 and not result.billed_on_failure


def test_gemini_no_text_is_billed_failure(source):
    usage = {"promptTokenCount": 1000, "candidatesTokenCount": 0}
    body = {"candidates": [{"finishReason": "MAX_TOKENS"}], "usageMetadata": usage}
    analyzer, _ = _make(GeminiAnalyzer, _ok(body))

    result = analyzer.analyze(source, "ja")

    assert not result.ok and result.billed_on_failure and result.cost_usd == pytest.approx(0.00075)
