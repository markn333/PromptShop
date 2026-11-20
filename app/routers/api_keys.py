"""API キーの登録状況と登録・削除の API。キーの全体を返すルートは作らない。"""
from fastapi import APIRouter, Depends, Request

from app.schemas import ApiKeyWrite
from app.services.api_keys import ApiKeyStore

router = APIRouter(prefix="/api/api-keys", tags=["api-keys"])


def get_key_store(request: Request) -> ApiKeyStore:
    """アプリが持つ API キーの管理。"""
    return request.app.state.api_keys


@router.get("")
def list_api_keys(store: ApiKeyStore = Depends(get_key_store)) -> list[dict]:
    """プロバイダーごとの登録状況（登録済みか、末尾の数文字）。"""
    return store.list()


# キーは URL ではなく本文で受け取る（URL はアクセスログに残るため）
@router.put("/{provider}")
def set_api_key(provider: str, payload: ApiKeyWrite, store: ApiKeyStore = Depends(get_key_store)) -> dict:
    """API キーを登録する（登録済みなら置き換える）。"""
    return store.set(provider, payload.key)


@router.delete("/{provider}")
def delete_api_key(provider: str, store: ApiKeyStore = Depends(get_key_store)) -> dict:
    """API キーを削除する。"""
    return store.delete(provider)
