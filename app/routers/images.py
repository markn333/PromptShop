"""画像の API。"""
import sqlite3
from typing import Literal, Optional

from fastapi import APIRouter, Depends, Query, Request, UploadFile, status
from fastapi.responses import FileResponse

from app import config
from app.errors import InvalidInputError, TooLargeError
from app.presenters import image_view, transform_view
from app.repositories import images as image_repo
from app.repositories.images import ImageFilter
from app.routers.deps import get_conn
from app.schemas import ImageUpdate
from app.services.chain import chain_of
from app.services.images import ImageStore

router = APIRouter(prefix="/api/images", tags=["images"])

_BYTES_PER_MB = 1024 * 1024


def get_store(request: Request) -> ImageStore:
    """アプリが持つ画像の保存先。"""
    return request.app.state.store


@router.post("", status_code=status.HTTP_201_CREATED)
def upload_image(
    file: UploadFile, conn: sqlite3.Connection = Depends(get_conn), store: ImageStore = Depends(get_store)
) -> dict:
    """元画像を取り込む。"""
    # 上限より 1 バイトだけ多く読み、超えていたら全体を読まずに断る
    data = file.file.read(config.MAX_UPLOAD_BYTES + 1)
    if len(data) > config.MAX_UPLOAD_BYTES:
        raise TooLargeError(f"ファイルが大きすぎます（上限 {config.MAX_UPLOAD_BYTES // _BYTES_PER_MB} MB）。")
    return image_view(store.add(conn, image_repo.KIND_SOURCE, data, original_name=file.filename))


@router.get("")
def list_images(
    kind: Optional[Literal["source", "result"]] = None,
    favorite: bool = False,
    example: bool = False,
    min_rating: Optional[int] = Query(None, ge=config.RATING_MIN, le=config.RATING_MAX),
    provider: Optional[str] = None,
    prompt_id: Optional[int] = None,
    limit: int = Query(config.IMAGE_LIST_LIMIT, ge=1, le=config.IMAGE_LIST_MAX_LIMIT),
    conn: sqlite3.Connection = Depends(get_conn),
) -> list[dict]:
    """削除されていない画像の一覧（新しい順）。favorite=true でお気に入り、example=true で作例だけに絞る。"""
    image_filter = ImageFilter(
        kind=kind, favorite_only=favorite, example_only=example,
        min_rating=min_rating, provider=provider, prompt_id=prompt_id,
    )
    return [image_view(image) for image in image_repo.list_images(conn, image_filter, limit=limit)]


@router.get("/{image_id}")
def get_image(image_id: int, conn: sqlite3.Connection = Depends(get_conn)) -> dict:
    """画像 1 件の情報。"""
    return image_view(image_repo.get_image(conn, image_id))


@router.patch("/{image_id}")
def update_image(image_id: int, payload: ImageUpdate, conn: sqlite3.Connection = Depends(get_conn)) -> dict:
    """お気に入り・評価・作例を更新する。送られた項目だけを変える。"""
    image = image_repo.get_image(conn, image_id)
    # 作例は「どのプロンプトの見本か」が決まらないと出しようがないので、登録できるものを限る
    if payload.example and image["made_prompt_id"] is None:
        raise InvalidInputError("作例にできるのは、保存済みのプロンプトで変換した結果だけです。")
    if payload.favorite is not None:
        image_repo.set_favorite(conn, image_id, payload.favorite)
    if payload.example is not None:
        image_repo.set_example(conn, image_id, payload.example)
    # rating は null（未評価に戻す）にも意味があるので、送られたかどうかで判断する
    if "rating" in payload.model_fields_set:
        image_repo.set_rating(conn, image_id, payload.rating)
    return image_view(image_repo.get_image(conn, image_id))


@router.delete("/{image_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_image(
    image_id: int, conn: sqlite3.Connection = Depends(get_conn), store: ImageStore = Depends(get_store)
) -> None:
    """画像を削除する。ファイルは消すが、履歴と料金の記録は残る。"""
    store.delete(conn, image_repo.get_image(conn, image_id))


@router.get("/{image_id}/chain")
def get_image_chain(image_id: int, conn: sqlite3.Connection = Depends(get_conn)) -> dict:
    """最初の元画像からこの画像までの変換の連鎖（古い順）。削除済みの画像も情報だけは返す。"""
    image, steps = chain_of(conn, image_id)
    return {"image": image_view(image), "steps": [transform_view(conn, step) for step in steps]}


@router.get("/{image_id}/file")
def get_image_file(
    image_id: int,
    download: bool = False,
    conn: sqlite3.Connection = Depends(get_conn),
    store: ImageStore = Depends(get_store),
) -> FileResponse:
    """画像本体。download=true のときは、保存用のファイル名を付けて返す。"""
    path = store.file_of(image_repo.get_image(conn, image_id))
    if download:
        # 保存先の名前はサーバーが決める（取り込み時の元ファイル名は使わない）
        return FileResponse(path, filename=f"promptshop_{image_id}{path.suffix}")
    return FileResponse(path)


@router.get("/{image_id}/thumb")
def get_image_thumb(
    image_id: int, conn: sqlite3.Connection = Depends(get_conn), store: ImageStore = Depends(get_store)
) -> FileResponse:
    """サムネイル。"""
    return FileResponse(store.thumb_of(image_repo.get_image(conn, image_id)))
