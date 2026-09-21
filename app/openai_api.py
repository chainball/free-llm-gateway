"""OpenAI-compatible endpoints: /v1/chat/completions (sync + SSE), /v1/models."""
from __future__ import annotations

import json

from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse, StreamingResponse

from .models import (
    ChatCompletion,
    ChatCompletionChunk,
    ChatCompletionRequest,
    ChatMessage,
    CompletionChoice,
    Model,
    ModelList,
    StreamChoice,
    StreamDelta,
    Usage,
    new_id,
    now,
)
from .providers import BadRequestError, ProviderError
from .router import UnknownModelError

router = APIRouter()


def _messages(req: ChatCompletionRequest) -> list[dict]:
    return [{"role": m.role, "content": m.content} for m in req.messages]


def _actual_model(req_model: str, rt) -> str:
    if req_model not in ("", "auto"):
        return req_model
    return rt.cfg.models[0] if rt.cfg.models else rt.cfg.name


def _error(status: int, message: str, etype: str) -> JSONResponse:
    return JSONResponse(
        status_code=status,
        content={"error": {"message": message, "type": etype, "code": status}},
    )


def _map_error(e: ProviderError) -> JSONResponse:
    if isinstance(e, UnknownModelError):
        return _error(404, str(e), "invalid_request_error")
    if isinstance(e, BadRequestError):
        return _error(400, str(e), "invalid_request_error")
    return _error(502, str(e), "upstream_error")


@router.post("/v1/chat/completions")
async def chat_completions(req: ChatCompletionRequest, request: Request):
    app_router = request.app.state.router
    messages = _messages(req)
    temperature = req.temperature if req.temperature is not None else 0.7
    max_tokens = req.max_tokens if req.max_tokens is not None else 2048

    if req.stream:
        return StreamingResponse(
            _stream(req, app_router, messages, temperature, max_tokens),
            media_type="text/event-stream",
            headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
        )

    try:
        content, rt = await app_router.complete(
            req.model, messages, temperature=temperature, max_tokens=max_tokens
        )
    except ProviderError as e:
        return _map_error(e)

    actual = _actual_model(req.model, rt)
    prompt_tokens = max(1, sum(len(str(m.get("content", ""))) for m in messages) // 4)
    completion_tokens = max(1, len(content) // 4)
    return ChatCompletion(
        id=new_id("chatcmpl"),
        created=now(),
        model=actual,
        choices=[CompletionChoice(message=ChatMessage(role="assistant", content=content))],
        usage=Usage(
            prompt_tokens=prompt_tokens,
            completion_tokens=completion_tokens,
            total_tokens=prompt_tokens + completion_tokens,
        ),
    )


async def _stream(req: ChatCompletionRequest, app_router, messages, temperature, max_tokens):
    try:
        async for line, rt in app_router.complete_stream(
            req.model, messages, temperature=temperature, max_tokens=max_tokens
        ):
            yield f"{line}\n\n"
    except ProviderError as e:
        err = {"error": {"message": str(e), "type": type(e).__name__}}
        yield f"data: {json.dumps(err, ensure_ascii=False)}\n\n"
        yield "data: [DONE]\n\n"


@router.get("/v1/models")
async def list_models(request: Request):
    app_router = request.app.state.router
    data = [Model(id="auto", created=now(), owned_by="gateway")]
    for model, owner in app_router.all_models():
        data.append(Model(id=model, created=now(), owned_by=owner))
    return ModelList(data=data)
