from __future__ import annotations

import json
from typing import Any, Callable, Optional

import pytest

from leadveyor import SignatureVerificationError, Webhook, models

# Signed by the server's own signWebhook() in @leadveyor/core.
BODY = '{"object":"event","id":"evt_1","type":"lead.scored","livemode":false,"workspaceId":"ws_1","createdAt":"2026-11-23T00:00:00Z","data":{"object":{"object":"lead","id":"lead_1","evaluation":{"tier":"hot","score":90}}}}'
SECRET = "whsec_test123"
T = 1795000000
HEADER = "t=1795000000,v1=2f6536601191dcc9c22c74a425c157609577065c2fc6e3dc1ae6df37f0682da3"


def test_accepts_the_servers_own_signature() -> None:
    event = Webhook.construct_event(BODY.encode(), HEADER, SECRET, now=T + 10)
    assert isinstance(event, models.Event)
    assert event.type == "lead.scored"
    assert isinstance(event.data.object, models.Lead)
    assert event.data.object.evaluation.tier == "hot"
    assert Webhook.verify(BODY, HEADER, SECRET, now=T)


def code(fn: Callable[[], Any]) -> Optional[str]:
    try:
        fn()
    except SignatureVerificationError as e:
        return e.code
    return None


def test_rejects_bad_signatures() -> None:
    assert code(lambda: Webhook.construct_event(BODY, HEADER, "whsec_other", now=T)) == "signature_mismatch"
    assert code(lambda: Webhook.construct_event(BODY.replace("lead_1", "lead_2"), HEADER, SECRET, now=T)) == "signature_mismatch"
    assert code(lambda: Webhook.construct_event(BODY, HEADER, SECRET, now=T + 600)) == "timestamp_out_of_range"
    assert code(lambda: Webhook.construct_event(BODY, None, SECRET)) == "missing_signature"
    assert code(lambda: Webhook.construct_event(BODY, "garbage", SECRET)) == "malformed_signature"
    assert code(lambda: Webhook.construct_event(BODY, HEADER, "")) == "missing_secret"
    assert code(lambda: Webhook.construct_event(json.loads(BODY), HEADER, SECRET)) == "payload_not_raw"  # type: ignore[arg-type]
    assert Webhook.verify(BODY, HEADER, "whsec_other", now=T) is False


def test_generate_test_header_matches_the_server() -> None:
    assert Webhook.generate_test_header(BODY, SECRET, T) == HEADER
    assert Webhook.verify(BODY, Webhook.generate_test_header(BODY, SECRET), SECRET)


def test_several_v1_signatures_during_rotation() -> None:
    old = Webhook.generate_test_header(BODY, "whsec_old", T)
    assert Webhook.verify(BODY, old + "," + HEADER.split(",")[1], SECRET, now=T)


def test_raises_on_missing_signature() -> None:
    with pytest.raises(SignatureVerificationError):
        Webhook.construct_event(BODY, "", SECRET)
