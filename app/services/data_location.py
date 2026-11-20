"""データ（データベースと画像）の置き場の表示と変更。

置き場は、次に起動したときから切り替わる（動いている間は、開いているデータベースを差し替えない）。
どこを使うかは、固定の場所にある小さなファイル（config.LOCATION_FILE）に覚えておく。
API キーのファイル（.env）は動かさない（同期フォルダーなどへ、うっかりキーを置かないため）。
"""
import json
import os
import shutil
import sqlite3
from pathlib import Path
from typing import Optional

from app import config
from app.errors import BusyError, InvalidInputError

_POINTER_KEY = "data_dir"
# 画面に出すときに、Windows のアカウント名を含む部分を置き換える環境変数（長い方から先に当てる）
_MASK_VARIABLES = ("LOCALAPPDATA", "APPDATA", "USERPROFILE")
_IMAGE_DIR_NAMES = (config.SOURCES_DIR_NAME, config.RESULTS_DIR_NAME, config.THUMBS_DIR_NAME)


def display_path(path: Path) -> str:
    """画面に出すためのパス。アカウント名を含む部分は %APPDATA% のような書き方に置き換える。

    画面を人に見せたり、画面の写真を共有したりしたときに、Windows のアカウント名が写らないようにする。
    置き換えた書き方は、そのままエクスプローラーのアドレス欄に貼って開ける。
    """
    text = str(path)
    bases = sorted(
        ((os.environ.get(name, "").rstrip("\\/"), name) for name in _MASK_VARIABLES),
        key=lambda pair: len(pair[0]),
        reverse=True,
    )
    for base, name in bases:
        if base and (text.lower() == base.lower() or text.lower().startswith(base.lower() + os.sep)):
            return f"%{name}%{text[len(base):]}"
    return text


def read_pointer(pointer_file: Path) -> Optional[Path]:
    """覚えてある置き場を返す。覚えていない、または読めなければ None。"""
    try:
        value = json.loads(pointer_file.read_text(encoding="utf-8")).get(_POINTER_KEY)
    except (OSError, ValueError, AttributeError):
        return None
    return Path(value) if isinstance(value, str) and value.strip() else None


def _is_inside(path: Path, parent: Path) -> bool:
    return path == parent or parent in path.parents


