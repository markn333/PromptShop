"""アプリ全体の設定値。

プロバイダーのモデル ID・単価は、それぞれを実装するフェーズで最新の値を確認してから追加する。
"""
import json
import os
import sys
from pathlib import Path
from typing import Optional

PROJECT_ROOT = Path(__file__).resolve().parent.parent
STATIC_DIR = Path(__file__).resolve().parent / "static"

# 利用者のデータ（データベース、画像、API キー、ログ）を置く場所を決める環境変数
HOME_ENV = "PROMPTSHOP_HOME"
APP_DIR_NAME = "PromptShop"


def _home() -> Path:
    """利用者のデータを置く場所を返す。

    - 環境変数 PROMPTSHOP_HOME があれば、そこ（確認用に、本物のデータと別の場所で動かすため）。
    - exe として動いているときは %APPDATA%\\PromptShop。
      exe の隣は書き込めない場所のことがあり、exe を置き換えたときにデータごと消す事故も起きやすいため。
    - それ以外（run.bat や python -m app）は、これまでどおりプロジェクトのフォルダー。
    """
    override = os.environ.get(HOME_ENV, "").strip()
    if override:
        return Path(override)
    if getattr(sys, "frozen", False):
        return Path(os.environ.get("APPDATA") or Path.home()) / APP_DIR_NAME
    return PROJECT_ROOT


HOME = _home()

# データベースと画像の保存先（Git 管理外）。既定は HOME の下。設定画面で別の場所に変えられる。
DEFAULT_DATA_DIR = HOME / "data"
# 変えた置き場を覚えておくファイル（置き場そのものの中には置けないので、HOME に置く）
LOCATION_FILE = HOME / "location.json"


def _data_dir() -> tuple[Path, Optional[Path]]:
    """使う置き場と、「覚えてあったが見つからなかった置き場」を返す。

    覚えてある置き場が見つからないとき（外付けドライブを外している等）は、起動できなくならないよう
    既定の場所を使い、見つからなかった置き場を 2 つ目の値で返す（画面で知らせるため）。
    """
    try:
        value = json.loads(LOCATION_FILE.read_text(encoding="utf-8")).get("data_dir")
    except (OSError, ValueError, AttributeError):
        return DEFAULT_DATA_DIR, None
    if not isinstance(value, str) or not value.strip():
        return DEFAULT_DATA_DIR, None
    chosen = Path(value)
    try:
        if chosen.is_dir():
            return chosen, None
    except OSError:
        pass
    return DEFAULT_DATA_DIR, chosen


DATA_DIR, DATA_DIR_MISSING = _data_dir()
DB_FILE_NAME = "promptshop.db"
# 専用の窓で開く版（app/desktop.py）のログと、窓の部品（WebView）の作業用フォルダー
LOG_FILE = HOME / "promptshop.log"
WEBVIEW_DIR_NAME = "webview"

# 外部に公開しないため、待ち受けは自分の PC からの接続のみに限る
HOST = "127.0.0.1"
PORT = 8765

# データの置き場として入力できるパスの長さの上限
DATA_PATH_MAX_LENGTH = 400

GENRE_NAME_MAX_LENGTH = 50
PROMPT_TITLE_MAX_LENGTH = 100
PROMPT_BODY_MAX_LENGTH = 4000

# ---------- 画像 ----------
ENV_FILE = HOME / ".env"
SOURCES_DIR_NAME = "sources"
RESULTS_DIR_NAME = "results"
THUMBS_DIR_NAME = "thumbs"

MAX_UPLOAD_BYTES = 20 * 1024 * 1024
THUMB_MAX_PX = 320
THUMB_JPEG_QUALITY = 85
ORIGINAL_NAME_MAX_LENGTH = 200
IMAGE_LIST_LIMIT = 100
# ギャラリーが 1 回に取り出せる件数の上限
IMAGE_LIST_MAX_LIMIT = 500
RATING_MIN = 1
RATING_MAX = 5

# ---------- 料金 ----------
SETTING_MONTHLY_BUDGET = "monthly_budget_usd"
# 料金画面の「失敗した変換」をクリアしたときに、そこまでの履歴の id を覚えておく設定
# （一覧から隠すだけで、履歴と料金の記録は消さない）
SETTING_FAILED_CLEARED_ID = "failed_cleared_id"
# 月の予算として受け付ける上限（入力ミスの桁違いを弾くため）
MONTHLY_BUDGET_MAX_USD = 10_000
# 集計した金額を返すときの小数点以下の桁数（浮動小数点の端数を見せないため）
COST_ROUND_DIGITS = 6

# ---------- 変換 ----------
DEFAULT_PROVIDER = "openai"
# 保存済みプロンプトを選ばずに本文を直接書いて変換したときに、履歴へ残すタイトル
UNSAVED_PROMPT_TITLE = "（保存していないプロンプト）"
# プロバイダーが返すエラー文は長いことがあるため、履歴と画面に出す長さを抑える
PROVIDER_ERROR_MAX_LENGTH = 300

