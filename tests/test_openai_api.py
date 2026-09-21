async def test_chat_completions(gateway):
    r = await gateway.client.post(
        "/v1/chat/completions",
        json={"model": "auto", "messages": [{"role": "user", "content": "hi"}]},
    )
    assert r.status_code == 200
    body = r.json()
    assert body["object"] == "chat.completion"
    assert body["choices"][0]["message"]["content"] == "fake reply"


async def test_chat_stream(gateway):
    async with gateway.client.stream(
        "POST",
        "/v1/chat/completions",
        json={"model": "auto", "messages": [{"role": "user", "content": "hi"}], "stream": True},
    ) as r:
        assert r.status_code == 200
        text = ""
        async for line in r.aiter_lines():
            text += line
    assert "data: [DONE]" in text


async def test_models(gateway):
    r = await gateway.client.get("/v1/models")
    assert r.status_code == 200
    ids = [m["id"] for m in r.json()["data"]]
    assert "auto" in ids
    assert "fake-model" in ids


async def test_unknown_model_404(gateway):
    r = await gateway.client.post(
        "/v1/chat/completions",
        json={"model": "nope", "messages": [{"role": "user", "content": "hi"}]},
    )
    assert r.status_code == 404
