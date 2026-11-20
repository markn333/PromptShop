"""Gemini プロバイダーのテスト。通信は差し替え、実際の API は呼ばない。"""
import base64
import json

import httpx
import pytest
from PIL import Image

from app import config
from app.providers.gemini_provider import GeminiProvider, aspect_ratio, image_price_usd, usage_cost_usd
from tests.fakes import image_bytes

FAKE_KEY = "gemini-test-not-a-real-key"
MODEL = config.GEMINI_IMAGE_MODEL
USAGE = {
    "promptTokenCount": 600,
    "candidatesTokenCount": 1220,
    "candidatesTokensDetails": [
        {"modality": "IMAGE", "tokenCount": 1120},
        {"modality": "TEXT", "tokenCount": 100},
    ],
    "thoughtsTokenCount": 200,
}
# 既定モデル: 600 * 1.5 + 1120 * 30 + (100 + 200) * 1.5 = 34,950 → 100 万トークンあたりの単価なので 0.03495
USAGE_COST = 0.03495


@pytest.fixture
def source(tmp_path):
    path = tmp_path / "in.png"
    path.write_bytes(image_bytes("PNG"))
    return path


@pytest.fixture(autouse=True)
def api_key(monkeypatch):
    monkeypatch.setenv(config.GEMINI_API_KEY_ENV, FAKE_KEY)


def _provider(handler):
    requests = []

    def record(request):
        requests.append(request)
        return handler(request)

    return GeminiProvider(transport=httpx.MockTransport(record)), requests


def _ok(body):
    return lambda request: httpx.Response(200, json=body)


def _image_body(data=None, usage=USAGE):
    encoded = base64.b64encode(data or image_bytes()).decode()
    parts = [{"text": "変換しました"}, {"inlineData": {"mimeType": "image/png", "data": encoded}}]
    body = {"candidates": [{"content": {"parts": parts}, "finishReason": "STOP"}]}
    if usage is not None:
        body["usageMetadata"] = usage
    return body


def test_success_returns_image_and_cost(source):
    output = image_bytes(color="green")
    provider, requests = _provider(_ok(_image_body(output)))

    result = provider.transform(source, "水彩画風にする")

    assert result.ok and result.image_bytes == output
    assert result.model == MODEL
    assert result.cost_usd == pytest.approx(USAGE_COST)
    assert len(requests) == 1


def test_request_contents(source):
    provider, requests = _provider(_ok(_image_body()))

    provider.transform(source, "水彩画風にする")

    request = requests[0]
    sent = json.loads(request.content)
    assert str(request.url) == f"https://generativelanguage.googleapis.com/v1beta/models/{MODEL}:generateContent"
    assert request.headers["x-goog-api-key"] == FAKE_KEY
    assert FAKE_KEY not in str(request.url), "キーを URL に入れない"
    text_part, image_part = sent["contents"][0]["parts"]
    assert text_part == {"text": "水彩画風にする"}
    assert image_part["inline_data"]["mime_type"] == "image/png"
    assert base64.b64decode(image_part["inline_data"]["data"]) == source.read_bytes()
    generation = sent["generationConfig"]
    assert generation["responseModalities"] == ["TEXT", "IMAGE"]
    assert generation["imageConfig"] == {"aspectRatio": "4:3", "imageSize": "1K"}, "64 x 48 の元画像は 4:3"


def test_model_can_be_overridden_by_env(source, monkeypatch):
    monkeypatch.setenv(config.GEMINI_MODEL_ENV, "gemini-3-pro-image")
    provider, requests = _provider(_ok(_image_body()))

    result = provider.transform(source, "x")

    assert result.model == "gemini-3-pro-image"
    assert str(requests[0].url).endswith("/models/gemini-3-pro-image:generateContent")
    # 600 * 2 + 1120 * 120 + 300 * 12 = 139,200
    assert result.cost_usd == pytest.approx(0.1392)


def test_is_configured_follows_env(monkeypatch):
    assert GeminiProvider().is_configured()
    monkeypatch.setenv(config.GEMINI_API_KEY_ENV, "")
    assert not GeminiProvider().is_configured()


# ---------- 縦横比 ----------

@pytest.mark.parametrize(
    ("width", "height", "expected"),
    [
        (1024, 1024, "1:1"),
        (941, 1672, "9:16"),
        (1672, 941, "16:9"),
        (1200, 1600, "3:4"),
        (1600, 1200, "4:3"),
        (1000, 1500, "2:3"),
        (1500, 1000, "3:2"),
        (1000, 1250, "4:5"),
        (1000, 1050, "1:1"),
        (4000, 500, "21:9"),
        (500, 4000, "9:16"),
    ],
)
def test_aspect_ratio_is_nearest_supported(width, height, expected):
    assert aspect_ratio(width, height) == expected


def test_rotation_info_is_respected(tmp_path):
    """画素は横長でも、90 度回して表示する指定があれば、見た目どおり縦長として扱う。"""
    path = tmp_path / "rotated.jpg"
    exif = Image.Exif()
    exif[0x0112] = 6
    Image.new("RGB", (160, 90)).save(path, format="JPEG", exif=exif)
    provider, requests = _provider(_ok(_image_body()))

    provider.transform(path, "x")

    assert json.loads(requests[0].content)["generationConfig"]["imageConfig"]["aspectRatio"] == "9:16"


# ---------- 料金 ----------

