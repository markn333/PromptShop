"""画像変換プロバイダー。"""
from app.providers.base import Provider
from app.providers.gemini_provider import GeminiProvider
from app.providers.grok_provider import GrokProvider
from app.providers.openai_provider import OpenAIProvider


def default_providers() -> dict[str, Provider]:
    """使えるプロバイダーを、画面に並べる順で返す。"""
    providers: list[Provider] = [OpenAIProvider(), GrokProvider(), GeminiProvider()]
    return {provider.name: provider for provider in providers}
