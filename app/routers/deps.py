"""ルート共通の依存関係。"""
import sqlite3
from typing import Iterator

from fastapi import Request

from app import db


def get_conn(request: Request) -> Iterator[sqlite3.Connection]:
    """リクエストごとにデータベース接続を作り、終わったら閉じる。"""
    conn = db.connect(request.app.state.db_path)
    try:
        yield conn
    finally:
        conn.close()
