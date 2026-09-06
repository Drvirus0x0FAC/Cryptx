from __future__ import annotations

import sys
from pathlib import Path


def tgbot_dir() -> Path:
    backend_dir = Path(__file__).resolve().parent
    project_root = backend_dir.parent
    candidates = [
        project_root / "python-modules",
        project_root.parent / "python-modules",
        project_root / "TGBot",
        project_root.parent / "TGBot",
    ]
    for candidate in candidates:
        if candidate.is_dir():
            return candidate
    return candidates[0]


def tgbot_env() -> Path:
    return tgbot_dir() / ".env"


def ensure_tgbot_path() -> Path:
    path = tgbot_dir()
    path_str = str(path)
    if path.is_dir() and path_str not in sys.path:
        sys.path.insert(0, path_str)
    return path
