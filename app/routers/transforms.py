"""変換と履歴の API。"""
import sqlite3
from typing import Literal, Optional

from fastapi import APIRouter, Depends, Query, Request, status

from app import config
from app.presenters import transform_view
from app.repositories import transforms as transform_repo
from app.repositories.transforms import TransformFilter
from app.routers.deps import get_conn
from app.schemas import TransformCreate
from app.services.transform import TransformRequest, TransformService

router = APIRouter(prefix="/api", tags=["transforms"])


def get_service(request: Request) -> TransformService:
    """アプリが持つ変換サービス。"""
    return request.app.state.transform_service


@router.post("/transforms", status_code=status.HTTP_201_CREATED)
def create_transform(
    payload: TransformCreate,
    conn: sqlite3.Connection = Depends(get_conn),
    service: TransformService = Depends(get_service),
) -> dict:
    """変換を 1 回実行する。完了まで待ち、成功・失敗のどちらでも履歴を返す。"""
    request = TransformRequest(
        input_image_id=payload.input_image_id,
        prompt_title=payload.prompt_title,
        prompt_body=payload.prompt_body,
        provider=payload.provider,
        prompt_id=payload.prompt_id,
        keep_aspect=payload.keep_aspect,
    )
    return transform_view(conn, service.run(conn, request))


@router.get("/transforms")
def list_transforms(
    input_image_id: Optional[int] = None,
    prompt_id: Optional[int] = None,
    status_filter: Optional[Literal["success", "failed"]] = Query(None, alias="status"),
    conn: sqlite3.Connection = Depends(get_conn),
) -> list[dict]:
    """履歴の一覧（新しい順）。"""
    transform_filter = TransformFilter(input_image_id=input_image_id, prompt_id=prompt_id, status=status_filter)
    return [transform_view(conn, row) for row in transform_repo.list_transforms(conn, transform_filter)]


@router.get("/transforms/{transform_id}")
def get_transform(transform_id: int, conn: sqlite3.Connection = Depends(get_conn)) -> dict:
    """履歴 1 件。"""
    return transform_view(conn, transform_repo.get_transform(conn, transform_id))


@router.get("/providers")
def list_providers(request: Request) -> list[dict]:
    """プロバイダーの一覧。API キーの有無は返すが、キーそのものは返さない。"""
    return [
        {
            "name": provider.name,
            "label": provider.label,
            "model": provider.model,
            "configured": provider.is_configured(),
            "default": provider.name == config.DEFAULT_PROVIDER,
        }
        for provider in request.app.state.providers.values()
    ]
