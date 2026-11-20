"""FastAPI アプリの組み立て。"""
from pathlib import Path
from typing import Optional
from urllib.parse import urlsplit

from fastapi import FastAPI, Request, status
from fastapi.exceptions import RequestValidationError
from fastapi.responses import FileResponse, JSONResponse, Response
from fastapi.staticfiles import StaticFiles
from starlette.middleware.trustedhost import TrustedHostMiddleware

from app import config, db
from app.analyzers import default_analyzers
from app.analyzers.base import Analyzer
from app.errors import (
    AppError,
    BusyError,
    DuplicateNameError,
    InvalidImageError,
    InvalidInputError,
    InvalidReferenceError,
    NotFoundError,
    ProviderNotConfiguredError,
    TooLargeError,
)
from app.providers import default_providers
from app.providers.base import Provider
from app.routers import about, analyses, api_keys, costs, data_location, genres, images, prompts, transforms
from app.services.analysis import AnalysisService
from app.services.api_keys import ApiKeyStore
from app.services.data_location import DataLocation
from app.services.images import ImageStore
from app.services.transform import TransformService
from app.validation_messages import describe_errors

# starlette の版によって 413 と 422 の定数名が違うため、数値で持つ
_HTTP_PAYLOAD_TOO_LARGE = 413
_HTTP_UNPROCESSABLE = 422

_STATUS_BY_ERROR: dict[type, int] = {
    NotFoundError: status.HTTP_404_NOT_FOUND,
    DuplicateNameError: status.HTTP_409_CONFLICT,
    BusyError: status.HTTP_409_CONFLICT,
    InvalidReferenceError: status.HTTP_400_BAD_REQUEST,
    InvalidImageError: status.HTTP_400_BAD_REQUEST,
    InvalidInputError: status.HTTP_400_BAD_REQUEST,
    ProviderNotConfiguredError: status.HTTP_400_BAD_REQUEST,
    TooLargeError: _HTTP_PAYLOAD_TOO_LARGE,
}

# データを変える（または課金が発生する）操作に使うメソッド
_UNSAFE_METHODS = frozenset({"POST", "PUT", "PATCH", "DELETE"})


def _handle_app_error(_request: Request, exc: AppError) -> JSONResponse:
    """アプリの例外を、利用者向けメッセージつきの HTTP 応答に変える。"""
    status_code = _STATUS_BY_ERROR.get(type(exc), status.HTTP_400_BAD_REQUEST)
    return JSONResponse(status_code=status_code, content={"detail": exc.message})


def _handle_validation_error(_request: Request, exc: RequestValidationError) -> JSONResponse:
    """入力の検証エラーを、項目名つきの日本語の文で返す。入力された値は含めない。"""
    return JSONResponse(
        status_code=_HTTP_UNPROCESSABLE, content={"detail": describe_errors(exc.errors())}
    )


async def _reject_cross_site_writes(request: Request, call_next) -> Response:
    """ほかのサイトのページから送られた、データを変える要求を断る。

    ブラウザで開いた別サイトのページは、この PC の PromptShop へ要求を送れてしまう。
    放置すると、API キーの書き換えや、意図しない変換（課金）を勝手に起こされうる。
    ブラウザは送信元を Origin ヘッダーに入れるので、PromptShop 自身の画面と一致しなければ断る。
    Origin のない要求（ブラウザ以外からの呼び出し）は対象外。
    """
    origin = request.headers.get("origin")
    if request.method in _UNSAFE_METHODS and origin is not None:
        if urlsplit(origin).netloc != request.headers.get("host"):
            message = "PromptShop の画面以外からの操作は受け付けません。"
            return JSONResponse(status_code=status.HTTP_403_FORBIDDEN, content={"detail": message})
    return await call_next(request)


class _RevalidatedStaticFiles(StaticFiles):
    """画面のファイルを、毎回サーバーに確認させてから使わせる。

    指定がないとブラウザが古い app.js / style.css を使い続け、更新後に画面が壊れて見えることがある。
    """

    def file_response(self, *args, **kwargs) -> Response:
        response = super().file_response(*args, **kwargs)
        response.headers["Cache-Control"] = "no-cache"
        return response


def create_app(
    data_dir: Optional[Path] = None,
    providers: Optional[dict[str, Provider]] = None,
    env_file: Optional[Path] = None,
    analyzers: Optional[dict[str, Analyzer]] = None,
    location_file: Optional[Path] = None,
) -> FastAPI:
    """アプリを作る。

    data_dir を渡すと、データベースと画像の保存先をそこに変える（テストで一時フォルダを使うため）。
    providers を渡すと、プロバイダーを差し替える（テストで実際の API を呼ばないため）。
    env_file を渡すと、API キーの保存先をそこに変える（テストで本物の .env に触れないため）。
    analyzers を渡すと、作風の読み取り役を差し替える（テストで実際の API を呼ばないため）。
    location_file を渡すと、データの置き場を覚えるファイルをそこに変える（テストで本物の設定に触れないため）。
    """
    base_dir = data_dir if data_dir is not None else config.DATA_DIR
    db_path = base_dir / config.DB_FILE_NAME
    db.init_db(db_path)
    store = ImageStore(base_dir)
    active_providers = providers if providers is not None else default_providers()

    app = FastAPI(title="PromptShop")
    app.state.db_path = db_path
    app.state.store = store
    app.state.providers = active_providers
    app.state.transform_service = TransformService(store, active_providers)
    app.state.analyzers = analyzers if analyzers is not None else default_analyzers()
    app.state.analysis_service = AnalysisService(store, app.state.analyzers)
    app.state.api_keys = ApiKeyStore(env_file if env_file is not None else config.ENV_FILE, active_providers)

    # data_dir を渡されたとき（テストや確認用）は、それを既定の場所として扱う
    app.state.data_location = DataLocation(
        pointer_file=location_file if location_file is not None else config.LOCATION_FILE,
        default_dir=base_dir if data_dir is not None else config.DEFAULT_DATA_DIR,
        current_dir=base_dir,
        missing_dir=config.DATA_DIR_MISSING if data_dir is None else None,
    )

    app.add_exception_handler(AppError, _handle_app_error)
    app.add_exception_handler(RequestValidationError, _handle_validation_error)
    app.middleware("http")(_reject_cross_site_writes)
    # 外部のドメイン名をこの PC に向けて画面や API を読み出す手口を防ぐ
    app.add_middleware(TrustedHostMiddleware, allowed_hosts=config.ALLOWED_HOSTS)

    for module in (genres, prompts, images, transforms, analyses, api_keys, costs, about, data_location):
        app.include_router(module.router)
    app.mount("/static", _RevalidatedStaticFiles(directory=config.STATIC_DIR), name="static")

    @app.get("/", include_in_schema=False)
    def index() -> FileResponse:
        return FileResponse(config.STATIC_DIR / "index.html", headers={"Cache-Control": "no-cache"})

    return app
