from __future__ import annotations

import asyncio
from types import SimpleNamespace

import httpx
import pytest
from fastapi import FastAPI

from app import batch_api, openai_api, web
from app.db import Database
from app.router import Router
from app.worker import Worker
from tests.helpers import make_runtime


@pytest.fixture
async def gateway(tmp_path):
    db = Database(str(tmp_path / "test.db"))
    await db.connect()
    await db.reset_running_to_pending()

    router = Router([make_runtime("fake", ["fake-model"])])
    wake = asyncio.Event()
    worker = Worker(db, router, wake, concurrency=2, max_requeue=2)

    app = FastAPI()
    app.include_router(openai_api.router)
    app.include_router(batch_api.router)
    app.include_router(web.router)
    app.state.db = db
    app.state.router = router
    app.state.wake = wake
    app.state.worker = worker

    await worker.start()
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        yield SimpleNamespace(client=client, db=db, router=router, worker=worker, wake=wake, app=app)
    await worker.stop()
    await db.close()
