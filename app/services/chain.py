"""変換の連鎖（最初の元画像から、指定した画像までの道のり）をたどる。"""
import sqlite3

from app.repositories import images as image_repo
from app.repositories import transforms as transform_repo


def chain_of(conn: sqlite3.Connection, image_id: int) -> tuple[dict, list[dict]]:
    """指定した画像と、そこへ至る変換の履歴（古い順）を返す。

    取り込んだ元画像なら履歴は空。途中の画像が削除済みでも、履歴は残っているのでたどれる。
    """
    image = image_repo.get_image(conn, image_id, include_deleted=True)
    steps: list[dict] = []
    visited = {image_id}
    current = image_id
    while True:
        transform = transform_repo.find_by_output(conn, current)
        if transform is None:
            break
        steps.append(transform)
        current = transform["input_image_id"]
        # データが壊れて輪になっていても、止まるようにする
        if current in visited:
            break
        visited.add(current)
    steps.reverse()
    return image, steps
