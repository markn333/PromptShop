"""OpenAI プロバイダーのテスト。通信は差し替え、実際の API は呼ばない。"""
import base64

import httpx
import pytest

from app import config
from app.providers.openai_provider import OpenAIProvider, output_size, usage_cost_usd
from tests.fakes import image_bytes

FAKE_KEY = "sk-test-not-a-real-key"
USAGE = {
    "input_tokens": 1100,
    "input_tokens_details": {"text_tokens": 100, "image_tokens": 1000},
    "output_tokens": 2000,
}
# 100 * 5 + 1000 * 8 + 2000 * 30 = 68,500 → 100 万トークンあたりの単価なので 0.0685
USAGE_COST = 0.0685


@pytest.fixture
def source(tmp_path):
    path = tmp_path / "in.jpg"
    path.write_bytes(image_bytes("JPEG"))
    return path


@pytest.fixture(autouse=True)
def api_key(monkeypatch):
    monkeypatch.setenv(config.OPENAI_API_KEY_ENV, FAKE_KEY)
    monkeypatch.delenv(config.OPENAI_MODEL_ENV, raising=False)


def _provider(handler):
    """handler で応答を作る差し替え通信つきのプロバイダーと、受けた要求の記録を返す。"""
    requests = []

    def record(request):
        requests.append(request)
        return handler(request)

    return OpenAIProvider(transport=httpx.MockTransport(record)), requests


def _ok(body):
    return lambda request: httpx.Response(200, json=body)


def test_success_returns_image_and_cost(source):
    output = image_bytes(color="green")
    body = {"data": [{"b64_json": base64.b64encode(output).decode()}], "usage": USAGE}
    provider, requests = _provider(_ok(body))

    result = provider.transform(source, "水彩画風にする")

    assert result.ok and result.image_bytes == output
    assert result.model == config.OPENAI_IMAGE_MODEL
    assert result.cost_usd == pytest.approx(USAGE_COST)
    assert len(requests) == 1


def test_request_contents(source):
    body = {"data": [{"b64_json": base64.b64encode(image_bytes()).decode()}]}
    provider, requests = _provider(_ok(body))

    provider.transform(source, "水彩画風にする")

    request = requests[0]
    sent = request.content
    assert str(request.url) == "https://api.openai.com/v1/images/edits"
    assert request.headers["authorization"] == f"Bearer {FAKE_KEY}"
    assert request.headers["content-type"].startswith("multipart/form-data")
    assert "水彩画風にする".encode() in sent
    assert config.OPENAI_IMAGE_MODEL.encode() in sent
    assert b'name="quality"\r\n\r\nmedium' in sent
    assert b'name="size"\r\n\r\n1536x1024' in sent, "64 x 48 の横長の元画像には横長の出力を頼む"
    assert b'filename="in.jpg"' in sent and b"image/jpeg" in sent
    assert source.read_bytes() in sent
    assert b"input_fidelity" not in sent


def test_model_can_be_overridden_by_env(source, monkeypatch):
    monkeypatch.setenv(config.OPENAI_MODEL_ENV, "gpt-image-other")
    body = {"data": [{"b64_json": base64.b64encode(image_bytes()).decode()}]}
    provider, requests = _provider(_ok(body))

    result = provider.transform(source, "x")

    assert result.model == "gpt-image-other"
    assert b"gpt-image-other" in requests[0].content


def test_is_configured_follows_env(monkeypatch):
    assert OpenAIProvider().is_configured()
    monkeypatch.setenv(config.OPENAI_API_KEY_ENV, "   ")
    assert not OpenAIProvider().is_configured()
    monkeypatch.delenv(config.OPENAI_API_KEY_ENV)
    assert not OpenAIProvider().is_configured()


def test_missing_usage_uses_fallback_cost(source):
    body = {"data": [{"b64_json": base64.b64encode(image_bytes()).decode()}]}
    provider, _ = _provider(_ok(body))
    assert provider.transform(source, "x").cost_usd == pytest.approx(config.OPENAI_FALLBACK_COST_USD)


def test_usage_without_breakdown_counts_input_as_image_tokens():
    cost = usage_cost_usd({"input_tokens": 1000, "output_tokens": 0})
    assert cost == pytest.approx(1000 * config.OPENAI_TOKEN_PRICE_PER_M["image_input"] / 1_000_000)


@pytest.mark.parametrize(
    ("status", "body", "expected"),
    [
        (401, {"error": {"code": "invalid_api_key", "message": "Incorrect API key provided"}}, "API キーが正しくありません"),
        (429, {"error": {"code": "insufficient_quota", "message": "You exceeded your quota"}}, "残高"),
        (400, {"error": {"code": "moderation_blocked", "message": "Rejected by safety system"}}, "コンテンツポリシー"),
        (500, {"error": {"message": "server exploded"}}, "HTTP 500"),
    ],
    ids=["401", "429", "moderation", "500"],
)
def test_http_errors_fail_without_retry(source, status, body, expected):
    provider, requests = _provider(lambda request: httpx.Response(status, json=body))

    result = provider.transform(source, "x")

    assert not result.ok and expected in result.error
    assert result.cost_usd == 0 and result.image_bytes is None
    assert len(requests) == 1, "429 や 5xx でも自動で再試行しない"


