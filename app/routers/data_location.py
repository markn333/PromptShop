"""データ（データベースと画像）の置き場の API。変更は、次に起動したときから効く。"""
from fastapi import APIRouter, Request

from app.schemas import DataLocationWrite
from app.services.data_location import DataLocation

router = APIRouter(prefix="/api", tags=["data-location"])


def _location(request: Request) -> DataLocation:
    return request.app.state.data_location


def _busy(request: Request) -> bool:
    """変換か読み取りを実行中か（実行中は、データを写している間に中身が変わるので変更させない）。"""
    state = request.app.state
    return state.transform_service.is_busy() or state.analysis_service.is_busy()


@router.get("/data-location")
def get_data_location(request: Request) -> dict:
    """今の置き場、既定の場所、次の起動で切り替わる先。"""
    return _location(request).status()


@router.put("/data-location")
def put_data_location(payload: DataLocationWrite, request: Request) -> dict:
    """置き場を変える。新しい場所にデータがなければ、今のデータを写す（元は消さない）。"""
    return _location(request).change(payload.path, _busy(request))


@router.delete("/data-location")
def delete_data_location(request: Request) -> dict:
    """既定の場所に戻す。"""
    return _location(request).reset(_busy(request))
