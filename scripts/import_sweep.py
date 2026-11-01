"""Import every tuvl module: an install whose dependencies resolved to an incompatible version fails here."""

import importlib
import pkgutil
import sys

import tuvl
from tuvl.extras import MissingExtraError

failed = []
need_extra = []
for mod in pkgutil.walk_packages(tuvl.__path__, "tuvl."):
    try:
        importlib.import_module(mod.name)
    except MissingExtraError as exc:  # a bare install: the module's extra is not installed
        need_extra.append(f"{mod.name}: {exc.extra}")
    except Exception as exc:  # noqa: BLE001
        failed.append(f"{mod.name}: {type(exc).__name__}: {str(exc).splitlines()[0][:160]}")
total = sum(1 for _ in pkgutil.walk_packages(tuvl.__path__, "tuvl."))
print(f"imported {total - len(need_extra)} of {total} modules, {len(failed)} failed")
for line in need_extra:
    print("  needs an extra:", line)
for line in failed:
    print("  FAIL", line)
sys.exit(1 if failed else 0)
