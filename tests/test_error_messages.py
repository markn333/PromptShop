"""利用者に見せるエラー文のテスト。"""
import pytest

from app import config
from app.errors import InvalidImageError
from app.services.images import ImageStore
from tests.fakes import FAKE_COST_USD, run_transform, upload


def _detail(response):
    assert response.status_code == 422
    detail = response.json()["detail"]
    assert isinstance(detail, str), "画面にそのまま出せる文で返す"
    return detail


def test_blank_genre_name(client):
    assert _detail(client.post("/api/genres", json={"name": "   "})) == "ジャンル名を入力してください。"


def test_too_long_prompt_title_and_body(client):
    payload = {
        "title": "あ" * (config.PROMPT_TITLE_MAX_LENGTH + 1),
        "body": "あ" * (config.PROMPT_BODY_MAX_LENGTH + 1),
    }

    detail = _detail(client.post("/api/prompts", json=payload))

    assert f"タイトルは {config.PROMPT_TITLE_MAX_LENGTH} 文字以内で入力してください。" in detail
    assert f"本文は {config.PROMPT_BODY_MAX_LENGTH} 文字以内で入力してください。" in detail


def test_missing_fields(client):
    assert _detail(client.post("/api/prompts", json={"title": "水彩"})) == "本文を指定してください。"
    assert _detail(client.post("/api/transforms", json={"prompt_body": "x"})) == "元画像を指定してください。"
    assert _detail(client.post("/api/images")) == "画像ファイルを指定してください。"


def test_too_long_body_for_transform_does_not_call_api(client, provider):
    image = upload(client)
    too_long = "あ" * (config.PROMPT_BODY_MAX_LENGTH + 1)

    response = client.post("/api/transforms", json={"input_image_id": image["id"], "prompt_body": too_long})

    assert _detail(response) == f"本文は {config.PROMPT_BODY_MAX_LENGTH} 文字以内で入力してください。"
    assert provider.calls == []


@pytest.mark.parametrize(
    ("payload", "expected"),
    [
        ({"monthly_budget_usd": 0}, "月の予算は 0 より大きい値で指定してください。"),
        ({"monthly_budget_usd": 99999999}, f"月の予算は {config.MONTHLY_BUDGET_MAX_USD} 以下で指定してください。"),
        ({"monthly_budget_usd": "abc"}, "月の予算の値が正しくありません。"),
    ],
)
def test_budget_messages(client, payload, expected):
    assert _detail(client.put("/api/settings", json=payload)) == expected


def test_rating_messages(client):
    image = upload(client)
    url = f"/api/images/{image['id']}"

    assert _detail(client.patch(url, json={"rating": 6})) == f"評価は {config.RATING_MAX} 以下で指定してください。"
    assert _detail(client.patch(url, json={"rating": 0})) == f"評価は {config.RATING_MIN} 以上で指定してください。"


def test_unknown_field_and_broken_json_get_generic_message(client):
    assert _detail(client.get("/api/images/abc")) == "入力内容を確認してください。"
    response = client.post("/api/genres", content=b"{not json", headers={"Content-Type": "application/json"})
    assert _detail(response) == "入力内容を確認してください。"


def test_input_value_is_never_echoed(client):
    """既定の 422 応答は入力値をそのまま返す。API キーなどが応答に載らないことを確かめる。"""
    secret_like = ["sk-should-not-appear-in-response"]

    response = client.put("/api/api-keys/openai", json={"key": secret_like})

    assert _detail(response) == "API キーの値が正しくありません。"
    assert "should-not-appear" not in response.text


# ---------- 変換結果を保存できなかった場合 ----------