def test_missing_usage_uses_one_image_price(source):
    provider, _ = _provider(_ok(_image_body(usage=None)))
    assert provider.transform(source, "x").cost_usd == pytest.approx(image_price_usd(MODEL))
    assert image_price_usd(MODEL) == pytest.approx(0.0336)


def test_usage_without_breakdown_counts_output_as_image_tokens():
    cost = usage_cost_usd(MODEL, {"promptTokenCount": 0, "candidatesTokenCount": 1000})
    assert cost == pytest.approx(1000 * 30 / 1_000_000)


def test_unknown_model_is_priced_as_most_expensive():
    assert image_price_usd("gemini-some-future-image") == pytest.approx(image_price_usd("gemini-3-pro-image"))
    assert image_price_usd("gemini-3-pro-image") == pytest.approx(0.1344)


# ---------- 失敗 ----------

def test_output_blocked_by_safety_is_billed(source):
    """出力が安全フィルターで止められても課金される。使用量が返らなくても 1 枚分を記録する。"""
    body = {"candidates": [{"finishReason": "IMAGE_SAFETY"}]}
    provider, requests = _provider(_ok(body))

    result = provider.transform(source, "x")

    assert not result.ok and "IMAGE_SAFETY" in result.error and "課金" in result.error
    assert result.billed_on_failure and result.cost_usd == pytest.approx(image_price_usd(MODEL))
    assert len(requests) == 1, "止められても再試行しない"


def test_blocked_output_cost_is_not_below_one_image(source):
    body = {"candidates": [{"finishReason": "IMAGE_SAFETY"}], "usageMetadata": {"promptTokenCount": 600}}
    provider, _ = _provider(_ok(body))
    assert provider.transform(source, "x").cost_usd == pytest.approx(image_price_usd(MODEL))


def test_text_only_answer_is_billed_failure(source):
    body = {
        "candidates": [{"content": {"parts": [{"text": "できません"}]}, "finishReason": "STOP"}],
        "usageMetadata": USAGE,
    }
    provider, _ = _provider(_ok(body))

    result = provider.transform(source, "x")

    assert not result.ok and result.billed_on_failure
    assert result.cost_usd == pytest.approx(USAGE_COST)


def test_prompt_blocked_before_generation(source):
    provider, _ = _provider(_ok({"promptFeedback": {"blockReason": "PROHIBITED_CONTENT"}}))

    result = provider.transform(source, "x")

    assert not result.ok and "PROHIBITED_CONTENT" in result.error
    assert result.cost_usd == 0 and not result.billed_on_failure


@pytest.mark.parametrize(
    ("status", "body", "expected"),
    [
        (400, {"error": {"code": 400, "message": "API key not valid. Please pass a valid API key.",
                         "status": "INVALID_ARGUMENT"}}, "API キーが正しくありません"),
        (429, {"error": {"code": 429, "message": "Quota exceeded", "status": "RESOURCE_EXHAUSTED"}}, "HTTP 429"),
        (404, {"error": {"code": 404, "message": "models/x is not found", "status": "NOT_FOUND"}}, "HTTP 404"),
        (500, {"error": {"code": 500, "message": "internal"}}, "HTTP 500"),
    ],
    ids=["bad key", "429", "404", "500"],
)
def test_http_errors_fail_without_retry(source, status, body, expected):
    provider, requests = _provider(lambda request: httpx.Response(status, json=body))

    result = provider.transform(source, "x")

    assert not result.ok and expected in result.error
    assert result.cost_usd == 0 and len(requests) == 1


@pytest.mark.parametrize(
    "response",
    [
        httpx.Response(200, text="not json"),
        httpx.Response(200, json=["unexpected"]),
        httpx.Response(200, json={"candidates": []}),
        httpx.Response(200, json=_image_body() | {"candidates": [
            {"content": {"parts": [{"inlineData": {"data": "!!!not-base64!!!"}}]}}]}),
    ],
    ids=["not json", "not object", "no candidates", "bad base64"],
)
def test_broken_success_response_fails_but_keeps_cost(source, response):
    provider, _ = _provider(lambda request: response)

    result = provider.transform(source, "x")

    assert not result.ok and result.billed_on_failure and result.cost_usd > 0


def test_network_error_and_timeout(source):
    def refuse(request):
        raise httpx.ConnectError(f"cannot connect with {FAKE_KEY}")

    def slow(request):
        raise httpx.ReadTimeout("timed out")

    provider, requests = _provider(refuse)
    refused = provider.transform(source, "x")
    assert not refused.ok and "Gemini に接続できませんでした" in refused.error and FAKE_KEY not in refused.error

    provider, requests = _provider(slow)
    timed_out = provider.transform(source, "x")
    assert not timed_out.ok and timed_out.billed_on_failure and len(requests) == 1


def test_unreadable_source_fails_without_calling_api(tmp_path):
    provider, requests = _provider(_ok({}))

    result = provider.transform(tmp_path / "missing.png", "x")

    assert not result.ok and result.cost_usd == 0 and requests == []


def test_aspect_ratio_is_left_to_provider_when_not_kept(tmp_path):
    """「縦横比維持」を外したときは、縦横比を送らない（大きさの指定は残す）。"""
    path = tmp_path / "tall.png"
    Image.new("RGB", (90, 160)).save(path)
    provider, requests = _provider(_ok(_image_body()))

    result = provider.transform(path, "x", keep_aspect=False)

    image_config = json.loads(requests[0].content)["generationConfig"]["imageConfig"]
    assert result.ok and image_config == {"imageSize": config.GEMINI_IMAGE_SIZE}
