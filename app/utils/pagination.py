"""Pagination primitives shared by every list endpoint.

`PaginationParams` is a FastAPI-compatible dependency: declare it as a
parameter and FastAPI will populate `page` and `page_size` from the query
string. `PaginatedResponse[T]` is a generic envelope used by all list
responses.
"""

from typing import Generic, TypeVar

from fastapi import Query
from pydantic import BaseModel

T = TypeVar("T")

MAX_PAGE_SIZE = 200
DEFAULT_PAGE_SIZE = 50


class PaginationParams:
    """Validated page/page_size pair with derived offset."""

    def __init__(
        self,
        page: int = Query(1, ge=1, description="1-based page number."),
        page_size: int = Query(
            DEFAULT_PAGE_SIZE,
            ge=1,
            le=MAX_PAGE_SIZE,
            description=f"Page size (1–{MAX_PAGE_SIZE}).",
        ),
    ) -> None:
        self.page = page
        self.page_size = page_size

    @property
    def offset(self) -> int:
        return (self.page - 1) * self.page_size

    @property
    def limit(self) -> int:
        return self.page_size


class PaginatedResponse(BaseModel, Generic[T]):
    """Generic paginated list envelope."""

    items: list[T]
    total: int
    page: int
    page_size: int
    total_pages: int

    @classmethod
    def build(
        cls,
        *,
        items: list[T],
        total: int,
        params: PaginationParams,
    ) -> "PaginatedResponse[T]":
        total_pages = (total + params.page_size - 1) // params.page_size if total else 0
        return cls(
            items=items,
            total=total,
            page=params.page,
            page_size=params.page_size,
            total_pages=total_pages,
        )
