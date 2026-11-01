"""The ``file`` type: a reference to an object a trigger stored from an upload.

A workflow never sees the bytes, only this record, so nothing binary enters the
journal, the queue or a model prompt. Agents pass it on; ``tool: storage`` and
``ctx.read_file`` read it back.
"""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field


class FileRef(BaseModel):
    model_config = ConfigDict(extra="forbid")

    store: str = Field(description="The named store holding the object")
    key: str = Field(description="The object's key within the store")
    name: str = Field(description="The file name the client sent (display only)")
    size: int = Field(ge=0, description="Bytes")
    content_type: str = Field(description="The content type the client declared")
    sha256: str = Field(description="Hex digest of the content")
