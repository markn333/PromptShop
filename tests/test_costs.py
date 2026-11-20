"""料金の集計と、月の予算のテスト。"""
import sqlite3
from datetime import datetime, timedelta, timezone

import pytest

from app import config, db
from app.providers.base import TransformResult
from app.services import costs
from tests.fakes import FAKE_COST_USD, FAKE_MODEL, run_transform, upload

JST = timezone(timedelta(hours=9))
NOW_JST = datetime(2026, 11, 19, 12, 0, tzinfo=JST)


@pytest.fixture
def conn(client, tmp_path):
    """テスト用データベースへの接続（client がテーブルを作ったあとで開く）。"""
    connection = db.connect(tmp_path / config.DB_FILE_NAME)
    yield connection
    connection.close()


def _add(conn: sqlite3.Connection, created_at: str, cost: float, provider="openai", status="success") -> None:
    """実行日時を指定して、履歴を直接 1 行入れる。"""
    with conn:
        image_id = conn.execute(
            "INSERT INTO images (kind, file_path, created_at) VALUES ('source', 'sources/x.png', ?)", (created_at,)
        ).lastrowid
        conn.execute(
            "INSERT INTO transforms (input_image_id, prompt_title, prompt_body, provider, model, status,"
            " cost_usd, created_at) VALUES (?, 't', 'b', ?, 'm', ?, ?, ?)",
            (image_id, provider, status, cost, created_at),
        )


# ---------- 月の区切り ----------

@pytest.mark.parametrize(
    ("created_at", "expected"),
    [
        ("2026-10-31T14:59:59+00:00", "2026-10"),  # 日本時間 10/31 23:59:59
        ("2026-10-31T15:00:00+00:00", "2026-11"),  # 日本時間 11/1 0:00:00
        ("2026-11-30T14:59:59+00:00", "2026-11"),
        ("2026-11-30T15:00:00+00:00", "2026-12"),
        ("2026-12-31T15:00:00+00:00", "2027-01"),  # 年またぎ
    ],
)
def test_month_boundary_is_local_midnight(created_at, expected):
    assert costs.month_key(created_at, NOW_JST) == expected


def test_summary_counts_only_this_local_month(conn):
    _add(conn, "2026-10-31T14:59:59+00:00", 1.00)   # 先月の最後の 1 秒
    _add(conn, "2026-10-31T15:00:00+00:00", 0.10)   # 今月の最初の 1 秒
    _add(conn, "2026-11-19T03:00:00+00:00", 0.20)
    _add(conn, "2026-11-30T15:00:00+00:00", 5.00)   # 来月

    summary = costs.month_summary(conn, NOW_JST)

    assert summary["month"] == "2026-11"
    assert summary["total_usd"] == pytest.approx(0.30)
    assert summary["count"] == 2


def test_monthly_totals_newest_first(conn):
    _add(conn, "2026-09-10T00:00:00+00:00", 0.50)
    _add(conn, "2026-10-31T14:59:59+00:00", 1.00)
    _add(conn, "2026-10-31T15:00:00+00:00", 0.10)
    _add(conn, "2026-11-19T03:00:00+00:00", 0.20, status="failed")

    monthly = costs.monthly_totals(conn, NOW_JST)

    assert [(row["month"], row["count"]) for row in monthly] == [("2026-11", 2), ("2026-10", 1), ("2026-09", 1)]
    assert [row["total_usd"] for row in monthly] == pytest.approx([0.30, 1.00, 0.50])
    assert monthly[0]["failed_count"] == 1


def test_summary_breaks_down_by_provider(conn):
    _add(conn, "2026-11-01T00:00:00+00:00", 0.05, provider="openai")
    _add(conn, "2026-11-02T00:00:00+00:00", 0.07, provider="openai")
    _add(conn, "2026-11-03T00:00:00+00:00", 0.04, provider="gemini", status="failed")

    summary = costs.month_summary(conn, NOW_JST)

    by_name = {entry["provider"]: entry for entry in summary["providers"]}
    assert by_name["openai"]["total_usd"] == pytest.approx(0.12) and by_name["openai"]["count"] == 2
    assert by_name["gemini"]["total_usd"] == pytest.approx(0.04), "課金された失敗は合計に含める"
    assert by_name["gemini"]["failed_count"] == 1
    assert summary["total_usd"] == pytest.approx(0.16) and summary["failed_count"] == 1


