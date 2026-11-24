"""Shared HTTP layer (retries, timeouts, error mapping). The generated clients add the resources on top."""

from __future__ import annotations

import asyncio
import email.utils
import json
import os
import platform
import random
import time
from typing import Any, Dict, Mapping, Optional, Type, TypeVar, Union, overload
from urllib.parse import quote

import httpx

from ._errors import APIConnectionError, APITimeoutError, AuthenticationError, LeadveyorError, error_from_response
from ._object import LeadveyorObject, convert
from ._pagination import AsyncPageRequest, SyncPage
from ._version import __version__

__all__ = ["NOT_GIVEN", "NotGiven", "DEFAULT_BASE_URL"]

DEFAULT_BASE_URL = "https://core.leadveyor.com"
DEFAULT_TIMEOUT = 60.0
DEFAULT_MAX_RETRIES = 2

#: Retried for requests that are safe to repeat.
_RETRY_STATUSES = {500, 502, 503, 504}
#: POST can create things twice if retried after the server got it; only 429 (rejected up front) is retried for POST.
_IDEMPOTENT_METHODS = {"GET", "PUT", "PATCH", "DELETE"}

T = TypeVar("T", bound=LeadveyorObject)


class NotGiven:
    """Marks an argument that was not passed (None is a real value: it sends JSON null)."""

    _instance: Optional["NotGiven"] = None

    def __new__(cls) -> "NotGiven":
        if cls._instance is None:
            cls._instance = super().__new__(cls)
        return cls._instance

    def __bool__(self) -> bool:
        return False

    def __repr__(self) -> str:
        return "NOT_GIVEN"


NOT_GIVEN = NotGiven()


def _env(name: str) -> Optional[str]:
    v = os.environ.get(name)
    return v or None


def path_param(value: Union[str, int]) -> str:
    """Encodes a path parameter."""
    return quote(str(value), safe="")


def build_query(query: Optional[Mapping[str, Any]]) -> Dict[str, str]:
    """Drops unset values; booleans as true / false."""
    out: Dict[str, str] = {}
    for k, v in (query or {}).items():
        if v is None or isinstance(v, NotGiven):
            continue
        out[k] = ("true" if v else "false") if isinstance(v, bool) else str(v)
    return out


def build_body(fields: Mapping[str, Any]) -> Dict[str, Any]:
    """Drops arguments that were not passed."""
    return {k: v for k, v in fields.items() if not isinstance(v, NotGiven)}


def retry_delay(attempt: int, retry_after: Optional[str]) -> float:
    """Exponential backoff with jitter (0.5 s, 1 s, 2 s … capped at 8 s); ``Retry-After`` wins when present."""
    if retry_after:
        try:
            secs = float(retry_after)
            if secs >= 0:
                return min(secs, 60.0)
        except ValueError:
            try:
                parsed = email.utils.parsedate_to_datetime(retry_after)
            except (TypeError, ValueError):
                parsed = None
            if parsed is not None:
                return min(max(parsed.timestamp() - time.time(), 0.0), 60.0)
    base = min(0.5 * float(2**attempt), 8.0)
    return base * (0.75 + random.random() * 0.5)


def _parse(response: httpx.Response) -> Any:
    text = response.text
    if not text:
        return None
    ctype = response.headers.get("content-type", "")
    if "json" in ctype or text.lstrip()[:1] in ("{", "["):
        try:
            return json.loads(text)
        except ValueError:
            return text
    return text


# Patched in tests.
_sleep = time.sleep
_async_sleep = asyncio.sleep


class _ClientConfig:
    def __init__(
        self,
        api_key: Optional[str],
        *,
        base_url: Optional[str],
        workspace: Optional[str],
        account: Optional[str],
        timeout: Optional[float],
        max_retries: Optional[int],
        default_headers: Optional[Mapping[str, str]],
    ) -> None:
        key = api_key or _env("LEADVEYOR_API_KEY")
        if not key:
            raise AuthenticationError(
                'No API key. Pass it to Leadveyor("lv_live_…") or set LEADVEYOR_API_KEY. Keys: console → API keys.',
                type="authentication_error",
            )
        self.api_key: str = key
        self.base_url = (base_url or _env("LEADVEYOR_BASE_URL") or DEFAULT_BASE_URL).rstrip("/")
        self.workspace = workspace
        self.account = account
        self.timeout = float(timeout) if timeout is not None else DEFAULT_TIMEOUT
        self.max_retries = int(max_retries) if max_retries is not None else DEFAULT_MAX_RETRIES
        self.default_headers = dict(default_headers or {})

    def headers(self, workspace: Optional[str], account: Optional[str], extra: Optional[Mapping[str, str]], has_body: bool) -> Dict[str, str]:
        h = {
            "Accept": "application/json",
            "Authorization": f"Bearer {self.api_key}",
            "User-Agent": f"leadveyor-sdk-python/{__version__} Python/{platform.python_version()}",
            **self.default_headers,
        }
        ws = workspace or self.workspace
        acc = account or self.account
        if ws:
            h["Leadveyor-Workspace"] = ws
        if acc:
            h["Leadveyor-Account"] = acc
        if has_body:
            h["Content-Type"] = "application/json"
        h.update(extra or {})
        return h


