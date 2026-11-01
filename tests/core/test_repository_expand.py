"""Fetching a record (or a page) with its relations embedded, one extra query per relation."""

from __future__ import annotations

import pytest
from sqlalchemy.ext.asyncio import create_async_engine
from sqlalchemy.orm import sessionmaker
from sqlmodel import SQLModel
from sqlmodel.ext.asyncio.session import AsyncSession

from tuvl.core.models.loader import (
    MODEL_DATASOURCE_MAP,
    MODEL_REGISTRY,
    MODEL_RELATIONS,
    MODEL_VERSION_REGISTRY,
    SCHEMA_REGISTRY,
    _register_model_from_dict,
)
from tuvl.core.repositories.base import BaseRepository


def _model(name: str, table: str, fields: list[dict], relations: list[dict]) -> dict:
    return {
        "kind": "ModelDefinition",
        "metadata": {"name": name},
        "spec": {"tablename": table, "fields": fields, "relations": relations},
    }


@pytest.fixture
async def session():
    for registry in (MODEL_REGISTRY, MODEL_VERSION_REGISTRY, SCHEMA_REGISTRY, MODEL_RELATIONS):
        registry.clear()
    MODEL_DATASOURCE_MAP.clear()
    _register_model_from_dict(
        _model(
            "ExpAuthor",
            "exp_authors",
            [
                {"name": "id", "type": "string", "primary_key": True},
                {"name": "name", "type": "string"},
            ],
            [
                {
                    "name": "books",
                    "model": "ExpBook",
                    "foreign_key": "author_id",
                    "type": "one_to_many",
                }
            ],
        )
    )
    _register_model_from_dict(
        _model(
            "ExpBook",
            "exp_books",
            [
                {"name": "id", "type": "string", "primary_key": True},
                {"name": "author_id", "type": "string"},
                {"name": "title", "type": "string"},
            ],
            [
                {
                    "name": "author",
                    "model": "ExpAuthor",
                    "foreign_key": "author_id",
                    "type": "many_to_one",
                }
            ],
        )
    )
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    tables = [MODEL_REGISTRY["ExpAuthor"].__table__, MODEL_REGISTRY["ExpBook"].__table__]
    async with engine.begin() as conn:
        await conn.run_sync(SQLModel.metadata.create_all, tables=tables)
    async with sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)() as s:
        author = BaseRepository("ExpAuthor", s)
        book = BaseRepository("ExpBook", s)
        await author.add({"id": "a1", "name": "Ada"})
        await author.add({"id": "a2", "name": "Grace"})
        await book.add({"id": "b1", "author_id": "a1", "title": "Notes"})
        await book.add({"id": "b2", "author_id": "a1", "title": "Engines"})
        await book.add({"id": "b3", "author_id": None, "title": "Anonymous"})
        yield s
    for registry in (MODEL_REGISTRY, MODEL_VERSION_REGISTRY, SCHEMA_REGISTRY, MODEL_RELATIONS):
        registry.clear()


async def test_one_record_with_its_many_to_one_relation(session) -> None:
    got = await BaseRepository("ExpBook", session).get_expanded("b1", {"author"})
    assert got is not None and got["title"] == "Notes"
    assert got["author"]["name"] == "Ada"


async def test_one_record_with_its_one_to_many_relation(session) -> None:
    got = await BaseRepository("ExpAuthor", session).get_expanded("a1", {"books"})
    assert got is not None
    assert sorted(b["title"] for b in got["books"]) == ["Engines", "Notes"]
    none_yet = await BaseRepository("ExpAuthor", session).get_expanded("a2", {"books"})
    assert none_yet is not None and none_yet["books"] == []


async def test_a_missing_record_is_none_and_unrequested_relations_are_left_out(session) -> None:
    repo = BaseRepository("ExpBook", session)
    assert await repo.get_expanded("nope", {"author"}) is None
    plain = await repo.get_expanded("b1", set())
    assert plain is not None and "author" not in plain


async def test_a_page_resolves_each_relation_in_one_query(session) -> None:
    rows = await BaseRepository("ExpBook", session).list_expanded({"author"}, limit=10)
    by_title = {r["title"]: r["author"] for r in rows}
    assert by_title["Notes"]["name"] == "Ada" and by_title["Engines"]["name"] == "Ada"
    assert by_title["Anonymous"] is None  # no author_id: no query for it, and a null result
