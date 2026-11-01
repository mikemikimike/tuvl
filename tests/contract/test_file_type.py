"""The ``file`` type: parsing, typing in expressions, stubs, codegen."""

from __future__ import annotations

import pytest

from tuvl.contract.files import FileRef
from tuvl.contract.schema import HttpTrigger
from tuvl.contract.tel import compile_expr
from tuvl.contract.types import build_model, format_type, parse_type, registry_resolver
from tuvl.runtime.engines import stub_value

REF = {
    "store": "inbox",
    "key": "in/abc/a.pdf",
    "name": "a.pdf",
    "size": 3,
    "content_type": "application/pdf",
    "sha256": "0" * 64,
}


def test_file_parses_and_round_trips() -> None:
    for text in ("file", "file?", "list[file]", "list[file]?"):
        assert format_type(parse_type(text)) == text


def test_a_file_input_validates_a_reference_and_rejects_anything_else() -> None:
    model = build_model("In", {"doc": "file", "more": "list[file]?"})
    assert model.model_validate({"doc": REF}).doc == FileRef(**REF)  # type: ignore[attr-defined]
    for bad in ({"doc": "a.pdf"}, {"doc": {**REF, "extra": 1}}, {"doc": {"key": "k"}}):
        with pytest.raises(ValueError):
            model.model_validate(bad)


def test_expressions_can_read_a_files_fields() -> None:
    env = {"doc": "file"}
    compile_expr("doc.size > 0 and doc.content_type == 'application/pdf'").check(
        env, registry_resolver
    )
    with pytest.raises(ValueError, match="size"):
        compile_expr("doc.nope").check(env, registry_resolver)


def test_a_pending_agent_stubs_a_file() -> None:
    stub = stub_value(parse_type("file"), registry_resolver)
    assert FileRef.model_validate(stub)


def test_upload_needs_a_request_body() -> None:
    with pytest.raises(ValueError, match="needs a request body"):
        HttpTrigger(path="/a", method="GET", upload={"store": "s"})
