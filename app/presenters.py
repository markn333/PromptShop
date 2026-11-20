"""データベースの行を、API が返す形に変える。"""
import sqlite3
from typing import Optional

from app.repositories import images as image_repo


def image_view(image: dict) -> dict:
    """画像 1 件の応答。保存先のパスは返さず、id で取得する URL を返す。"""
    image_id = image["id"]
    is_deleted = bool(image["deleted"])
    return {
        "id": image_id,
        "kind": image["kind"],
        "original_name": image["original_name"],
        "width": image["width"],
        "height": image["height"],
        "favorite": bool(image["favorite"]),
        "rating": image["rating"],
        # 作例: この画像を作ったプロンプト（prompt_id）とプロバイダー（provider）の見本として登録したもの
        "example": bool(image["example"]),
        "prompt_id": image["made_prompt_id"],
        # 変換を実行した時点のプロンプトのタイトル（あとでプロンプトを直しても消しても変わらない）
        "prompt_title": image["made_prompt_title"],
        "provider": image["made_provider"],
        "deleted": is_deleted,
        "created_at": image["created_at"],
        "file_url": None if is_deleted else f"/api/images/{image_id}/file",
        "thumb_url": None if is_deleted else f"/api/images/{image_id}/thumb",
    }


def _image_view_by_id(conn: sqlite3.Connection, image_id: Optional[int]) -> Optional[dict]:
    if image_id is None:
        return None
    return image_view(image_repo.get_image(conn, image_id, include_deleted=True))


def transform_view(conn: sqlite3.Connection, transform: dict) -> dict:
    """履歴 1 件の応答。入力画像と出力画像の情報を添える。"""
    view = dict(transform)
    view["input_image"] = _image_view_by_id(conn, transform["input_image_id"])
    view["output_image"] = _image_view_by_id(conn, transform["output_image_id"])
    return view
