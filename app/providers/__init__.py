"""Provider adapters: OpenAI-compatible free LLM upstreams."""
from __future__ import annotations

from ..config import ProviderConfig
from .base import (
    AuthError,
    BadRequestError,
    OpenAICompatProvider,
    Provider,
    ProviderError,
    RateLimitError,
    ServerError,
    TimeoutError,
)
from .glm import GLMProvider
from .siliconflow import SiliconFlowProvider

_REGISTRY: dict[str, type[Provider]] = {
    "glm": GLMProvider,
    "siliconflow": SiliconFlowProvider,
}


def build_provider(cfg: ProviderConfig) -> Provider:
    cls = _REGISTRY.get(cfg.name, OpenAICompatProvider)
    return cls(cfg)


__all__ = [
    "Provider",
    "ProviderError",
    "AuthError",
    "BadRequestError",
    "RateLimitError",
    "ServerError",
    "TimeoutError",
    "OpenAICompatProvider",
    "GLMProvider",
    "SiliconFlowProvider",
    "build_provider",
]
