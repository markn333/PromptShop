"""作風の読み取り（画像からプロンプトの下書きを作る）に使うモデル。"""
from app.analyzers.base import Analyzer
from app.analyzers.gemini_analyzer import GeminiAnalyzer
from app.analyzers.grok_analyzer import GrokAnalyzer
from app.analyzers.openai_analyzer import OpenAIAnalyzer


def default_analyzers() -> dict[str, Analyzer]:
    """使える読み取り役を、画面に並べる順で返す。"""
    analyzers: list[Analyzer] = [OpenAIAnalyzer(), GrokAnalyzer(), GeminiAnalyzer()]
    return {analyzer.name: analyzer for analyzer in analyzers}