@pytest.mark.parametrize(
    ("error", "expected"),
    [
        (OSError("disk full"), "ディスクの空き容量"),
        (InvalidImageError("画像として読み込めません。"), "画像として読み込めません"),
    ],
    ids=["disk error", "not an image"],
)
def test_failure_while_saving_result_keeps_history_and_cost(client, monkeypatch, error, expected):
    """課金済みの変換は、結果を保存できなくても履歴と料金に残す。"""
    image = upload(client)
    original_add = ImageStore.add

    def failing_add(self, conn, kind, data, original_name=None):
        if kind == "result":
            raise error
        return original_add(self, conn, kind, data, original_name)

    monkeypatch.setattr(ImageStore, "add", failing_add)

    transform = run_transform(client, image["id"])

    assert transform["status"] == "failed" and expected in transform["error_message"]
    assert transform["cost_usd"] == pytest.approx(FAKE_COST_USD) and transform["output_image"] is None
    assert "disk full" not in transform["error_message"], "例外の本文は出さない"
    assert client.get("/api/costs/summary").json()["total_usd"] == pytest.approx(FAKE_COST_USD)
    failed = client.get("/api/transforms", params={"status": "failed"}).json()
    assert [item["id"] for item in failed] == [transform["id"]]


# ---------- コードレビュー（2026-11-19）の指摘 ----------

def test_prompt_deleted_during_transform_still_records_history_and_cost(client, provider, tmp_path):
    """変換の実行中（1〜2 分）に、使ったプロンプトが削除されても、課金済みの変換を履歴から落とさない。"""
    import sqlite3

    image = upload(client)
    prompt = client.post("/api/prompts", json={"title": "水彩", "body": "水彩画風にする"}).json()
    original_transform = provider.transform

    def delete_prompt_then_transform(image_path, text, keep_aspect=True):
        conn = sqlite3.connect(tmp_path / config.DB_FILE_NAME)
        with conn:
            conn.execute("DELETE FROM prompts WHERE id = ?", (prompt["id"],))
        conn.close()
        return original_transform(image_path, text, keep_aspect)

    provider.transform = delete_prompt_then_transform

    response = client.post(
        "/api/transforms",
        json={"input_image_id": image["id"], "prompt_body": "水彩画風にする", "prompt_title": "水彩",
              "prompt_id": prompt["id"]},
    )

    assert response.status_code == 201
    transform = response.json()
    assert transform["status"] == "success" and transform["prompt_id"] is None
    assert (transform["prompt_title"], transform["prompt_body"]) == ("水彩", "水彩画風にする")
    assert client.get("/api/costs/summary").json()["total_usd"] == pytest.approx(FAKE_COST_USD)


@pytest.mark.parametrize("name", ["openai", "grok", "gemini"])
def test_unexpected_shape_of_success_response_keeps_cost(name, tmp_path, monkeypatch):
    """HTTP 200 の応答が想定外の形でも、課金済みとして料金を残す（料金 0 の失敗にしない）。"""
    import httpx

    from app.providers.gemini_provider import GeminiProvider
    from app.providers.grok_provider import GrokProvider
    from app.providers.openai_provider import OpenAIProvider
    from tests.fakes import image_bytes

    cases = {
        "openai": (OpenAIProvider, "OPENAI_API_KEY", {"data": [{"b64_json": 12345}], "usage": ["not", "a", "dict"]}),
        "grok": (GrokProvider, "XAI_API_KEY", {"data": [{"b64_json": 12345}]}),
        "gemini": (GeminiProvider, "GEMINI_API_KEY",
                   {"candidates": [{"content": {"parts": [{"inlineData": {"data": 12345}}]}}],
                    "usageMetadata": {"promptTokenCount": "many"}}),
    }
    provider_class, env_name, body = cases[name]
    monkeypatch.setenv(env_name, "dummy-key-for-test")
    source = tmp_path / "in.png"
    source.write_bytes(image_bytes())
    provider = provider_class(transport=httpx.MockTransport(lambda request: httpx.Response(200, json=body)))

    result = provider.transform(source, "x")

    assert not result.ok and result.billed_on_failure
    assert result.cost_usd > 0 and "読み取れませんでした" in result.error
