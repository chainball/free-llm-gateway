"""OpenAI-compatible provider base: request building, error classification, parse."""
from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Any, AsyncIterator

import httpx

from ..config import ProviderConfig


class ProviderError(Exception):
    """Classified upstream error. `retryable` drives retry vs failover."""

    retryable = True


class RateLimitError(ProviderError):
    """HTTP 429 / upstream rate-limit."""


class AuthError(ProviderError):
    """HTTP 401/403 — key invalid or quota exhausted."""

    retryable = False


class BadRequestError(ProviderError):
    """HTTP 400 — malformed request or content policy rejection."""

    retryable = False


class ServerError(ProviderError):
    """HTTP 5xx."""


class TimeoutError(ProviderError):
    """Connection/read timeout."""


class Provider(ABC):
    name = "base"
    models: list[str] = []

    @abstractmethod
    async def chat(
        self,
        messages: list[dict],
        model: str,
        *,
        temperature: float = 0.7,
        max_tokens: int = 2048,
    ) -> str: ...

    @abstractmethod
    async def chat_stream(
        self,
        messages: list[dict],
        model: str,
        *,
        temperature: float = 0.7,
        max_tokens: int = 2048,
    ) -> AsyncIterator[str]: ...


class OpenAICompatProvider(Provider):
    name = "openai-compat"
    models: list[str] = []

    def __init__(self, config: ProviderConfig, client: httpx.AsyncClient | None = None):
        self.config = config
        self.models = list(config.models)
        self._keys = config.key_list
        self._key_idx = 0
        self._client = client or httpx.AsyncClient(
            timeout=httpx.Timeout(connect=10.0, read=120.0, write=30.0, pool=30.0),
            limits=httpx.Limits(max_connections=20, max_keepalive_connections=10),
        )

    async def close(self) -> None:
        await self._client.aclose()

    def _pick_key(self) -> str:
        if not self._keys:
            return ""
        key = self._keys[self._key_idx % len(self._keys)]
        self._key_idx += 1
        return key

    def _rotate_key(self) -> None:
        if self._keys:
            self._key_idx += 1

    def _headers(self, key: str) -> dict[str, str]:
        return {"Authorization": f"Bearer {key}", "Content-Type": "application/json"}

    def _payload(self, messages: list[dict], model: str, temperature: float, max_tokens: int, stream: bool) -> dict:
        return {
            "model": model,
            "messages": messages,
            "temperature": temperature,
            "max_tokens": max_tokens,
            "stream": stream,
        }

    def _classify(self, status: int) -> ProviderError:
        if status == 429:
            return RateLimitError(f"{self.name}: rate limited (429)")
        if status in (401, 403):
            return AuthError(f"{self.name}: auth failed ({status})")
        if status == 400:
            return BadRequestError(f"{self.name}: bad request (400)")
        if status >= 500:
            return ServerError(f"{self.name}: server error ({status})")
        return ProviderError(f"{self.name}: http {status}")

    def _extract_content(self, data: dict) -> str:
        try:
            return data["choices"][0]["message"]["content"] or ""
        except (KeyError, IndexError, TypeError) as e:
            raise ProviderError(f"{self.name}: unexpected response shape") from e

    async def chat(self, messages, model, *, temperature=0.7, max_tokens=2048) -> str:
        key = self._pick_key()
        url = f"{self.config.base_url}/chat/completions"
        payload = self._payload(messages, model, temperature, max_tokens, stream=False)
        try:
            resp = await self._client.post(url, json=payload, headers=self._headers(key))
        except httpx.TimeoutException as e:
            raise TimeoutError(f"{self.name}: timeout") from e
        except httpx.TransportError as e:
            raise ServerError(f"{self.name}: transport error: {e}") from e

        if resp.status_code != 200:
            err = self._classify(resp.status_code)
            if isinstance(err, AuthError):
                self._rotate_key()
            raise err

        return self._extract_content(resp.json())

    async def chat_stream(self, messages, model, *, temperature=0.7, max_tokens=2048) -> AsyncIterator[str]:
        key = self._pick_key()
        url = f"{self.config.base_url}/chat/completions"
        payload = self._payload(messages, model, temperature, max_tokens, stream=True)
        try:
            async with self._client.stream("POST", url, json=payload, headers=self._headers(key)) as resp:
                if resp.status_code != 200:
                    body = await resp.aread()
                    err = self._classify(resp.status_code)
                    if isinstance(err, AuthError):
                        self._rotate_key()
                    raise err
                async for line in resp.aiter_lines():
                    if line:
                        yield line
        except httpx.TimeoutException as e:
            raise TimeoutError(f"{self.name}: stream timeout") from e
        except httpx.TransportError as e:
            raise ServerError(f"{self.name}: transport error: {e}") from e
