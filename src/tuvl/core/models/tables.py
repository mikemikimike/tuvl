"""Typed access to what SQLModel's metaclass attaches to a table class."""

from __future__ import annotations

import sqlalchemy as sa


def table_of(model: type) -> sa.Table:
    """The ``Table`` of a SQLModel table class (``__table__`` is set by the metaclass, which mypy cannot see)."""
    table: sa.Table = model.__table__  # type: ignore[attr-defined]
    return table
