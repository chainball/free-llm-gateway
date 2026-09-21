"""智谱 GLM (BigModel) — glm-4-flash 永久免费."""
from __future__ import annotations

from .base import OpenAICompatProvider


class GLMProvider(OpenAICompatProvider):
    name = "glm"