# ---------- OpenAI ----------
# モデル ID と単価は、2026-11-19 時点に実際に使っていた値。
# モデルは .env の OPENAI_IMAGE_MODEL で上書きできる。値上げ・値下げの際は単価をここで書き換える。
OPENAI_API_BASE = "https://api.openai.com/v1"
OPENAI_API_KEY_ENV = "OPENAI_API_KEY"
OPENAI_MODEL_ENV = "OPENAI_IMAGE_MODEL"
OPENAI_IMAGE_MODEL = "gpt-image-2.6-sunburst"
# 費用を抑えるため品質は medium 固定。
OPENAI_IMAGE_QUALITY = "medium"
# 出力サイズは元画像の向きに合わせて 3 種類から選ぶ。
# "auto" に任せると、縦長の元画像に正方形が返ることがあった（2026-11-19 の実 API 確認）。
OPENAI_SIZE_SQUARE = "1024x1024"
# 「縦横比維持」を外したときだけ使う（出力の形を OpenAI に任せる）
OPENAI_SIZE_AUTO = "auto"
OPENAI_SIZE_LANDSCAPE = "1536x1024"
OPENAI_SIZE_PORTRAIT = "1024x1536"
# 幅 ÷ 高さがこの値以上なら横長、逆数以下なら縦長とみなす。
# 正方形（1.0）と横長（1.5）のちょうど中間（比の意味で）にあたる √1.5。
OPENAI_LANDSCAPE_MIN_RATIO = 1.5 ** 0.5
OPENAI_OUTPUT_FORMAT = "png"
OPENAI_TIMEOUT_SEC = 300
# 概算料金の計算に使うトークン単価（USD / 100 万トークン）
TOKENS_PER_PRICE_UNIT = 1_000_000
OPENAI_TOKEN_PRICE_PER_M = {
    "text_input": 5.00,
    "image_input": 8.00,
    "image_output": 30.00,
}
# 応答にトークン使用量が含まれなかった場合に使う 1 枚あたりの概算（入力 0.03 + medium 出力 0.053）
OPENAI_FALLBACK_COST_USD = 0.083

# ---------- Grok（xAI） ----------
# モデル ID と単価は 2026-11-19 に xAI の公式ページ（docs.x.ai の models / images）で確認した。
# モデルは .env の XAI_IMAGE_MODEL で上書きできる。
XAI_API_BASE = "https://api.x.ai/v1"
XAI_API_KEY_ENV = "XAI_API_KEY"
XAI_MODEL_ENV = "XAI_IMAGE_MODEL"
XAI_IMAGE_MODEL = "grok-imagine-image-2.0"
XAI_IMAGE_RESOLUTION = "1k"
# 出力に指定できる縦横比（幅, 高さ）。元画像にいちばん近いものを選んで指定する。
# 指定しないと、縦長の元画像に正方形が返った（2026-11-19 の実 API 確認、BUG-0003）。
XAI_ASPECT_RATIOS = ((1, 1), (2, 3), (3, 2), (3, 4), (4, 3), (9, 16), (16, 9))
XAI_TIMEOUT_SEC = 180
# 出力 1 枚の単価（公式の料金表）。
XAI_OUTPUT_PRICE_USD = 0.04
# 編集では入力画像にも課金されるが、単価は公表されていない。少なく見積もらないための仮の値。
XAI_INPUT_PRICE_USD = 0.02

# ---------- Gemini ----------
# モデル ID と単価は 2026-11-19 に Google の公式の料金表で確認した。
# 既定は、画像 1 枚あたりが最も安い部類の gemini-nano-banana-2.1。
# モデルは .env の GEMINI_IMAGE_MODEL で上書きできる。
GEMINI_API_BASE = "https://generativelanguage.googleapis.com/v1beta"
GEMINI_API_KEY_ENV = "GEMINI_API_KEY"
GEMINI_MODEL_ENV = "GEMINI_IMAGE_MODEL"
GEMINI_IMAGE_MODEL = "gemini-nano-banana-2.1"
# 出力の大きさ。"1K" は長辺およそ 1024 px（大文字の K で書く。小文字は拒否される）。
GEMINI_IMAGE_SIZE = "1K"
GEMINI_TIMEOUT_SEC = 300
# 出力に指定できる縦横比（幅, 高さ）。元画像にいちばん近いものを選ぶ。
GEMINI_ASPECT_RATIOS = (
    (1, 1), (2, 3), (3, 2), (3, 4), (4, 3), (4, 5), (5, 4), (9, 16), (16, 9), (21, 9),
)
# モデルごとのトークン単価（USD / 100 万トークン）と、1K の画像 1 枚の出力トークン数。
#   input: 入力（テキスト・画像）、image_output: 出力画像、text_output: 出力テキストと思考
GEMINI_PRICES = {
    "gemini-nano-banana-2.1": {"input": 1.50, "image_output": 30.00, "text_output": 1.50, "image_tokens": 1120},
    "gemini-3.1-flash-lite-image": {"input": 0.25, "image_output": 30.00, "text_output": 1.50, "image_tokens": 1120},
    "gemini-3.1-flash-image": {"input": 0.50, "image_output": 60.00, "text_output": 3.00, "image_tokens": 1120},
    "gemini-3-pro-image": {"input": 2.00, "image_output": 120.00, "text_output": 12.00, "image_tokens": 1120},
}
# 単価表にないモデルを .env で指定した場合は、少なく見積もらないよう、いちばん高いモデルの単価で計算する。
GEMINI_UNKNOWN_MODEL_PRICE_KEY = "gemini-3-pro-image"

