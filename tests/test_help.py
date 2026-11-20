"""ヘルプ用の情報（バージョン・ライセンス）と、「失敗した変換」のクリアのテスト。"""
import pytest

from app import about, config
from app.providers.base import TransformResult
from app.services.data_location import display_path
from tests.fakes import FAKE_MODEL, FakeProvider, make_client, run_transform, upload

FAKE_KEY = "sk-test-not-a-real-key-1234"


# ---------- アプリの情報 ----------

def test_about_returns_version_license_and_locations(client, tmp_path):
    info = client.get("/api/about").json()

    assert (info["name"], info["version"]) == ("PromptShop", about.APP_VERSION)
    assert info["copyright"] == "Copyright (c) 2026 REDSUN" and info["license"] == "MIT License"
    assert info["data_dir"] == display_path(tmp_path)
    assert info["env_file"].endswith(".env")
    names = [item["name"] for item in info["third_party"]]
    assert names[0].startswith("Python") and {"FastAPI", "Pillow", "pywebview"} <= set(names)
    assert all(item["license"] and item["url"].startswith("https://") for item in info["third_party"])


def test_about_does_not_leak_api_key(client):
    client.put("/api/api-keys/openai", json={"key": FAKE_KEY})

    assert FAKE_KEY not in client.get("/api/about").text


def test_version_looks_like_a_version():
    parts = about.APP_VERSION.split(".")

    assert len(parts) == 3 and all(part.isdigit() for part in parts)


def test_bundled_license_texts_are_served_and_cover_every_component(client):
    """ヘルプ画面で開く、同梱ソフトのライセンス全文。一覧にあるものが全部入っていること。"""
    response = client.get("/static/third_party_licenses.txt")

    assert response.status_code == 200
    text = response.content.decode("utf-8")
    assert "\nPython " in text
    for item in about.THIRD_PARTY:
        assert f"\n{item['name']} " in text, f"{item['name']} のライセンスが入っていない（tools/collect_licenses.py を実行する）"


def test_help_screen_shows_license_and_disclaimer(client):
    page = client.get("/").text

    assert 'data-tab="help"' in page and 'id="panel-help"' in page
    assert "MIT License" in page and "Copyright (c) 2026 REDSUN" in page
    assert "免責事項" in page and "料金" in page and "一切の責任を負いません" in page


def test_project_license_file_matches_about():
    license_text = (config.PROJECT_ROOT / "LICENSE").read_text(encoding="utf-8")

    assert license_text.startswith("MIT License") and about.COPYRIGHT in license_text


# ---------- 「失敗した変換」のクリア ----------

@pytest.fixture
def failing(tmp_path):
    """必ず失敗し、失敗でも料金がかかる偽プロバイダーと、そのクライアント。"""
    provider = FakeProvider(
        TransformResult(model=FAKE_MODEL, cost_usd=0.03, error="拒否されました", billed_on_failure=True)
    )
    return make_client(tmp_path, provider), provider


def _failures(client):
    return client.get("/api/costs/failures").json()


def test_failures_lists_failed_transforms_only(client, tmp_path, provider):
    image = upload(client)
    run_transform(client, image["id"])
    provider.result = TransformResult(model=FAKE_MODEL, error="失敗 1")
    failed = run_transform(client, image["id"])

    listed = _failures(client)

    assert [item["id"] for item in listed] == [failed["id"]]
    assert listed[0]["error_message"] == "失敗 1" and listed[0]["input_image"]["id"] == image["id"]


def test_clear_hides_failures_but_keeps_history_and_cost(failing):
    client, _ = failing
    image = upload(client)
    run_transform(client, image["id"])
    run_transform(client, image["id"])
    before = client.get("/api/costs/summary").json()

    response = client.post("/api/costs/failures/clear")

    assert response.status_code == 200 and response.json() == {"cleared": 2}
    assert _failures(client) == []
    after = client.get("/api/costs/summary").json()
    assert (after["total_usd"], after["count"], after["failed_count"]) == (
        before["total_usd"], before["count"], before["failed_count"]
    ), "クリアしても、料金と回数は変わらない"
    assert after["total_usd"] == pytest.approx(0.06) and after["failed_count"] == 2
    assert len(client.get("/api/transforms", params={"status": "failed"}).json()) == 2, "履歴そのものは残る"


def test_failures_after_clear_are_shown_again(failing):
    client, _ = failing
    image = upload(client)
    run_transform(client, image["id"])
    client.post("/api/costs/failures/clear")

    newer = run_transform(client, image["id"])

    assert [item["id"] for item in _failures(client)] == [newer["id"]]


def test_clear_with_nothing_to_clear(client):
    assert client.post("/api/costs/failures/clear").json() == {"cleared": 0}
    assert _failures(client) == []


def test_clear_from_other_site_is_rejected(failing):
    client, _ = failing
    image = upload(client)
    run_transform(client, image["id"])

    response = client.post("/api/costs/failures/clear", headers={"Origin": "https://evil.example"})

    assert response.status_code == 403 and len(_failures(client)) == 1
