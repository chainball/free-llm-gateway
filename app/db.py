"""SQLite persistence (WAL) for batches, items, and runtime settings."""
from __future__ import annotations

import asyncio
import json
from pathlib import Path
from typing import Any

import aiosqlite

from .models import new_id, now

_SCHEMA = """
CREATE TABLE IF NOT EXISTS batches (
    id          TEXT PRIMARY KEY,
    input_jsonl TEXT NOT NULL,
    status      TEXT NOT NULL DEFAULT 'in_progress',
    total       INTEGER NOT NULL DEFAULT 0,
    completed   INTEGER NOT NULL DEFAULT 0,
    failed      INTEGER NOT NULL DEFAULT 0,
    created_at  INTEGER NOT NULL,
    updated_at  INTEGER NOT NULL
);

CREATE TABLE IF NOT EXISTS items (
    id           TEXT PRIMARY KEY,
    batch_id     TEXT NOT NULL,
    custom_id    TEXT,
    request_json TEXT NOT NULL,
    status       TEXT NOT NULL DEFAULT 'pending',
    result_json  TEXT,
    provider     TEXT,
    model        TEXT,
    error        TEXT,
    retry_count  INTEGER NOT NULL DEFAULT 0,
    updated_at   INTEGER NOT NULL
);

CREATE TABLE IF NOT EXISTS settings (
    key   TEXT PRIMARY KEY,
    value TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_items_batch ON items(batch_id);
CREATE INDEX IF NOT EXISTS idx_items_status ON items(status);
"""


