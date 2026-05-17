"""Small helper that makes SQLAlchemy's `Enum` use the Python enum's *value*.

By default SQLAlchemy 2.0 serializes a Python `enum.Enum` member by its `name`
(uppercase ``"ADMIN"``), while our Postgres enum types are created with the
lowercase string values (``"admin"``). Wrapping every column declaration with
this helper keeps the application and the database in sync.
"""

from collections.abc import Sequence
from enum import Enum
from typing import Any

from sqlalchemy import Enum as SAEnum


def pg_enum(
    enum_cls: type[Enum],
    *,
    name: str,
    **kwargs: Any,
) -> SAEnum:
    """Build a SQLAlchemy ENUM bound to *value* (not *name*) for `enum_cls`."""

    def values_callable(cls: type[Enum]) -> Sequence[str]:
        return [e.value for e in cls]

    return SAEnum(
        enum_cls,
        name=name,
        values_callable=values_callable,
        **kwargs,
    )
