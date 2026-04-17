"""LLM provider abstraction — pluggable backends for the orchestrator brain."""

from __future__ import annotations

from typing import TYPE_CHECKING

from llm.base import LLMProvider, LLMResponse, Message, ToolCall

if TYPE_CHECKING:
    from config import OrchestratorSettings


def create_provider(settings: OrchestratorSettings) -> LLMProvider:
    """Factory — instantiate the configured LLM provider.

    The ``anthropic`` path always routes through llm-router (:8070) so that
    Opus 4.7's temperature restriction is handled transparently by the router.
    Gemini, OpenAI, and Ollama paths remain as direct-provider calls for now
    (those providers accept temperature; router migration for them is deferred
    to a later PR — scope kept minimal per PR 4 brief).
    """
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
        # Route through llm-router — never pass temperature directly.
        # Opus 4.7 returns 400 on temperature=; the router strips it per model.
        from llm.router_llm import RouterLLMProvider

        return RouterLLMProvider(
            router_url=settings.llm_router_url,
            model=settings.anthropic_model,
            max_tokens=settings.llm_max_tokens,
        )

    if name == "ollama":
        from llm.openai_compat import OpenAICompatProvider

        return OpenAICompatProvider(
            api_key="ollama",
            model=settings.ollama_model,
            temperature=settings.llm_temperature,
            base_url=f"{settings.ollama_url}/v1",
        )

    raise ValueError(
        f"Unknown LLM provider: {name!r}. Use gemini|openai|anthropic|ollama."
    )


__all__ = [
    "LLMProvider",
    "LLMResponse",
    "Message",
    "ToolCall",
    "create_provider",
]
