"""設定画面からの API キーの登録・削除。

キーは .env（Git 管理外）に保存し、同時に環境変数へ反映して、起動し直さなくても使えるようにする。
キーの全体は、画面にもログにもエラー文にも返さない。
"""
import os
import re
from pathlib import Path

from dotenv import set_key, unset_key

from app import config
from app.errors import InvalidInputError, NotFoundError
from app.providers.base import Provider

# 英数字と . _ - のみ。改行・空白・引用符・= などを通さないことで、.env の他の行を書き換えられないようにする
_KEY_PATTERN = re.compile(r"[A-Za-z0-9._\-]+")
# 値に特別な文字が入らないことを上で保証しているため、引用符で囲まずに書く
_QUOTE_MODE = "never"


def _validated(raw_key: str) -> str:
    """前後の空白を除き、保存してよい形式かを確かめる。エラー文に入力値は含めない。"""
    key = raw_key.strip()
    if not config.API_KEY_MIN_LENGTH <= len(key) <= config.API_KEY_MAX_LENGTH:
        raise InvalidInputError(
            f"API キーは {config.API_KEY_MIN_LENGTH}〜{config.API_KEY_MAX_LENGTH} 文字で入力してください。"
        )
    if not _KEY_PATTERN.fullmatch(key):
        raise InvalidInputError(
            "API キーに使えない文字が含まれています（使えるのは英数字と . _ - です）。"
            "途中に空白や改行が入っていないか確認してください。"
        )
    return key


class ApiKeyStore:
    """プロバイダーごとの API キーを .env と環境変数で管理する。"""

    def __init__(self, env_file: Path, providers: dict[str, Provider]) -> None:
        self._env_file = env_file
        self._providers = providers

    @property
    def env_file(self) -> Path:
        """API キーを保存するファイルの場所（中身ではない）。"""
        return self._env_file

    def list(self) -> list[dict]:
        """プロバイダーごとの登録状況。キーそのものは含めない。"""
        return [self._status(provider) for provider in self._providers.values()]

    def set(self, provider_name: str, raw_key: str) -> dict:
        """キーを保存し、すぐ使えるようにする。"""
        provider = self._provider(provider_name)
        key = _validated(raw_key)
        self._env_file.touch(exist_ok=True)
        set_key(self._env_file, provider.api_key_env, key, quote_mode=_QUOTE_MODE)
        os.environ[provider.api_key_env] = key
        return self._status(provider)

    def delete(self, provider_name: str) -> dict:
        """キーを .env と環境変数から消す。登録されていなくてもエラーにしない。"""
        provider = self._provider(provider_name)
        if self._env_file.is_file():
            unset_key(self._env_file, provider.api_key_env, quote_mode=_QUOTE_MODE)
        os.environ.pop(provider.api_key_env, None)
        return self._status(provider)

    def _provider(self, name: str) -> Provider:
        provider = self._providers.get(name)
        if provider is None:
            raise NotFoundError(f"プロバイダー「{name}」は使えません。")
        return provider

    @staticmethod
    def _status(provider: Provider) -> dict:
        key = os.environ.get(provider.api_key_env, "").strip()
        return {
            "provider": provider.name,
            "label": provider.label,
            "env_name": provider.api_key_env,
            "configured": bool(key),
            # 短すぎるキーで全体が見えてしまわないよう、十分な長さがあるときだけ末尾を出す
            "hint": key[-config.API_KEY_HINT_LENGTH:] if len(key) >= config.API_KEY_MIN_LENGTH else None,
        }
