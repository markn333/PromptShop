"""HTTP API が受け取る入力の形と検証。"""
from typing import Annotated, Literal, Optional

from pydantic import BaseModel, Field, StrictBool, StringConstraints

from app import config

# 前後の空白を落としたうえで 1 文字以上を要求する（空白のみの入力を弾く）
GenreName = Annotated[
    str, StringConstraints(strip_whitespace=True, min_length=1, max_length=config.GENRE_NAME_MAX_LENGTH)
]
PromptTitle = Annotated[
    str, StringConstraints(strip_whitespace=True, min_length=1, max_length=config.PROMPT_TITLE_MAX_LENGTH)
]
PromptBody = Annotated[
    str, StringConstraints(strip_whitespace=True, min_length=1, max_length=config.PROMPT_BODY_MAX_LENGTH)
]


class TransformCreate(BaseModel):
    """変換の実行。prompt_id は保存済みプロンプトを使うときだけ指定する。

    prompt_body は実際に送る本文（保存済みの本文をその場で書き換えたものでもよい）。
    """

    input_image_id: int
    prompt_body: PromptBody
    prompt_title: PromptTitle = config.UNSAVED_PROMPT_TITLE
    prompt_id: Optional[int] = None
    provider: str = config.DEFAULT_PROVIDER
    # False にすると、出力の縦横比を指定せずプロバイダーに任せる
    keep_aspect: StrictBool = True


class AnalysisCreate(BaseModel):
    """作風の読み取りの実行。language は、下書きを書かせる言語。"""

    image_id: int
    provider: str = config.DEFAULT_PROVIDER
    language: Literal[config.ANALYSIS_LANGUAGE_JA, config.ANALYSIS_LANGUAGE_EN] = config.ANALYSIS_LANGUAGE_JA


class ImageUpdate(BaseModel):
    """お気に入り・評価・作例の更新。送った項目だけが変わる。rating に null を送ると未評価に戻る。"""

    favorite: Optional[StrictBool] = None
    example: Optional[StrictBool] = None
    rating: Optional[Annotated[int, Field(ge=config.RATING_MIN, le=config.RATING_MAX)]] = None


class DataLocationWrite(BaseModel):
    """データの置き場の変更。path はフォルダーの場所。"""

    path: Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=config.DATA_PATH_MAX_LENGTH)]


class SettingsWrite(BaseModel):
    """設定の保存。monthly_budget_usd に null を送ると、予算なしに戻る。"""

    monthly_budget_usd: Optional[Annotated[float, Field(gt=0, le=config.MONTHLY_BUDGET_MAX_USD)]]


class ApiKeyWrite(BaseModel):
    """API キーの登録。形式の検証は、入力値をエラー文に出さないようサービス側で行う。"""

    key: str


class GenreCreate(BaseModel):
    """ジャンルの追加。"""

    name: GenreName


class GenreUpdate(BaseModel):
    """ジャンルの更新。指定した項目だけが変わる。"""

    name: Optional[GenreName] = None
    sort_order: Optional[int] = None


class PromptWrite(BaseModel):
    """プロンプトの登録・編集。genre_id を省くと未分類になる。"""

    title: PromptTitle
    body: PromptBody
    genre_id: Optional[int] = None
