"""SQLite の接続とテーブル作成。"""
import sqlite3
from datetime import datetime, timezone
from pathlib import Path

SCHEMA = """
CREATE TABLE IF NOT EXISTS genres (
    id          INTEGER PRIMARY KEY,
    name        TEXT    NOT NULL UNIQUE,
    sort_order  INTEGER NOT NULL DEFAULT 0
);

CREATE TABLE IF NOT EXISTS prompts (
    id          INTEGER PRIMARY KEY,
    title       TEXT    NOT NULL,
    body        TEXT    NOT NULL,
    genre_id    INTEGER REFERENCES genres(id) ON DELETE SET NULL,
    created_at  TEXT    NOT NULL,
    updated_at  TEXT    NOT NULL
);

CREATE TABLE IF NOT EXISTS images (
    id             INTEGER PRIMARY KEY,
    kind           TEXT    NOT NULL CHECK (kind IN ('source', 'result')),
    file_path      TEXT    NOT NULL,
    thumb_path     TEXT,
    original_name  TEXT,
    width          INTEGER,
    height         INTEGER,
    favorite       INTEGER NOT NULL DEFAULT 0,
    rating         INTEGER CHECK (rating IS NULL OR rating BETWEEN 1 AND 5),
    deleted        INTEGER NOT NULL DEFAULT 0,
    created_at     TEXT    NOT NULL,
    example        INTEGER NOT NULL DEFAULT 0
);

CREATE TABLE IF NOT EXISTS transforms (
    id               INTEGER PRIMARY KEY,
    input_image_id   INTEGER NOT NULL REFERENCES images(id),
    output_image_id  INTEGER REFERENCES images(id),
    prompt_id        INTEGER REFERENCES prompts(id) ON DELETE SET NULL,
    prompt_title     TEXT    NOT NULL,
    prompt_body      TEXT    NOT NULL,
    provider         TEXT    NOT NULL,
    model            TEXT    NOT NULL,
    status           TEXT    NOT NULL CHECK (status IN ('success', 'failed')),
    error_message    TEXT,
    cost_usd         REAL    NOT NULL DEFAULT 0,
    created_at       TEXT    NOT NULL
);

CREATE TABLE IF NOT EXISTS analyses (
    id             INTEGER PRIMARY KEY,
    image_id       INTEGER NOT NULL REFERENCES images(id),
    provider       TEXT    NOT NULL,
    model          TEXT    NOT NULL,
    language       TEXT    NOT NULL,
    status         TEXT    NOT NULL CHECK (status IN ('success', 'failed')),
    error_message  TEXT,
    title          TEXT,
    body           TEXT,
    cost_usd       REAL    NOT NULL DEFAULT 0,
    created_at     TEXT    NOT NULL
);

CREATE TABLE IF NOT EXISTS settings (
    key    TEXT PRIMARY KEY,
    value  TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_prompts_genre ON prompts(genre_id);
CREATE INDEX IF NOT EXISTS idx_transforms_input ON transforms(input_image_id);
CREATE INDEX IF NOT EXISTS idx_transforms_output ON transforms(output_image_id);
CREATE INDEX IF NOT EXISTS idx_transforms_created ON transforms(created_at);
"""


def connect(db_path: Path) -> sqlite3.Connection:
    """データベースへ接続する。呼び出し側が close すること。"""
    # FastAPI は依存関係と処理本体を別スレッドで動かすことがあるため、スレッドの一致検査を外す。
    # 接続はリクエストごとに作って閉じるので、複数スレッドから同時に使われることはない。
    conn = sqlite3.connect(db_path, check_same_thread=False)
    conn.row_factory = sqlite3.Row
    # SQLite は既定で外部キーを検査しない。ジャンル削除時の SET NULL に必要。
    conn.execute("PRAGMA foreign_keys = ON")
    return conn


def init_db(db_path: Path) -> None:
    """保存先フォルダとテーブルがなければ作る。"""
    db_path.parent.mkdir(parents=True, exist_ok=True)
    conn = connect(db_path)
    try:
        with conn:
            conn.executescript(SCHEMA)
            _add_missing_columns(conn)
    finally:
        conn.close()


# あとから足した列。古い版で作ったデータベースには、起動時に足す（中身は消さない）。
# (テーブル名, 列名, 列の定義)。ここに書くのは固定の語だけで、外から受け取った値は入れない。
_ADDED_COLUMNS = (
    ("images", "example", "INTEGER NOT NULL DEFAULT 0"),
)


def _add_missing_columns(conn: sqlite3.Connection) -> None:
    """古い版のデータベースに、あとから足した列を追加する。"""
    for table, column, definition in _ADDED_COLUMNS:
        existing = {row["name"] for row in conn.execute(f"PRAGMA table_info({table})")}
        if column not in existing:
            conn.execute(f"ALTER TABLE {table} ADD COLUMN {column} {definition}")


def now_iso() -> str:
    """保存用の現在時刻（UTC、秒まで）。"""
    return datetime.now(timezone.utc).isoformat(timespec="seconds")
