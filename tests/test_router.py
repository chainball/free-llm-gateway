import pytest

from app.providers import BadRequestError, ServerError
from app.router import NoProviderError, Router, UnknownModelError
from tests.helpers import make_runtime


def test_resolve_auto():
    router = Router([make_runtime("a", ["m1"]), make_runtime("b", ["m2"])])
    assert len(router.resolve("auto")) == 2


def test_resolve_by_model():
    router = Router([make_runtime("a", ["m1"]), make_runtime("b", ["m2"])])
    assert router.resolve("m2")[0].cfg.name == "b"


def test_resolve_unknown_empty():
    router = Router([make_runtime("a", ["m1"])])
    assert router.resolve("nope") == []


def test_meltdown_after_failures():
    rt = make_runtime("a", ["m1"])
    for _ in range(3):
        rt.record_failure()
    assert rt.melted


async def test_failover_on_server_error():
    a = make_runtime("a", ["m1"], fail=ServerError("boom"))
    b = make_runtime("b", ["m1"], respond="from-b")
    router = Router([a, b])
    content, used = await router.complete("m1", [{"role": "user", "content": "hi"}])
    assert content == "from-b"
    assert used.cfg.name == "b"


async def test_badrequest_not_failover():
    a = make_runtime("a", ["m1"], fail=BadRequestError("bad"))
    b = make_runtime("b", ["m1"], respond="from-b")
    router = Router([a, b])
    with pytest.raises(BadRequestError):
        await router.complete("m1", [{"role": "user", "content": "hi"}])


async def test_empty_no_provider():
    router = Router([make_runtime("a", ["m1"], enabled=False)])
    with pytest.raises(NoProviderError):
        await router.complete("auto", [{"role": "user", "content": "hi"}])


async def test_empty_unknown_model():
    router = Router([make_runtime("a", ["m1"], enabled=False)])
    with pytest.raises(UnknownModelError):
        await router.complete("nope", [{"role": "user", "content": "hi"}])
