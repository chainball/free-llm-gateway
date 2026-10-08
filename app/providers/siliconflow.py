"""硅基流动 SiliconFlow — OpenAI 兼容上游，提供免费额度模型."""
from __future__ import annotations

from .base import OpenAICompatProvider


class SiliconFlowProvider(OpenAICompatProvider):
    name = "siliconflow"
