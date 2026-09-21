"""Background worker pool: drains pending batch items through the router."""
from __future__ import annotations

import asyncio
import json

from .db import Database
from .models import ChatCompletion, ChatMessage, CompletionChoice, Usage, new_id, now
from .providers import (
    AuthError,
    BadRequestError,
    ProviderError,
    RateLimitError,
    ServerError,
    TimeoutError,
)
from .router import NoProviderError, Router, UnknownModelError, backoff_delay, estimate_tokens


class Worker:
    def __init__(
        self,
        db: Database,
        router: Router,
        wake: asyncio.Event,
        concurrency: int = 4,
        max_requeue: int = 5,
    ):
        self.db = db
        self.router = router
        self.wake = wake
        self.concurrency = concurrency
        self.max_requeue = max_requeue
        self._stop = asyncio.Event()
        self._tasks: list[asyncio.Task] = []

    async def start(self) -> None:
        self._tasks = [asyncio.create_task(self._loop()) for _ in range(self.concurrency)]

    async def stop(self) -> None:
        self._stop.set()
        self.wake.set()
        if self._tasks:
            await asyncio.gather(*self._tasks, return_exceptions=True)
        self._tasks = []

    async def _loop(self) -> None:
        while not self._stop.is_set():
            item = await self.db.claim_next_pending()
            if item is None:
                self.wake.clear()
                try:
                    await asyncio.wait_for(self.wake.wait(), timeout=3.0)
                except asyncio.TimeoutError:
                    pass
                continue
            await self._process(item)

    async def _process(self, item: dict) -> None:
        try:
            body = json.loads(item["request_json"])
        except json.JSONDecodeError as e:
            await self.db.set_item(item["id"], "failed", error=f"invalid request json: {e}")
            return

        model = body.get("model", "auto") or "auto"
        messages = body.get("messages", [])
        temperature = body.get("temperature", 0.7) if body.get("temperature") is not None else 0.7
        max_tokens = body.get("max_tokens", 2048) if body.get("max_tokens") is not None else 2048

        try:
            content, rt, _failover = await self.router.complete(
                model, messages, temperature=temperature, max_tokens=max_tokens
            )
        except (BadRequestError, UnknownModelError) as e:
            await self.db.set_item(item["id"], "failed", error=str(e))
            return
        except (RateLimitError, ServerError, TimeoutError, AuthError, NoProviderError, ProviderError) as e:
            rc = item["retry_count"] + 1
            if rc <= self.max_requeue:
                await self.db.set_item(item["id"], "pending", retry_count=rc, error=str(e))
                await asyncio.sleep(backoff_delay(rc))
            else:
                await self.db.set_item(item["id"], "failed", error=str(e))
            return

        actual = model if model not in ("", "auto") else (rt.cfg.models[0] if rt.cfg.models else rt.cfg.name)
        prompt_tokens = max(1, estimate_tokens(messages, 0))
        completion_tokens = max(1, len(content) // 4)
        completion = ChatCompletion(
            id=new_id("chatcmpl"),
            created=now(),
            model=actual,
            choices=[CompletionChoice(message=ChatMessage(role="assistant", content=content))],
            usage=Usage(
                prompt_tokens=prompt_tokens,
                completion_tokens=completion_tokens,
                total_tokens=prompt_tokens + completion_tokens,
            ),
        )
        await self.db.set_item(
            item["id"],
            "done",
            result_json=completion.model_dump_json(),
            provider=rt.cfg.name,
            model=actual,
        )
