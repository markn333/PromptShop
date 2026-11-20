"""データ（データベースと画像）の置き場の表示と変更のテスト。本物の設定とデータには触れない。"""
import importlib
import json
import sqlite3
import threading

import pytest

from app import config
from app.services.data_location import display_path
from tests.fakes import LOCATION_FILE_NAME, make_client, run_transform, upload


@pytest.fixture
def home(tmp_path):
    """既定の置き場（アプリが今使っている場所）。"""
    path = tmp_path / "home"
    path.mkdir()
    return path


@pytest.fixture
def app_client(home, provider, analyzer):
    return make_client(home, provider, analyzer)


def _pointer(home):
    file = home / LOCATION_FILE_NAME
    return json.loads(file.read_text(encoding="utf-8"))["data_dir"] if file.exists() else None


def _change(client, path):
    return client.put("/api/data-location", json={"path": str(path)})


# ---------- 画面に出すパス ----------

def test_display_path_hides_account_name(monkeypatch):
    monkeypatch.setenv("USERPROFILE", r"C:\Users\someone")
    monkeypatch.setenv("APPDATA", r"C:\Users\someone\AppData\Roaming")
    monkeypatch.setenv("LOCALAPPDATA", r"C:\Users\someone\AppData\Local")
    from pathlib import PureWindowsPath

    shown = display_path(PureWindowsPath(r"C:\Users\someone\AppData\Roaming\PromptShop\data"))
    local = display_path(PureWindowsPath(r"C:\Users\someone\AppData\Local\Temp\x"))
    documents = display_path(PureWindowsPath(r"C:\Users\someone\Documents\ps"))
    elsewhere = display_path(PureWindowsPath(r"D:\PromptShopData"))
    lookalike = display_path(PureWindowsPath(r"C:\Users\someone2\data"))

    assert shown == r"%APPDATA%\PromptShop\data" and "someone" not in shown
    assert local == r"%LOCALAPPDATA%\Temp\x" and documents == r"%USERPROFILE%\Documents\ps"
    assert elsewhere == r"D:\PromptShopData"
    assert lookalike == r"C:\Users\someone2\data", "名前が前半だけ一致する別のフォルダーは置き換えない"


def test_about_and_status_do_not_show_account_name(app_client, monkeypatch, home):
    monkeypatch.setenv("USERPROFILE", str(home.parent))

    about = app_client.get("/api/about").json()
    status = app_client.get("/api/data-location").json()

    for shown in (about["data_dir"], about["env_file"], status["current"], status["default"]):
        assert shown.startswith("%USERPROFILE%") and str(home.parent) not in shown


# ---------- 状態 ----------

def test_status_of_default_location(app_client):
    status = app_client.get("/api/data-location").json()

    assert status["is_default"] is True and status["pending"] is None and status["missing"] is None
    assert status["current"] == status["default"]


# ---------- 変更 ----------

def test_change_copies_data_and_takes_effect_on_next_start(app_client, home, tmp_path, provider, analyzer):
    image = upload(app_client)
    result = run_transform(app_client, image["id"])["output_image"]
    target = tmp_path / "new place" / "data"

    response = _change(app_client, target)

    assert response.status_code == 200
    status = response.json()
    assert status["copied"] is True and status["pending"] == display_path(target)
    assert status["current"] == display_path(home), "動いている間は、今の置き場のまま"
    assert _pointer(home) == str(target)
    assert (home / config.DB_FILE_NAME).exists(), "元のデータは消さない"
    copied = sqlite3.connect(target / config.DB_FILE_NAME)
    assert copied.execute("SELECT COUNT(*) FROM images").fetchone()[0] == 2
    copied.close()

    # 次に起動したとき（新しい置き場でアプリを作り直す）に、同じ画像が読めること
    restarted = make_client(target, provider, analyzer)
    assert restarted.get(result["file_url"]).status_code == 200
    assert restarted.get(result["thumb_url"]).status_code == 200
    assert len(restarted.get("/api/images").json()) == 2


def test_change_accepts_quoted_path_and_env_variable(app_client, home, tmp_path, monkeypatch):
    monkeypatch.setenv("PS_TEST_BASE", str(tmp_path))

    quoted = _change(app_client, f'"{tmp_path / "quoted"}"')
    variable = app_client.put("/api/data-location", json={"path": r"%PS_TEST_BASE%\from-variable"})

    assert quoted.status_code == 200 and (tmp_path / "quoted" / config.DB_FILE_NAME).exists()
    assert variable.status_code == 200 and _pointer(home) == str(tmp_path / "from-variable")


def test_existing_promptshop_data_is_adopted_without_copying(app_client, home, tmp_path, provider, analyzer):
    other = tmp_path / "other"
    other_client = make_client(other, provider, analyzer)
    upload(other_client)
    upload(other_client)
    upload(app_client)

    status = _change(app_client, other).json()

    assert status["copied"] is False and _pointer(home) == str(other)
    conn = sqlite3.connect(other / config.DB_FILE_NAME)
    assert conn.execute("SELECT COUNT(*) FROM images").fetchone()[0] == 2, "向こうのデータを上書きしない"
    conn.close()


