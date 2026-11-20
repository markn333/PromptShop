"""入力の検証エラー（422）を、利用者向けの日本語の文にする。

入力された値そのものは文に含めない（API キーなどを画面やログに出さないため）。
"""
from typing import Any

# API の項目名 → 画面での呼び名
_FIELD_LABELS = {
    "name": "ジャンル名",
    "title": "タイトル",
    "body": "本文",
    "prompt_title": "タイトル",
    "keep_aspect": "縦横比維持",
    "path": "フォルダーの場所",
    "language": "言語",
    "prompt_body": "本文",
    "genre_id": "ジャンル",
    "sort_order": "並び順",
    "input_image_id": "元画像",
    "prompt_id": "プロンプト",
    "provider": "プロバイダー",
    "favorite": "お気に入り",
    "example": "作例",
    "rating": "評価",
    "min_rating": "評価",
    "limit": "件数",
    "monthly_budget_usd": "月の予算",
    "key": "API キー",
    "file": "画像ファイル",
}
_FALLBACK_MESSAGE = "入力内容を確認してください。"


def _number(value: Any) -> str:
    """上限・下限の値を表示用にする。10000.0 のような端数のない小数は 10000 と書く。"""
    if isinstance(value, float) and value.is_integer():
        return str(int(value))
    return str(value)


def _describe(error: dict[str, Any]) -> str:
    """検証エラー 1 件を文にする。"""
    location = error.get("loc") or ()
    label = _FIELD_LABELS.get(str(location[-1])) if location else None
    if label is None:
        return _FALLBACK_MESSAGE
    kind = error.get("type", "")
    context = error.get("ctx") or {}
    if kind == "missing":
        return f"{label}を指定してください。"
    if kind == "string_too_short":
        return f"{label}を入力してください。"
    if kind == "string_too_long":
        return f"{label}は {context.get('max_length')} 文字以内で入力してください。"
    if kind in ("greater_than", "greater_than_equal"):
        limit = context.get("gt", context.get("ge"))
        suffix = "より大きい値" if kind == "greater_than" else "以上"
        return f"{label}は {_number(limit)} {suffix}で指定してください。"
    if kind in ("less_than", "less_than_equal"):
        limit = context.get("lt", context.get("le"))
        suffix = "より小さい値" if kind == "less_than" else "以下"
        return f"{label}は {_number(limit)} {suffix}で指定してください。"
    return f"{label}の値が正しくありません。"


def describe_errors(errors: list[dict[str, Any]]) -> str:
    """検証エラーの一覧を、重複を除いて 1 つの文にまとめる。"""
    messages = list(dict.fromkeys(_describe(error) for error in errors))
    return " ".join(messages) or _FALLBACK_MESSAGE
