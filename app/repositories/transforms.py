"""transforms テーブル（変換の履歴）の読み書き。"""
import sqlite3
from dataclasses import dataclass
from typing import Optional

from app import config
from app.db import now_iso
from app.errors import NotFoundError

_COLUMNS = (
    "id, input_image_id, output_image_id, prompt_id, prompt_title, prompt_body,"
    " provider, model, status, error_message, cost_usd, created_at"
)

STATUS_SUCCESS = "success"
STATUS_FAILED = "failed"


@dataclass(frozen=True)
class NewTransform:
    """記録する変換 1 回分。prompt_title と prompt_body は実行時点の内容。"""

    input_image_id: int
    output_image_id: Optional[int]
    prompt_id: Optional[int]
    prompt_title: str
    prompt_body: str
    provider: str
    model: str
    status: str
    error_message: Optional[str]
    cost_usd: float


@dataclass(frozen=True)
class TransformFilter:
    """履歴一覧の絞り込み条件。指定しない項目は絞り込まない。"""

    input_image_id: Optional[int] = None
    prompt_id: Optional[int] = None
    status: Optional[str] = None
    # 指定すると、id がこれより大きい（新しい）履歴だけを返す
    after_id: Optional[int] = None


def create_transform(conn: sqlite3.Connection, record: NewTransform) -> dict:
    """履歴を 1 行追加する。"""
    with conn:
        cursor = conn.execute(
            "INSERT INTO transforms (input_image_id, output_image_id, prompt_id, prompt_title, prompt_body,"
            " provider, model, status, error_message, cost_usd, created_at)"
            " VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (
                record.input_image_id, record.output_image_id, record.prompt_id, record.prompt_title,
                record.prompt_body, record.provider, record.model, record.status, record.error_message,
                record.cost_usd, now_iso(),
            ),
        )
    return get_transform(conn, cursor.lastrowid)


def get_transform(conn: sqlite3.Connection, transform_id: int) -> dict:
    """1 件返す。なければ NotFoundError。"""
    row = conn.execute(f"SELECT {_COLUMNS} FROM transforms WHERE id = ?", (transform_id,)).fetchone()
    if row is None:
        raise NotFoundError("変換の履歴が見つかりません。")
    return dict(row)


def find_by_output(conn: sqlite3.Connection, output_image_id: int) -> Optional[dict]:
    """指定した画像を出力した変換を返す。取り込んだ元画像など、変換で作られていなければ None。"""
    row = conn.execute(
        f"SELECT {_COLUMNS} FROM transforms WHERE output_image_id = ? ORDER BY id LIMIT 1", (output_image_id,)
    ).fetchone()
    return dict(row) if row is not None else None


def list_costs(conn: sqlite3.Connection) -> list[dict]:
    """料金の集計に使う項目だけを、全履歴について古い順に返す。"""
    rows = conn.execute("SELECT created_at, provider, status, cost_usd FROM transforms ORDER BY id").fetchall()
    return [dict(row) for row in rows]


def max_id(conn: sqlite3.Connection) -> int:
    """いちばん新しい履歴の id。履歴がなければ 0。"""
    row = conn.execute("SELECT COALESCE(MAX(id), 0) AS value FROM transforms").fetchone()
    return row["value"]


def list_transforms(
    conn: sqlite3.Connection,
    transform_filter: TransformFilter = TransformFilter(),
    limit: int = config.IMAGE_LIST_LIMIT,
) -> list[dict]:
    """条件に合う履歴を新しい順に返す。"""
    candidates = {
        "input_image_id = ?": transform_filter.input_image_id,
        "prompt_id = ?": transform_filter.prompt_id,
        "status = ?": transform_filter.status,
        "id > ?": transform_filter.after_id,
    }
    conditions = [clause for clause, value in candidates.items() if value is not None]
    params = [value for value in candidates.values() if value is not None]
    where = f"WHERE {' AND '.join(conditions)}" if conditions else ""
    sql = f"SELECT {_COLUMNS} FROM transforms {where} ORDER BY id DESC LIMIT ?"
    return [dict(row) for row in conn.execute(sql, [*params, limit]).fetchall()]
