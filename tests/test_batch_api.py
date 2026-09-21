import asyncio
import json


async def _wait_completed(client, batch_id):
    for _ in range(100):
        r = await client.get(f"/v1/batches/{batch_id}")
        b = r.json()
        if b["status"] == "completed":
            return b
        await asyncio.sleep(0.02)
    raise AssertionError("batch did not complete in time")


async def test_batch_end_to_end(gateway):
    inp = (
        '{"custom_id":"1","method":"POST","url":"/v1/chat/completions",'
        '"body":{"model":"auto","messages":[{"role":"user","content":"hi"}]}}'
    )
    r = await gateway.client.post("/v1/batches", json={"input": inp})
    assert r.status_code == 200
    batch_id = r.json()["id"]

    b = await _wait_completed(gateway.client, batch_id)
    assert b["request_counts"]["total"] == 1
    assert b["request_counts"]["completed"] == 1

    r2 = await gateway.client.get(f"/v1/batches/{batch_id}/content")
    lines = [ln for ln in r2.text.strip().split("\n") if ln.strip()]
    assert len(lines) == 1
    obj = json.loads(lines[0])
    assert obj["custom_id"] == "1"
    assert obj["response"]["status_code"] == 200
    assert obj["response"]["body"]["choices"][0]["message"]["content"] == "fake reply"


async def test_batch_not_found(gateway):
    r = await gateway.client.get("/v1/batches/batch_nope")
    assert r.status_code == 404
