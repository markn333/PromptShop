"""genres テーブルの読み書き。"""
import sqlite3
from typing import Optional

from app.errors import DuplicateNameError, NotFoundError

_COLUMNS = "id, name, sort_order"


def list_genres(conn: sqlite3.Connection) -> list[dict]:
    """並び順どおりに全ジャンルを返す。"""
    rows = conn.execute(f"SELECT {_COLUMNS} FROM genres ORDER BY sort_order, id").fetchall()
    return [dict(row) for row in rows]


def get_genre(conn: sqlite3.Connection, genre_id: int) -> dict:
    """1 件返す。なければ NotFoundError。"""
    row = conn.execute(f"SELECT {_COLUMNS} FROM genres WHERE id = ?", (genre_id,)).fetchone()
    if row is None:
        raise NotFoundError("ジャンルが見つかりません。")
    return dict(row)


def create_genre(conn: sqlite3.Connection, name: str) -> dict:
    """末尾に追加する。同名があれば DuplicateNameError。"""
    try:
        with conn:
            next_order = conn.execute("SELECT COALESCE(MAX(sort_order), 0) + 1 FROM genres").fetchone()[0]
            cursor = conn.execute("INSERT INTO genres (name, sort_order) VALUES (?, ?)", (name, next_order))
    except sqlite3.IntegrityError as exc:
        raise DuplicateNameError(f"ジャンル「{name}」はすでにあります。") from exc
    return get_genre(conn, cursor.lastrowid)


def update_genre(
    conn: sqlite3.Connection,
    genre_id: int,
    name: Optional[str] = None,
    sort_order: Optional[int] = None,
) -> dict:
    """名前・並び順のうち、指定されたものだけを更新する。"""
    current = get_genre(conn, genre_id)
    new_name = current["name"] if name is None else name
    new_order = current["sort_order"] if sort_order is None else sort_order
    try:
        with conn:
            conn.execute("UPDATE genres SET name = ?, sort_order = ? WHERE id = ?", (new_name, new_order, genre_id))
    except sqlite3.IntegrityError as exc:
        raise DuplicateNameError(f"ジャンル「{new_name}」はすでにあります。") from exc
    return get_genre(conn, genre_id)


def delete_genre(conn: sqlite3.Connection, genre_id: int) -> None:
    """削除する。所属していたプロンプトは外部キーの SET NULL で未分類になる。"""
    with conn:
        cursor = conn.execute("DELETE FROM genres WHERE id = ?", (genre_id,))
    if cursor.rowcount == 0:
        raise NotFoundError("ジャンルが見つかりません。")
