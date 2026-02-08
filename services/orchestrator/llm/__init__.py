"""LLM provider abstraction — pluggable backends for the orchestrator brain."""

from __future__ import annotations

from typing import TYPE_CHECKING

from llm.base import LLMProvider, LLMResponse, Message, ToolCall

if TYPE_CHECKING:
    from config import OrchestratorSettings


def create_provider(settings: OrchestratorSettings) -> LLMProvider:
    """Factory — instantiate the configured LLM provider."""
    name = settings.llm_provider.lower()

    if name == "gemini":
        from llm.gemini import GeminiProvider

        return GeminiProvider(
            api_key=settings.gemini_api_key,
            model=settings.gemini_model,
            temperature=settings.llm_temperature,
        )

    if name == "openai":
        from llm.openai_compat import OpenAICompatProvider

        return OpenAICompatProvider(
            api_key=settings.openai_api_key,
            model=settings.openai_model,
            temperature=settings.llm_temperature,
        )

    if name == "anthropic":
        from llm.anthropic_llm import AnthropicProvider

        return AnthropicProvider(
            api_key=settings.anthropic_api_key,
            model=settings.anthropic_model,
            temperature=settings.llm_temperature,
        )

    if name == "ollama":
        from llm.openai_compat import OpenAICompatProvider

        return OpenAICompatProvider(
            api_key="ollama",
            model=settings.ollama_model,
            temperature=settings.llm_temperature,
            base_url=f"{settings.ollama_url}/v1",
        )

    raise ValueError(f"Unknown LLM provider: {name!r}. Use gemini|openai|anthropic|ollama.")


__all__ = [
    "LLMProvider",
    "LLMResponse",
    "Message",
    "ToolCall",
    "create_provider",
]
