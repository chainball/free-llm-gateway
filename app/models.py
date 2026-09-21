"""Pydantic schemas, OpenAI-compatible request/response shapes."""
from __future__ import annotations

import time
import uuid
from typing import Any, Literal

from pydantic import BaseModel, Field


# --- chat.completions request -------------------------------------------------

class ChatMessage(BaseModel):
    role: Literal["system", "user", "assistant", "tool"] = "user"
    content: str | list[Any] = ""


class ChatCompletionRequest(BaseModel):
    model: str = "auto"
    messages: list[ChatMessage]
    temperature: float | None = 0.7
    top_p: float | None = None
    max_tokens: int | None = 2048
    stream: bool = False
    # extras tolerated, ignored


# --- chat.completions response ------------------------------------------------

class CompletionChoice(BaseModel):
    index: int = 0
    message: ChatMessage
    finish_reason: str | None = "stop"


class Usage(BaseModel):
    prompt_tokens: int = 0
    completion_tokens: int = 0
    total_tokens: int = 0


class ChatCompletion(BaseModel):
    id: str
    object: str = "chat.completion"
    created: int
    model: str
    choices: list[CompletionChoice]
    usage: Usage = Field(default_factory=Usage)


# --- streaming chunk ----------------------------------------------------------

class StreamDelta(BaseModel):
    role: str | None = None
    content: str | None = None


class StreamChoice(BaseModel):
    index: int = 0
    delta: StreamDelta
    finish_reason: str | None = None


class ChatCompletionChunk(BaseModel):
    id: str
    object: str = "chat.completion.chunk"
    created: int
    model: str
    choices: list[StreamChoice]


# --- /v1/models ---------------------------------------------------------------

class Model(BaseModel):
    id: str
    object: str = "model"
    created: int
    owned_by: str


class ModelList(BaseModel):
    object: str = "list"
    data: list[Model]


# --- /v1/batches --------------------------------------------------------------

class BatchCreateRequest(BaseModel):
    # Simplified: inline JSONL string (each line = one request object)
    input: str
    endpoint: str = "/v1/chat/completions"


class BatchRequestCounts(BaseModel):
    total: int = 0
    completed: int = 0
    failed: int = 0


class Batch(BaseModel):
    id: str
    object: str = "batch"
    endpoint: str = "/v1/chat/completions"
    status: str
    request_counts: BatchRequestCounts = Field(default_factory=BatchRequestCounts)
    created_at: int


class BatchList(BaseModel):
    object: str = "list"
    data: list[Batch]


# --- helpers ------------------------------------------------------------------

def new_id(prefix: str) -> str:
    return f"{prefix}_{uuid.uuid4().hex}"


def now() -> int:
    return int(time.time())
