"""作風の読み取り（画像からプロンプトの下書きを作る）の API。"""
import sqlite3

from fastapi import APIRouter, Depends, Request, status

from app import config
from app.routers.deps import get_conn
from app.schemas import AnalysisCreate
from app.services.analysis import AnalysisRequest, AnalysisService

router = APIRouter(prefix="/api", tags=["analyses"])


def get_service(request: Request) -> AnalysisService:
    """アプリが持つ読み取りサービス。"""
    return request.app.state.analysis_service


@router.post("/analyses", status_code=status.HTTP_201_CREATED)
def create_analysis(
    payload: AnalysisCreate,
    conn: sqlite3.Connection = Depends(get_conn),
    service: AnalysisService = Depends(get_service),
) -> dict:
    """読み取りを 1 回実行する。完了まで待ち、成功・失敗のどちらでも履歴を返す。"""
    request = AnalysisRequest(image_id=payload.image_id, provider=payload.provider, language=payload.language)
    return service.run(conn, request)


@router.get("/analyzers")
def list_analyzers(request: Request) -> list[dict]:
    """読み取りに使えるプロバイダーの一覧。API キーの有無は返すが、キーそのものは返さない。"""
    return [
        {
            "name": analyzer.name,
            "label": analyzer.label,
            "model": analyzer.model,
            "configured": analyzer.is_configured(),
            "default": analyzer.name == config.DEFAULT_PROVIDER,
        }
        for analyzer in request.app.state.analyzers.values()
    ]
