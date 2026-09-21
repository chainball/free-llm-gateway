"""百度千帆 — ERNIE-Speed/Lite 永久免费不限量."""
from __future__ import annotations

from .base import OpenAICompatProvider


class BaiduProvider(OpenAICompatProvider):
    name = "baidu"