def test_sum_has_no_floating_point_noise(conn):
    for _ in range(3):
        _add(conn, "2026-11-01T00:00:00+00:00", 0.1)

    assert costs.month_summary(conn, NOW_JST)["total_usd"] == 0.3


# ---------- API ----------

def test_summary_with_no_history(client):
    summary = client.get("/api/costs/summary").json()

    assert summary["total_usd"] == 0 and summary["count"] == 0 and summary["providers"] == []
    assert summary["budget_usd"] is None and summary["remaining_usd"] is None
    assert summary["over_budget"] is False
    assert client.get("/api/costs/monthly").json() == []


def test_summary_after_transforms(client, provider):
    source = upload(client)
    run_transform(client, source["id"])
    run_transform(client, source["id"])
    # 課金されない失敗（料金 0）も、回数には数える
    provider.result = TransformResult(model=FAKE_MODEL, error="接続できませんでした")
    run_transform(client, source["id"])

    summary = client.get("/api/costs/summary").json()

    assert summary["total_usd"] == pytest.approx(FAKE_COST_USD * 2)
    assert (summary["count"], summary["failed_count"]) == (3, 1)
    assert summary["providers"] == [
        {"provider": "openai", "label": "Fake", "total_usd": pytest.approx(FAKE_COST_USD * 2),
         "count": 3, "failed_count": 1}
    ]
    monthly = client.get("/api/costs/monthly").json()
    assert len(monthly) == 1 and monthly[0]["month"] == summary["month"]


def test_unknown_provider_in_history_uses_its_name_as_label(client, conn):
    _add(conn, db.now_iso(), 0.02, provider="retired")

    providers = client.get("/api/costs/summary").json()["providers"]

    assert providers[0]["label"] == "retired"


# ---------- 月の予算 ----------

def test_budget_can_be_set_and_cleared(client):
    assert client.get("/api/settings").json() == {"monthly_budget_usd": None}

    assert client.put("/api/settings", json={"monthly_budget_usd": 5}).json() == {"monthly_budget_usd": 5.0}
    assert client.get("/api/settings").json() == {"monthly_budget_usd": 5.0}
    assert client.put("/api/settings", json={"monthly_budget_usd": 2.5}).json() == {"monthly_budget_usd": 2.5}

    assert client.put("/api/settings", json={"monthly_budget_usd": None}).json() == {"monthly_budget_usd": None}
    assert client.get("/api/costs/summary").json()["budget_usd"] is None


@pytest.mark.parametrize(
    "payload",
    [{"monthly_budget_usd": 0}, {"monthly_budget_usd": -1}, {"monthly_budget_usd": "abc"},
     {"monthly_budget_usd": config.MONTHLY_BUDGET_MAX_USD + 1}, {}],
    ids=["zero", "negative", "text", "too large", "missing"],
)
def test_budget_rejects_invalid_values(client, payload):
    assert client.put("/api/settings", json=payload).status_code == 422
    assert client.get("/api/settings").json() == {"monthly_budget_usd": None}


def test_remaining_and_over_budget(client):
    source = upload(client)
    run_transform(client, source["id"])

    client.put("/api/settings", json={"monthly_budget_usd": 1})
    under = client.get("/api/costs/summary").json()
    assert under["remaining_usd"] == pytest.approx(1 - FAKE_COST_USD) and under["over_budget"] is False

    client.put("/api/settings", json={"monthly_budget_usd": FAKE_COST_USD})
    reached = client.get("/api/costs/summary").json()
    assert reached["remaining_usd"] == pytest.approx(0) and reached["over_budget"] is True

    run_transform(client, source["id"])
    over = client.get("/api/costs/summary").json()
    assert over["remaining_usd"] == pytest.approx(-FAKE_COST_USD) and over["over_budget"] is True


def test_over_budget_does_not_block_transform(client):
    """予算は目安。超えていても、サーバーは変換を止めない（確認は画面で出す）。"""
    source = upload(client)
    client.put("/api/settings", json={"monthly_budget_usd": 0.01})
    run_transform(client, source["id"])

    assert run_transform(client, source["id"])["status"] == "success"
