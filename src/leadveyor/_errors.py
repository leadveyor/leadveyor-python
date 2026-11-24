"""Exceptions raised by the SDK. Docs: https://leadveyor.com/docs/errors"""

from __future__ import annotations

from typing import Any, Dict, List, Mapping, Optional, Type

__all__ = [
    "LeadveyorError",
    "InvalidRequestError",
    "AuthenticationError",
    "PermissionDeniedError",
    "NotFoundError",
    "ConflictError",
    "QuotaExceededError",
    "RateLimitError",
    "APIError",
    "APIConnectionError",
    "APITimeoutError",
    "SignatureVerificationError",
]


class LeadveyorError(Exception):
    """Base class of every error the SDK raises.

    API errors carry the fields of the error envelope (``type``, ``code``, ``param``, ``errors``, ``request_id``).
    """

    message: str
    #: HTTP status; None for connection problems and timeouts.
    status_code: Optional[int]
    #: ``invalid_request_error``, ``authentication_error``, ``permission_error``, ``not_found_error``,
    #: ``conflict_error``, ``rate_limit_error``, ``quota_error``, ``api_error`` or ``connection_error``.
    type: str
    #: Machine-readable reason, e.g. ``profile_invalid``, ``insufficient_permission``.
    code: Optional[str]
    #: The request field the error is about.
    param: Optional[str]
    #: All field-level problems (profile validation): ``[{"path": ..., "message": ...}]``.
    errors: List[Dict[str, str]]
    #: Quote this when contacting support.
    request_id: Optional[str]
    #: Response headers (lower-case names).
    headers: Dict[str, str]
    #: The parsed response body.
    body: Any

    def __init__(
        self,
        message: str,
        *,
        status_code: Optional[int] = None,
        type: str = "api_error",
        code: Optional[str] = None,
        param: Optional[str] = None,
        errors: Optional[List[Dict[str, str]]] = None,
        request_id: Optional[str] = None,
        headers: Optional[Mapping[str, str]] = None,
        body: Any = None,
    ) -> None:
        super().__init__(message)
        self.message = message
        self.status_code = status_code
        self.type = type
        self.code = code
        self.param = param
        self.errors = errors or []
        self.request_id = request_id
        self.headers = {k.lower(): v for k, v in (headers or {}).items()}
        self.body = body

    def __str__(self) -> str:
        parts = [self.message]
        if self.request_id:
            parts.append(f"(request_id: {self.request_id})")
        return " ".join(parts)


class InvalidRequestError(LeadveyorError):
    """400: the request is malformed or failed validation; ``errors`` lists every field problem."""


class AuthenticationError(LeadveyorError):
    """401: missing, invalid or revoked API key."""


class PermissionDeniedError(LeadveyorError):
    """403: the key is valid but not allowed to do this (permission or workspace)."""


class NotFoundError(LeadveyorError):
    """404: no such object, or it belongs to another workspace."""


class ConflictError(LeadveyorError):
    """409: conflicts with the current state, e.g. publishing a profile without a draft."""


class QuotaExceededError(LeadveyorError):
    """402: the plan's allowance for this period is used up (``quota_exceeded``, ``spend_limit_reached``…). Not retried."""


class RateLimitError(LeadveyorError):
    """429: too many requests. The SDK already retried with backoff before raising this."""


class APIError(LeadveyorError):
    """5xx: a problem on Leadveyor's side."""


class APIConnectionError(LeadveyorError):
    """The API could not be reached (DNS, TLS, connection reset)."""


class APITimeoutError(APIConnectionError):
    """No response within ``timeout``."""


class SignatureVerificationError(LeadveyorError):
    """``Webhook.construct_event``: the signature header is missing, malformed, too old, or does not match."""


_BY_STATUS: Dict[int, Type[LeadveyorError]] = {
    400: InvalidRequestError,
    401: AuthenticationError,
    402: QuotaExceededError,
    403: PermissionDeniedError,
    404: NotFoundError,
    409: ConflictError,
    429: RateLimitError,
}


def error_from_response(status: int, body: Any, headers: Mapping[str, str]) -> LeadveyorError:
    """Builds the right error class from a non-2xx response. Works for non-JSON bodies too (proxy errors)."""
    env: Dict[str, Any] = body["error"] if isinstance(body, dict) and isinstance(body.get("error"), dict) else {}

    def s(v: Any) -> Optional[str]:
        return v if isinstance(v, str) else None

    cls = _BY_STATUS.get(status) or (APIError if status >= 500 else LeadveyorError)
    fallback_type = "api_error" if status >= 500 else "rate_limit_error" if status == 429 else "invalid_request_error"
    message = s(env.get("message")) or (f"HTTP {status}: {body[:200]}" if isinstance(body, str) and body else f"HTTP {status}")
    errors = [
        {"path": str(e.get("path", "")), "message": str(e.get("message", ""))}
        for e in (env.get("errors") or [])
        if isinstance(e, dict)
    ]
    lower = {k.lower(): v for k, v in headers.items()}
    return cls(
        message,
        status_code=status,
        type=s(env.get("type")) or fallback_type,
        code=s(env.get("code")),
        param=s(env.get("param")),
        errors=errors,
        request_id=s(env.get("request_id")) or lower.get("x-request-id"),
        headers=lower,
        body=body,
    )
