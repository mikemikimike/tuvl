"""Pull one string field out of a JSON object while the object is still arriving.

A structured ``llm`` answer is a JSON object. To show a draft, the text of one top-level string field
is decoded character by character as chunks arrive: ``feed`` returns what is new since the last call.
The final answer is validated from the complete text as usual; this reader only has to be right about
the characters it returns, and silent about everything else (other keys, nested values, a field that
is not a string, text before the object such as a Markdown fence).
"""

from __future__ import annotations

import contextlib

_ESCAPES = {'"': '"', "\\": "\\", "/": "/", "b": "\b", "f": "\f", "n": "\n", "r": "\r", "t": "\t"}

# states
_FIND_OBJECT, _KEY_OR_END, _KEY, _COLON, _VALUE, _AFTER_VALUE = range(6)
_TARGET, _SKIP_STRING, _SKIP_NESTED, _SKIP_BARE = range(4)


class JsonFieldStream:
    """``JsonFieldStream("draft").feed(chunk)`` returns the new characters of ``draft``'s string value."""

    def __init__(self, field: str) -> None:
        self.field = field
        self.done = False
        self._got = False  # only the first occurrence of the key is read
        self._state = _FIND_OBJECT
        self._key: list[str] = []
        self._value_mode = _SKIP_BARE
        self._depth = 0
        self._in_string = False
        self._escape = False
        self._unicode = ""  # hex digits of a \uXXXX being read
        self._high: str | None = None  # a high surrogate waiting for its pair
        self._in_key_escape = False
        self._key_hex = ""

    def feed(self, chunk: str) -> str:
        out: list[str] = []
        for ch in chunk:
            if self.done:
                break
            self._step(ch, out)
        return "".join(out)

    # ── one character ────────────────────────────────────────────────────────
    def _step(self, ch: str, out: list[str]) -> None:
        state = self._state
        if state == _FIND_OBJECT:
            if ch == "{":
                self._state = _KEY_OR_END
        elif state == _KEY_OR_END:
            if ch == '"':
                self._key, self._in_key_escape, self._state = [], False, _KEY
            elif ch == "}":
                self.done = True
        elif state == _KEY:
            self._key_char(ch)
        elif state == _COLON:
            if ch == ":":
                self._state = _VALUE
        elif state == _VALUE:
            self._begin_value(ch)
        elif state == _AFTER_VALUE:
            if ch == ",":
                self._state = _KEY_OR_END
            elif ch == "}":
                self.done = True
        else:  # inside a value
            self._value_char(ch, out)

    def _key_char(self, ch: str) -> None:
        if self._key_hex:
            self._key_hex += ch
            if len(self._key_hex) == 5:
                with contextlib.suppress(ValueError):
                    self._key.append(chr(int(self._key_hex[1:], 16)))
                self._key_hex = ""
        elif self._in_key_escape:
            self._in_key_escape = False
            if ch == "u":
                self._key_hex = "u"
            else:
                self._key.append(_ESCAPES.get(ch, ch))
        elif ch == "\\":
            self._in_key_escape = True
        elif ch == '"':
            self._state = _COLON
        else:
            self._key.append(ch)

    def _begin_value(self, ch: str) -> None:
        if ch in " \t\r\n":
            return
        wanted = "".join(self._key) == self.field and not self.done and not self._got
        self._depth, self._in_string, self._escape = 0, False, False
        if ch == '"':
            self._in_string = True
            self._value_mode = _TARGET if wanted else _SKIP_STRING
            self._unicode, self._high = "", None
            self._got = self._got or wanted
        elif ch in "{[":
            self._value_mode, self._depth = _SKIP_NESTED, 1
        else:
            self._value_mode = _SKIP_BARE
            if ch in ",}":  # an empty bare value; treat as the end
                self._end_value(ch)
                return
        self._state = 99  # any state outside the named ones means "inside a value"

    def _end_value(self, ch: str = "") -> None:
        self._state = _AFTER_VALUE
        if ch == ",":
            self._state = _KEY_OR_END
        elif ch == "}":
            self.done = True

    def _value_char(self, ch: str, out: list[str]) -> None:
        mode = self._value_mode
        if mode == _TARGET:
            self._target_char(ch, out)
        elif mode == _SKIP_STRING:
            if self._escape:
                self._escape = False
            elif ch == "\\":
                self._escape = True
            elif ch == '"':
                self._end_value()
        elif mode == _SKIP_NESTED:
            self._nested_char(ch)
        elif ch in ",}":  # a number, true, false or null ends at the next delimiter
            self._end_value(ch)

    def _nested_char(self, ch: str) -> None:
        if self._in_string:
            if self._escape:
                self._escape = False
            elif ch == "\\":
                self._escape = True
            elif ch == '"':
                self._in_string = False
        elif ch == '"':
            self._in_string = True
        elif ch in "{[":
            self._depth += 1
        elif ch in "}]":
            self._depth -= 1
            if self._depth == 0:
                self._end_value()

    def _target_char(self, ch: str, out: list[str]) -> None:
        if self._unicode:
            self._unicode += ch
            if len(self._unicode) == 5:  # the leading "u" plus four hex digits
                self._emit_code(int(self._unicode[1:], 16), out)
                self._unicode = ""
            return
        if self._escape:
            self._escape = False
            if ch == "u":
                self._unicode = "u"
            else:
                self._flush_high(out)
                out.append(_ESCAPES.get(ch, ch))
            return
        if ch == "\\":
            self._escape = True
        elif ch == '"':
            self._flush_high(out)
            self._end_value()
        else:
            self._flush_high(out)
            out.append(ch)

    def _emit_code(self, code: int, out: list[str]) -> None:
        if 0xD800 <= code < 0xDC00:
            self._flush_high(out)
            self._high = chr(code)
        elif 0xDC00 <= code < 0xE000 and self._high is not None:
            pair = (self._high + chr(code)).encode("utf-16", "surrogatepass").decode("utf-16")
            self._high = None
            out.append(pair)
        else:
            self._flush_high(out)
            out.append(chr(code))

    def _flush_high(self, out: list[str]) -> None:
        # a lone high surrogate cannot be shown; drop it rather than emit invalid text
        self._high = None
