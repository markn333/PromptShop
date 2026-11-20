"""analyses テーブル（作風の読み取りの履歴）の読み書き。"""
import sqlite3
from dataclasses import dataclass
from typing import Optional

from app.db import now_iso

_COLUMNS = "id, image_id, provider, model, language, status, error_message, title, body, cost_usd, created_at"

STATUS_SUCCESS = "success"
STATUS_FAILED = "failed"


@dataclass(frozen=True)
class NewAnalysis:
    """記録する読み取り 1 回分。title と body は、成功したときに AI が書いた下書き。"""

    image_id: int
    provider: str
    model: str
    language: str
    status: str
    error_message: Optional[str]
    title: Optional[str]
    body: Optional[str]
    cost_usd: float


def create_analysis(conn: sqlite3.Connection, record: NewAnalysis) -> dict:
    """履歴を 1 行追加する。"""
    with conn:
        cursor = conn.execute(
            "INSERT INTO analyses (image_id, provider, model, language, status, error_message, title, body,"
            " cost_usd, created_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (
                record.image_id, record.provider, record.model, record.language, record.status,
                record.error_message, record.title, record.body, record.cost_usd, now_iso(),
            ),
        )
    row = conn.execute(f"SELECT {_COLUMNS} FROM analyses WHERE id = ?", (cursor.lastrowid,)).fetchone()
    return dict(row)


def list_costs(conn: sqlite3.Connection) -> list[dict]:
    """料金の集計に使う項目だけを、全履歴について古い順に返す。"""
    rows = conn.execute("SELECT created_at, provider, status, cost_usd FROM analyses ORDER BY id").fetchall()
    return [dict(row) for row in rows]
