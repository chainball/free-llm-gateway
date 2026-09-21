"""FastAPI app: OpenAI-compatible gateway over domestic free LLM APIs."""
from __future__ import annotations

import asyncio
import logging
import os
from contextlib import asynccontextmanager

from pathlib import Path

from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles

from . import batch_api, openai_api, web
from .config import build_providers
from .db import Database
from .providers import build_provider
from .router import ProviderRuntime, Router
from .worker import Worker

logger = logging.getLogger("gateway")


def _build_router(db: Database) -> tuple[Router, list[ProviderRuntime]]:
    providers = build_providers()
    runtimes = [ProviderRuntime(build_provider(cfg), cfg) for cfg in providers]
    router = Router(runtimes)
    # settings are applied after db.connect() at startup (see lifespan)
    return router, runtimes


@asynccontextmanager
async def lifespan(app: FastAPI):
    db_path = os.environ.get("GATEWAY_DB", "./data/tasks.db")
    workers = int(os.environ.get("GATEWAY_WORKERS", "4"))

    db = Database(db_path)
    await db.connect()
    await db.reset_running_to_pending()

    router, runtimes = _build_router(db)
    settings = await db.get_settings()
    router.apply_settings(settings)

    wake = asyncio.Event()
    worker = Worker(db, router, wake, concurrency=workers)

    app.state.db = db
    app.state.router = router
    app.state.wake = wake
    app.state.worker = worker
    app.state.runtimes = runtimes

    await worker.start()
    logger.info("gateway started: %d provider(s), %d worker(s)", len(runtimes), workers)

    yield

    await worker.stop()
    for rt in runtimes:
        await rt.provider.close()
    await db.close()
    logger.info("gateway stopped")


app = FastAPI(title="free-llm-gateway", version="0.1.0", lifespan=lifespan)

app.include_router(openai_api.router)
app.include_router(batch_api.router)
app.include_router(web.router)

_STATIC_DIR = Path(__file__).resolve().parent.parent / "static"
app.mount("/static", StaticFiles(directory=_STATIC_DIR), name="static")


@app.get("/health")
async def health():
    return {"status": "ok"}
