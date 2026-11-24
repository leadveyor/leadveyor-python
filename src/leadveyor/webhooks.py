"""Webhook signature verification. Docs: https://leadveyor.com/docs/webhooks"""

from __future__ import annotations

import hashlib
import hmac
import json
import time
from typing import List, Optional, Tuple, Union

from ._errors import SignatureVerificationError
from .models import Event, Inbound, Lead

__all__ = ["Webhook", "DEFAULT_TOLERANCE", "SIGNATURE_HEADER"]

#: Default allowed clock difference between Leadveyor and your server, in seconds. Same as the server's.
DEFAULT_TOLERANCE = 300
SIGNATURE_HEADER = "Leadveyor-Signature"


def _fail(code: str, message: str) -> SignatureVerificationError:
    return SignatureVerificationError(message, type="invalid_request_error", code=code)


def _parse_header(header: str) -> Tuple[Optional[int], List[str]]:
    t: Optional[int] = None
    v1: List[str] = []
    for part in header.split(","):
        k, sep, v = part.partition("=")
        if not sep:
            continue
        k, v = k.strip(), v.strip()
        if k == "t" and v.isdigit():
            t = int(v)
        elif k == "v1" and v:
            v1.append(v)
    return t, v1


def _sign(secret: str, timestamp: int, payload: str) -> str:
    return hmac.new(secret.encode(), f"{timestamp}.{payload}".encode(), hashlib.sha256).hexdigest()


class Webhook:
    """Checks the ``Leadveyor-Signature`` header of a webhook request.

    .. code-block:: python

        event = Webhook.construct_event(
            request.body,                               # the raw body (bytes or str)
            request.headers.get("Leadveyor-Signature"),
            os.environ["LEADVEYOR_WEBHOOK_SECRET"],     # whsec_…
        )
        if event.type == "lead.scored":
            print(event.data.object.evaluation.tier)    # data.object is a models.Lead
    """

    @staticmethod
    def construct_event(
        payload: Union[str, bytes, bytearray],
        signature_header: Optional[str],
        secret: str,
        *,
        tolerance: int = DEFAULT_TOLERANCE,
        now: Optional[float] = None,
    ) -> Event:
        """Verifies the signature and returns the event; raises SignatureVerificationError when it does not match.

        ``data.object`` is a ``models.Lead`` for ``lead.*`` events and a ``models.Inbound`` for ``inbound.*`` events.
        Pass the raw request body exactly as received, not parsed and re-encoded JSON.
        """
        if isinstance(payload, (bytes, bytearray)):
            body = bytes(payload).decode("utf-8")
        elif isinstance(payload, str):
            body = payload
        else:
            raise _fail(
                "payload_not_raw",
                "Pass the raw request body (str or bytes), not parsed JSON: re-serialising changes the bytes and the "
                "signature will not match. Flask: request.get_data(); Django: request.body; FastAPI: await request.body().",
            )
        if not secret:
            raise _fail("missing_secret", "No signing secret. It starts with whsec_ and is shown when the destination is created.")
        if not signature_header:
            raise _fail("missing_signature", "No Leadveyor-Signature header on the request.")
        t, v1 = _parse_header(signature_header)
        if t is None or not v1:
            raise _fail("malformed_signature", "Leadveyor-Signature header is malformed (expected t=…,v1=…).")
        current = time.time() if now is None else now
        if abs(current - t) > tolerance:
            raise _fail(
                "timestamp_out_of_range",
                f"Signature timestamp is more than {tolerance} s away from now (replay, or the server clock is off).",
            )
        expected = _sign(secret, t, body)
        if not any(hmac.compare_digest(expected, sig) for sig in v1):
            raise _fail(
                "signature_mismatch",
                "Signature does not match. Check the secret, and that the body is the raw, unmodified request body.",
            )
        try:
            data = json.loads(body)
        except ValueError as err:
            raise _fail("invalid_json", "Webhook body is not valid JSON.") from err
        if not isinstance(data, dict):
            raise _fail("invalid_json", "Webhook body is not a JSON object.")
        event = Event.construct_from(data)
        raw_type = data.get("type")
        typ = raw_type if isinstance(raw_type, str) else ""
        obj = (data.get("data") or {}).get("object") if isinstance(data.get("data"), dict) else None
        event_data = event.get("data")
        if isinstance(obj, dict) and isinstance(event_data, dict):
            if typ.startswith("lead."):
                event_data["object"] = Lead.construct_from(obj)
            elif typ.startswith("inbound."):
                event_data["object"] = Inbound.construct_from(obj)
        return event

    @staticmethod
    def verify(
        payload: Union[str, bytes, bytearray],
        signature_header: Optional[str],
        secret: str,
        *,
        tolerance: int = DEFAULT_TOLERANCE,
        now: Optional[float] = None,
    ) -> bool:
        """Same check as ``construct_event``, as a boolean."""
        try:
            Webhook.construct_event(payload, signature_header, secret, tolerance=tolerance, now=now)
            return True
        except SignatureVerificationError:
            return False

    @staticmethod
    def generate_test_header(payload: str, secret: str, timestamp: Optional[int] = None) -> str:
        """Signs a payload like Leadveyor does — for testing your webhook handler."""
        ts = int(time.time()) if timestamp is None else timestamp
        return f"t={ts},v1={_sign(secret, ts, payload)}"
