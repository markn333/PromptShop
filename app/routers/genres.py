"""ジャンルの API。"""
import sqlite3

from fastapi import APIRouter, Depends, Response, status

from app.repositories import genres as genre_repo
from app.routers.deps import get_conn
from app.schemas import GenreCreate, GenreUpdate

router = APIRouter(prefix="/api/genres", tags=["genres"])


@router.get("")
def list_genres(conn: sqlite3.Connection = Depends(get_conn)) -> list[dict]:
    """ジャンルの一覧（並び順どおり）。"""
    return genre_repo.list_genres(conn)


@router.post("", status_code=status.HTTP_201_CREATED)
def create_genre(payload: GenreCreate, conn: sqlite3.Connection = Depends(get_conn)) -> dict:
    """ジャンルを追加する。"""
    return genre_repo.create_genre(conn, payload.name)


@router.put("/{genre_id}")
def update_genre(genre_id: int, payload: GenreUpdate, conn: sqlite3.Connection = Depends(get_conn)) -> dict:
    """ジャンルの名前・並び順を変える。"""
    return genre_repo.update_genre(conn, genre_id, name=payload.name, sort_order=payload.sort_order)


@router.delete("/{genre_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_genre(genre_id: int, conn: sqlite3.Connection = Depends(get_conn)) -> Response:
    """ジャンルを削除する。所属していたプロンプトは未分類になる。"""
    genre_repo.delete_genre(conn, genre_id)
    return Response(status_code=status.HTTP_204_NO_CONTENT)
