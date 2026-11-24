"""Paginated lists. Docs: https://leadveyor.com/docs/pagination"""

from __future__ import annotations

from typing import Any, AsyncIterator, Awaitable, Callable, Generator, Generic, Iterator, List, Optional, Type, TypeVar

from ._object import LeadveyorObject

__all__ = ["SyncPage", "AsyncPage", "AsyncPageRequest"]

T = TypeVar("T", bound=LeadveyorObject)


def _items(response: LeadveyorObject, item_cls: Type[T]) -> List[T]:
    out: List[T] = []
    for item in response.get("data") or []:
        out.append(item_cls.construct_from(item) if isinstance(item, dict) else item)
    return out


class _PageBase(Generic[T]):
    #: Items of this page.
    data: List[T]
    has_more: bool
    next_cursor: Optional[str]

    def __init__(self, response: LeadveyorObject, item_cls: Type[T]) -> None:
        self._item_cls = item_cls
        self.data = _items(response, item_cls)
        self.has_more = bool(response.get("has_more"))
        cursor = response.get("next_cursor")
        self.next_cursor = cursor if isinstance(cursor, str) else None

    def __len__(self) -> int:
        return len(self.data)

    def __repr__(self) -> str:
        return f"{type(self).__name__}(data=[{len(self.data)} items], has_more={self.has_more}, next_cursor={self.next_cursor!r})"


class SyncPage(_PageBase[T]):
    """One page of a list, plus iteration over every item.

    .. code-block:: python

        page = lv.leads.list(tier="hot", limit=50)
        page.data, page.has_more, page.next_cursor     # this page

        for lead in lv.leads.list(outcome="none"):     # every item; next pages fetched as you go
            ...

        recent = lv.events.list(type="lead.*").to_list(limit=500)
    """

    def __init__(self, response: LeadveyorObject, item_cls: Type[T], fetch: Callable[[Optional[str]], LeadveyorObject]) -> None:
        super().__init__(response, item_cls)
        self._fetch = fetch

    def next_page(self) -> Optional["SyncPage[T]"]:
        """The next page, or None on the last one."""
        if not self.has_more or self.next_cursor is None:
            return None
        return SyncPage(self._fetch(self.next_cursor), self._item_cls, self._fetch)

    def __iter__(self) -> Iterator[T]:
        """Every item from this page on, fetching the next pages as needed."""
        page: Optional[SyncPage[T]] = self
        while page is not None:
            yield from page.data
            page = page.next_page()

    def auto_paging_iter(self) -> Iterator[T]:
        return iter(self)

    def to_list(self, limit: Optional[int] = None) -> List[T]:
        """Up to ``limit`` items (across pages); every item when None."""
        out: List[T] = []
        if limit is not None and limit <= 0:
            return out
        for item in self:
            out.append(item)
            if limit is not None and len(out) >= limit:
                break
        return out


class AsyncPage(_PageBase[T]):
    """One page of a list (async client). ``async for`` goes through every item across pages."""

    def __init__(
        self, response: LeadveyorObject, item_cls: Type[T], fetch: Callable[[Optional[str]], Awaitable[LeadveyorObject]]
    ) -> None:
        super().__init__(response, item_cls)
        self._fetch = fetch

    async def next_page(self) -> Optional["AsyncPage[T]"]:
        if not self.has_more or self.next_cursor is None:
            return None
        return AsyncPage(await self._fetch(self.next_cursor), self._item_cls, self._fetch)

    async def __aiter__(self) -> AsyncIterator[T]:
        page: Optional[AsyncPage[T]] = self
        while page is not None:
            for item in page.data:
                yield item
            page = await page.next_page()

    async def to_list(self, limit: Optional[int] = None) -> List[T]:
        out: List[T] = []
        if limit is not None and limit <= 0:
            return out
        async for item in self:
            out.append(item)
            if limit is not None and len(out) >= limit:
                break
        return out


class AsyncPageRequest(Generic[T]):
    """What an async ``list()`` returns.

    - ``await lv.leads.list()`` → the first page (``AsyncPage``)
    - ``async for lead in lv.leads.list()`` → every item, fetching the next pages as needed
    - ``await lv.leads.list().to_list(limit=500)`` → up to 500 items

    Nothing is requested until you await or iterate it.
    """

    def __init__(self, item_cls: Type[T], fetch: Callable[[Optional[str]], Awaitable[LeadveyorObject]], start: Optional[str]) -> None:
        self._item_cls = item_cls
        self._fetch = fetch
        self._start = start

    async def _first(self) -> AsyncPage[T]:
        return AsyncPage(await self._fetch(self._start), self._item_cls, self._fetch)

    def __await__(self) -> Generator[Any, None, AsyncPage[T]]:
        return self._first().__await__()

    async def __aiter__(self) -> AsyncIterator[T]:
        page = await self._first()
        async for item in page:
            yield item

    async def to_list(self, limit: Optional[int] = None) -> List[T]:
        return await (await self._first()).to_list(limit)
