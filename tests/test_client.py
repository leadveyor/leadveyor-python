from __future__ import annotations

import asyncio
import json
from typing import Any, Callable, Dict, List, Optional
from urllib.parse import parse_qs, urlsplit

import httpx
import pytest

import leadveyor
from leadveyor import (
    APIConnectionError,
    APIError,
    APITimeoutError,
    AsyncLeadveyor,
    AuthenticationError,
    InvalidRequestError,
    Leadveyor,
    LeadveyorObject,
    NotFoundError,
    QuotaExceededError,
    RateLimitError,
    SyncPage,
    models,
)
from leadveyor import _base_client

Call = Dict[str, Any]


class Fake:
    """Records requests; ``respond(n, call)`` returns an httpx.Response or raises."""

    def __init__(self, respond: Callable[[int, Call], httpx.Response]) -> None:
        self.calls: List[Call] = []
        self.respond = respond

    def handler(self, request: httpx.Request) -> httpx.Response:
        call = {
            "method": request.method,
            "url": str(request.url),
            "headers": {k.lower(): v for k, v in request.headers.items()},
            "body": request.content.decode() if request.content else None,
            "timeout": request.extensions.get("timeout", {}).get("read"),
        }
        self.calls.append(call)
        return self.respond(len(self.calls), call)


def js(status: int, body: Any, headers: Optional[Dict[str, str]] = None) -> httpx.Response:
    return httpx.Response(status, json=body, headers=headers)


@pytest.fixture(autouse=True)
def no_sleep(monkeypatch: pytest.MonkeyPatch) -> List[float]:
    slept: List[float] = []

    async def async_sleep(s: float) -> None:
        slept.append(s)

    monkeypatch.setattr(_base_client, "_sleep", slept.append)
    monkeypatch.setattr(_base_client, "_async_sleep", async_sleep)
    return slept


def lv(fake: Fake, **extra: Any) -> Leadveyor:
    return Leadveyor("lv_test_abc", base_url="https://api.test/", http_client=httpx.Client(transport=httpx.MockTransport(fake.handler)), **extra)


def alv(fake: Fake, **extra: Any) -> AsyncLeadveyor:
    return AsyncLeadveyor("lv_test_abc", base_url="https://api.test", http_client=httpx.AsyncClient(transport=httpx.MockTransport(fake.handler)), **extra)


def page(ids: List[str], nxt: Optional[str]) -> Dict[str, Any]:
    return {"object": "list", "data": [{"object": "lead", "id": i} for i in ids], "has_more": nxt is not None, "next_cursor": nxt}


def test_sends_auth_workspace_and_json_and_builds_paths_and_queries() -> None:
    f = Fake(lambda n, c: js(200, {"object": "lead", "id": "lead_1"}))
    c = lv(f, workspace="ws_1")
    c.leads.retrieve("lead/1?x")
    c.inbounds.create(text="Hi", wait=True, workspace="ws_2")
    c.leads.list(tier="hot", min_score=50, limit=10)
    c.sources.update("src_1")
    c.sources.update("src_2", name=None)

    assert f.calls[0]["url"] == "https://api.test/v1/leads/lead%2F1%3Fx"
    assert f.calls[0]["headers"]["authorization"] == "Bearer lv_test_abc"
    assert f.calls[0]["headers"]["leadveyor-workspace"] == "ws_1"
    assert f.calls[0]["headers"]["user-agent"].startswith(f"leadveyor-sdk-python/{leadveyor.__version__} Python/")
    assert "content-type" not in f.calls[0]["headers"]
    assert f.calls[0]["body"] is None

    assert f.calls[1]["method"] == "POST"
    assert f.calls[1]["url"] == "https://api.test/v1/inbounds?wait=true"
    assert f.calls[1]["headers"]["leadveyor-workspace"] == "ws_2"
    assert f.calls[1]["headers"]["content-type"] == "application/json"
    assert json.loads(f.calls[1]["body"]) == {"text": "Hi"}

    assert f.calls[2]["url"].startswith("https://api.test/v1/leads?")
    assert parse_qs(urlsplit(f.calls[2]["url"]).query) == {"tier": ["hot"], "min_score": ["50"], "limit": ["10"]}
    # Optional body with nothing given → no body; None is sent as JSON null.
    assert f.calls[3]["method"] == "PATCH" and f.calls[3]["body"] is None
    assert json.loads(f.calls[4]["body"]) == {"name": None}


def test_freeform_document_body() -> None:
    f = Fake(lambda n, c: js(200, {"object": "profile", "id": "prof_1"}))
    p = lv(f).profiles.create({"name": "Plumbing", "criteria": []}, publish=True)
    assert isinstance(p, models.Profile)
    assert f.calls[0]["url"] == "https://api.test/v1/profiles?publish=true"
    assert json.loads(f.calls[0]["body"]) == {"name": "Plumbing", "criteria": []}