def test_non_json_error_body(source):
    provider, _ = _provider(lambda request: httpx.Response(502, text="<html>Bad Gateway</html>"))
    assert "HTTP 502" in provider.transform(source, "x").error


def test_long_error_is_truncated(source):
    body = {"error": {"message": "x" * 5000}}
    provider, _ = _provider(lambda request: httpx.Response(500, json=body))
    assert len(provider.transform(source, "x").error) < config.PROVIDER_ERROR_MAX_LENGTH + 100


def test_network_error_fails_once_without_leaking_key(source):
    def handler(request):
        raise httpx.ConnectError(f"cannot connect with {FAKE_KEY}")

    provider, requests = _provider(handler)

    result = provider.transform(source, "x")

    assert not result.ok and "ConnectError" in result.error
    assert FAKE_KEY not in result.error
    assert len(requests) == 1


def test_timeout_is_reported_as_possibly_billed(source):
    def handler(request):
        raise httpx.ReadTimeout("timed out")

    provider, requests = _provider(handler)

    result = provider.transform(source, "x")

    assert not result.ok and result.billed_on_failure
    assert "課金" in result.error
    assert len(requests) == 1


@pytest.mark.parametrize(
    "response",
    [
        httpx.Response(200, json={"data": [], "usage": USAGE}),
        httpx.Response(200, json={"data": [{"url": "https://example.com/x.png"}], "usage": USAGE}),
        httpx.Response(200, json={"data": [{"b64_json": "!!!not-base64!!!"}], "usage": USAGE}),
        httpx.Response(200, text="not json"),
        httpx.Response(200, json=["unexpected"]),
    ],
    ids=["empty data", "no b64", "bad base64", "not json", "not object"],
)
def test_broken_success_response_fails_but_keeps_cost(source, response):
    provider, _ = _provider(lambda request: response)

    result = provider.transform(source, "x")

    assert not result.ok and result.billed_on_failure
    assert result.cost_usd > 0

# ---------- 出力サイズ（元画像の向きに合わせる） ----------

@pytest.mark.parametrize(
    ("width", "height", "expected"),
    [
        (941, 1672, "1024x1536"),   # 2026-11-19 の実 API 確認で正方形が返った縦長の画像
        (1672, 941, "1536x1024"),
        (1024, 1024, "1024x1024"),
        (1000, 1100, "1024x1024"),  # わずかに縦長 → 正方形の方が近い
        (1100, 1000, "1024x1024"),
        (1200, 1600, "1024x1536"),  # 3:4
        (1600, 1200, "1536x1024"),  # 4:3
        (1000, 1200, "1024x1024"),  # 5:6 は正方形の方が近い
        (4000, 500, "1536x1024"),
        (500, 4000, "1024x1536"),
    ],
)
def test_output_size_follows_orientation(width, height, expected):
    assert output_size(width, height) == expected


def _sent_size(tmp_path, image, **save_options):
    path = tmp_path / "sized.jpg"
    image.save(path, format="JPEG", **save_options)
    body = {"data": [{"b64_json": base64.b64encode(image_bytes()).decode()}]}
    provider, requests = _provider(_ok(body))
    provider.transform(path, "x")
    content = requests[0].content
    marker = b'name="size"\r\n\r\n'
    start = content.index(marker) + len(marker)
    return content[start:content.index(b"\r\n", start)].decode()


def test_portrait_image_requests_portrait_output(tmp_path):
    from PIL import Image

    assert _sent_size(tmp_path, Image.new("RGB", (94, 167))) == "1024x1536"


def test_rotation_info_is_respected(tmp_path):
    """画素は横長でも、90 度回して表示する指定があれば、見た目どおり縦長として扱う。"""
    from PIL import Image

    image = Image.new("RGB", (167, 94))
    exif = Image.Exif()
    exif[0x0112] = 6
    assert _sent_size(tmp_path, image, exif=exif) == "1024x1536"


def test_unreadable_source_fails_without_calling_api(tmp_path):
    provider, requests = _provider(_ok({}))

    result = provider.transform(tmp_path / "missing.png", "x")

    assert not result.ok and result.cost_usd == 0
    assert requests == []


def test_size_is_left_to_provider_when_not_kept(tmp_path):
    """「縦横比維持」を外したときは、size を auto にする（OpenAI に任せる）。"""
    from PIL import Image

    path = tmp_path / "tall.png"
    Image.new("RGB", (94, 167)).save(path)
    body = {"data": [{"b64_json": base64.b64encode(image_bytes()).decode()}]}
    provider, requests = _provider(_ok(body))

    result = provider.transform(path, "x", keep_aspect=False)

    assert result.ok and b'name="size"\r\n\r\nauto\r\n' in requests[0].content
