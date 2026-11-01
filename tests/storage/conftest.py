from __future__ import annotations

from pathlib import Path

import pytest

from tuvl.storage import Store, StoreSpec
from tuvl.storage.local import LocalBackend


@pytest.fixture
def local_store(tmp_path: Path) -> Store:
    spec = StoreSpec(provider="local", root=str(tmp_path / "root"), prefix="inv/")
    return Store("invoices", spec, LocalBackend(tmp_path / "root"))
