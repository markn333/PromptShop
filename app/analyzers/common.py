"""作風の読み取りで共通に使う道具（AI への指示文、送る画像の準備、応答の読み取り、料金）。

API キーはログ・エラー文・履歴のどこにも出さない。
"""
import base64
import io
from pathlib import Path
from typing import Callable, Optional, Union

import httpx
from PIL import Image, ImageOps

from app import config
from app.analyzers.base import AnalysisResult
from app.providers import common as provider_common
from app.providers.base import TransformResult

HTTP_OK = provider_common.HTTP_OK
JPEG_MIME = "image/jpeg"

_LANGUAGE_NAMES = {config.ANALYSIS_LANGUAGE_JA: "Japanese", config.ANALYSIS_LANGUAGE_EN: "English"}
_LENGTH_GUIDE = {
    config.ANALYSIS_LANGUAGE_JA: "about 600 to 1000 Japanese characters",
    config.ANALYSIS_LANGUAGE_EN: "about 250 to 400 English words",
}

# 写っている中身（人物・物・構図）を書かせると、変換のときに元画像の中身まで書き換わるため、作風だけに限る。
# 2026-11-20 の実 API での初回確認を受けて、次の点を足した:
#   - 色: お手本の被写体の色（髪や服の色）を「基調色」として書かせない。色の扱い方だけを書かせる。
#   - 度合い: 「適度に」のようなぼかした言い方をさせず、粗さ・完成度・簡略化の強さをはっきり書かせる。
#   - 禁止事項と、最後の 1 文の要約を書かせる（画像 AI が勝手に仕上げを良くするのを抑えるため）。
_INSTRUCTION = """\
You are helping a user build a reusable prompt for an image-editing AI.
Look at the attached reference image and extract ONLY its artistic style.
Do NOT describe what is depicted: no subject, people, characters, pose, clothing, objects,
background contents, text in the image, or layout of the reference.

Then write a prompt that tells an image-editing AI to redraw a DIFFERENT input image in this style,
keeping that input image's subject, identity, composition and pose unchanged.

Rules for the prompt body:
- Be specific and committed about DEGREE. State plainly how rough or polished, how accurate or wobbly,
  how simplified or detailed the drawing is. If the reference is crude, childish, messy or unfinished,
  say so in strong words. Never soften with words like "moderately", "slightly" or "somewhat"
  unless the reference really is in the middle.
- Colors: describe HOW color is applied (flat fills or gradients, opaque or transparent, coverage,
  overflow past the outlines, unpainted gaps, saturation and contrast, number of tones).
  Do NOT list the specific hues of the reference's subject (hair, skin, clothes, objects) as the
  palette; instead tell the editor to keep the input image's own colors. Only prescribe hues when the
  palette itself is clearly a stylistic limit (for example monochrome, sepia, a two-color print).
- Cover, each in its own short section with a heading line: overall style and drawing tool/medium;
  line work; coloring, shading and highlights; texture; how faces, hair, clothing and small details
  are simplified or exaggerated (proportions, deformation); background treatment.
- Add a section listing what the editor must NOT do: the typical "improvements" an image AI would
  add that would break this style (for example clean vector lines, smooth gradients, extra detail,
  3D shading, automatic polishing), chosen to fit this reference.
- End with one sentence that sums up the final look.
- Within sections, use short bullet lines starting with "* ".

Output format (plain text, no markdown other than the "* " bullets, no quotation marks,
no preface or closing remarks):
Line 1: a short name for the style, at most 30 characters.
Line 2: empty.
Line 3 onward: the prompt body, {length}.
Write both the name and the body in {language}."""


def instruction(language: str) -> str:
    """AI に送る指示文。本文を書かせる言語だけが変わる。"""
    return _INSTRUCTION.format(language=_LANGUAGE_NAMES[language], length=_LENGTH_GUIDE[language])


def prepared_image(image_path: Path) -> bytes:
    """送る画像を用意する。見た目の向きに直し、長辺を縮めて JPEG にする。

    作風を読むだけなら大きな画像は要らず、小さくすると入力の料金が下がる。
    WebP を受け付けないプロバイダーがあるため、形式は JPEG にそろえる。
    """
    with Image.open(image_path) as image:
        upright = ImageOps.exif_transpose(image).convert("RGB")
    upright.thumbnail((config.ANALYSIS_IMAGE_MAX_PX, config.ANALYSIS_IMAGE_MAX_PX))
    buffer = io.BytesIO()
    upright.save(buffer, format="JPEG", quality=config.ANALYSIS_JPEG_QUALITY)
    return buffer.getvalue()


