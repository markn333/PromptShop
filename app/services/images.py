"""画像ファイルの検証・保存・サムネイル作成。"""
import io
import logging
import sqlite3
import uuid
from dataclasses import dataclass
from pathlib import Path, PurePath
from typing import Optional

from PIL import Image, ImageOps, UnidentifiedImageError

from app import config
from app.errors import InvalidImageError, NotFoundError, TooLargeError
from app.repositories import images as image_repo
from app.repositories.images import NewImage

# Pillow が判定した形式名 → 保存時の拡張子。ここにない形式は受け付けない。
_EXTENSION_BY_FORMAT = {"PNG": "png", "JPEG": "jpg", "WEBP": "webp"}
_DIR_BY_KIND = {
    image_repo.KIND_SOURCE: config.SOURCES_DIR_NAME,
    image_repo.KIND_RESULT: config.RESULTS_DIR_NAME,
}
_BYTES_PER_MB = 1024 * 1024
_THUMB_BACKGROUND = (255, 255, 255)
_logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class ImageInfo:
    """検証済みの画像の基本情報。"""

    extension: str
    width: int
    height: int


def inspect_image(data: bytes) -> ImageInfo:
    """画像として開けるか、対応形式かを確かめる。拡張子ではなく中身で判定する。"""
    if len(data) > config.MAX_UPLOAD_BYTES:
        limit_mb = config.MAX_UPLOAD_BYTES // _BYTES_PER_MB
        raise TooLargeError(f"ファイルが大きすぎます（上限 {limit_mb} MB）。")
    try:
        with Image.open(io.BytesIO(data)) as image:
            image_format = image.format
            width, height = image.size
            image.verify()
    except (UnidentifiedImageError, OSError, SyntaxError, ValueError, Image.DecompressionBombError) as exc:
        raise InvalidImageError("画像として読み込めません。PNG / JPEG / WebP のファイルを指定してください。") from exc
    extension = _EXTENSION_BY_FORMAT.get(image_format or "")
    if extension is None:
        raise InvalidImageError("対応していない形式です。PNG / JPEG / WebP のファイルを指定してください。")
    return ImageInfo(extension=extension, width=width, height=height)


def _make_thumbnail(data: bytes) -> bytes:
    """長辺を縮めた JPEG のサムネイルを作る。透過部分は白で埋める。"""
    with Image.open(io.BytesIO(data)) as image:
        # スマホ写真などは回転情報を持つ。一覧で横倒しに見えないよう、向きを反映してから縮める。
        upright = ImageOps.exif_transpose(image).convert("RGBA")
    canvas = Image.new("RGB", upright.size, _THUMB_BACKGROUND)
    canvas.paste(upright, mask=upright.getchannel("A"))
    canvas.thumbnail((config.THUMB_MAX_PX, config.THUMB_MAX_PX))
    buffer = io.BytesIO()
    canvas.save(buffer, format="JPEG", quality=config.THUMB_JPEG_QUALITY)
    return buffer.getvalue()


def _display_name(original_name: Optional[str]) -> Optional[str]:
    """表示用のファイル名。フォルダ部分を落とし、長さを抑える。保存先のパスには使わない。"""
    if not original_name:
        return None
    name = PurePath(original_name.replace("\\", "/")).name
    return name[: config.ORIGINAL_NAME_MAX_LENGTH] or None


class ImageStore:
    """保存先フォルダの中だけで画像ファイルを読み書きする。"""

    def __init__(self, data_dir: Path) -> None:
        self._root = data_dir.resolve()
        for name in (config.SOURCES_DIR_NAME, config.RESULTS_DIR_NAME, config.THUMBS_DIR_NAME):
            (self._root / name).mkdir(parents=True, exist_ok=True)

    def add(self, conn: sqlite3.Connection, kind: str, data: bytes, original_name: Optional[str] = None) -> dict:
        """画像を検証して保存し、登録した行を返す。ファイル名はここで付け直す。"""
        info = inspect_image(data)
        stem = f"{kind}_{uuid.uuid4().hex}"
        file_rel = f"{_DIR_BY_KIND[kind]}/{stem}.{info.extension}"
        thumb_rel = f"{config.THUMBS_DIR_NAME}/{stem}.jpg"
        written = [self._root / file_rel, self._root / thumb_rel]
        try:
            written[0].write_bytes(data)
            written[1].write_bytes(_make_thumbnail(data))
            new_image = NewImage(
                kind=kind, file_path=file_rel, thumb_path=thumb_rel,
                width=info.width, height=info.height, original_name=_display_name(original_name),
            )
            return image_repo.create_image(conn, new_image)
        except Exception:
            # 登録まで終わらなかった場合、どこからも参照されないファイルを残さない
            for path in written:
                path.unlink(missing_ok=True)
            raise

    def delete(self, conn: sqlite3.Connection, image: dict) -> None:
        """画像を削除する。行には削除済みの印を付けて残し、ファイルとサムネイルを消す。

        先に印を付ける。ファイルを消せなかった場合（ほかのソフトが開いている等）でも、
        画面からは消えた状態になり、履歴と食い違わない。
        """
        image_repo.mark_deleted(conn, image["id"])
        for relative in (image["file_path"], image["thumb_path"]):
            path = self._inside(relative)
            if path is None:
                continue
            try:
                path.unlink(missing_ok=True)
            except OSError:
                _logger.warning("画像ファイルを消せませんでした（画像 id %s）。", image["id"])

    def file_of(self, image: dict) -> Path:
        """画像本体の絶対パス。"""
        return self._resolve(image["file_path"])

    def thumb_of(self, image: dict) -> Path:
        """サムネイルの絶対パス。"""
        return self._resolve(image["thumb_path"])

    def _inside(self, relative: Optional[str]) -> Optional[Path]:
        """相対パスを絶対パスにする。保存先フォルダの外を指すものは None。"""
        if not relative:
            return None
        path = (self._root / relative).resolve()
        return path if self._root in path.parents else None

    def _resolve(self, relative: Optional[str]) -> Path:
        """相対パスを絶対パスにする。保存先フォルダの外を指すもの、存在しないものは返さない。"""
        path = self._inside(relative)
        if path is None or not path.is_file():
            raise NotFoundError("画像ファイルが見つかりません。")
        return path