def _result(parsed: Any, cls: Optional[Type[LeadveyorObject]]) -> Any:
    if parsed is None:
        return None
    if cls is not None and isinstance(parsed, dict):
        return cls.construct_from(parsed)
    return convert(parsed)


def _transport_error(err: Exception, method: str, path: str, timeout: float) -> LeadveyorError:
    if isinstance(err, httpx.TimeoutException):
        e: LeadveyorError = APITimeoutError(f"Request timed out after {timeout:g} s: {method} {path}", type="connection_error")
    else:
        e = APIConnectionError(f"Could not reach the Leadveyor API ({method} {path}): {err}", type="connection_error")
    e.__cause__ = err
    return e


class SyncAPIClient:
    """Synchronous HTTP layer of ``Leadveyor``."""

    def __init__(
        self,
        api_key: Optional[str] = None,
        *,
        base_url: Optional[str] = None,
        workspace: Optional[str] = None,
        account: Optional[str] = None,
        timeout: Optional[float] = None,
        max_retries: Optional[int] = None,
        default_headers: Optional[Mapping[str, str]] = None,
        http_client: Optional[httpx.Client] = None,
    ) -> None:
        self._config = _ClientConfig(
            api_key, base_url=base_url, workspace=workspace, account=account, timeout=timeout, max_retries=max_retries, default_headers=default_headers
        )
        self._options: Dict[str, Any] = dict(
            api_key=self._config.api_key, base_url=base_url, workspace=workspace, account=account, timeout=timeout,
            max_retries=max_retries, default_headers=default_headers,
        )
        self._own_http = http_client is None
        self._http = http_client or httpx.Client()
        self._options["http_client"] = self._http

    @property
    def livemode(self) -> bool:
        """``lv_test_…`` keys work on test data only."""
        return not self._config.api_key.startswith("lv_test_")

    def close(self) -> None:
        """Closes the HTTP connection pool (only if the client created it)."""
        if self._own_http:
            self._http.close()

    def __enter__(self: Any) -> Any:
        return self

    def __exit__(self, *args: Any) -> None:
        self.close()

    @overload
    def _request(
        self,
        method: str,
        path: str,
        *,
        query: Optional[Mapping[str, Any]] = None,
        body: Optional[Mapping[str, Any]] = None,
        cls: Type[T],
        idempotent: Optional[bool] = None,
        workspace: Optional[str] = None,
        account: Optional[str] = None,
        timeout: Optional[float] = None,
        max_retries: Optional[int] = None,
        extra_headers: Optional[Mapping[str, str]] = None,
    ) -> T: ...

    @overload
    def _request(
        self,
        method: str,
        path: str,
        *,
        query: Optional[Mapping[str, Any]] = None,
        body: Optional[Mapping[str, Any]] = None,
        cls: None = None,
        idempotent: Optional[bool] = None,
        workspace: Optional[str] = None,
        account: Optional[str] = None,
        timeout: Optional[float] = None,
        max_retries: Optional[int] = None,
        extra_headers: Optional[Mapping[str, str]] = None,
    ) -> Any: ...

    def _request(
        self,
        method: str,
        path: str,
        *,
        query: Optional[Mapping[str, Any]] = None,
        body: Optional[Mapping[str, Any]] = None,
        cls: Optional[Type[LeadveyorObject]] = None,
        idempotent: Optional[bool] = None,
        workspace: Optional[str] = None,
        account: Optional[str] = None,
        timeout: Optional[float] = None,
        max_retries: Optional[int] = None,
        extra_headers: Optional[Mapping[str, str]] = None,
    ) -> Any:
        cfg = self._config
        url = cfg.base_url + path
        params = build_query(query)
        content = json.dumps(body, ensure_ascii=False, separators=(",", ":")).encode() if body is not None else None
        headers = cfg.headers(workspace, account, extra_headers, content is not None)
        retries = cfg.max_retries if max_retries is None else max_retries
        t = cfg.timeout if timeout is None else float(timeout)
        safe = (method in _IDEMPOTENT_METHODS) if idempotent is None else idempotent
        attempt = 0
        while True:
            can_retry = attempt < retries
            try:
                res = self._http.request(method, url, params=params, content=content, headers=headers, timeout=t)
            except httpx.TransportError as err:
                if can_retry and safe:
                    _sleep(retry_delay(attempt, None))
                    attempt += 1
                    continue
                raise _transport_error(err, method, path, t) from err
            parsed = _parse(res)
            if 200 <= res.status_code < 300:
                return _result(parsed, cls)
            if (res.status_code == 429 or (res.status_code in _RETRY_STATUSES and safe)) and can_retry:
                _sleep(retry_delay(attempt, res.headers.get("retry-after")))
                attempt += 1
                continue
            raise error_from_response(res.status_code, parsed, dict(res.headers))

    def _request_page(self, path: str, query: Mapping[str, Any], item_cls: Type[T], **options: Any) -> SyncPage[T]:
        def fetch(cursor: Optional[str]) -> LeadveyorObject:
            q = dict(query, starting_after=cursor) if cursor is not None else dict(query)
            res = self._request("GET", path, query=q, **options)
            if not isinstance(res, LeadveyorObject):
                raise LeadveyorError(f"Unexpected response for a list: {type(res).__name__}")
            return res

        start = query.get("starting_after")
        return SyncPage(fetch(start if isinstance(start, str) else None), item_cls, fetch)


