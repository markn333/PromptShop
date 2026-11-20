"""テスト共通の準備。"""
import pytest

from tests.fakes import FakeAnalyzer, FakeProvider, make_client


@pytest.fixture(autouse=True)
def no_real_api_keys(monkeypatch):
    """開発者の環境変数にある本物の API キーを、テストから見えなくする。

    空文字で上書きしておくと、テスト中にアプリが環境変数を書き換えても、終了時に元へ戻る。
    """
    names = (
        "OPENAI_API_KEY", "XAI_API_KEY", "GEMINI_API_KEY",
        "OPENAI_IMAGE_MODEL", "XAI_IMAGE_MODEL", "GEMINI_IMAGE_MODEL",
        "OPENAI_TEXT_MODEL", "XAI_TEXT_MODEL", "GEMINI_TEXT_MODEL",
    )
    for name in names:
        monkeypatch.setenv(name, "")


@pytest.fixture
def provider():
    """実際の API を呼ばない偽プロバイダー。"""
    return FakeProvider()


@pytest.fixture
def analyzer():
    """実際の API を呼ばない偽の読み取り役。"""
    return FakeAnalyzer()


@pytest.fixture
def client(tmp_path, provider, analyzer):
    """一時フォルダのデータベース・.env と偽プロバイダーを使うテスト用クライアント。実データには触れない。"""
    return make_client(tmp_path, provider, analyzer)
