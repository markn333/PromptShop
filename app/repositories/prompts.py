"""prompts テーブルの読み書き。"""
import sqlite3
from dataclasses import dataclass
from typing import Optional

from app.db import now_iso
from app.errors import InvalidReferenceError, NotFoundError

_COLUMNS = "id, title, body, genre_id, created_at, updated_at"
_LIKE_ESCAPE = "\\"


@dataclass(frozen=True)
class PromptFilter:
    """一覧の絞り込み条件。指定しない項目は絞り込まない。"""

    genre_id: Optional[int] = None
    unclassified: bool = False
    keyword: Optional[str] = None


def _like_pattern(keyword: str) -> str:
    """キーワード中の % と _ をワイルドカードとして扱わせない部分一致パターンを作る。"""
    escaped = keyword.replace(_LIKE_ESCAPE, _LIKE_ESCAPE * 2).replace("%", "\\%").replace("_", "\\_")
    return f"%{escaped}%"


def _build_where(prompt_filter: PromptFilter) -> tuple[str, list]:
    """絞り込み条件から WHERE 句とパラメーターを作る。値は必ずプレースホルダーで渡す。"""
    conditions: list[str] = []
    params: list = []
    if prompt_filter.unclassified:
        conditions.append("genre_id IS NULL")
    elif prompt_filter.genre_id is not None:
        conditions.append("genre_id = ?")
        params.append(prompt_filter.genre_id)
    if prompt_filter.keyword:
        pattern = _like_pattern(prompt_filter.keyword)
        conditions.append("(title LIKE ? ESCAPE '\\' OR body LIKE ? ESCAPE '\\')")
        params.extend([pattern, pattern])
    where = f"WHERE {' AND '.join(conditions)}" if conditions else ""
    return where, params


def list_prompts(conn: sqlite3.Connection, prompt_filter: PromptFilter = PromptFilter()) -> list[dict]:
    """条件に合うプロンプトをタイトル順で返す。"""
    where, params = _build_where(prompt_filter)
    sql = f"SELECT {_COLUMNS} FROM prompts {where} ORDER BY title COLLATE NOCASE, id"
    return [dict(row) for row in conn.execute(sql, params).fetchall()]


def get_prompt(conn: sqlite3.Connection, prompt_id: int) -> dict:
    """1 件返す。なければ NotFoundError。"""
    row = conn.execute(f"SELECT {_COLUMNS} FROM prompts WHERE id = ?", (prompt_id,)).fetchone()
    if row is None:
        raise NotFoundError("プロンプトが見つかりません。")
    return dict(row)


def create_prompt(conn: sqlite3.Connection, title: str, body: str, genre_id: Optional[int]) -> dict:
    """登録する。存在しないジャンルを指定すると InvalidReferenceError。"""
    timestamp = now_iso()
    try:
        with conn:
            cursor = conn.execute(
                "INSERT INTO prompts (title, body, genre_id, created_at, updated_at) VALUES (?, ?, ?, ?, ?)",
                (title, body, genre_id, timestamp, timestamp),
            )
    except sqlite3.IntegrityError as exc:
        raise InvalidReferenceError("指定されたジャンルが見つかりません。") from exc
    return get_prompt(conn, cursor.lastrowid)


def update_prompt(conn: sqlite3.Connection, prompt_id: int, title: str, body: str, genre_id: Optional[int]) -> dict:
    """タイトル・本文・ジャンルを置き換える。"""
    try:
        with conn:
            cursor = conn.execute(
                "UPDATE prompts SET title = ?, body = ?, genre_id = ?, updated_at = ? WHERE id = ?",
                (title, body, genre_id, now_iso(), prompt_id),
            )
    except sqlite3.IntegrityError as exc:
        raise InvalidReferenceError("指定されたジャンルが見つかりません。") from exc
    if cursor.rowcount == 0:
        raise NotFoundError("プロンプトが見つかりません。")
    return get_prompt(conn, prompt_id)


def delete_prompt(conn: sqlite3.Connection, prompt_id: int) -> None:
    """削除する。変換履歴は実行時点のタイトルと本文を持っているので残る。"""
    with conn:
        cursor = conn.execute("DELETE FROM prompts WHERE id = ?", (prompt_id,))
    if cursor.rowcount == 0:
        raise NotFoundError("プロンプトが見つかりません。")
