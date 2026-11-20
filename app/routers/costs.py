"""使用料金と、月の予算の API。"""
import sqlite3

from fastapi import APIRouter, Depends, Request

from app.presenters import transform_view
from app.routers.deps import get_conn
from app.schemas import SettingsWrite
from app.services import costs

router = APIRouter(prefix="/api", tags=["costs"])


def _with_labels(request: Request, providers: list[dict]) -> list[dict]:
    """プロバイダー別の内訳に、画面に出す名前を添える。今は使えないプロバイダーの分は識別子のまま。"""
    known = request.app.state.providers
    return [
        {**entry, "label": known[entry["provider"]].label if entry["provider"] in known else entry["provider"]}
        for entry in providers
    ]


@router.get("/costs/summary")
def get_summary(request: Request, conn: sqlite3.Connection = Depends(get_conn)) -> dict:
    """今月の合計（概算）、プロバイダー別の内訳、予算と残り。"""
    summary = costs.month_summary(conn, costs.local_now())
    summary["providers"] = _with_labels(request, summary["providers"])
    return summary


@router.get("/costs/monthly")
def get_monthly(conn: sqlite3.Connection = Depends(get_conn)) -> list[dict]:
    """月ごとの合計（新しい月から）。"""
    return costs.monthly_totals(conn, costs.local_now())


@router.get("/costs/failures")
def get_failures(conn: sqlite3.Connection = Depends(get_conn)) -> list[dict]:
    """料金画面の「失敗した変換」に出す履歴（新しい順）。クリアしたあとに起きたものだけ。"""
    return [transform_view(conn, row) for row in costs.visible_failures(conn)]


@router.post("/costs/failures/clear")
def clear_failures(conn: sqlite3.Connection = Depends(get_conn)) -> dict:
    """「失敗した変換」の一覧を空にする。履歴・料金の記録・回数は変えない。"""
    return {"cleared": costs.clear_failures(conn)}


@router.get("/settings")
def get_settings(conn: sqlite3.Connection = Depends(get_conn)) -> dict:
    """設定の取得。"""
    return {"monthly_budget_usd": costs.get_budget(conn)}


@router.put("/settings")
def put_settings(payload: SettingsWrite, conn: sqlite3.Connection = Depends(get_conn)) -> dict:
    """設定の保存。"""
    costs.set_budget(conn, payload.monthly_budget_usd)
    return {"monthly_budget_usd": costs.get_budget(conn)}