# ---------- 作風の読み取り（画像からプロンプトの下書きを作る） ----------
# 画像を見て文章を書けるモデルを使う。API キーは、同じ会社の画像変換と共通。
# モデル ID・単価（USD / 100 万トークン）は 2026-11-20 に各社の公式ページで確認した。
ANALYSIS_LANGUAGE_JA = "ja"
ANALYSIS_LANGUAGE_EN = "en"
# 送る前に、画像の長辺をここまで縮める（作風を読むには十分で、入力の料金が下がる）
ANALYSIS_IMAGE_MAX_PX = 1024
ANALYSIS_JPEG_QUALITY = 90
# 出力の上限。考える途中で使う分を含むプロバイダーがあるため、本文の長さより大きめに取る
ANALYSIS_MAX_OUTPUT_TOKENS = 4000
ANALYSIS_TIMEOUT_SEC = 120
# 応答に使用量がなかったときの概算に使う、入力（指示文 + 画像 1 枚）のトークン数
ANALYSIS_FALLBACK_INPUT_TOKENS = 2000

# OpenAI: /v1/responses。モデルは .env の OPENAI_TEXT_MODEL で上書きできる。
OPENAI_TEXT_MODEL_ENV = "OPENAI_TEXT_MODEL"
OPENAI_TEXT_MODEL = "gpt-6.1-terra"
OPENAI_TEXT_PRICES = {
    "gpt-6.2-astra": {"input": 8.00, "output": 40.00},
    "gpt-6.2-sol": {"input": 2.00, "output": 10.00},
    "gpt-6.1-terra": {"input": 1.00, "output": 5.00},
    "gpt-6-luna": {"input": 0.10, "output": 0.50},
}
OPENAI_TEXT_UNKNOWN_PRICE_KEY = "gpt-6.2-astra"

# Grok（xAI）: /v1/responses。モデルは .env の XAI_TEXT_MODEL で上書きできる。
# 公式の画像入力の例が grok-4.7 を使っているため、既定はこれにする（ほかのモデルの画像入力は未確認）。
XAI_TEXT_MODEL_ENV = "XAI_TEXT_MODEL"
XAI_TEXT_MODEL = "grok-4.7"
XAI_TEXT_PRICES = {
    "grok-4.7": {"input": 2.00, "output": 6.00},
    "grok-4.6": {"input": 2.00, "output": 6.00},
    "grok-4.5": {"input": 2.00, "output": 6.00},
    "grok-4.3": {"input": 1.25, "output": 2.50},
}
XAI_TEXT_UNKNOWN_PRICE_KEY = "grok-4.7"
# xAI は応答に実際の料金を入れて返す（usage.cost_in_usd_ticks）。1 USD がこの数にあたる
XAI_USD_TICKS_PER_USD = 10_000_000_000

# Gemini: generateContent。モデルは .env の GEMINI_TEXT_MODEL で上書きできる。
# 注意: gemini-3.8-flash と gemini-3.6-flash の単価は 2026-12-31 まで。
#       2027-01-01 から入力 1.50 / 出力 7.50 に上がると公式に書かれている。そのときはここを書き換える。
GEMINI_TEXT_MODEL_ENV = "GEMINI_TEXT_MODEL"
GEMINI_TEXT_MODEL = "gemini-3.8-flash"
GEMINI_TEXT_PRICES = {
    "gemini-4-neon": {"input": 3.00, "output": 15.00},
    "gemini-3.8-flash": {"input": 0.75, "output": 3.75},
    "gemini-3.6-flash": {"input": 0.75, "output": 3.75},
    "gemini-3.5-flash-lite": {"input": 0.30, "output": 2.50},
    "gemini-3.1-flash-lite": {"input": 0.25, "output": 1.50},
}
GEMINI_TEXT_UNKNOWN_PRICE_KEY = "gemini-4-neon"

# ---------- API キーの登録（設定画面） ----------
# .env に安全に書けるよう、キーに使える文字を限る（改行や引用符による書き換えを防ぐ）
API_KEY_MIN_LENGTH = 8
API_KEY_MAX_LENGTH = 500
# 画面には全体を出さず、見分けがつく末尾の数文字だけを出す
API_KEY_HINT_LENGTH = 4

# ---------- 待ち受けるホスト名 ----------
# これ以外の名前（外部のドメインをこの PC に向けたもの等）で届いた要求は受け付けない
ALLOWED_HOSTS = ["127.0.0.1", "localhost"]
