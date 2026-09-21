"""OpenAI-style batch endpoints: /v1/batches (simplified inline JSONL)."""
from __future__ import annotations

import json

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import Response

from .models import Batch, BatchCreateRequest, BatchRequestCounts, now

router = APIRouter()


def parse_jsonl(input_str: str) -> list[dict]:
    """Parse an inline JSONL string into per-line request dicts."""
    items: list[dict] = []
    for line in input_str.splitlines():
        line = line.strip()
        if not line:
            continue
        obj = json.loads(line)
        items.append(obj)
    return items


def batch_to_dict(b: dict) -> dict:
    return {
        "id": b["id"],
        "object": "batch",
        "endpoint": "/v1/chat/completions",
        "status": b["status"],
        "request_counts": {
            "total": b["total"],
            "completed": b["completed"],
            "failed": b["failed"],
        },
        "created_at": b["created_at"],
    }


def _result_line(item: dict) -> str:
    if item["status"] == "done" and item["result_json"]:
        body = json.loads(item["result_json"])
        response = {"status_code": 200, "request_id": item["id"], "body": body}
        error = None
    else:
        response = None
        error = {"message": item.get("error") or "failed", "type": "batch_error"}
    return json.dumps(
        {"id": item["id"], "custom_id": item.get("custom_id"), "response": response, "error": error},
        ensure_ascii=False,
    )


@router.post("/v1/batches")
async def create_batch(req: BatchCreateRequest, request: Request):
    db = request.app.state.db
    try:
        items = parse_jsonl(req.input)
    except (json.JSONDecodeError, ValueError) as e:
        raise HTTPException(status_code=400, detail=f"invalid JSONL input: {e}")

    if not items:
        raise HTTPException(status_code=400, detail="no valid requests in input")

    batch = await db.create_batch(req.input)
    await db.add_items(batch["id"], items)
    request.app.state.wake.set()  # nudge workers

    b = await db.get_batch(batch["id"])
    return batch_to_dict(b)


@router.get("/v1/batches/{batch_id}")
async def get_batch(batch_id: str, request: Request):
    b = await request.app.state.db.get_batch(batch_id)
    if b is None:
        raise HTTPException(status_code=404, detail="batch not found")
    return batch_to_dict(b)


@router.get("/v1/batches/{batch_id}/content")
async def get_batch_content(batch_id: str, request: Request):
    db = request.app.state.db
    b = await db.get_batch(batch_id)
    if b is None:
        raise HTTPException(status_code=404, detail="batch not found")
    items = await db.get_batch_items(batch_id)
    lines = [_result_line(it) for it in items]
    return Response("\n".join(lines) + ("\n" if lines else ""), media_type="application/x-ndjson")