def test_responses_become_typed_objects() -> None:
    body = {
        "object": "inbound", "id": "inb_1", "metadata": {},
        "leads": [{"object": "lead", "id": "lead_1", "evaluation": {"tier": "hot", "score": 90, "reasons": []}, "fields": {"guests": 80}}],
    }
    f = Fake(lambda n, c: js(200, body))
    r = lv(f).inbounds.create(text="Hi", wait=True)
    assert isinstance(r, models.InboundResult)
    assert isinstance(r.leads[0], models.Lead)
    assert isinstance(r.leads[0].evaluation, models.Evaluation)
    assert r.leads[0].evaluation.tier == "hot"
    assert r["leads"][0]["evaluation"]["score"] == 90
    assert r.leads[0].fields.guests == 80
    assert r.leads[0].outcome is None  # declared, absent → None
    with pytest.raises(AttributeError):
        r.nope  # noqa: B018 — unknown → AttributeError
    assert json.loads(json.dumps(r)) == body
    assert r.to_dict() == body
    assert type(r.to_dict()["leads"][0]) is dict


def test_with_workspace_and_with_options() -> None:
    f = Fake(lambda n, c: js(200, page([], None)))
    base = lv(f)
    base.with_workspace("ws_9").leads.list()
    base.leads.list()
    assert f.calls[0]["headers"]["leadveyor-workspace"] == "ws_9"
    assert "leadveyor-workspace" not in f.calls[1]["headers"]
    base.with_options(timeout=5).leads.list()
    assert f.calls[2]["timeout"] == 5
    base.leads.list(timeout=2)
    assert f.calls[3]["timeout"] == 2
    assert base.livemode is False