@pytest.mark.parametrize("bad", ["relative\\folder", "data", "%NO_SUCH_VARIABLE_PS%\\x"])
def test_relative_or_unresolved_path_is_rejected(app_client, home, bad):
    response = app_client.put("/api/data-location", json={"path": bad})

    assert response.status_code == 400 and _pointer(home) is None


def test_non_empty_folder_without_data_is_rejected(app_client, home, tmp_path):
    occupied = tmp_path / "occupied"
    occupied.mkdir()
    (occupied / "family-photo.jpg").write_bytes(b"x")

    response = _change(app_client, occupied)

    assert response.status_code == 400 and "空のフォルダー" in response.json()["detail"]
    assert _pointer(home) is None and sorted(path.name for path in occupied.iterdir()) == ["family-photo.jpg"]


def test_folder_inside_current_data_is_rejected(app_client, home):
    response = _change(app_client, home / config.SOURCES_DIR_NAME / "nested")

    assert response.status_code == 400 and _pointer(home) is None


def test_file_is_rejected(app_client, home, tmp_path):
    file = tmp_path / "a.txt"
    file.write_text("x", encoding="utf-8")

    assert _change(app_client, file).status_code == 400 and _pointer(home) is None


def test_empty_path_is_rejected_with_message(app_client):
    response = app_client.put("/api/data-location", json={"path": "   "})

    assert response.status_code == 422 and "フォルダーの場所" in response.json()["detail"]


def test_change_is_refused_while_transform_is_running(app_client, home, tmp_path, provider):
    image = upload(app_client)
    provider.release = threading.Event()
    worker = threading.Thread(
        target=lambda: app_client.post("/api/transforms", json={"input_image_id": image["id"], "prompt_body": "x"})
    )
    worker.start()
    assert provider.entered.wait(timeout=5)

    response = _change(app_client, tmp_path / "busy")

    provider.release.set()
    worker.join(timeout=10)
    assert response.status_code == 409 and _pointer(home) is None and not (tmp_path / "busy").exists()


def test_change_from_other_site_is_rejected(app_client, home, tmp_path):
    response = app_client.put(
        "/api/data-location", json={"path": str(tmp_path / "evil")}, headers={"Origin": "https://evil.example"}
    )

    assert response.status_code == 403 and _pointer(home) is None and not (tmp_path / "evil").exists()


# ---------- 既定に戻す ----------

def test_reset_returns_to_default_without_copying(app_client, home, tmp_path):
    _change(app_client, tmp_path / "moved")

    status = app_client.delete("/api/data-location").json()

    assert status["pending"] is None and status["copied"] is False and _pointer(home) is None


def test_setting_the_default_path_is_the_same_as_reset(app_client, home, tmp_path):
    _change(app_client, tmp_path / "moved")

    status = _change(app_client, home).json()

    assert status["pending"] is None and _pointer(home) is None


# ---------- 起動時にどこを使うか ----------

def _reloaded(monkeypatch, tmp_path, pointer_value):
    """HOME を一時フォルダーにして app.config を読み直し、使う置き場を返す。終わったら元に戻す。"""
    monkeypatch.setenv(config.HOME_ENV, str(tmp_path))
    if pointer_value is not None:
        (tmp_path / "location.json").write_text(json.dumps({"data_dir": pointer_value}), encoding="utf-8")
    try:
        reloaded = importlib.reload(config)
        return reloaded.DATA_DIR, reloaded.DATA_DIR_MISSING, reloaded.ENV_FILE
    finally:
        monkeypatch.undo()
        importlib.reload(config)


def test_startup_uses_default_when_nothing_is_remembered(monkeypatch, tmp_path):
    data_dir, missing, _ = _reloaded(monkeypatch, tmp_path, None)

    assert data_dir == tmp_path / "data" and missing is None


def test_startup_uses_remembered_location(monkeypatch, tmp_path):
    chosen = tmp_path / "elsewhere"
    chosen.mkdir()

    data_dir, missing, env_file = _reloaded(monkeypatch, tmp_path, str(chosen))

    assert data_dir == chosen and missing is None
    assert env_file == tmp_path / ".env", "API キーのファイルは動かさない"


def test_startup_falls_back_when_remembered_location_is_gone(monkeypatch, tmp_path):
    """外付けドライブを外しているときなどでも、起動できなくならないこと。"""
    gone = tmp_path / "unplugged"

    data_dir, missing, _ = _reloaded(monkeypatch, tmp_path, str(gone))

    assert data_dir == tmp_path / "data" and missing == gone
    assert not gone.exists(), "見つからない置き場を勝手に作らない"


def test_startup_ignores_broken_pointer_file(monkeypatch, tmp_path):
    (tmp_path / "location.json").write_text("{broken", encoding="utf-8")

    data_dir, missing, _ = _reloaded(monkeypatch, tmp_path, None)

    assert data_dir == tmp_path / "data" and missing is None
