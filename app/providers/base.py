"""画像変換プロバイダー共通のインターフェース。"""
from abc import ABC, abstractmethod
from dataclasses import dataclass
from pathlib import Path
from typing import Optional


@dataclass(frozen=True)
class TransformResult:
    """プロバイダーを 1 回呼んだ結果。

    成功時は image_bytes が入り、失敗時は error に利用者向けの理由が入る。
    billed_on_failure は、失敗でも課金された可能性があるときに True にする。
    """

    model: str
    image_bytes: Optional[bytes] = None
    cost_usd: float = 0.0
    error: Optional[str] = None
    billed_on_failure: bool = False

    @property
    def ok(self) -> bool:
        """画像を受け取れたか。"""
        return self.error is None and self.image_bytes is not None


class Provider(ABC):
    """画像変換プロバイダー。

    transform は例外を外に投げず、失敗を TransformResult.error で返す。
    課金を暴走させないため、実装側で自動の再試行をしてはならない。
    """

    name: str          # 履歴に記録する識別子（例: "openai"）
    label: str         # 画面に表示する名前（例: "OpenAI"）
    api_key_env: str   # API キーを読む環境変数の名前（例: "OPENAI_API_KEY"）

    @property
    @abstractmethod
    def model(self) -> str:
        """現在の設定で使うモデル ID。"""

    @abstractmethod
    def is_configured(self) -> bool:
        """API キーが設定されていて呼び出せる状態か。"""

    @abstractmethod
    def transform(self, image_path: Path, prompt: str, keep_aspect: bool = True) -> TransformResult:
        """画像とプロンプトを送り、変換結果を返す。API の呼び出しは 1 回だけ。

        keep_aspect が True なら、出力の縦横比を元画像に合わせて指定する。
        False なら指定せず、プロバイダーに任せる（プロンプトの指示や既定の形になる）。
        """
