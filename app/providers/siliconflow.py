"""硅基流动 SiliconFlow — 9B 以下永久免费(白名单 Qwen3-8B 等)."""
from __future__ import annotations

from .base import OpenAICompatProvider


class SiliconFlowProvider(OpenAICompatProvider):
    name = "siliconflow"
