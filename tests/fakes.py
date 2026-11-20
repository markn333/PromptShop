"""テスト用の道具。実際の API は呼ばない。"""
import io
import threading
from pathlib import Path
from typing import Optional

from fastapi.testclient import TestClient
from PIL import Image

from app import config
from app.analyzers.base import AnalysisResult, Analyzer
from app.main import create_app
from app.providers.base import Provider, TransformResult

FAKE_MODEL = "fake-model-1"
FAKE_COST_USD = 0.05
# 実際の画面と同じホスト名で要求を送る（それ以外のホスト名はアプリが断る）
BASE_URL = f"http://{config.HOST}:{config.PORT}"
ENV_FILE_NAME = ".env"
LOCATION_FILE_NAME = "location.json"


def make_client(data_dir, provider, analyzer=None) -> TestClient:
    """一時フォルダを保存先にしたアプリのテスト用クライアントを作る。"""
    analyzer = analyzer or FakeAnalyzer()
    app = create_app(
        data_dir=data_dir, providers={provider.name: provider}, env_file=data_dir / ENV_FILE_NAME,
        analyzers={analyzer.name: analyzer}, location_file=Path(data_dir) / LOCATION_FILE_NAME,
    )
    return TestClient(app, base_url=BASE_URL)


def image_bytes(image_format: str = "PNG", size: tuple[int, int] = (64, 48), color: str = "red") -> bytes:
    """指定した形式の小さな画像を作る。"""
    buffer = io.BytesIO()
    Image.new("RGB", size, color).save(buffer, format=image_format)
    return buffer.getvalue()


def upload(client, name: str = "in.png") -> dict:
    """元画像を 1 枚取り込み、その情報を返す。"""
    return client.post("/api/images", files={"file": (name, image_bytes(), "image/png")}).json()


def run_transform(client, image_id: int, **overrides) -> dict:
    """変換を 1 回実行し、履歴を返す。"""
    payload = {"input_image_id": image_id, "prompt_body": "水彩画風にする", "prompt_title": "水彩"}
    payload.update(overrides)
    return client.post("/api/transforms", json=payload).json()


FAKE_ANALYSIS_TEXT = "淡い水彩\n\nにじみのある淡い水彩で描き直す。元画像の構図は変えない。"
FAKE_ANALYSIS_COST_USD = 0.004


class FakeAnalyzer(Analyzer):
    """決めておいた結果を返す読み取り役。呼ばれた内容を記録する。"""

    name = "openai"
    label = "Fake"
    api_key_env = "OPENAI_API_KEY"
    model_env = "OPENAI_TEXT_MODEL"
    default_model = "fake-text-1"

    def __init__(self, result: Optional[AnalysisResult] = None, configured: bool = True) -> None:
        self.result = result or AnalysisResult(
            model=self.default_model, text=FAKE_ANALYSIS_TEXT, cost_usd=FAKE_ANALYSIS_COST_USD
        )
        self.configured = configured
        self.calls: list[tuple[Path, str]] = []
        self.raises: Optional[Exception] = None

    def is_configured(self) -> bool:
        return self.configured

    def analyze(self, image_path: Path, language: str) -> AnalysisResult:
        self.calls.append((image_path, language))
        if self.raises is not None:
            raise self.raises
        return self.result


class FakeProvider(Provider):
    """決めておいた結果を返すプロバイダー。呼ばれた回数と内容を記録する。"""

    name = "openai"
    label = "Fake"
    api_key_env = "OPENAI_API_KEY"

    def __init__(self, result: Optional[TransformResult] = None, configured: bool = True) -> None:
        self.result = result or TransformResult(
            model=FAKE_MODEL, image_bytes=image_bytes(color="blue"), cost_usd=FAKE_COST_USD
        )
        self.configured = configured
        self.calls: list[tuple[Path, str]] = []
        self.keep_aspect_calls: list[bool] = []
        self.raises: Optional[Exception] = None
        # 設定すると、transform の中でこのイベントが立つまで待つ（実行中の状態を作るため）
        self.release: Optional[threading.Event] = None
        self.entered = threading.Event()

    @property
    def model(self) -> str:
        return FAKE_MODEL

    def is_configured(self) -> bool:
        return self.configured

    def transform(self, image_path: Path, prompt: str, keep_aspect: bool = True) -> TransformResult:
        self.calls.append((image_path, prompt))
        self.keep_aspect_calls.append(keep_aspect)
        self.entered.set()
        if self.release is not None:
            self.release.wait(timeout=10)
        if self.raises is not None:
            raise self.raises
        return self.result
