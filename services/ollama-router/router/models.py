"""Pydantic models for requests/responses."""

from __future__ import annotations

import time
from enum import Enum
from typing import Any

from pydantic import BaseModel, Field


# --- Enums ---

class TaskType(str, Enum):
    FAST = "fast"
    DEEP = "deep"
    CODE = "code"
    EMBEDDING = "embedding"
    REASONING = "reasoning"


class NodeStatus(str, Enum):
    ONLINE = "online"
    DEGRADED = "degraded"
    OFFLINE = "offline"


class BalancerStrategy(str, Enum):
    LEAST_LOADED = "least_loaded"
    MODEL_AFFINITY = "model_affinity"
    ROUND_ROBIN = "round_robin"


# --- Node ---

class NodeConfig(BaseModel):
    name: str
    url: str
    tags: list[str] = []
    max_concurrent: int = 2
    default_models: list[str] = []


class NodeState(BaseModel):
    name: str
    url: str
    status: NodeStatus = NodeStatus.OFFLINE
    tags: list[str] = []
    max_concurrent: int = 2
    available_models: list[str] = []
    loaded_models: list[str] = []
    in_flight: int = 0
    total_memory: int = 0
    free_memory: int = 0
    avg_latency_ms: float = 0.0
    error_count: int = 0
    last_seen: float = 0.0


# --- Ollama API models ---

class OllamaGenerateRequest(BaseModel):
    model: str
    prompt: str = ""
    system: str = ""
    template: str = ""
    context: list[int] | None = None
    stream: bool = True
    raw: bool = False
    format: str | None = None
    images: list[str] | None = None
    options: dict[str, Any] | None = None
    keep_alive: str | int | None = None

    model_config = {"extra": "allow"}


class OllamaChatRequest(BaseModel):
    model: str
    messages: list[dict[str, Any]]
    stream: bool = True
    format: str | None = None
    options: dict[str, Any] | None = None
    keep_alive: str | int | None = None

    model_config = {"extra": "allow"}


class OllamaEmbeddingsRequest(BaseModel):
    model: str
    prompt: str | None = None
    input: str | list[str] | None = None
    options: dict[str, Any] | None = None
    keep_alive: str | int | None = None

    model_config = {"extra": "allow"}


class OllamaPullRequest(BaseModel):
    name: str
    insecure: bool = False
    stream: bool = True


class OllamaDeleteRequest(BaseModel):
    name: str


# --- OpenAI-compatible models ---

class OpenAIChatMessage(BaseModel):
    role: str
    content: str | list[Any] | None = None
    name: str | None = None

    model_config = {"extra": "allow"}


class OpenAIChatRequest(BaseModel):
    model: str
    messages: list[OpenAIChatMessage]
    temperature: float | None = None
    top_p: float | None = None
    max_tokens: int | None = None
    stream: bool = False
    stop: str | list[str] | None = None
    frequency_penalty: float | None = None
    presence_penalty: float | None = None
    seed: int | None = None

    model_config = {"extra": "allow"}


class OpenAIEmbeddingRequest(BaseModel):
    model: str
    input: str | list[str]
    encoding_format: str | None = None

    model_config = {"extra": "allow"}


class OpenAIChatChoice(BaseModel):
    index: int = 0
    message: OpenAIChatMessage
    finish_reason: str | None = "stop"


class OpenAIChatResponse(BaseModel):
    id: str = ""
    object: str = "chat.completion"
    created: int = Field(default_factory=lambda: int(time.time()))
    model: str = ""
    choices: list[OpenAIChatChoice] = []
    usage: dict[str, int] = {}


class OpenAIEmbeddingData(BaseModel):
    object: str = "embedding"
    index: int = 0
    embedding: list[float] = []


class OpenAIEmbeddingResponse(BaseModel):
    object: str = "list"
    data: list[OpenAIEmbeddingData] = []
    model: str = ""
    usage: dict[str, int] = {}


class OpenAIModel(BaseModel):
    id: str
    object: str = "model"
    created: int = 0
    owned_by: str = "ollama"


# --- Admin models ---

class PreloadRequest(BaseModel):
    model: str
    node: str | None = None


class UnloadRequest(BaseModel):
    model: str
    node: str | None = None


class PullRequest(BaseModel):
    model: str
    node: str | None = None
