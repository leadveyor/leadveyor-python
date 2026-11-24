# Leadveyor SDK for Python

[![PyPI](https://img.shields.io/pypi/v/leadveyor)](https://pypi.org/project/leadveyor/) [![Tests](https://github.com/leadveyor/leadveyor-python/actions/workflows/tests.yml/badge.svg)](https://github.com/leadveyor/leadveyor-python/actions/workflows/tests.yml)

Official client for the [Leadveyor API](https://leadveyor.com/docs/api): send messages, get scored leads, manage profiles, sources and webhooks. Python 3.9+, sync and async, typed. One dependency: [httpx](https://www.python-httpx.org).

```bash
pip install leadveyor
```

## Quick start

```python
from leadveyor import Leadveyor

lv = Leadveyor()  # reads LEADVEYOR_API_KEY; or Leadveyor("lv_live_…")

inbound = lv.inbounds.create(
    text="Hi, we need catering for 80 guests on 12 March in Richmond. Budget around $6k.",
    wait=True,  # wait for scoring instead of getting a webhook later
)
lead = inbound.leads[0] if inbound.leads else None
if lead:
    print(lead.evaluation.tier, lead.evaluation.score)
```

Create API keys in the [console](https://console.leadveyor.com) → API keys. `lv_test_…` keys work on test data only.

### Async

```python
import asyncio
from leadveyor import AsyncLeadveyor

async def main() -> None:
    async with AsyncLeadveyor() as lv:
        inbound = await lv.inbounds.create(text="Hi, need a plumber tomorrow", wait=True)
        async for lead in lv.leads.list(tier="hot"):
            print(lead.id, lead.evaluation.score)

asyncio.run(main())
```

## Resources

Methods are named like the [TypeScript SDK](https://leadveyor.com/docs/sdk), in snake_case. Path IDs are positional; everything else is a keyword argument with the API's own field name (`externalId=`, `sourceId=`), so the [API reference](https://leadveyor.com/docs/inbounds) applies as is.

| | Methods |
|---|---|
| `lv.inbounds` | `create`, `list`, `retrieve`, `reprocess` |
| `lv.leads` | `list`, `retrieve`, `list_evaluations`, `record_outcome`, `clear_outcome` |
| `lv.contacts` | `list`, `retrieve`, `update`, `list_leads` |
| `lv.profiles` | `list`, `create`, `retrieve`, `delete`, `validate`, `generate`, `generate_criterion`, `save_draft`, `update_draft`, `discard_draft`, `publish`, `activate`, `list_versions`, `retrieve_version` |
| `lv.templates` | `list`, `retrieve` |
| `lv.sources` | `list`, `create`, `retrieve`, `update`, `delete` |
| `lv.destinations` | `list`, `create`, `retrieve`, `update`, `delete`, `rotate_secret`, `test`, `list_deliveries`, `retry_delivery` |
| `lv.events` | `list`, `retrieve` |
| `lv.workspaces` | `list`, `create`, `retrieve`, `update` |
| `lv.api_keys` | `list`, `create`, `revoke` |
| `lv.billing` | `retrieve`, `checkout`, `change_plan`, `portal`, `set_spend_limit` |
| `lv.usage` | `retrieve`: this period's leads against the plan |
| `lv.reports` | `retrieve`, `compare_workspaces` |
| `lv.evaluate()` | Score a message without saving anything |

```python
# Record what happened to a lead — this is what teaches scoring what "good" means
lv.leads.record_outcome("lead_2Ph6Tc9Ks4Wm1Lx7Qv3Nb8Dr", status="won", amount=6200)

# Send a form submission; safe to repeat with the same externalId
lv.inbounds.create(fields={"name": "Ann Lee", "email": "ann@example.com", "guests": 80}, externalId="form-4711")

# Profile documents are passed as a dict
lv.profiles.create(document, publish=True)
```

An argument you leave out is not sent. `None` is sent as JSON `null` (for example `lv.billing.set_spend_limit(spendLimitUsd=None)` removes the limit).

## Responses

Responses are dicts whose fields can also be read as attributes:

```python
lead = lv.leads.retrieve("lead_…")   # leadveyor.models.Lead
lead.evaluation.tier                  # "hot"
lead["evaluation"]["score"]           # 90
lead.to_dict()                        # plain dicts
json.dumps(lead)                      # works: it is a dict
```

Every object has a class in `leadveyor.models` (`Lead`, `Inbound`, `Profile`, `Source` …) with type annotations, so editors and mypy know the fields. A field the API left out reads as `None`.

## Pagination

```python
# This page
page = lv.leads.list(tier="hot", limit=50)
page.data, page.has_more, page.next_cursor

# Every item; next pages are fetched as you go
for lead in lv.leads.list(outcome="none"):
    print(lead.id, lead.evaluation.score)

# Up to N items as a list
recent = lv.events.list(type="lead.*").to_list(limit=500)
```

Async: `await lv.leads.list()` is the first page, `async for lead in lv.leads.list()` goes through every item, `await lv.leads.list().to_list(limit=500)`.

## Webhooks

Verify the `Leadveyor-Signature` header against the **raw** request body:

```python
from flask import Flask, request
from leadveyor import SignatureVerificationError, Webhook

app = Flask(__name__)

@app.post("/leadveyor-webhook")
def leadveyor_webhook():
    try:
        event = Webhook.construct_event(
            request.get_data(),                         # raw bytes
            request.headers.get("Leadveyor-Signature"),
            os.environ["LEADVEYOR_WEBHOOK_SECRET"],     # whsec_…
        )
    except SignatureVerificationError:
        return "", 400
    if event.type == "lead.scored":
        save_lead(event.data.object)                    # leadveyor.models.Lead
    return "", 200
```

Django: `Webhook.construct_event(request.body, request.headers.get("Leadveyor-Signature"), secret)`. FastAPI: `await request.body()`.

`Webhook.verify(...)` returns a bool instead of raising. `Webhook.generate_test_header(payload, secret)` signs a payload like Leadveyor does, for your tests.

## Workspaces

A workspace key works in its own workspace. With an account-wide key (agencies, several clients) choose the workspace:

```python
client = lv.with_workspace("ws_1Bq7Xn4KpRz9Lc2Vt6Hy0Mde")   # every request
lv.leads.list(workspace="ws_…")                              # one request
```

## Errors

Failed calls raise a subclass of `leadveyor.LeadveyorError`:

| Class | When |
|---|---|
| `InvalidRequestError` | 400: invalid parameters; `e.errors` lists every field problem |
| `AuthenticationError` | 401: missing, invalid or revoked key |
| `PermissionDeniedError` | 403: the key's permission or workspace doesn't allow it |
| `NotFoundError` | 404 |
| `ConflictError` | 409 |
| `QuotaExceededError` | 402: the plan's leads for this period are used up ([plans and limits](https://leadveyor.com/docs/plans-and-limits)); not retried |
| `RateLimitError` | 429, after the automatic retries |
| `APIError` | 5xx |
| `APIConnectionError` / `APITimeoutError` | the API could not be reached / no answer in time |

```python
from leadveyor import NotFoundError

try:
    lead = lv.leads.retrieve("lead_…")
except NotFoundError:
    lead = None
# e.status_code, e.type, e.code, e.param, e.request_id (quote it to support)
```

## Retries and timeouts

- 429 responses are retried for every method, honouring `Retry-After`.
- 5xx responses and network errors are retried for `GET`, `PUT`, `PATCH` and `DELETE`, for `evaluate()` and `profiles.validate()`, and for `inbounds.create()` **with an `externalId`** (the API returns the original inbound for a repeated ID). Other `POST`s are not retried on them, because the request may already have been applied.
- Two retries by default with exponential backoff.

```python
lv = Leadveyor(max_retries=4, timeout=30)
lv.evaluate(text=text, timeout=120)
```

## Options

| Option | Default | |
|---|---|---|
| `api_key` | `LEADVEYOR_API_KEY` | |
| `workspace` | — | `Leadveyor-Workspace` for account-wide keys |
| `base_url` | `https://core.leadveyor.com` | or `LEADVEYOR_BASE_URL` |
| `timeout` | `60` | seconds per attempt |
| `max_retries` | `2` | |
| `http_client` | new `httpx.Client` | your own `httpx.Client` / `httpx.AsyncClient` (proxies, tests) |
| `default_headers` | — | added to every request |

Per-request keyword arguments on every method: `workspace`, `timeout`, `max_retries`, `extra_headers`. `lv.with_options(timeout=5)` makes a client with changed options.

## Links

- Docs: https://leadveyor.com/docs/sdk/python
- API reference: https://leadveyor.com/docs/inbounds
- Support: support@leadveyor.com
