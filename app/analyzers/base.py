"""画像の作風を読み取って、プロンプトの下書きを書かせる機能（作風の読み取り）の共通インターフェース。"""
import os
from abc import ABC, abstractmethod
from dataclasses import dataclass
from pathlib import Path
from typing import Optional


@dataclass(frozen=True)
class AnalysisResult:
    """読み取りを 1 回呼んだ結果。

    成功時は text に AI が書いた文章が入り、失敗時は error に利用者向けの理由が入る。
    billed_on_failure は、失敗でも課金された可能性があるときに True にする。
    """

    model: str
    text: Optional[str] = None
    cost_usd: float = 0.0
    error: Optional[str] = None
    billed_on_failure: bool = False

    @property
    def ok(self) -> bool:
        """文章を受け取れたか。"""
        return self.error is None and bool(self.text)


class Analyzer(ABC):
    """画像を見て文章を書けるモデルを呼ぶ。

    analyze は例外を外に投げず、失敗を AnalysisResult.error で返す。
    課金を暴走させないため、実装側で自動の再試行をしてはならない。
    API キーは、同じ会社の画像変換プロバイダーと同じ環境変数から読む。
    """

    name: str            # 履歴に記録する識別子（画像変換プロバイダーと同じ。例: "openai"）
    label: str           # 画面に表示する名前
    api_key_env: str     # API キーを読む環境変数の名前
    model_env: str       # モデル ID を上書きする環境変数の名前
    default_model: str   # 上書きがないときのモデル ID

    @property
    def model(self) -> str:
        """現在の設定で使うモデル ID。"""
        return os.environ.get(self.model_env, "").strip() or self.default_model

    def _api_key(self) -> str:
        return os.environ.get(self.api_key_env, "").strip()

    def is_configured(self) -> bool:
        """API キーが設定されていて呼び出せる状態か。"""
        return bool(self._api_key())

    @abstractmethod
    def analyze(self, image_path: Path, language: str) -> AnalysisResult:
        """画像を送り、作風を書いた文章を返す。API の呼び出しは 1 回だけ。"""