class DataLocation:
    """データの置き場の、今の状態と変更。"""

    def __init__(
        self, pointer_file: Path, default_dir: Path, current_dir: Path, missing_dir: Optional[Path] = None
    ) -> None:
        self._pointer_file = pointer_file
        self._default_dir = default_dir.resolve()
        # いま動いているアプリが使っている置き場
        self._current_dir = current_dir.resolve()
        # 起動時に、覚えてあった置き場が見つからず既定の場所で動いている場合の、その置き場
        self._missing_dir = missing_dir

    def _next_dir(self) -> Path:
        """次に起動したときに使う置き場。"""
        return (read_pointer(self._pointer_file) or self._default_dir).resolve()

    def status(self) -> dict:
        """画面に出す状態。パスは display_path を通したもの。"""
        next_dir = self._next_dir()
        return {
            "current": display_path(self._current_dir),
            "default": display_path(self._default_dir),
            "is_default": self._current_dir == self._default_dir,
            # 次に起動したときに切り替わる先（変わらないなら None）
            "pending": display_path(next_dir) if next_dir != self._current_dir else None,
            "missing": display_path(self._missing_dir) if self._missing_dir is not None else None,
        }

    def change(self, raw_path: str, busy: bool) -> dict:
        """置き場を変える。新しい場所にデータがなければ、今のデータを写す（元は消さない）。

        返す値は status() に、写したかどうか（copied）を足したもの。
        """
        if busy:
            raise BusyError("変換または読み取りを実行中です。終わってから変更してください。")
        target = self._parse(raw_path)
        if target == self._default_dir:
            return self.reset(busy)
        copied = False
        if target != self._current_dir:
            copied = self._prepare(target)
        self._write_pointer(target)
        return {**self.status(), "copied": copied}

    def reset(self, busy: bool) -> dict:
        """既定の場所に戻す。データは写さない（既定の場所に残っているデータをそのまま使う）。"""
        if busy:
            raise BusyError("変換または読み取りを実行中です。終わってから変更してください。")
        try:
            self._pointer_file.unlink(missing_ok=True)
        except OSError as exc:
            raise InvalidInputError(f"設定を保存できませんでした（{type(exc).__name__}）。") from exc
        return {**self.status(), "copied": False}

    @staticmethod
    def _parse(raw_path: str) -> Path:
        # エクスプローラーの「パスのコピー」は前後に " を付けるので、取り除く
        text = os.path.expandvars(raw_path.strip().strip('"').strip())
        if not text or "%" in text:
            raise InvalidInputError("フォルダーの場所を入力してください。")
        path = Path(text)
        if not path.is_absolute():
            raise InvalidInputError("フォルダーは、ドライブ名から始まる場所（例: D:\\PromptShopData）で指定してください。")
        try:
            return path.resolve()
        except OSError as exc:
            raise InvalidInputError("そのフォルダーは使えません。場所を確認してください。") from exc

    def _prepare(self, target: Path) -> bool:
        """新しい置き場を使える状態にする。今のデータを写した場合は True を返す。"""
        if target.is_file():
            raise InvalidInputError("ファイルではなく、フォルダーを指定してください。")
        if _is_inside(target, self._current_dir):
            raise InvalidInputError("今のデータの置き場の中は指定できません。別の場所を指定してください。")
        if (target / config.DB_FILE_NAME).is_file():
            # すでに PromptShop のデータがある場所。写さずに、そのデータを使う
            return False
        try:
            if target.exists() and any(target.iterdir()):
                raise InvalidInputError(
                    "空のフォルダーか、PromptShop のデータが入っているフォルダーを指定してください。"
                )
            target.mkdir(parents=True, exist_ok=True)
            self._copy_to(target)
        except InvalidInputError:
            raise
        except (OSError, sqlite3.Error, shutil.Error) as exc:
            # 途中まで写したデータベースが残ると、次に「データがある場所」と見なしてしまうので消す
            try:
                (target / config.DB_FILE_NAME).unlink(missing_ok=True)
            except OSError:
                pass
            raise InvalidInputError(
                f"新しい場所へデータを写せませんでした（{type(exc).__name__}）。"
                "フォルダーに書き込めるか、空き容量が足りるかを確認してください。今の置き場は変えていません。"
            ) from exc
        return True

    def _copy_to(self, target: Path) -> None:
        """今のデータを写す。データベースは最後に写す（あれば「写し終えた」しるしになる）。"""
        for name in _IMAGE_DIR_NAMES:
            source = self._current_dir / name
            if source.is_dir():
                shutil.copytree(source, target / name, dirs_exist_ok=True)
        source_db = self._current_dir / config.DB_FILE_NAME
        if not source_db.is_file():
            return
        # 動いている最中でも中身がそろった写しになるよう、SQLite の機能で写す
        source_conn = sqlite3.connect(source_db)
        try:
            target_conn = sqlite3.connect(target / config.DB_FILE_NAME)
            try:
                source_conn.backup(target_conn)
            finally:
                target_conn.close()
        finally:
            source_conn.close()

    def _write_pointer(self, target: Path) -> None:
        try:
            self._pointer_file.parent.mkdir(parents=True, exist_ok=True)
            temporary = self._pointer_file.with_suffix(".tmp")
            temporary.write_text(json.dumps({_POINTER_KEY: str(target)}, ensure_ascii=False), encoding="utf-8")
            temporary.replace(self._pointer_file)
        except OSError as exc:
            raise InvalidInputError(f"設定を保存できませんでした（{type(exc).__name__}）。") from exc
