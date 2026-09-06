"""
Settings router — read/write API keys from the project .env files.
Keys are masked on read; only send a value to update it.
"""
import os
from pathlib import Path
from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel
from tgbot_runtime import tgbot_env

router = APIRouter()

_TGBOT_ENV = tgbot_env()
_PROJECT_ENV = Path(__file__).resolve().parents[2] / ".env"


def _managed_env_paths() -> list[Path]:
    paths: list[Path] = []
    for path in (_TGBOT_ENV, _PROJECT_ENV):
        if path not in paths:
            paths.append(path)
    return paths

# API key names we expose in the settings UI
_MANAGED_KEYS = [
    "AI_PROVIDER",
    "ETHERSCAN_API_KEY",
    "ARKHAM_API_KEY",
    "CHAINALYSIS_API_KEY",
    "SCAMSEARCH_API_KEY",
    "BLOCKCYPHER_TOKEN",
    "THEGRAPH_API_KEY",
    "ETHPLORER_API_KEY",
    "UD_API_KEY",
    "DEEPSEEK_API_KEY",
    "DEEPSEEK_MODEL",
    "DEEPSEEK_BASE_URL",
    "OPENAI_API_KEY",
    "OPENAI_MODEL",
    "OPENAI_BASE_URL",
    "CODEX_API_KEY",
    "CODEX_MODEL",
    "CODEX_BASE_URL",
    "CLAUDE_API_KEY",
    "CLAUDE_MODEL",
    "CLAUDE_BASE_URL",
    "GEMINI_API_KEY",
    "GEMINI_MODEL",
    "GEMINI_BASE_URL",
    "QWEN_API_KEY",
    "QWEN_MODEL",
    "QWEN_BASE_URL",
    "KIMI_API_KEY",
    "KIMI_MODEL",
    "KIMI_BASE_URL",
    "MISTRAL_API_KEY",
    "MISTRAL_MODEL",
    "MISTRAL_BASE_URL",
    "ANTIGRAVITY_API_KEY",
    "ANTIGRAVITY_MODEL",
    "ANTIGRAVITY_BASE_URL",
    "MANUS_API_KEY",
    "MANUS_MODEL",
    "MANUS_BASE_URL",
    "MIMI_API_KEY",
    "MIMI_MODEL",
    "MIMI_BASE_URL",
    "CUSTOM_LLM_API_KEY",
    "CUSTOM_LLM_MODEL",
    "CUSTOM_LLM_BASE_URL",
    "BITCOINABUSE_API_TOKEN",
    "PASTEBIN_API_KEY",
    "PASTEBIN_USER_KEY",
    "DUNE_API_KEY",
    "DUNE_LABELS_QUERY_ID",
]


def _read_env_file(path: Path) -> dict[str, str]:
    env: dict[str, str] = {}
    if not path.exists():
        return env
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        k, v = line.split("=", 1)
        env[k.strip()] = v.strip().strip("\"'")
    return env


def _read_env() -> dict[str, str]:
    env: dict[str, str] = {}
    for path in reversed(_managed_env_paths()):
        env.update(_read_env_file(path))
    return env


def _write_env_file(path: Path, updates: dict[str, str]) -> None:
    original_lines: list[str] = []
    if path.exists():
        original_lines = path.read_text(encoding="utf-8").splitlines()

    # Build new file: keep non-managed lines, update managed ones
    result_lines: list[str] = []
    seen_keys: set[str] = set()
    for line in original_lines:
        stripped = line.strip()
        if stripped and not stripped.startswith("#") and "=" in stripped:
            k = stripped.split("=", 1)[0].strip()
            if k in _MANAGED_KEYS:
                if k in updates and updates[k]:
                    result_lines.append(f"{k}={updates[k]}")
                else:
                    result_lines.append(line)
                seen_keys.add(k)
            else:
                result_lines.append(line)
        else:
            result_lines.append(line)

    # Append any new managed keys that weren't in the file
    for k in _MANAGED_KEYS:
        if k not in seen_keys and k in updates and updates[k]:
            result_lines.append(f"{k}={updates[k]}")

    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("\n".join(result_lines) + "\n", encoding="utf-8")


def _write_env(updates: dict[str, str]) -> list[str]:
    written: list[str] = []
    for path in _managed_env_paths():
        _write_env_file(path, updates)
        written.append(str(path))
    return written


def _is_secret_key(key: str) -> bool:
    return key.endswith("_API_KEY") or key.endswith("_USER_KEY") or key.endswith("_TOKEN")


