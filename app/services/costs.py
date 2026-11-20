"""使用料金の集計と、月の予算。

金額は、変換と作風の読み取りのたびに記録した概算の合計で、実際の請求額ではない。
月の区切りは、この PC の時刻（日本で使うなら日本時間）の毎月 1 日 0 時。
"""
import sqlite3
from datetime import datetime
from typing import Optional

from app import config
from app.repositories import analyses as analysis_repo
from app.repositories import settings as settings_repo
from app.repositories import transforms as transform_repo

_MONTH_FORMAT = "%Y-%m"


def local_now() -> datetime:
    """この PC の時刻（時差つき）。"""
    return datetime.now().astimezone()


def month_key(created_at: str, now: datetime) -> str:
    """UTC で保存した実行日時が、now と同じ時差で見て何年何月にあたるかを返す（例: "2026-11"）。"""
    return datetime.fromisoformat(created_at).astimezone(now.tzinfo).strftime(_MONTH_FORMAT)


def _rounded(amount: float) -> float:
    return round(amount, config.COST_ROUND_DIGITS)


def get_budget(conn: sqlite3.Connection) -> Optional[float]:
    """月の予算（USD）。未設定なら None。"""
    value = settings_repo.get_setting(conn, config.SETTING_MONTHLY_BUDGET)
    return float(value) if value is not None else None


def set_budget(conn: sqlite3.Connection, budget_usd: Optional[float]) -> None:
    """月の予算を保存する。None で未設定に戻す。"""
    if budget_usd is None:
        settings_repo.delete_setting(conn, config.SETTING_MONTHLY_BUDGET)
    else:
        settings_repo.set_setting(conn, config.SETTING_MONTHLY_BUDGET, repr(float(budget_usd)))


def _totals_by(rows: list[dict], key_of) -> dict[str, dict]:
    """行をキーごとにまとめ、合計金額・回数・失敗の回数を出す。順番は最初に現れた順。"""
    totals: dict[str, dict] = {}
    for row in rows:
        entry = totals.setdefault(key_of(row), {"total_usd": 0.0, "count": 0, "failed_count": 0})
        entry["total_usd"] += row["cost_usd"]
        entry["count"] += 1
        entry["failed_count"] += row["status"] == transform_repo.STATUS_FAILED
    for entry in totals.values():
        entry["total_usd"] = _rounded(entry["total_usd"])
    return totals


def _all_costs(conn: sqlite3.Connection) -> list[dict]:
    """変換と作風の読み取りの料金の行を合わせて返す。読み取りの行には analysis=True を付ける。"""
    transforms = [{**row, "analysis": False} for row in transform_repo.list_costs(conn)]
    analyses = [{**row, "analysis": True} for row in analysis_repo.list_costs(conn)]
    return transforms + analyses


def month_summary(conn: sqlite3.Connection, now: datetime) -> dict:
    """今月の合計、プロバイダー別の内訳、予算と残り。"""
    this_month = now.strftime(_MONTH_FORMAT)
    rows = [row for row in _all_costs(conn) if month_key(row["created_at"], now) == this_month]
    analysis_rows = [row for row in rows if row["analysis"]]
    by_provider = _totals_by(rows, lambda row: row["provider"])
    total = _rounded(sum(entry["total_usd"] for entry in by_provider.values()))
    budget = get_budget(conn)
    return {
        "month": this_month,
        "total_usd": total,
        # count と providers は、変換と作風の読み取りを合わせた数。読み取りの分だけを下の 2 項目に出す
        "count": len(rows),
        "analysis_count": len(analysis_rows),
        "analysis_usd": _rounded(sum(row["cost_usd"] for row in analysis_rows)),
        "failed_count": sum(entry["failed_count"] for entry in by_provider.values()),
        "providers": [{"provider": name, **entry} for name, entry in sorted(by_provider.items())],
        "budget_usd": budget,
        "remaining_usd": _rounded(budget - total) if budget is not None else None,
        # 予算ちょうどに達した時点で「超過」とみなす（次の 1 枚で必ず超えるため）
        "over_budget": budget is not None and total >= budget,
    }


def monthly_totals(conn: sqlite3.Connection, now: datetime) -> list[dict]:
    """月ごとの合計を新しい月から順に返す。変換も読み取りもなかった月は含まない。"""
    by_month = _totals_by(_all_costs(conn), lambda row: month_key(row["created_at"], now))
    return [{"month": month, **entry} for month, entry in sorted(by_month.items(), reverse=True)]


def failed_cleared_id(conn: sqlite3.Connection) -> int:
    """「失敗した変換」の一覧をクリアした時点の、いちばん新しい履歴の id。クリアしていなければ 0。"""
    value = settings_repo.get_setting(conn, config.SETTING_FAILED_CLEARED_ID)
    return int(value) if value is not None else 0


def visible_failures(conn: sqlite3.Connection) -> list[dict]:
    """一覧に出す失敗した変換（クリアしたあとに起きたものだけ。新しい順）。"""
    failed = transform_repo.TransformFilter(
        status=transform_repo.STATUS_FAILED, after_id=failed_cleared_id(conn)
    )
    return transform_repo.list_transforms(conn, failed)


def clear_failures(conn: sqlite3.Connection) -> int:
    """「失敗した変換」の一覧を空にする。隠すだけで、履歴と料金の記録は消さない。隠した件数を返す。"""
    hidden = len(visible_failures(conn))
    settings_repo.set_setting(conn, config.SETTING_FAILED_CLEARED_ID, str(transform_repo.max_id(conn)))
    return hidden
