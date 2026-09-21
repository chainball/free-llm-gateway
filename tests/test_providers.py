import httpx
import pytest

from app.config import ProviderConfig
from app.providers.base import OpenAICompatProvider, RateLimitError


def cfg(**kw) -> ProviderConfig:
    d = dict(name="t", base_url="http://x/v1", api_key="k", models=["m"])
    d.update(kw)
    return ProviderConfig(**d)


async def test_chat_parses_content():
    def handler(req):
        return httpx.Response(200, json={"choices": [{"message": {"content": "hi"}}]})

    p = OpenAICompatProvider(cfg(), client=httpx.AsyncClient(transport=httpx.MockTransport(handler)))
    out = await p.chat([{"role": "user", "content": "x"}], "m")
    assert out == "hi"
    await p.close()


async def test_chat_429_raises_ratelimit():
    def handler(req):
        return httpx.Response(429, json={})

    p = OpenAICompatProvider(cfg(), client=httpx.AsyncClient(transport=httpx.MockTransport(handler)))
    with pytest.raises(RateLimitError):
        await p.chat([{"role": "user", "content": "x"}], "m")
    await p.close()


async def test_chat_stream_passthrough():
    def handler(req):
        return httpx.Response(
            200,
            content=b'data: {"x":1}\n\ndata: [DONE]\n\n',
            headers={"content-type": "text/event-stream"},
        )

    p = OpenAICompatProvider(cfg(), client=httpx.AsyncClient(transport=httpx.MockTransport(handler)))
    lines = [line async for line in p.chat_stream([{"role": "user", "content": "x"}], "m")]
    assert "data: [DONE]" in lines
    await p.close()
