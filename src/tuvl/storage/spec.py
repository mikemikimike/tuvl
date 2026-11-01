"""``kind: Storage`` — a named store: where objects live and how to reach them."""

from __future__ import annotations

import re
from typing import Any, Literal
from urllib.parse import urlsplit

from pydantic import BaseModel, ConfigDict, Field, ValidationError, field_validator, model_validator

from tuvl.storage.errors import ConfigError

MAX_OBJECT_CEILING = 64 * 1024 * 1024
_REF = re.compile(r"^\$\{[A-Za-z_][A-Za-z0-9_]*(:[^}]*)?\}$")
_LOCAL_HOSTS = ("localhost", "127.0.0.1", "[::1]", "::1")
SECRET_FIELDS = (
    "access_key",
    "secret_key",
    "session_token",
    "account_key",
    "sas_token",
    "credentials",
    "access_token",
)


def check_endpoint(value: str) -> str:
    """*value* without a trailing slash; only https, or http to localhost, is accepted."""
    if not value:
        return value
    parts = urlsplit(value)
    host = (parts.hostname or "").lower()
    local = host in _LOCAL_HOSTS or host.endswith(".localhost")
    if parts.scheme == "https" or (parts.scheme == "http" and local):
        return value.rstrip("/")
    raise ValueError("endpoint must be https (http is allowed only for localhost)")


class StoreSpec(BaseModel):
    model_config = ConfigDict(extra="forbid")

    provider: Literal["s3", "azure", "gcs", "local"]
    prefix: str = ""
    readonly: bool = False
    max_object_bytes: int = Field(default=16 * 1024 * 1024, ge=1, le=MAX_OBJECT_CEILING)
    presign_max_seconds: int = Field(default=3600, ge=1, le=604_800)
    timeout: float = Field(default=30.0, gt=0, le=600)
    endpoint: str = ""
    # s3 (and gcs with HMAC keys)
    bucket: str = ""
    region: str = ""
    path_style: bool | None = None
    role_arn: str = ""
    # azure
    account: str = ""
    container: str = ""
    # gcs
    project: str = ""
    # secrets: ${ENV} references only
    access_key: str = ""
    secret_key: str = ""
    session_token: str = ""
    account_key: str = ""
    sas_token: str = ""
    credentials: str = ""
    access_token: str = ""
    # local
    root: str = "./data/storage"

    @field_validator(*SECRET_FIELDS)
    @classmethod
    def _secret_is_reference(cls, value: str, info: Any) -> str:
        if value and not _REF.match(value):
            raise ValueError(f"{info.field_name} must be an ${{ENV_VAR}} reference, not a literal")
        return value

    @field_validator("prefix")
    @classmethod
    def _prefix_shape(cls, value: str) -> str:
        if value and (value.startswith("/") or ".." in value.split("/") or "\\" in value):
            raise ValueError("prefix must be relative and must not contain '..'")
        return value

    @field_validator("endpoint")
    @classmethod
    def _endpoint_scheme(cls, value: str) -> str:
        return value if value.startswith("${") else check_endpoint(value)

    @model_validator(mode="after")
    def _provider_fields(self) -> StoreSpec:
        need = {"s3": ("bucket",), "gcs": ("bucket",), "azure": ("account", "container")}
        for name in need.get(self.provider, ()):
            if not getattr(self, name):
                raise ValueError(f"provider '{self.provider}' needs '{name}'")
        return self


def parse_store(data: dict[str, Any]) -> tuple[str, StoreSpec]:
    """The store name and spec of a ``kind: Storage`` document."""
    name = str((data.get("metadata") or {}).get("name") or "")
    if not name:
        raise ConfigError("Storage needs metadata.name")
    try:
        return name, StoreSpec.model_validate(data.get("spec") or {})
    except ValidationError as exc:
        problems = "; ".join(
            f"{'.'.join(str(p) for p in e['loc']) or 'spec'}: {e['msg']}" for e in exc.errors()
        )
        raise ConfigError(f"Storage '{name}': {problems}") from exc


STORE_REGISTRY: dict[str, StoreSpec] = {}


def register_store_from_dict(data: dict[str, Any], filename: str = "<unknown>") -> None:
    name, spec = parse_store(data)
    STORE_REGISTRY[name] = spec
