"""`python -m app` でサーバーを起動する。"""
import argparse
import threading
import webbrowser

import uvicorn
from dotenv import load_dotenv

from app import config
from app.main import create_app

# サーバーが待ち受けを始める前にブラウザが開くと接続エラーになるため、少し待ってから開く
BROWSER_OPEN_DELAY_SEC = 1.5


def main() -> None:
    """サーバーを起動し、指定がなければブラウザで画面を開く。"""
    parser = argparse.ArgumentParser(description="PromptShop を起動する")
    parser.add_argument("--no-browser", action="store_true", help="ブラウザを自動で開かない")
    parser.add_argument(
        "--port", type=int, default=config.PORT, help=f"待ち受けるポート番号（既定 {config.PORT}）"
    )
    args = parser.parse_args()

    # API キーを .env から環境変数へ読み込む。
    # 設定タブで保存したキーが必ず使われるよう、OS 側に同名の環境変数があっても .env の値を優先する
    load_dotenv(config.ENV_FILE, override=True)

    url = f"http://{config.HOST}:{args.port}/"
    if not args.no_browser:
        timer = threading.Timer(BROWSER_OPEN_DELAY_SEC, webbrowser.open, args=(url,))
        timer.daemon = True
        timer.start()

    print(f"PromptShop: {url}  (stop: Ctrl+C)")
    uvicorn.run(create_app(), host=config.HOST, port=args.port)


if __name__ == "__main__":
    main()
