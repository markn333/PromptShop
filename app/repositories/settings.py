"""settings テーブル（キーと値）の読み書き。"""
import sqlite3
from typing import Optional


def get_setting(conn: sqlite3.Connection, key: str) -> Optional[str]:
    """値を返す。未設定なら None。"""
    row = conn.execute("SELECT value FROM settings WHERE key = ?", (key,)).fetchone()
    return row["value"] if row is not None else None


def set_setting(conn: sqlite3.Connection, key: str, value: str) -> None:
    """値を保存する。すでにあれば置き換える。"""
    with conn:
        conn.execute(
            "INSERT INTO settings (key, value) VALUES (?, ?)"
            " ON CONFLICT(key) DO UPDATE SET value = excluded.value",
            (key, value),
        )


def delete_setting(conn: sqlite3.Connection, key: str) -> None:
    """値を消す（未設定に戻す）。"""
    with conn:
        conn.execute("DELETE FROM settings WHERE key = ?", (key,))
