"""作風の読み取り（画像からプロンプトの下書きを作る）の API・履歴・料金のテスト。実際の API は呼ばない。"""
import pytest

from app import config
from app.analyzers.base import AnalysisResult
from app.services.analysis import split_draft
from tests.fakes import FAKE_ANALYSIS_COST_USD, FAKE_COST_USD, FakeAnalyzer, make_client, run_transform, upload


def _analyze(client, target_id, **overrides):
    payload = {"image_id": target_id, "provider": "openai", "language": "ja"}
    payload.update(overrides)
    return client.post("/api/analyses", json=payload)


# ---------- 下書きの切り分け ----------

@pytest.mark.parametrize(
    "text, expected",
    [
        ("淡い水彩\n\nにじみのある水彩で描く。", ("淡い水彩", "にじみのある水彩で描く。")),
        ("# 「淡い水彩」\n本文 1 行目\n本文 2 行目", ("淡い水彩", "本文 1 行目\n本文 2 行目")),
        ("タイトル: 淡い水彩\n\n本文", ("淡い水彩", "本文")),
        ("Title: Soft watercolor\n\nRedraw the image.", ("Soft watercolor", "Redraw the image.")),
        ("```\n淡い水彩\n\n本文\n```", ("淡い水彩", "本文")),
        ("本文だけが 1 行で返った。", ("", "本文だけが 1 行で返った。")),
        ("  \n\n", ("", "")),
    ],
)
def test_split_draft(text, expected):
    assert split_draft(text) == expected


def test_split_draft_cuts_overlong_text():
    title, body = split_draft("あ" * 300 + "\n\n" + "い" * 9000)

    assert len(title) == config.PROMPT_TITLE_MAX_LENGTH and len(body) == config.PROMPT_BODY_MAX_LENGTH


# ---------- API ----------

def test_success_returns_draft_and_records_cost(client, analyzer):
    image = upload(client)

    response = _analyze(client, image["id"], language="en")

    assert response.status_code == 201
    draft = response.json()
    assert (draft["status"], draft["title"], draft["error_message"]) == ("success", "淡い水彩", None)
    assert draft["body"].startswith("にじみのある淡い水彩")
    assert (draft["provider"], draft["model"], draft["language"]) == ("openai", "fake-text-1", "en")
    assert draft["cost_usd"] == pytest.approx(FAKE_ANALYSIS_COST_USD)
    assert len(analyzer.calls) == 1 and analyzer.calls[0][1] == "en"


def test_result_image_can_be_analyzed(client, analyzer):
    source = upload(client)
    result = run_transform(client, source["id"])["output_image"]

    assert _analyze(client, result["id"]).json()["status"] == "success"
    assert analyzer.calls[0][0].exists()


def test_language_defaults_to_japanese(client, analyzer):
    image = upload(client)

    client.post("/api/analyses", json={"image_id": image["id"]})

    assert analyzer.calls[0][1] == "ja"


def test_draft_is_not_saved_as_prompt(client):
    image = upload(client)

    _analyze(client, image["id"])

    assert client.get("/api/prompts").json() == [], "下書きは、利用者が保存を押すまでプロンプトにしない"


def test_failure_is_recorded_with_cost(tmp_path, provider):
    failing = FakeAnalyzer(AnalysisResult(model="fake-text-1", cost_usd=0.01, error="拒否されました", billed_on_failure=True))
    client = make_client(tmp_path, provider, failing)
    image = upload(client)

    draft = _analyze(client, image["id"]).json()

    assert (draft["status"], draft["error_message"], draft["body"]) == ("failed", "拒否されました", None)
    assert client.get("/api/costs/summary").json()["total_usd"] == pytest.approx(0.01)


def test_exception_becomes_failed_history(client, analyzer):
    analyzer.raises = RuntimeError("secret detail")
    image = upload(client)

    draft = _analyze(client, image["id"]).json()

    assert draft["status"] == "failed" and "RuntimeError" in draft["error_message"]
    assert "secret detail" not in draft["error_message"]


def test_empty_body_is_treated_as_failure_but_keeps_cost(tmp_path, provider):
    blank = FakeAnalyzer(AnalysisResult(model="fake-text-1", text="```\n```", cost_usd=0.02))
    client = make_client(tmp_path, provider, blank)
    image = upload(client)

    draft = _analyze(client, image["id"]).json()

    assert draft["status"] == "failed" and draft["cost_usd"] == pytest.approx(0.02)


@pytest.mark.parametrize(
    "overrides, expected_status",
    [
        ({"image_id": 999}, 404),
        ({"provider": "nobody"}, 400),
        ({"language": "fr"}, 422),
    ],
)
def test_invalid_request_does_not_call_analyzer(client, analyzer, overrides, expected_status):
    image = upload(client)

    response = _analyze(client, image["id"], **overrides)

    assert response.status_code == expected_status and analyzer.calls == []


def test_unconfigured_analyzer_is_rejected_before_calling(tmp_path, provider):
    unconfigured = FakeAnalyzer(configured=False)
    client = make_client(tmp_path, provider, unconfigured)
    image = upload(client)

    response = _analyze(client, image["id"])

    assert response.status_code == 400 and "API キー" in response.json()["detail"]
    assert unconfigured.calls == []


def test_deleted_image_cannot_be_analyzed(client, analyzer):
    image = upload(client)
    client.delete(f"/api/images/{image['id']}")

    assert _analyze(client, image["id"]).status_code == 404 and analyzer.calls == []


def test_request_from_other_site_is_rejected(client, analyzer):
    image = upload(client)

    response = client.post(
        "/api/analyses", json={"image_id": image["id"]}, headers={"Origin": "https://evil.example"}
    )

    assert response.status_code == 403 and analyzer.calls == []


def test_analyzers_endpoint(client):
    assert client.get("/api/analyzers").json() == [
        {"name": "openai", "label": "Fake", "model": "fake-text-1", "configured": True, "default": True}
    ]


# ---------- 料金 ----------

def test_costs_include_analyses_and_show_them_separately(client):
    image = upload(client)
    run_transform(client, image["id"])
    _analyze(client, image["id"])
    _analyze(client, image["id"])

    summary = client.get("/api/costs/summary").json()
    monthly = client.get("/api/costs/monthly").json()

    total = FAKE_COST_USD + 2 * FAKE_ANALYSIS_COST_USD
    assert summary["total_usd"] == pytest.approx(total) and summary["count"] == 3
    assert summary["analysis_count"] == 2
    assert summary["analysis_usd"] == pytest.approx(2 * FAKE_ANALYSIS_COST_USD)
    assert [(entry["provider"], entry["count"]) for entry in summary["providers"]] == [("openai", 3)]
    assert monthly[0]["total_usd"] == pytest.approx(total) and monthly[0]["count"] == 3


def test_summary_without_analyses(client):
    summary = client.get("/api/costs/summary").json()

    assert summary["analysis_count"] == 0 and summary["analysis_usd"] == 0


def test_old_database_gets_analysis_table(tmp_path, provider):
    """読み取りの機能がなかった版のデータベースでも、そのまま開けて使える。"""
    import sqlite3

    first = make_client(tmp_path, provider)
    image = upload(first)
    conn = sqlite3.connect(tmp_path / config.DB_FILE_NAME)
    with conn:
        conn.execute("DROP TABLE analyses")
    conn.close()

    second = make_client(tmp_path, provider)

    assert _analyze(second, image["id"]).json()["status"] == "success"
