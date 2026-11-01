"""The incremental reader of one string field of a JSON object that is still arriving."""

from __future__ import annotations

import json
import random
from typing import Any

import pytest

from tuvl.runtime.jsonstream import JsonFieldStream


def read(text: str, field: str, sizes: list[int] | None = None) -> str:
    """The characters streamed for *field*, feeding *text* in chunks of the given sizes."""
    stream = JsonFieldStream(field)
    out, i = [], 0
    sizes = sizes or [len(text)]
    k = 0
    while i < len(text):
        n = max(1, sizes[k % len(sizes)])
        out.append(stream.feed(text[i : i + n]))
        i += n
        k += 1
    return "".join(out)


TRICKY = [
    "plain",
    "",
    'quote " inside',
    "back\\slash and \\n literal",
    "line1\nline2\ttab\r",
    "unicode é ü 日本語",
    "emoji 😀 and 𝄞",
    "slash / and   separator",
    "}{][,:",
    '"nested-looking": {"draft": "no"}',
]


@pytest.mark.parametrize("value", TRICKY)
@pytest.mark.parametrize("ensure_ascii", [True, False])
def test_every_way_of_splitting_the_text_gives_the_same_field(
    value: str, ensure_ascii: bool
) -> None:
    doc = {"title": "t", "draft": value, "tail": [1, 2, {"draft": "deep"}], "n": None}
    text = json.dumps(doc, ensure_ascii=ensure_ascii, indent=2)
    for size in (1, 2, 3, 5, 7, 64, len(text)):
        assert read(text, "draft", [size]) == value, size
    rng = random.Random(7)
    for _ in range(40):
        sizes = [rng.randint(1, 9) for _ in range(rng.randint(1, 6))]
        assert read(text, "draft", sizes) == value


def test_random_documents_match_json_loads() -> None:
    rng = random.Random(11)
    alphabet = ["a", "Z", " ", '"', "\\", "\n", "é", "😀", "{", "}", "[", "]", ",", ":", "\u0001"]

    def value(depth: int = 0) -> Any:
        kind = rng.choice(["s", "s", "n", "b", "z", "l", "o"] if depth < 3 else ["s", "n"])
        if kind == "s":
            return "".join(rng.choice(alphabet) for _ in range(rng.randint(0, 12)))
        if kind == "n":
            return rng.choice([0, -3, 4.5, 1e10])
        if kind == "b":
            return rng.choice([True, False])
        if kind == "z":
            return None
        if kind == "l":
            return [value(depth + 1) for _ in range(rng.randint(0, 3))]
        return {rng.choice(["draft", "x", "y"]): value(depth + 1) for _ in range(rng.randint(0, 3))}

    for _ in range(300):
        doc = {
            "a": value(),
            "draft": "".join(rng.choice(alphabet) for _ in range(rng.randint(0, 30))),
            "b": value(),
        }
        keys = list(doc)
        rng.shuffle(keys)
        text = json.dumps({k: doc[k] for k in keys}, ensure_ascii=rng.random() < 0.5)
        sizes = [rng.randint(1, 11) for _ in range(3)]
        assert read(text, "draft", sizes) == doc["draft"]


def test_text_arrives_as_it_is_written_not_at_the_end() -> None:
    stream = JsonFieldStream("draft")
    assert stream.feed('{"other": 1, "dra') == ""
    assert stream.feed('ft": "Hel') == "Hel"
    assert stream.feed("lo, wor") == "lo, wor"
    assert stream.feed('ld", "x": "y"}') == "ld"
    assert stream.done


def test_a_split_escape_or_surrogate_pair_is_completed_before_it_is_emitted() -> None:
    stream = JsonFieldStream("d")
    got = [stream.feed(c) for c in '{"d": "a\\u00e9\\ud83d\\ude00\\n"}']
    assert "".join(got) == "aé😀\n"
    assert "\\" not in "".join(got) and "u00" not in "".join(got)


def test_only_a_top_level_string_field_is_read() -> None:
    assert read('{"draft": 42, "x": "y"}', "draft") == ""
    assert read('{"draft": null}', "draft") == ""
    assert read('{"draft": ["a"], "x": "y"}', "draft") == ""
    assert read('{"draft": {"draft": "inner"}}', "draft") == ""
    assert read('{"x": {"draft": "inner"}, "draft": "outer"}', "draft") == "outer"
    assert read('{"other": "x"}', "draft") == ""


def test_the_first_occurrence_of_a_repeated_key_wins() -> None:
    assert read('{"draft": "one", "draft": "two"}', "draft", [3]) == "one"


def test_a_markdown_fence_or_preamble_before_the_object_is_ignored() -> None:
    assert read('```json\n{"draft": "hi"}\n```', "draft", [2]) == "hi"
    assert read('Sure! Here it is: {"draft": "hi"}', "draft", [1]) == "hi"


def test_nothing_after_the_object_is_read() -> None:
    stream = JsonFieldStream("draft")
    assert stream.feed('{"draft": "a"} {"draft": "b"}') == "a"


def test_keys_with_escapes_match() -> None:
    assert read('{"dr\\u0061ft": "ok"}', "draft", [1]) == "ok"


def test_a_truncated_document_returns_what_it_had() -> None:
    assert read('{"draft": "half of a sent', "draft", [4]) == "half of a sent"
