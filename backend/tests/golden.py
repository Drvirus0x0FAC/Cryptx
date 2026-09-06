"""Tiny golden-file helper. Set REGOLD=1 to (re)write goldens instead of asserting."""
from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any

GOLDEN_DIR = Path(__file__).parent / "goldens"


def check_golden(name: str, value: Any) -> None:
    """Compare `value` against the stored golden JSON; regenerate with REGOLD=1."""
    GOLDEN_DIR.mkdir(exist_ok=True)
    path = GOLDEN_DIR / f"{name}.json"
    normalized = json.loads(json.dumps(value, sort_keys=True, default=str))
    if os.environ.get("REGOLD") == "1" or not path.exists():
        path.write_text(json.dumps(normalized, indent=2, sort_keys=True))
        if os.environ.get("REGOLD") == "1":
            return
    stored = json.loads(path.read_text())
    assert normalized == stored, (
        f"Golden mismatch for '{name}'. If the change is intentional, re-run with REGOLD=1 "
        f"and review the diff of tests/goldens/{name}.json"
    )