class Database:
    def __init__(self, path: str):
        self.path = path
        self._conn: aiosqlite.Connection | None = None
        self._lock = asyncio.Lock()

    async def connect(self) -> None:
        Path(self.path).parent.mkdir(parents=True, exist_ok=True)
        self._conn = await aiosqlite.connect(self.path)
        self._conn.row_factory = aiosqlite.Row
        await self._conn.execute("PRAGMA journal_mode=WAL")
        await self._conn.execute("PRAGMA synchronous=NORMAL")
        await self._conn.executescript(_SCHEMA)
        await self._conn.commit()

    async def close(self) -> None:
        if self._conn is not None:
            await self._conn.close()
            self._conn = None

    async def _run(self, sql: str, params: tuple = ()) -> aiosqlite.Cursor:
        assert self._conn is not None, "database not connected"
        async with self._lock:
            cur = await self._conn.execute(sql, params)
            await self._conn.commit()
            return cur

    async def _fetchone(self, sql: str, params: tuple = ()) -> dict | None:
        cur = await self._run(sql, params)
        row = await cur.fetchone()
        await cur.close()
        return dict(row) if row else None

    async def _fetchall(self, sql: str, params: tuple = ()) -> list[dict]:
        cur = await self._run(sql, params)
        rows = await cur.fetchall()
        await cur.close()
        return [dict(r) for r in rows]

    # --- batches -------------------------------------------------------------

    async def create_batch(self, input_jsonl: str) -> dict:
        batch_id = new_id("batch")
        ts = now()
        await self._run(
            "INSERT INTO batches (id, input_jsonl, status, total, completed, failed, created_at, updated_at) "
            "VALUES (?, ?, 'in_progress', 0, 0, 0, ?, ?)",
            (batch_id, input_jsonl, ts, ts),
        )
        return await self.get_batch(batch_id)

    async def add_items(self, batch_id: str, items: list[dict]) -> int:
        ts = now()
        count = 0
        async with self._lock:
            for it in items:
                item_id = new_id("item")
                await self._conn.execute(
                    "INSERT INTO items (id, batch_id, custom_id, request_json, status, retry_count, updated_at) "
                    "VALUES (?, ?, ?, ?, 'pending', 0, ?)",
                    (
                        item_id,
                        batch_id,
                        it.get("custom_id"),
                        json.dumps(it.get("body", {}), ensure_ascii=False),
                        ts,
                    ),
                )
                count += 1
            await self._conn.execute(
                "UPDATE batches SET total = ?, updated_at = ? WHERE id = ?",
                (count, ts, batch_id),
            )
            await self._conn.commit()
        return count

    async def get_batch(self, batch_id: str) -> dict | None:
        return await self._fetchone("SELECT * FROM batches WHERE id = ?", (batch_id,))

    async def list_batches(self) -> list[dict]:
        return await self._fetchall("SELECT * FROM batches ORDER BY created_at DESC")

    async def get_batch_items(self, batch_id: str) -> list[dict]:
        return await self._fetchall(
            "SELECT * FROM items WHERE batch_id = ? ORDER BY rowid", (batch_id,)
        )

    # --- items ---------------------------------------------------------------

    async def claim_next_pending(self) -> dict | None:
        async with self._lock:
            cur = await self._conn.execute(
                "SELECT id FROM items WHERE status = 'pending' ORDER BY rowid LIMIT 1"
            )
            row = await cur.fetchone()
            await cur.close()
            if row is None:
                return None
            item_id = row["id"]
            ts = now()
            await self._conn.execute(
                "UPDATE items SET status = 'running', updated_at = ? WHERE id = ?",
                (ts, item_id),
            )
            await self._conn.commit()
        return await self.get_item(item_id)

    async def get_item(self, item_id: str) -> dict | None:
        return await self._fetchone("SELECT * FROM items WHERE id = ?", (item_id,))

    async def set_item(
        self,
        item_id: str,
        status: str,
        *,
        result_json: str | None = None,
        provider: str | None = None,
        model: str | None = None,
        error: str | None = None,
        retry_count: int | None = None,
    ) -> None:
        ts = now()
        await self._run(
            "UPDATE items SET status = ?, result_json = ?, provider = ?, model = ?, "
            "error = ?, retry_count = COALESCE(?, retry_count), updated_at = ? WHERE id = ?",
            (status, result_json, provider, model, error, retry_count, ts, item_id),
        )
        await self.recalc_batch_for_item(item_id)

    async def requeue(self, item_id: str) -> None:
        ts = now()
        await self._run(
            "UPDATE items SET status = 'pending', updated_at = ? WHERE id = ?",
            (ts, item_id),
        )

    async def recalc_batch_for_item(self, item_id: str) -> None:
        item = await self.get_item(item_id)
        if item is None:
            return
        await self.recalc_batch(item["batch_id"])

    async def recalc_batch(self, batch_id: str) -> None:
        cur = await self._run(
            "SELECT COUNT(*) AS total, "
            "SUM(CASE WHEN status='done' THEN 1 ELSE 0 END) AS completed, "
            "SUM(CASE WHEN status='failed' THEN 1 ELSE 0 END) AS failed, "
            "SUM(CASE WHEN status IN ('pending','running') THEN 1 ELSE 0 END) AS active "
            "FROM items WHERE batch_id = ?",
            (batch_id,),
        )
        row = await cur.fetchone()
        await cur.close()
        if row is None:
            return
        total = row["total"] or 0
        completed = row["completed"] or 0
        failed = row["failed"] or 0
        active = row["active"] or 0
        status = "completed" if active == 0 else "in_progress"
        ts = now()
        await self._run(
            "UPDATE batches SET total = ?, completed = ?, failed = ?, status = ?, updated_at = ? WHERE id = ?",
            (total, completed, failed, status, ts, batch_id),
        )

    async def reset_running_to_pending(self) -> int:
        ts = now()
        async with self._lock:
            cur = await self._conn.execute(
                "UPDATE items SET status = 'pending', updated_at = ? WHERE status = 'running'",
                (ts,),
            )
            await self._conn.commit()
            return cur.rowcount

    # --- settings ------------------------------------------------------------

    async def get_settings(self) -> dict[str, str]:
        rows = await self._fetchall("SELECT key, value FROM settings")
        return {r["key"]: r["value"] for r in rows}

    async def set_setting(self, key: str, value: str) -> None:
        await self._run(
            "INSERT INTO settings (key, value) VALUES (?, ?) "
            "ON CONFLICT(key) DO UPDATE SET value = excluded.value",
            (key, value),
        )

    async def delete_setting(self, key: str) -> None:
        await self._run("DELETE FROM settings WHERE key = ?", (key,))