def _clear_osint_cache_if_needed(updated_keys: set[str]) -> None:
    if not {"PASTEBIN_API_KEY", "PASTEBIN_USER_KEY"} & updated_keys:
        return
    try:
        import osint_sweep_engine

        with osint_sweep_engine._conn() as con:
            con.execute("DELETE FROM osint_sweeps")
            con.commit()
    except Exception:
        pass


class SettingsPayload(BaseModel):
    AI_PROVIDER: str = ""
    ETHERSCAN_API_KEY: str = ""
    ARKHAM_API_KEY: str = ""
    CHAINALYSIS_API_KEY: str = ""
    SCAMSEARCH_API_KEY: str = ""
    BLOCKCYPHER_TOKEN: str = ""
    THEGRAPH_API_KEY: str = ""
    ETHPLORER_API_KEY: str = ""
    UD_API_KEY: str = ""
    DEEPSEEK_API_KEY: str = ""
    DEEPSEEK_MODEL: str = ""
    DEEPSEEK_BASE_URL: str = ""
    OPENAI_API_KEY: str = ""
    OPENAI_MODEL: str = ""
    OPENAI_BASE_URL: str = ""
    CODEX_API_KEY: str = ""
    CODEX_MODEL: str = ""
    CODEX_BASE_URL: str = ""
    CLAUDE_API_KEY: str = ""
    CLAUDE_MODEL: str = ""
    CLAUDE_BASE_URL: str = ""
    GEMINI_API_KEY: str = ""
    GEMINI_MODEL: str = ""
    GEMINI_BASE_URL: str = ""
    QWEN_API_KEY: str = ""
    QWEN_MODEL: str = ""
    QWEN_BASE_URL: str = ""
    KIMI_API_KEY: str = ""
    KIMI_MODEL: str = ""
    KIMI_BASE_URL: str = ""
    MISTRAL_API_KEY: str = ""
    MISTRAL_MODEL: str = ""
    MISTRAL_BASE_URL: str = ""
    ANTIGRAVITY_API_KEY: str = ""
    ANTIGRAVITY_MODEL: str = ""
    ANTIGRAVITY_BASE_URL: str = ""
    MANUS_API_KEY: str = ""
    MANUS_MODEL: str = ""
    MANUS_BASE_URL: str = ""
    MIMI_API_KEY: str = ""
    MIMI_MODEL: str = ""
    MIMI_BASE_URL: str = ""
    CUSTOM_LLM_API_KEY: str = ""
    CUSTOM_LLM_MODEL: str = ""
    CUSTOM_LLM_BASE_URL: str = ""
    BITCOINABUSE_API_TOKEN: str = ""
    PASTEBIN_API_KEY: str = ""
    PASTEBIN_USER_KEY: str = ""
    DUNE_API_KEY: str = ""
    DUNE_LABELS_QUERY_ID: str = ""


@router.get("/settings")
async def get_settings():
    env = _read_env()
    values = {
        k: ("SET" if _is_secret_key(k) and env.get(k) else env.get(k, ""))
        for k in _MANAGED_KEYS
    }
    values["_meta"] = {
        "runtime_env_path": str(_TGBOT_ENV),
        "project_env_path": str(_PROJECT_ENV),
        "written_env_paths": [str(path) for path in _managed_env_paths()],
    }
    return values


@router.post("/settings")
async def save_settings(payload: SettingsPayload, request: Request):
    # SECURITY: only admins can modify production configuration / API keys.
    # Any authenticated user could previously overwrite API keys (Etherscan,
    # AI providers, etc.) — a server-side configuration injection vector.
    user = getattr(request.state, "user", None) or {}
    if user.get("role") != "admin":
        raise HTTPException(status_code=403, detail="admin role required to modify settings")
    payload_data = payload.model_dump() if hasattr(payload, "model_dump") else payload.dict()
    updates = {k: str(v).strip() for k, v in payload_data.items() if v and v != "SET"}
    try:
        written_paths = _write_env(updates)
        os.environ.update(updates)
        _clear_osint_cache_if_needed(set(updates.keys()))
        return {"saved": True, "updated_keys": list(updates.keys()), "env_paths": written_paths}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/settings/provider-status")
async def provider_status():
    """I/O-discipline observability: per-provider request counts, failures,
    circuit-breaker state, rate budgets, and cache stats."""
    try:
        import http_cache
        return http_cache.provider_status()
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
