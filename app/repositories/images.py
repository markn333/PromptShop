"""images テーブルの読み書き。"""
import sqlite3
from dataclasses import dataclass
from typing import Optional

from app import config
from app.db import now_iso
from app.errors import NotFoundError

# made_prompt_id / made_provider は、その画像を出力した変換のプロンプトとプロバイダー。
# 取り込んだ元画像や、保存していないプロンプトで作った結果では NULL になる。
# made_prompt_title は実行時点のタイトル（保存していないプロンプトでも入る。元画像では NULL）。
_COLUMNS = (
    "id, kind, file_path, thumb_path, original_name, width, height, favorite, rating, deleted, created_at, example,"
    " (SELECT t.prompt_id FROM transforms t WHERE t.output_image_id = images.id ORDER BY t.id LIMIT 1)"
    " AS made_prompt_id,"
    " (SELECT t.prompt_title FROM transforms t WHERE t.output_image_id = images.id ORDER BY t.id LIMIT 1)"
    " AS made_prompt_title,"
    " (SELECT t.provider FROM transforms t WHERE t.output_image_id = images.id ORDER BY t.id LIMIT 1)"
    " AS made_provider"
)

KIND_SOURCE = "source"
KIND_RESULT = "result"


@dataclass(frozen=True)
class NewImage:
    """登録する画像の情報。パスは保存先フォルダからの相対パス。"""

    kind: str
    file_path: str
    thumb_path: str
    width: int
    height: int
    original_name: Optional[str] = None


def create_image(conn: sqlite3.Connection, image: NewImage) -> dict:
    """画像を登録する。"""
    with conn:
        cursor = conn.execute(
            "INSERT INTO images (kind, file_path, thumb_path, original_name, width, height, created_at)"
            " VALUES (?, ?, ?, ?, ?, ?, ?)",
            (image.kind, image.file_path, image.thumb_path, image.original_name, image.width, image.height, now_iso()),
        )
    return get_image(conn, cursor.lastrowid, include_deleted=True)


def get_image(conn: sqlite3.Connection, image_id: int, include_deleted: bool = False) -> dict:
    """1 件返す。なければ NotFoundError。削除済みは include_deleted を指定したときだけ返す。"""
    row = conn.execute(f"SELECT {_COLUMNS} FROM images WHERE id = ?", (image_id,)).fetchone()
    if row is None:
        raise NotFoundError("画像が見つかりません。")
    if row["deleted"] and not include_deleted:
        raise NotFoundError("この画像は削除されています。")
    return dict(row)


@dataclass(frozen=True)
class ImageFilter:
    """画像一覧の絞り込み条件。指定しない項目は絞り込まない。

    provider と prompt_id は、その画像を作った変換の履歴で判定する（変換結果だけが当てはまる）。
    """

    kind: Optional[str] = None
    favorite_only: bool = False
    example_only: bool = False
    min_rating: Optional[int] = None
    provider: Optional[str] = None
    prompt_id: Optional[int] = None


# その画像を出力した変換が条件に合うかを調べる部分。{column} には固定の列名だけを入れる
_MADE_BY = "EXISTS (SELECT 1 FROM transforms t WHERE t.output_image_id = images.id AND t.{column} = ?)"


def list_images(
    conn: sqlite3.Connection,
    image_filter: ImageFilter = ImageFilter(),
    limit: int = config.IMAGE_LIST_LIMIT,
) -> list[dict]:
    """削除されていない画像を新しい順に返す。"""
    candidates = {
        "kind = ?": image_filter.kind,
        "rating >= ?": image_filter.min_rating,
        _MADE_BY.format(column="provider"): image_filter.provider,
        _MADE_BY.format(column="prompt_id"): image_filter.prompt_id,
    }
    conditions = ["deleted = 0"]
    if image_filter.favorite_only:
        conditions.append("favorite = 1")
    if image_filter.example_only:
        conditions.append("example = 1")
    conditions += [clause for clause, value in candidates.items() if value is not None]
    params = [value for value in candidates.values() if value is not None]
    sql = f"SELECT {_COLUMNS} FROM images WHERE {' AND '.join(conditions)} ORDER BY id DESC LIMIT ?"
    return [dict(row) for row in conn.execute(sql, [*params, limit]).fetchall()]


def set_favorite(conn: sqlite3.Connection, image_id: int, favorite: bool) -> None:
    """お気に入りを付ける・外す。"""
    with conn:
        conn.execute("UPDATE images SET favorite = ? WHERE id = ?", (int(favorite), image_id))


def set_example(conn: sqlite3.Connection, image_id: int, example: bool) -> None:
    """プロンプトの作例として登録する・外す。"""
    with conn:
        conn.execute("UPDATE images SET example = ? WHERE id = ?", (int(example), image_id))


def set_rating(conn: sqlite3.Connection, image_id: int, rating: Optional[int]) -> None:
    """評価を付ける。None で未評価に戻す。"""
    with conn:
        conn.execute("UPDATE images SET rating = ? WHERE id = ?", (rating, image_id))


def mark_deleted(conn: sqlite3.Connection, image_id: int) -> None:
    """削除済みの印を付ける。行は残す（履歴と料金から参照されるため）。"""
    with conn:
        conn.execute("UPDATE images SET deleted = 1 WHERE id = ?", (image_id,))