def send_once(
    label: str, model: str, send: Callable[[], httpx.Response]
) -> Union[httpx.Response, AnalysisResult]:
    """API を 1 回だけ呼ぶ。通信できなかった場合は、失敗の結果を返す。再試行はしない。"""
    response = provider_common.send_once(label, model, config.ANALYSIS_TIMEOUT_SEC, send)
    if isinstance(response, TransformResult):
        return AnalysisResult(
            model=model, error=response.error, billed_on_failure=response.billed_on_failure
        )
    return response


def http_failure(label: str, model: str, response: httpx.Response) -> AnalysisResult:
    """HTTP エラーの応答を、失敗の結果にする（課金はないものとして扱う）。"""
    message = provider_common.http_error_message(label, response.status_code, response.text)
    return AnalysisResult(model=model, error=message)


def billed_failure(model: str, cost_usd: float, message: str) -> AnalysisResult:
    """応答は返ったが文章を受け取れなかった場合の結果。課金されているとみなし、料金を残す。"""
    return AnalysisResult(model=model, cost_usd=cost_usd, error=message, billed_on_failure=True)


def parse_billed(
    label: str, model: str, fallback_cost_usd: float, parse: Callable[[], AnalysisResult]
) -> AnalysisResult:
    """HTTP 200 の応答を読み取る。想定外の形で読み取りに失敗しても、課金済みとして料金を残す。"""
    try:
        return parse()
    except Exception:  # noqa: BLE001 - 応答の形が変わっても、課金済みの呼び出しを料金 0 で記録しない
        return billed_failure(model, fallback_cost_usd, f"{label} の応答を読み取れませんでした。")


def json_body(response: httpx.Response) -> Optional[dict]:
    """応答の本文を辞書として返す。JSON でない、または辞書でなければ None。"""
    try:
        body = response.json()
    except ValueError:
        return None
    return body if isinstance(body, dict) else None


def token_cost_usd(input_tokens: Optional[int], output_tokens: Optional[int], prices: dict) -> float:
    """トークン数と単価（USD / 100 万トークン）から概算料金を出す。"""
    total = (input_tokens or 0) * prices["input"] + (output_tokens or 0) * prices["output"]
    return total / config.TOKENS_PER_PRICE_UNIT


def fallback_cost_usd(prices: dict) -> float:
    """使用量が分からないときの概算。少なく見積もらないよう、出力を上限いっぱいまで使ったものとする。"""
    return token_cost_usd(config.ANALYSIS_FALLBACK_INPUT_TOKENS, config.ANALYSIS_MAX_OUTPUT_TOKENS, prices)


def prices_of(table: dict, model: str, unknown_key: str) -> dict:
    """モデルの単価。単価表にないモデルは、少なく見積もらないよう高いモデルの単価で計算する。"""
    return table.get(model, table[unknown_key])


def responses_request(model: str, language: str, image: bytes) -> dict:
    """Responses API（OpenAI と xAI で同じ形）の要求を作る。"""
    encoded = base64.b64encode(image).decode("ascii")
    return {
        "model": model,
        "input": [{
            "role": "user",
            "content": [
                {"type": "input_text", "text": instruction(language)},
                {"type": "input_image", "image_url": f"data:{JPEG_MIME};base64,{encoded}"},
            ],
        }],
        "max_output_tokens": config.ANALYSIS_MAX_OUTPUT_TOKENS,
        # 送った画像と応答を、プロバイダー側に保存させない
        "store": False,
    }


def responses_text(body: dict) -> str:
    """Responses API の応答から、AI が書いた文章を取り出す。なければ空文字。"""
    texts = []
    for item in body.get("output") or []:
        if not isinstance(item, dict) or item.get("type") != "message":
            continue
        for part in item.get("content") or []:
            if isinstance(part, dict) and part.get("type") == "output_text" and part.get("text"):
                texts.append(part["text"])
    return "\n".join(texts).strip()
