"""Routing: model -> provider resolution, weighted pick, meltdown, failover."""
from __future__ import annotations

import asyncio
import random
import time

from .config import ProviderConfig
from .providers import (
    AuthError,
    BadRequestError,
    Provider,
    ProviderError,
    RateLimitError,
    ServerError,
    TimeoutError,
)
from .ratelimit import RateLimiter

MELT_THRESHOLD = 3  # consecutive failures before a provider enters cooldown


class UnknownModelError(ProviderError):
    retryable = False


class NoProviderError(ProviderError):
    retryable = True


class ProviderRuntime:
    def __init__(self, provider: Provider, cfg: ProviderConfig):
        self.provider = provider
        self.cfg = cfg
        self.limiter = RateLimiter(cfg.concurrency, cfg.rpm, cfg.tpm)
        self._failures = 0
        self._cooled_until = 0.0

    @property
    def melted(self) -> bool:
        return time.monotonic() < self._cooled_until

    @property
    def usable(self) -> bool:
        return self.cfg.enabled and not self.melted and bool(self.cfg.key_list)

    def record_success(self) -> None:
        self._failures = 0

    def record_failure(self) -> None:
        self._failures += 1
        if self._failures >= MELT_THRESHOLD:
            self._cooled_until = time.monotonic() + self.cfg.cooldown
            self._failures = 0


def estimate_tokens(messages: list[dict], max_tokens: int) -> int:
    chars = sum(len(str(m.get("content", ""))) for m in messages)
    return chars // 4 + max_tokens


def backoff_delay(attempt: int) -> float:
    base = min(30.0, 2.0 ** attempt)
    return base * (0.5 + random.random())  # +50-150% jitter, standard


class Router:
    def __init__(self, runtimes: list[ProviderRuntime]):
        self.runtimes = runtimes

    def resolve(self, model: str) -> list[ProviderRuntime]:
        """Map a requested model to candidate providers (order matters for failover)."""
        if model in ("", "auto", None):
            return [rt for rt in self.runtimes if rt.usable]
        by_model = [rt for rt in self.runtimes if model in rt.cfg.models and rt.usable]
        if by_model:
            return by_model
        by_name = [rt for rt in self.runtimes if rt.cfg.name == model and rt.usable]
        return by_name

    def all_models(self) -> list[tuple[str, str]]:
        out: list[tuple[str, str]] = []
        for rt in self.runtimes:
            if not rt.cfg.enabled:
                continue
            for m in rt.cfg.models:
                out.append((m, rt.cfg.name))
        return out

    def apply_settings(self, settings: dict[str, str]) -> None:
        """Apply web-editable overrides and rebuild rate limiters in place."""
        for rt in self.runtimes:
            prefix = f"provider.{rt.cfg.name}."
            if f"{prefix}enabled" in settings:
                rt.cfg.enabled = settings[f"{prefix}enabled"].lower() == "true"
            if f"{prefix}rpm" in settings:
                rt.cfg.rpm = int(settings[f"{prefix}rpm"])
            if f"{prefix}tpm" in settings:
                rt.cfg.tpm = int(settings[f"{prefix}tpm"])
            if f"{prefix}concurrency" in settings:
                rt.cfg.concurrency = int(settings[f"{prefix}concurrency"])
            rt.limiter = RateLimiter(rt.cfg.concurrency, rt.cfg.rpm, rt.cfg.tpm)

    def _pick(self, candidates: list[ProviderRuntime]) -> ProviderRuntime | None:
        pool = [rt for rt in candidates if rt.usable]
        if not pool:
            return None
        weights = [max(1, rt.cfg.weight) for rt in pool]
        return random.choices(pool, weights=weights, k=1)[0]

    def _known(self, model: str) -> bool:
        return any(model in rt.cfg.models or rt.cfg.name == model for rt in self.runtimes)

    def _resolve_model(self, model: str, rt: ProviderRuntime) -> str:
        if model in ("", "auto"):
            return rt.cfg.models[0] if rt.cfg.models else rt.cfg.name
        return model

    def _empty_reason(self, model: str) -> ProviderError:
        if model in ("", "auto") or self._known(model):
            return NoProviderError(f"no provider available for {model!r} (all disabled or no key)")
        return UnknownModelError(f"unknown model: {model!r}")

    async def complete(
        self,
        model: str,
        messages: list[dict],
        *,
        temperature: float = 0.7,
        max_tokens: int = 2048,
    ) -> tuple[str, ProviderRuntime]:
        """Run a completion with retry + failover across providers."""
        candidates = self.resolve(model)
        if not candidates:
            raise self._empty_reason(model)

        est = estimate_tokens(messages, max_tokens)
        last_err: ProviderError | None = None

        for rt in candidates:
            for attempt in range(max(1, rt.cfg.max_retries)):
                if rt.melted:
                    break
                try:
                    async with rt.limiter:
                        await rt.limiter.wait(est)
                        content = await rt.provider.chat(
                            messages, self._resolve_model(model, rt),
                            temperature=temperature, max_tokens=max_tokens,
                        )
                    rt.record_success()
                    return content, rt
                except BadRequestError:
                    raise
                except AuthError as e:
                    last_err = e
                    rt.record_failure()
                    break  # key dead -> next provider
                except (RateLimitError, ServerError, TimeoutError) as e:
                    last_err = e
                    rt.record_failure()
                    if attempt < rt.cfg.max_retries - 1:
                        await asyncio.sleep(backoff_delay(attempt))

        if last_err is not None:
            raise last_err
        raise NoProviderError("no provider available")

    async def complete_stream(
        self,
        model: str,
        messages: list[dict],
        *,
        temperature: float = 0.7,
        max_tokens: int = 2048,
    ):
        """Yield (is_sse_data, text) tuples from a streaming completion."""
        candidates = self.resolve(model)
        if not candidates:
            raise self._empty_reason(model)

        est = estimate_tokens(messages, max_tokens)
        last_err: ProviderError | None = None

        for rt in candidates:
            if rt.melted:
                continue
            try:
                async with rt.limiter:
                    await rt.limiter.wait(est)
                    async for line in rt.provider.chat_stream(
                        messages, self._resolve_model(model, rt),
                        temperature=temperature, max_tokens=max_tokens,
                    ):
                        yield line, rt
                rt.record_success()
                return
            except BadRequestError:
                raise
            except AuthError as e:
                last_err = e
                rt.record_failure()
                continue
            except (RateLimitError, ServerError, TimeoutError) as e:
                last_err = e
                rt.record_failure()

        if last_err is not None:
            raise last_err
        raise NoProviderError("no provider available")
