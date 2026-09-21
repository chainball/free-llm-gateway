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
from .baidu import BaiduProvider
from .glm import GLMProvider
from .siliconflow import SiliconFlowProvider

_REGISTRY: dict[str, type[Provider]] = {
    "glm": GLMProvider,
    "siliconflow": SiliconFlowProvider,
    "baidu": BaiduProvider,
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
    "BaiduProvider",
    "build_provider",
]
