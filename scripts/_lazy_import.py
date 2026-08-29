"""Import a module from a downstream checkout only when it is first used.

#205. Five scripts did `sys.path.insert(0, <downstream root>/...)` followed by
a module-level import. That import runs before `main()` is entered, so
`--help` failed without the checkout -- and `--help` is how a reader discovers
which environment variable to set, which makes needing it circular (#179).

It was invisible before #198 only because the inserted path was a hardcoded
absolute one: the import worked on a single machine and failed everywhere else.

A proxy keeps every call site unchanged -- `chem_formula.parse_formula(...)`
still reads the same -- while moving the import to the first attribute access,
which is inside the work rather than at import time.
"""

from __future__ import annotations

import importlib
import sys
from pathlib import Path
from types import ModuleType
from typing import Callable, Iterable

__all__ = ["LazyModule"]


class LazyModule:
    """Stand in for `module`, importing it on first attribute access."""

    def __init__(
        self,
        name: str,
        search_paths: Callable[[], Iterable[Path]],
        *,
        hint: str = "",
    ) -> None:
        self._name = name
        self._search_paths = search_paths
        self._hint = hint
        self._module: ModuleType | None = None

    def _load(self) -> ModuleType:
        if self._module is None:
            for path in self._search_paths():
                entry = str(path)
                if entry not in sys.path:
                    sys.path.insert(0, entry)
            try:
                self._module = importlib.import_module(self._name)
            except ModuleNotFoundError as exc:
                # Only when *this* module is the one missing. A dependency
                # absent inside it is a different problem with a different
                # fix, and reporting it as "set the root variable" sends the
                # reader somewhere the answer is not.
                if exc.name not in (self._name, self._name.split(".")[0]):
                    raise
                raise SystemExit(
                    f"{self._name} could not be imported from "
                    f"{', '.join(str(p) for p in self._search_paths())}"
                    + (f"\n{self._hint}" if self._hint else "")
                ) from exc
        return self._module

    def __getattr__(self, attribute: str):
        if attribute.startswith("_"):
            raise AttributeError(attribute)
        return getattr(self._load(), attribute)

    def __repr__(self) -> str:  # pragma: no cover - debugging aid
        state = "loaded" if self._module is not None else "not yet imported"
        return f"<LazyModule {self._name} ({state})>"
