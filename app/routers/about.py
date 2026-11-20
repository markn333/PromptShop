"""アプリの情報（ヘルプ画面に出すバージョン、データの置き場、同梱ソフトの一覧）の API。"""
from fastapi import APIRouter, Request

from app import about, config
from app.services.data_location import display_path

router = APIRouter(prefix="/api", tags=["about"])


@router.get("/about")
def get_about(request: Request) -> dict:
    """バージョン、著作権表示、データの置き場、同梱しているソフトの一覧。API キーなどの秘密は含めない。"""
    return {
        "name": about.APP_NAME,
        "version": about.APP_VERSION,
        "copyright": about.COPYRIGHT,
        "license": about.LICENSE_NAME,
        # データベースと画像のフォルダー（バックアップするときに場所が分かるように出す）。
        # Windows のアカウント名が画面に出ないよう、%APPDATA% のような書き方に置き換えて返す
        "data_dir": display_path(request.app.state.db_path.parent),
        "env_file": display_path(request.app.state.api_keys.env_file),
        "log_file": display_path(config.LOG_FILE),
        "third_party": [
            {"name": "Python", "license": about.PYTHON_LICENSE, "url": "https://www.python.org/"},
            *({"name": item["name"], "license": item["license"], "url": item["url"]} for item in about.THIRD_PARTY),
        ],
    }