class AsyncAPIClient:
    """Asynchronous HTTP layer of ``AsyncLeadveyor``."""

    def __init__(
        self,
        api_key: Optional[str] = None,
        *,
        base_url: Optional[str] = None,
        workspace: Optional[str] = None,
        account: Optional[str] = None,
        timeout: Optional[float] = None,
        max_retries: Optional[int] = None,
        default_headers: Optional[Mapping[str, str]] = None,
        http_client: Optional[httpx.AsyncClient] = None,
    ) -> None:
        self._config = _ClientConfig(
            api_key, base_url=base_url, workspace=workspace, account=account, timeout=timeout, max_retries=max_retries, default_headers=default_headers
        )
        self._options: Dict[str, Any] = dict(
            api_key=self._config.api_key, base_url=base_url, workspace=workspace, account=account, timeout=timeout,
            max_retries=max_retries, default_headers=default_headers,
        )
        self._own_http = http_client is None
        self._http = http_client or httpx.AsyncClient()
        self._options["http_client"] = self._http

    @property
    def livemode(self) -> bool:
        """``lv_test_…`` keys work on test data only."""
        return not self._config.api_key.startswith("lv_test_")

    async def close(self) -> None:
        if self._own_http:
            await self._http.aclose()

    async def __aenter__(self: Any) -> Any:
        return self

    async def __aexit__(self, *args: Any) -> None:
        await self.close()

    @overload
    async def _request(
        self,
        method: str,
        path: str,
        *,
        query: Optional[Mapping[str, Any]] = None,
        body: Optional[Mapping[str, Any]] = None,
        cls: Type[T],
        idempotent: Optional[bool] = None,
        workspace: Optional[str] = None,
        account: Optional[str] = None,
        timeout: Optional[float] = None,
        max_retries: Optional[int] = None,
        extra_headers: Optional[Mapping[str, str]] = None,
    ) -> T: ...

    @overload
    async def _request(
        self,
        method: str,
        path: str,
        *,
        query: Optional[Mapping[str, Any]] = None,
        body: Optional[Mapping[str, Any]] = None,
        cls: None = None,
        idempotent: Optional[bool] = None,
        workspace: Optional[str] = None,
        account: Optional[str] = None,
        timeout: Optional[float] = None,
        max_retries: Optional[int] = None,
        extra_headers: Optional[Mapping[str, str]] = None,
    ) -> Any: ...

    async def _request(
        self,
        method: str,
        path: str,
        *,
        query: Optional[Mapping[str, Any]] = None,
        body: Optional[Mapping[str, Any]] = None,
        cls: Optional[Type[LeadveyorObject]] = None,
        idempotent: Optional[bool] = None,
        workspace: Optional[str] = None,
        account: Optional[str] = None,
        timeout: Optional[float] = None,
        max_retries: Optional[int] = None,
        extra_headers: Optional[Mapping[str, str]] = None,
    ) -> Any:
        cfg = self._config
        url = cfg.base_url + path
        params = build_query(query)
        content = json.dumps(body, ensure_ascii=False, separators=(",", ":")).encode() if body is not None else None
        headers = cfg.headers(workspace, account, extra_headers, content is not None)
        retries = cfg.max_retries if max_retries is None else max_retries
        t = cfg.timeout if timeout is None else float(timeout)
        safe = (method in _IDEMPOTENT_METHODS) if idempotent is None else idempotent
        attempt = 0
        while True:
            can_retry = attempt < retries
            try:
                res = await self._http.request(method, url, params=params, content=content, headers=headers, timeout=t)
            except httpx.TransportError as err:
                if can_retry and safe:
                    await _async_sleep(retry_delay(attempt, None))
                    attempt += 1
                    continue
                raise _transport_error(err, method, path, t) from err
            parsed = _parse(res)
            if 200 <= res.status_code < 300:
                return _result(parsed, cls)
            if (res.status_code == 429 or (res.status_code in _RETRY_STATUSES and safe)) and can_retry:
                await _async_sleep(retry_delay(attempt, res.headers.get("retry-after")))
                attempt += 1
                continue
            raise error_from_response(res.status_code, parsed, dict(res.headers))

    def _request_page(self, path: str, query: Mapping[str, Any], item_cls: Type[T], **options: Any) -> AsyncPageRequest[T]:
        async def fetch(cursor: Optional[str]) -> LeadveyorObject:
            q = dict(query, starting_after=cursor) if cursor is not None else dict(query)
            res = await self._request("GET", path, query=q, **options)
            if not isinstance(res, LeadveyorObject):
                raise LeadveyorError(f"Unexpected response for a list: {type(res).__name__}")
            return res

        start = query.get("starting_after")
        return AsyncPageRequest(item_cls, fetch, start if isinstance(start, str) else None)