def test_needs_an_api_key(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("LEADVEYOR_API_KEY", raising=False)
    with pytest.raises(AuthenticationError, match="No API key"):
        Leadveyor()
    monkeypatch.setenv("LEADVEYOR_API_KEY", "lv_live_x")
    assert Leadveyor().livemode is True


def test_maps_the_error_envelope() -> None:
    err = {"error": {"type": "invalid_request_error", "code": "profile_invalid", "param": "criteria", "message": "Bad profile", "request_id": "req_1", "errors": [{"path": "criteria.0", "message": "Required"}]}}
    f = Fake(lambda n, c: js(400, err))
    with pytest.raises(InvalidRequestError) as ei:
        lv(f).profiles.validate({"criteria": "x"})
    e = ei.value
    assert (e.status_code, e.type, e.code, e.param, e.request_id, e.message) == (400, "invalid_request_error", "profile_invalid", "criteria", "req_1", "Bad profile")
    assert e.errors == [{"path": "criteria.0", "message": "Required"}]
    assert "req_1" in str(e)


def test_status_classes_and_non_json_5xx() -> None:
    def respond(n: int, c: Call) -> httpx.Response:
        if n == 1:
            return js(401, {"error": {"type": "authentication_error", "message": "Invalid key"}})
        if n == 2:
            return js(404, {"error": {"type": "not_found_error", "message": "No such lead"}})
        return httpx.Response(502, text="<html>Bad gateway</html>", headers={"content-type": "text/html", "x-request-id": "req_px"})

    c = lv(Fake(respond), max_retries=0)
    with pytest.raises(AuthenticationError):
        c.leads.retrieve("x")
    with pytest.raises(NotFoundError):
        c.leads.retrieve("x")
    with pytest.raises(APIError, match="HTTP 502") as ei:
        c.leads.retrieve("x")
    assert ei.value.request_id == "req_px"


def test_retries_get_on_5xx_and_429_honouring_retry_after(no_sleep: List[float]) -> None:
    def respond(n: int, c: Call) -> httpx.Response:
        if n == 1:
            return js(503, {"error": {"message": "busy"}})
        if n == 2:
            return js(429, {"error": {"message": "slow"}}, {"retry-after": "3"})
        return js(200, {"id": "lead_1"})

    f = Fake(respond)
    assert lv(f).leads.retrieve("lead_1").id == "lead_1"
    assert len(f.calls) == 3
    assert no_sleep[1] == 3.0 and no_sleep[0] > 0


def test_post_retried_on_429_only() -> None:
    f500 = Fake(lambda n, c: js(500, {"error": {"message": "oops"}}))
    with pytest.raises(APIError):
        lv(f500).inbounds.create(text="x")
    assert len(f500.calls) == 1

    f429 = Fake(lambda n, c: js(429, {}, {"retry-after": "0"}) if n < 3 else js(202, {"object": "inbound_result"}))
    assert lv(f429).inbounds.create(text="x").object == "inbound_result"
    assert len(f429.calls) == 3


def test_safe_posts_retried_on_5xx() -> None:
    f = Fake(lambda n, c: js(500, {}) if n == 1 else js(200, {"object": "inbound"}))
    assert lv(f).inbounds.create(text="x", externalId="form-1").object == "inbound"
    assert len(f.calls) == 2
    g = Fake(lambda n, c: js(503, {}) if n == 1 else js(200, {"object": "evaluation_result"}))
    lv(g).evaluate(text="x")
    assert len(g.calls) == 2


def test_quota_exceeded_not_retried() -> None:
    f = Fake(lambda n, c: js(402, {"error": {"type": "quota_error", "code": "quota_exceeded", "message": "Plan limit"}}))
    with pytest.raises(QuotaExceededError) as ei:
        lv(f).leads.list()
    assert (ei.value.type, ei.value.code) == ("quota_error", "quota_exceeded")
    assert len(f.calls) == 1


def test_gives_up_after_max_retries() -> None:
    f = Fake(lambda n, c: js(429, {}, {"retry-after": "0"}))
    with pytest.raises(RateLimitError):
        lv(f, max_retries=1).leads.retrieve("x")
    assert len(f.calls) == 2


def test_network_errors_and_timeouts() -> None:
    def flaky(n: int, c: Call) -> httpx.Response:
        if n == 1:
            raise httpx.ConnectError("Connection reset")
        return js(200, {"id": "ok"})

    f = Fake(flaky)
    assert lv(f).leads.retrieve("x").id == "ok"
    assert len(f.calls) == 2

    def down(n: int, c: Call) -> httpx.Response:
        raise httpx.ConnectError("Connection reset")

    g = Fake(down)
    with pytest.raises(APIConnectionError, match="Connection reset") as ei:
        lv(g).inbounds.create(text="x")
    assert not isinstance(ei.value, APITimeoutError)
    assert len(g.calls) == 1

    def slow(n: int, c: Call) -> httpx.Response:
        raise httpx.ReadTimeout("timed out")

    with pytest.raises(APITimeoutError) as et:
        lv(Fake(slow), max_retries=0).leads.retrieve("x")
    assert et.value.type == "connection_error"


def test_empty_response_is_none() -> None:
    f = Fake(lambda n, c: httpx.Response(204))
    assert lv(f).leads.clear_outcome("lead_1") is None


def _pager(n: int, c: Call) -> httpx.Response:
    q = parse_qs(urlsplit(c["url"]).query)
    cursor = q.get("starting_after", [None])[0]
    if cursor is None:
        return js(200, page(["a", "b"], "b"))
    if cursor == "b":
        return js(200, page(["c", "d"], "d"))
    return js(200, page(["e"], None))


def test_pagination() -> None:
    f = Fake(_pager)
    c = lv(f)
    first = c.leads.list(limit=2)
    assert isinstance(first, SyncPage)
    assert [x.id for x in first.data] == ["a", "b"]
    assert isinstance(first.data[0], models.Lead)
    assert first.has_more and first.next_cursor == "b"
    assert len(f.calls) == 1

    assert [x.id for x in c.leads.list(limit=2)] == ["a", "b", "c", "d", "e"]
    assert [x["url"] for x in f.calls[1:]] == [
        "https://api.test/v1/leads?limit=2",
        "https://api.test/v1/leads?limit=2&starting_after=b",
        "https://api.test/v1/leads?limit=2&starting_after=d",
    ]
    assert [x.id for x in c.leads.list().to_list(limit=3)] == ["a", "b", "c"]
    assert c.leads.list(starting_after="d").next_page() is None
    c.events.list(starting_after="evt_5")
    assert f.calls[-1]["url"] == "https://api.test/v1/events?starting_after=evt_5"


def test_async_client() -> None:
    async def run() -> None:
        f = Fake(_pager)
        async with alv(f) as c:
            req = c.leads.list(limit=2)
            assert len(f.calls) == 0  # lazy until awaited / iterated
            first = await req
            assert [x.id for x in first.data] == ["a", "b"]
            ids = [x.id async for x in c.leads.list(limit=2)]
            assert ids == ["a", "b", "c", "d", "e"]
            assert [x.id for x in await c.leads.list().to_list(limit=3)] == ["a", "b", "c"]

        g = Fake(lambda n, c: js(500, {}) if n == 1 else js(200, {"object": "inbound", "id": "inb_1", "leads": [{"id": "lead_1"}]}))
        a = alv(g, workspace="ws_1")
        r = await a.inbounds.create(text="Hi", externalId="x-1", wait=True)
        assert isinstance(r, models.InboundResult) and isinstance(r.leads[0], models.Lead)
        assert len(g.calls) == 2 and g.calls[0]["headers"]["leadveyor-workspace"] == "ws_1"

        h = Fake(lambda n, c: js(404, {"error": {"message": "No lead"}}))
        with pytest.raises(NotFoundError):
            await alv(h).leads.retrieve("x")
        await a.close()

    asyncio.run(run())


def test_every_resource_method_exists() -> None:
    c = Leadveyor("lv_test_x")
    for res, m in [("inbounds", "create"), ("leads", "record_outcome"), ("profiles", "generate_criterion"), ("reports", "compare_workspaces"), ("api_keys", "revoke"), ("billing", "set_spend_limit"), ("usage", "retrieve")]:
        assert callable(getattr(getattr(c, res), m)), f"{res}.{m}"
    assert callable(c.evaluate)
    assert isinstance(models.Lead(), LeadveyorObject)
    assert Leadveyor.webhooks is leadveyor.Webhook
