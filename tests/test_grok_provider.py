"""Grok プロバイダーのテスト。通信は差し替え、実際の API は呼ばない。"""
import base64
import json

import httpx
import pytest

from app import config
from app.providers.grok_provider import GrokProvider, aspect_ratio
from tests.fakes import image_bytes

FAKE_KEY = "xai-test-not-a-real-key"
COST = config.XAI_OUTPUT_PRICE_USD + config.XAI_INPUT_PRICE_USD


@pytest.fixture
def source(tmp_path):
    path = tmp_path / "in.jpg"
    path.write_bytes(image_bytes("JPEG"))
    return path


@pytest.fixture(autouse=True)
def api_key(monkeypatch):
    monkeypatch.setenv(config.XAI_API_KEY_ENV, FAKE_KEY)


def _provider(handler):
    requests = []

    def record(request):
        requests.append(request)
        return handler(request)

    return GrokProvider(transport=httpx.MockTransport(record)), requests


def _ok(body):
    return lambda request: httpx.Response(200, json=body)


def _image_body(data=None):
    return {"data": [{"b64_json": base64.b64encode(data or image_bytes()).decode()}]}


def test_success_returns_image_and_fixed_cost(source):
    output = image_bytes(color="green")
    provider, requests = _provider(_ok(_image_body(output)))

    result = provider.transform(source, "水彩画風にする")

    assert result.ok and result.image_bytes == output
    assert result.model == config.XAI_IMAGE_MODEL
    assert result.cost_usd == pytest.approx(COST)
    assert len(requests) == 1


def test_request_contents(source):
    provider, requests = _provider(_ok(_image_body()))

    provider.transform(source, "水彩画風にする")

    request = requests[0]
    sent = json.loads(request.content)
    assert str(request.url) == "https://api.x.ai/v1/images/edits"
    assert request.headers["authorization"] == f"Bearer {FAKE_KEY}"
    assert sent["model"] == config.XAI_IMAGE_MODEL and sent["prompt"] == "水彩画風にする"
    assert (sent["n"], sent["response_format"], sent["resolution"]) == (1, "b64_json", "1k")
    assert sent["image"]["type"] == "image_url"
    prefix, encoded = sent["image"]["url"].split(",", 1)
    assert prefix == "data:image/jpeg;base64" and base64.b64decode(encoded) == source.read_bytes()
    assert sent["aspect_ratio"] == "4:3", "64 x 48 の元画像には 4:3 の出力を頼む"
    assert FAKE_KEY not in request.content.decode()


def test_model_can_be_overridden_by_env(source, monkeypatch):
    monkeypatch.setenv(config.XAI_MODEL_ENV, "grok-imagine-other")
    provider, requests = _provider(_ok(_image_body()))

    assert provider.transform(source, "x").model == "grok-imagine-other"
    assert json.loads(requests[0].content)["model"] == "grok-imagine-other"


def test_is_configured_follows_env(monkeypatch):
    assert GrokProvider().is_configured()
    monkeypatch.setenv(config.XAI_API_KEY_ENV, "  ")
    assert not GrokProvider().is_configured()


@pytest.mark.parametrize(
    ("status", "body", "expected"),
    [
        (401, {"error": "Incorrect API key provided"}, "API キーが正しくありません"),
        (400, {"code": "Client error", "error": "Incorrect API key provided: xa***"}, "API キーが正しくありません"),
        (429, {"error": {"message": "rate limited"}}, "HTTP 429"),
        (400, {"error": {"message": "Content violates usage policy"}}, "コンテンツポリシー"),
        (503, {"error": {"message": "overloaded"}}, "HTTP 503"),
    ],
    ids=["401", "bad key as 400", "429", "policy", "503"],
)
def test_http_errors_fail_without_retry(source, status, body, expected):
    provider, requests = _provider(lambda request: httpx.Response(status, json=body))

    result = provider.transform(source, "x")

    assert not result.ok and expected in result.error
    assert result.cost_usd == 0
    assert len(requests) == 1, "429 や 5xx でも自動で再試行しない"


