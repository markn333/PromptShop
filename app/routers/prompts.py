"""プロンプトの API。"""
import sqlite3
from typing import Optional

from fastapi import APIRouter, Depends, Response, status

from app.repositories import prompts as prompt_repo
from app.repositories.prompts import PromptFilter
from app.routers.deps import get_conn
from app.schemas import PromptWrite

router = APIRouter(prefix="/api/prompts", tags=["prompts"])


@router.get("")
def list_prompts(
    genre_id: Optional[int] = None,
    unclassified: bool = False,
    q: Optional[str] = None,
    conn: sqlite3.Connection = Depends(get_conn),
) -> list[dict]:
    """プロンプトの一覧。ジャンル（または未分類）とキーワードで絞り込める。"""
    keyword = q.strip() if q else None
    prompt_filter = PromptFilter(genre_id=genre_id, unclassified=unclassified, keyword=keyword)
    return prompt_repo.list_prompts(conn, prompt_filter)


@router.post("", status_code=status.HTTP_201_CREATED)
def create_prompt(payload: PromptWrite, conn: sqlite3.Connection = Depends(get_conn)) -> dict:
    """プロンプトを登録する。"""
    return prompt_repo.create_prompt(conn, payload.title, payload.body, payload.genre_id)


@router.put("/{prompt_id}")
def update_prompt(prompt_id: int, payload: PromptWrite, conn: sqlite3.Connection = Depends(get_conn)) -> dict:
    """プロンプトを編集する。"""
    return prompt_repo.update_prompt(conn, prompt_id, payload.title, payload.body, payload.genre_id)


@router.delete("/{prompt_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_prompt(prompt_id: int, conn: sqlite3.Connection = Depends(get_conn)) -> Response:
    """プロンプトを削除する。"""
    prompt_repo.delete_prompt(conn, prompt_id)
    return Response(status_code=status.HTTP_204_NO_CONTENT)
