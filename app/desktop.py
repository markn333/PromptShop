"""専用の窓（WebView）で PromptShop を開く。`python -m app.desktop` または PromptShop.exe から呼ばれる。

中では、ブラウザ版と同じサーバーをこの PC の中だけで動かし、その画面を窓に映している。
黒い窓（コンソール）は出さず、窓を閉じるとサーバーも止まる。
"""
import ctypes
import json
import logging
import socket
import sys
import threading
import time
from logging.handlers import RotatingFileHandler
from typing import Optional

import uvicorn
import webview
from dotenv import load_dotenv

from app import config
from app.main import create_app
from app.services.transform import TransformService

WINDOW_TITLE = "PromptShop"
WINDOW_SIZE = (1280, 860)
WINDOW_MIN_SIZE = (900, 600)
SERVER_START_TIMEOUT_SEC = 15
SERVER_STOP_TIMEOUT_SEC = 5
_POLL_INTERVAL_SEC = 0.05
# 変換中に窓を閉じようとしたとき、この秒数以内にもう一度閉じれば、そのまま終了する
FORCE_CLOSE_WINDOW_SEC = 10
LOG_MAX_BYTES = 1024 * 1024
LOG_BACKUP_COUNT = 2

# 二重起動の検出に使う、Windows の名前付きミューテックス
_MUTEX_NAME = "PromptShopDesktopSingleInstance"
_ERROR_ALREADY_EXISTS = 183
_MB_ICON_WARNING = 0x30

_CLOSE_WARNING = (
    "変換を実行中です。今閉じると、課金されていても履歴に残りません。"
    f"それでも閉じる場合は、{FORCE_CLOSE_WINDOW_SEC} 秒以内にもう一度閉じてください。"
)

logger = logging.getLogger(__name__)


def _setup_logging() -> None:
    """ログをファイルに書く。窓だけのアプリには出力先の画面がないため。API キーは書かない。"""
    config.HOME.mkdir(parents=True, exist_ok=True)
    handler = RotatingFileHandler(
        config.LOG_FILE, maxBytes=LOG_MAX_BYTES, backupCount=LOG_BACKUP_COUNT, encoding="utf-8"
    )
    handler.setFormatter(logging.Formatter("%(asctime)s %(levelname)s %(name)s: %(message)s"))
    logging.basicConfig(level=logging.INFO, handlers=[handler])


def _show_message(text: str) -> None:
    """窓を出す前の知らせ（二重起動、起動の失敗）を、Windows のメッセージ箱で出す。"""
    if sys.platform == "win32":
        ctypes.windll.user32.MessageBoxW(None, text, WINDOW_TITLE, _MB_ICON_WARNING)
    else:
        print(text)


def _acquire_single_instance() -> Optional[int]:
    """二重起動でなければ、ミューテックスのハンドルを返す。すでに起動していれば None。

    2 つ同時に動くと、「変換は同時に 1 件だけ」の決まりが窓ごとに別々になり、課金が重なりうる。
    返したハンドルは、終了まで持ち続けること（手放すと二重起動を検出できなくなる）。
    """
    if sys.platform != "win32":
        return 0
    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    handle = kernel32.CreateMutexW(None, False, _MUTEX_NAME)
    if ctypes.get_last_error() == _ERROR_ALREADY_EXISTS:
        return None
    return handle


def _free_port() -> int:
    """空いているポート番号を 1 つ選ぶ（決め打ちの番号がほかのソフトとぶつかるのを避ける）。"""
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as probe:
        probe.bind((config.HOST, 0))
        return probe.getsockname()[1]


def _start_server(app, port: int) -> tuple[uvicorn.Server, threading.Thread]:
    """サーバーを裏で動かし、待ち受けが始まるまで待つ。始まらなければ RuntimeError。"""
    # log_config=None: 窓だけのアプリには標準出力がなく、uvicorn の既定のログ設定だと起動に失敗する
    server = uvicorn.Server(uvicorn.Config(app, host=config.HOST, port=port, log_config=None, access_log=False))
    thread = threading.Thread(target=server.run, name="promptshop-server", daemon=True)
    thread.start()
    deadline = time.monotonic() + SERVER_START_TIMEOUT_SEC
    while not server.started:
        if not thread.is_alive() or time.monotonic() > deadline:
            raise RuntimeError("server did not start")
        time.sleep(_POLL_INTERVAL_SEC)
    return server, thread


class AnyBusy:
    """複数のサービスのどれかが実行中かどうかをまとめて答える。"""

    def __init__(self, *services) -> None:
        self._services = services

    def is_busy(self) -> bool:
        return any(service.is_busy() for service in self._services)


class CloseGuard:
    """変換の実行中に、うっかり窓を閉じてしまうのを防ぐ。

    変換中の 1 回目は閉じるのを取り消して画面に知らせ、一定時間内の 2 回目はそのまま閉じる。
    （応答が返らないときに、閉じる手段がなくならないようにするため。）
    """

    def __init__(self, service, notify) -> None:
        # service は is_busy() を持つもの（変換サービス、または AnyBusy）
        self._service = service
        self._notify = notify
        self._warned_at: Optional[float] = None

    def on_closing(self) -> Optional[bool]:
        """窓が閉じられる直前に呼ばれる。False を返すと、閉じるのを取り消す。"""
        if not self._service.is_busy():
            return None
        now = time.monotonic()
        if self._warned_at is not None and now - self._warned_at <= FORCE_CLOSE_WINDOW_SEC:
            return None
        self._warned_at = now
        # 画面への表示は、閉じる処理を止めないよう別のスレッドから行う
        threading.Thread(target=self._notify, args=(_CLOSE_WARNING,), daemon=True).start()
        return False


def main() -> None:
    """専用の窓で PromptShop を開く。窓を閉じるまで戻らない。"""
    _setup_logging()
    mutex = _acquire_single_instance()
    if mutex is None:
        _show_message("PromptShop はすでに起動しています。")
        return

    # 設定タブで保存したキーが必ず使われるよう、OS 側に同名の環境変数があっても .env の値を優先する
    load_dotenv(config.ENV_FILE, override=True)
    try:
        app = create_app()
        port = _free_port()
        server, thread = _start_server(app, port)
    except Exception as exc:  # noqa: BLE001 - 起動できない理由を利用者に知らせて終わる
        logger.error("startup failed: %s", type(exc).__name__)
        _show_message(f"PromptShop を起動できませんでした（{type(exc).__name__}）。\nログ: {config.LOG_FILE}")
        return
    logger.info("started on port %s, data in %s", port, config.HOME)

    # 画像の「保存」を、窓の中から使えるようにする
    webview.settings["ALLOW_DOWNLOADS"] = True
    window = webview.create_window(
        WINDOW_TITLE,
        f"http://{config.HOST}:{port}/",
        width=WINDOW_SIZE[0],
        height=WINDOW_SIZE[1],
        min_size=WINDOW_MIN_SIZE,
        text_select=True,
    )

    def notify(message: str) -> None:
        window.evaluate_js(f"showToast({json.dumps(message)}, true)")

    window.events.closing += CloseGuard(AnyBusy(app.state.transform_service, app.state.analysis_service), notify).on_closing
    try:
        webview.start(private_mode=False, storage_path=str(config.HOME / config.WEBVIEW_DIR_NAME))
    finally:
        server.should_exit = True
        thread.join(timeout=SERVER_STOP_TIMEOUT_SEC)
        logger.info("stopped")


if __name__ == "__main__":
    main()
