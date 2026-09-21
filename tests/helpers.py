"""Shared test helpers: fake provider + runtime factory."""
from __future__ import annotations

from app.config import ProviderConfig
from app.providers import Provider
from app.router import ProviderRuntime


class FakeProvider(Provider):
    name = "fake"
    models = ["fake-model"]

    def __init__(self, respond: str = "fake reply", fail: Exception | None = None):
        self.respond = respond
        self.fail = fail

    async def chat(self, messages, model, *, temperature=0.7, max_tokens=2048) -> str:
        if self.fail:
            raise self.fail
        return self.respond

    async def chat_stream(self, messages, model, *, temperature=0.7, max_tokens=2048):
        if self.fail:
            raise self.fail
        yield 'data: {"id":"c","object":"chat.completion.chunk","created":0,"model":"fake-model","choices":[{"index":0,"delta":{"content":"fake"},"finish_reason":null}]}'
        yield "data: [DONE]"


def make_cfg(
    name: str,
    models: list[str],
    *,
    enabled: bool = True,
    concurrency: int = 1,
    rpm: int = 1000,
    tpm: int = 1_000_000,
    max_retries: int = 1,
    cooldown: float = 0.1,
) -> ProviderConfig:
    return ProviderConfig(
        name=name,
        base_url="http://fake/v1",
        api_key="k",
        models=models,
        enabled=enabled,
        concurrency=concurrency,
        rpm=rpm,
        tpm=tpm,
        max_retries=max_retries,
        cooldown=cooldown,
    )


def make_runtime(
    name: str,
    models: list[str],
    *,
    respond: str = "fake reply",
    fail: Exception | None = None,
    **cfg_kw,
) -> ProviderRuntime:
    cfg = make_cfg(name, models, **cfg_kw)
    return ProviderRuntime(FakeProvider(respond=respond, fail=fail), cfg)