def test_moderated_output_is_failure_but_billed(source):
    body = {"data": [{"b64_json": base64.b64encode(image_bytes()).decode(), "respect_moderation": False}]}
    provider, _ = _provider(_ok(body))

    result = provider.transform(source, "x")

    assert not result.ok and "コンテンツポリシー" in result.error
    assert result.billed_on_failure and result.cost_usd == pytest.approx(COST)


@pytest.mark.parametrize(
    "response",
    [
        httpx.Response(200, json={"data": []}),
        httpx.Response(200, json={"data": [{"url": "https://example.com/x.png"}]}),
        httpx.Response(200, json={"data": [{"b64_json": "!!!not-base64!!!"}]}),
        httpx.Response(200, text="not json"),
        httpx.Response(200, json=["unexpected"]),
    ],
    ids=["empty data", "no b64", "bad base64", "not json", "not object"],
)
def test_broken_success_response_fails_but_keeps_cost(source, response):
    provider, _ = _provider(lambda request: response)

    result = provider.transform(source, "x")

    assert not result.ok and result.billed_on_failure
    assert result.cost_usd == pytest.approx(COST)


def test_network_error_and_timeout(source):
    def refuse(request):
        raise httpx.ConnectError(f"cannot connect with {FAKE_KEY}")

    def slow(request):
        raise httpx.ReadTimeout("timed out")

    provider, requests = _provider(refuse)
    refused = provider.transform(source, "x")
    assert not refused.ok and "Grok に接続できませんでした" in refused.error and FAKE_KEY not in refused.error
    assert len(requests) == 1

    provider, requests = _provider(slow)
    timed_out = provider.transform(source, "x")
    assert not timed_out.ok and timed_out.billed_on_failure and "課金" in timed_out.error
    assert len(requests) == 1


def test_unreadable_source_fails_without_calling_api(tmp_path):
    provider, requests = _provider(_ok({}))

    result = provider.transform(tmp_path / "missing.png", "x")

    assert not result.ok and result.cost_usd == 0 and requests == []


# ---------- 縦横比（BUG-0003） ----------

@pytest.mark.parametrize(
    ("width", "height", "expected"),
    [
        (941, 1672, "9:16"),   # 2026-11-19 の実 API 確認で正方形が返った縦長の画像
        (1672, 941, "16:9"),
        (1024, 1024, "1:1"),
        (1000, 1100, "1:1"),
        (1200, 1600, "3:4"),
        (1600, 1200, "4:3"),
        (1000, 1500, "2:3"),
        (1500, 1000, "3:2"),
        (500, 4000, "9:16"),
        (4000, 500, "16:9"),
    ],
)
def test_aspect_ratio_is_nearest_supported(width, height, expected):
    assert aspect_ratio(width, height) == expected


def test_portrait_source_requests_portrait_output(tmp_path):
    from PIL import Image

    path = tmp_path / "tall.png"
    Image.new("RGB", (94, 167)).save(path)
    provider, requests = _provider(_ok(_image_body()))

    provider.transform(path, "x")

    assert json.loads(requests[0].content)["aspect_ratio"] == "9:16"


def test_rotation_info_is_respected(tmp_path):
    """画素は横長でも、90 度回して表示する指定があれば、見た目どおり縦長として扱う。"""
    from PIL import Image

    path = tmp_path / "rotated.jpg"
    exif = Image.Exif()
    exif[0x0112] = 6
    Image.new("RGB", (167, 94)).save(path, format="JPEG", exif=exif)
    provider, requests = _provider(_ok(_image_body()))

    provider.transform(path, "x")

    assert json.loads(requests[0].content)["aspect_ratio"] == "9:16"


def test_aspect_ratio_is_left_to_provider_when_not_kept(tmp_path):
    """「縦横比維持」を外したときは、縦横比を送らない（Grok に任せる）。"""
    from PIL import Image

    path = tmp_path / "tall.png"
    Image.new("RGB", (94, 167)).save(path)
    provider, requests = _provider(_ok(_image_body()))

    result = provider.transform(path, "x", keep_aspect=False)

    assert result.ok and "aspect_ratio" not in json.loads(requests[0].content)
