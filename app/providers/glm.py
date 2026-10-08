"""智谱 BigModel (GLM) — OpenAI 兼容上游，提供免费额度模型."""
from __future__ import annotations

from .base import OpenAICompatProvider


class GLMProvider(OpenAICompatProvider):
    name = "glm"
