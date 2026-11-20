"""専用の窓で開く版（app/desktop.py）と、それに伴う変更のテスト。窓そのものは開かない。"""
import importlib
import sys
from pathlib import Path

import pytest

from app import config
from tests.fakes import image_bytes, upload


# ---------- データを置く場所 ----------

def _reloaded_home(monkeypatch, frozen: bool, override: str = "", appdata: str = r"C:\Users\someone\AppData\Roaming"):
    """条件を変えて app.config を読み直し、データを置く場所を返す。終わったら元に戻す。"""
    monkeypatch.setenv(config.HOME_ENV, override)
    monkeypatch.setenv("APPDATA", appdata)
    if frozen:
        monkeypatch.setattr(sys, "frozen", True, raising=False)
    try:
        reloaded = importlib.reload(config)
        return reloaded.HOME, reloaded.DATA_DIR, reloaded.ENV_FILE
    finally:
        monkeypatch.undo()
        importlib.reload(config)


def test_home_is_project_folder_when_run_from_source(monkeypatch):
    home, data_dir, env_file = _reloaded_home(monkeypatch, frozen=False)

    assert home == config.PROJECT_ROOT
    assert data_dir == config.PROJECT_ROOT / "data" and env_file == config.PROJECT_ROOT / ".env"


def test_home_is_appdata_when_run_as_exe(monkeypatch):
    home, data_dir, env_file = _reloaded_home(monkeypatch, frozen=True)

    expected = Path(r"C:\Users\someone\AppData\Roaming") / "PromptShop"
    assert (home, data_dir, env_file) == (expected, expected / "data", expected / ".env")


@pytest.mark.parametrize("frozen", [False, True])
def test_home_can_be_overridden_by_env(monkeypatch, tmp_path, frozen):
    home, data_dir, _ = _reloaded_home(monkeypatch, frozen=frozen, override=str(tmp_path))

    assert home == tmp_path and data_dir == tmp_path / "data"


# ---------- 画像の保存（拡大表示の「保存」） ----------

def test_download_gives_server_side_file_name(client):
    image = client.post("/api/images", files={"file": ("../my photo.jpg", image_bytes("JPEG"), "image/jpeg")}).json()

    inline = client.get(image["file_url"])
    download = client.get(image["file_url"], params={"download": "true"})

    assert "attachment" not in inline.headers.get("content-disposition", "")
    disposition = download.headers["content-disposition"]
    assert "attachment" in disposition and f'filename="promptshop_{image["id"]}.jpg"' in disposition
    assert "my photo" not in disposition, "取り込み時のファイル名は使わない"
    assert download.content == inline.content


def test_download_of_missing_image(client):
    assert client.get("/api/images/999/file", params={"download": "true"}).status_code == 404


# ---------- 変換中に窓を閉じようとしたとき ----------

desktop = pytest.importorskip("app.desktop", reason="pywebview が入っていない環境では、窓の版のテストを省く")


class _Service:
    def __init__(self, busy: bool) -> None:
        self.busy = busy

    def is_busy(self) -> bool:
        return self.busy


class _Clock:
    def __init__(self) -> None:
        self.now = 1000.0

    def monotonic(self) -> float:
        return self.now


@pytest.fixture
def clock(monkeypatch):
    fake = _Clock()
    monkeypatch.setattr(desktop.time, "monotonic", fake.monotonic)
    return fake


def _guard(service):
    messages = []
    guard = desktop.CloseGuard(service, messages.append)
    return guard, messages


def _wait_for(messages):
    """知らせは別のスレッドから出るので、届くまで少し待つ。"""
    import time

    for _ in range(100):
        if messages:
            return
        time.sleep(0.01)


def test_close_is_allowed_when_idle(clock):
    guard, messages = _guard(_Service(busy=False))

    assert guard.on_closing() is not False
    assert messages == []


def test_first_close_during_transform_is_cancelled_with_warning(clock):
    guard, messages = _guard(_Service(busy=True))

    assert guard.on_closing() is False
    _wait_for(messages)
    assert len(messages) == 1 and "課金" in messages[0] and "もう一度" in messages[0]


def test_second_close_within_window_is_allowed(clock):
    guard, _ = _guard(_Service(busy=True))
    guard.on_closing()

    clock.now += desktop.FORCE_CLOSE_WINDOW_SEC - 1

    assert guard.on_closing() is not False, "応答が返らないときに、閉じる手段を残す"


def test_second_close_after_window_warns_again(clock):
    guard, messages = _guard(_Service(busy=True))
    guard.on_closing()
    _wait_for(messages)

    clock.now += desktop.FORCE_CLOSE_WINDOW_SEC + 1

    assert guard.on_closing() is False
    for _ in range(100):
        if len(messages) == 2:
            break
        import time
        time.sleep(0.01)
    assert len(messages) == 2


def test_close_is_allowed_again_once_transform_finishes(clock):
    service = _Service(busy=True)
    guard, _ = _guard(service)
    guard.on_closing()

    service.busy = False
    clock.now += desktop.FORCE_CLOSE_WINDOW_SEC + 60

    assert guard.on_closing() is not False


def test_service_reports_busy_only_while_running(client, provider):
    """変換サービスの is_busy は、API の呼び出し中だけ True になる。"""
    import threading

    service = client.app.state.transform_service
    image = upload(client)
    provider.release = threading.Event()
    assert service.is_busy() is False

    worker = threading.Thread(
        target=lambda: client.post("/api/transforms", json={"input_image_id": image["id"], "prompt_body": "x"})
    )
    worker.start()
    assert provider.entered.wait(timeout=5)
    busy_during_call = service.is_busy()
    provider.release.set()
    worker.join(timeout=10)

    assert busy_during_call is True and service.is_busy() is False


def test_free_port_is_usable():
    import socket

    port = desktop._free_port()

    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as probe:
        probe.bind((config.HOST, port))
