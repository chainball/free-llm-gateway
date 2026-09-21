"""Management console: static page + provider/batch management JSON API."""
from __future__ import annotations

from pathlib import Path

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import FileResponse
from pydantic import BaseModel

from .batch_api import batch_to_dict

router = APIRouter()

_STATIC = Path(__file__).resolve().parent.parent / "static"


class ProviderUpdate(BaseModel):
    enabled: bool | None = None
    rpm: int | None = None
    tpm: int | None = None
    concurrency: int | None = None


@router.get("/")
async def index() -> FileResponse:
    return FileResponse(_STATIC / "index.html")


@router.get("/api/providers")
async def list_providers(request: Request) -> list[dict]:
    out = []
    for rt in request.app.state.router.runtimes:
        out.append(
            {
                "name": rt.cfg.name,
                "base_url": rt.cfg.base_url,
                "models": rt.cfg.models,
                "enabled": rt.cfg.enabled,
                "concurrency": rt.cfg.concurrency,
                "rpm": rt.cfg.rpm,
                "tpm": rt.cfg.tpm,
                "has_key": bool(rt.cfg.key_list),
                "melted": rt.melted,
            }
        )
    return out


@router.post("/api/providers/{name}")
async def update_provider(name: str, body: ProviderUpdate, request: Request) -> dict:
    app_router = request.app.state.router
    db = request.app.state.db
    rt = next((r for r in app_router.runtimes if r.cfg.name == name), None)
    if rt is None:
        raise HTTPException(status_code=404, detail="provider not found")

    prefix = f"provider.{name}."
    updates: dict[str, str] = {}
    if body.enabled is not None:
        updates[f"{prefix}enabled"] = "true" if body.enabled else "false"
    if body.rpm is not None:
        updates[f"{prefix}rpm"] = str(int(body.rpm))
    if body.tpm is not None:
        updates[f"{prefix}tpm"] = str(int(body.tpm))
    if body.concurrency is not None:
        updates[f"{prefix}concurrency"] = str(int(body.concurrency))

    for k, v in updates.items():
        await db.set_setting(k, v)
    app_router.apply_settings(updates)
    return {"ok": True, "name": name, "updates": updates}


@router.get("/api/batches")
async def list_batches(request: Request) -> list[dict]:
    batches = await request.app.state.db.list_batches()
    return [batch_to_dict(b) for b in batches]
