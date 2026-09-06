"""
Provider-neutral AI client for evidence-grounded investigation assistance.

The historical deepseek_* functions remain as compatibility wrappers for the
existing investigation modules. They now route to the selected provider.
"""
from __future__ import annotations

import json
import os
import re
from dataclasses import dataclass
from typing import Any, Dict, List, Optional

import aiohttp
from tgbot_runtime import tgbot_env

_TGBOT_ENV = tgbot_env()
HTTP_TIMEOUT = 60


@dataclass(frozen=True)
class ProviderConfig:
    id: str
    name: str
    kind: str
    key_env: str
    model_env: str
    default_model: str
    base_env: str = ""
    default_base_url: str = ""
    aliases: Optional[Dict[str, str]] = None
    notes: str = ""


PROVIDERS: Dict[str, ProviderConfig] = {
    "deepseek": ProviderConfig(
        id="deepseek",
        name="DeepSeek",
        kind="openai",
        key_env="DEEPSEEK_API_KEY",
        model_env="DEEPSEEK_MODEL",
        base_env="DEEPSEEK_BASE_URL",
        default_base_url="https://api.deepseek.com",
        default_model="deepseek-v4-pro",
        aliases={"deepseek-v3": "deepseek-chat", "deepseek-r1": "deepseek-reasoner"},
    ),
    "openai": ProviderConfig(
        id="openai",
        name="OpenAI",
        kind="openai",
        key_env="OPENAI_API_KEY",
        model_env="OPENAI_MODEL",
        base_env="OPENAI_BASE_URL",
        default_base_url="https://api.openai.com/v1",
        default_model="gpt-4o-mini",
    ),
    "codex": ProviderConfig(
        id="codex",
        name="Codex / OpenAI",
        kind="openai",
        key_env="CODEX_API_KEY",
        model_env="CODEX_MODEL",
        base_env="CODEX_BASE_URL",
        default_base_url="https://api.openai.com/v1",
        default_model="gpt-4o-mini",
        notes="Use an OpenAI-compatible API key/model for Codex-style investigation synthesis.",
    ),
    "claude": ProviderConfig(
        id="claude",
        name="Claude",
        kind="anthropic",
        key_env="CLAUDE_API_KEY",
        model_env="CLAUDE_MODEL",
        base_env="CLAUDE_BASE_URL",
        default_base_url="https://api.anthropic.com",
        default_model="claude-sonnet-4-5",
    ),
    "gemini": ProviderConfig(
        id="gemini",
        name="Gemini",
        kind="gemini",
        key_env="GEMINI_API_KEY",
        model_env="GEMINI_MODEL",
        base_env="GEMINI_BASE_URL",
        default_base_url="https://generativelanguage.googleapis.com/v1beta",
        default_model="gemini-2.5-pro",
    ),
    "qwen": ProviderConfig(
        id="qwen",
        name="Qwen",
        kind="openai",
        key_env="QWEN_API_KEY",
        model_env="QWEN_MODEL",
        base_env="QWEN_BASE_URL",
        default_base_url="https://dashscope-intl.aliyuncs.com/compatible-mode/v1",
        default_model="qwen-plus",
    ),
    "kimi": ProviderConfig(
        id="kimi",
        name="Kimi",
        kind="openai",
        key_env="KIMI_API_KEY",
        model_env="KIMI_MODEL",
        base_env="KIMI_BASE_URL",
        default_base_url="https://api.moonshot.ai/v1",
        default_model="kimi-k2",
    ),
    "mistral": ProviderConfig(
        id="mistral",
        name="Mistral",
        kind="openai",
        key_env="MISTRAL_API_KEY",
        model_env="MISTRAL_MODEL",
        base_env="MISTRAL_BASE_URL",
        default_base_url="https://api.mistral.ai/v1",
        default_model="mistral-large-latest",
    ),
    "antigravity": ProviderConfig(
        id="antigravity",
        name="Antigravity",
        kind="openai",
        key_env="ANTIGRAVITY_API_KEY",
        model_env="ANTIGRAVITY_MODEL",
        base_env="ANTIGRAVITY_BASE_URL",
        default_base_url="",
        default_model="",
        notes="Configure this as an OpenAI-compatible connector if your Antigravity runtime exposes an API.",
    ),
    "manus": ProviderConfig(
        id="manus",
        name="Manus",
        kind="openai",
        key_env="MANUS_API_KEY",
        model_env="MANUS_MODEL",
        base_env="MANUS_BASE_URL",
        default_base_url="",
        default_model="",
        notes="Configure this as an OpenAI-compatible connector when your Manus API gateway is available.",
    ),
    "mimi": ProviderConfig(
        id="mimi",
        name="Mimi",
        kind="openai",
        key_env="MIMI_API_KEY",
        model_env="MIMI_MODEL",
        base_env="MIMI_BASE_URL",
        default_base_url="",
        default_model="",
        notes="Configure this as an OpenAI-compatible connector when your Mimi API gateway is available.",
    ),
    "custom": ProviderConfig(
        id="custom",
        name="Custom OpenAI-compatible",
        kind="openai",
        key_env="CUSTOM_LLM_API_KEY",
        model_env="CUSTOM_LLM_MODEL",
        base_env="CUSTOM_LLM_BASE_URL",
        default_base_url="",
        default_model="",
    ),
}

PROVIDER_ALIASES = {
    "anthropic": "claude",
    "google": "gemini",
    "moonshot": "kimi",
    "openai-compatible": "custom",
}


class AIConfigError(RuntimeError):
    pass


class AIProviderError(RuntimeError):
    pass


def _read_saved_env() -> Dict[str, str]:
    if not _TGBOT_ENV.exists():
        return {}
    env: Dict[str, str] = {}
    for line in _TGBOT_ENV.read_text(encoding="utf-8").splitlines():
        stripped = line.strip()
        if not stripped or stripped.startswith("#") or "=" not in stripped:
            continue
        key, value = stripped.split("=", 1)
        env[key.strip()] = value.strip().strip("\"'")
    return env


def _env(key: str, default: str = "") -> str:
    return os.environ.get(key) or _read_saved_env().get(key) or default


def _provider_id(provider: Optional[str] = None) -> str:
    selected = (provider or _env("AI_PROVIDER") or "deepseek").strip().lower()
    selected = PROVIDER_ALIASES.get(selected, selected)
    return selected if selected in PROVIDERS else "deepseek"


def _provider(provider: Optional[str] = None) -> ProviderConfig:
    return PROVIDERS[_provider_id(provider)]


def _selected_model(cfg: ProviderConfig, model: Optional[str] = None) -> str:
    selected = (model or _env(cfg.model_env) or cfg.default_model).strip()
    if cfg.aliases:
        return cfg.aliases.get(selected, selected)
    return selected


def _selected_base_url(cfg: ProviderConfig) -> str:
    return (_env(cfg.base_env) if cfg.base_env else "") or cfg.default_base_url


def _chat_endpoint(base_url: str) -> str:
    base = base_url.rstrip("/")
    if base.endswith("/chat/completions"):
        return base
    return f"{base}/chat/completions"


def _extract_json(content: str) -> Any:
    text = (content or "").strip()
    if not text:
        return None
    fenced = re.search(r"```(?:json)?\s*(\{.*?\}|\[.*?\])\s*```", text, flags=re.DOTALL | re.IGNORECASE)
    if fenced:
        text = fenced.group(1).strip()
    else:
        obj_start = text.find("{")
        obj_end = text.rfind("}")
        arr_start = text.find("[")
        arr_end = text.rfind("]")
        if obj_start >= 0 and obj_end > obj_start:
            text = text[obj_start:obj_end + 1]
        elif arr_start >= 0 and arr_end > arr_start:
            text = text[arr_start:arr_end + 1]
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        return None


def ai_configured(provider: Optional[str] = None) -> bool:
    cfg = _provider(provider)
    return bool(_env(cfg.key_env)) and bool(_selected_model(cfg)) and bool(_selected_base_url(cfg))


def ai_settings(provider: Optional[str] = None) -> Dict[str, Any]:
    cfg = _provider(provider)
    api_key = _env(cfg.key_env)
    model = _selected_model(cfg)
    base_url = _selected_base_url(cfg)
    return {
        "provider": cfg.id,
        "provider_name": cfg.name,
        "kind": cfg.kind,
        "configured": bool(api_key and model and base_url),
        "model": model,
        "base_url": base_url,
        "api_key_env": cfg.key_env,
        "model_env": cfg.model_env,
        "base_url_env": cfg.base_env,
        "env_path": str(_TGBOT_ENV),
        "env_exists": _TGBOT_ENV.exists(),
        "key_length": len(api_key) if api_key else 0,
        "notes": cfg.notes,
        "providers": [
            {
                "id": item.id,
                "name": item.name,
                "kind": item.kind,
                "key_env": item.key_env,
                "model_env": item.model_env,
                "base_url_env": item.base_env,
                "default_model": item.default_model,
                "default_base_url": item.default_base_url,
                "notes": item.notes,
            }
            for item in PROVIDERS.values()
        ],
    }


def _ensure_configured(cfg: ProviderConfig, model: Optional[str] = None) -> tuple[str, str, str]:
    api_key = _env(cfg.key_env)
    selected_model = _selected_model(cfg, model)
    base_url = _selected_base_url(cfg)
    missing = []
    if not api_key:
        missing.append(cfg.key_env)
    if not selected_model:
        missing.append(cfg.model_env)
    if not base_url:
        missing.append(cfg.base_env or "base_url")
    if missing:
        raise AIConfigError(
            f"{cfg.name} is not configured. Add {', '.join(missing)} in Settings."
        )
    return api_key, selected_model, base_url


async def _post_json(url: str, headers: Dict[str, str], payload: Dict[str, Any], cfg: ProviderConfig, model: str) -> Dict[str, Any]:
    timeout = aiohttp.ClientTimeout(total=HTTP_TIMEOUT)
    async with aiohttp.ClientSession(timeout=timeout) as session:
        async with session.post(url, headers=headers, json=payload) as resp:
            try:
                data = await resp.json(content_type=None)
            except Exception:
                data = {"raw": await resp.text()}
            if resp.status >= 400:
                detail = data.get("error", data) if isinstance(data, dict) else data
                raise AIProviderError(
                    f"{cfg.name} API error {resp.status} using model {model} from {_TGBOT_ENV}: {detail}"
                )
            return data


async def _openai_chat(
    cfg: ProviderConfig,
    messages: List[Dict[str, str]],
    *,
    model: Optional[str],
    response_json: bool,
    max_tokens: int,
    temperature: float,
) -> Dict[str, Any]:
    api_key, selected_model, base_url = _ensure_configured(cfg, model)
    payload: Dict[str, Any] = {
        "model": selected_model,
        "messages": messages,
        "stream": False,
        "max_tokens": max_tokens,
        "temperature": temperature,
    }
    if response_json:
        payload["response_format"] = {"type": "json_object"}

    data = await _post_json(
        _chat_endpoint(base_url),
        {
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json",
        },
        payload,
        cfg,
        selected_model,
    )
    choice = (data.get("choices") or [{}])[0]
    message = choice.get("message") or {}
    content = message.get("content") or ""
    return {
        "provider": cfg.id,
        "model": data.get("model", selected_model),
        "content": content,
        "reasoning_content": message.get("reasoning_content") or "",
        "json": _extract_json(content) if response_json else None,
        "usage": data.get("usage", {}),
        "finish_reason": choice.get("finish_reason"),
    }


def _anthropic_messages(messages: List[Dict[str, str]]) -> tuple[str, List[Dict[str, str]]]:
    system_parts: List[str] = []
    converted: List[Dict[str, str]] = []
    for msg in messages:
        role = (msg.get("role") or "user").lower()
        content = msg.get("content") or ""
        if role in {"system", "developer"}:
            system_parts.append(content)
        elif role == "assistant":
            converted.append({"role": "assistant", "content": content})
        else:
            converted.append({"role": "user", "content": content})
    if not converted:
        converted.append({"role": "user", "content": "Continue."})
    return "\n\n".join(part for part in system_parts if part), converted


async def _anthropic_chat(
    cfg: ProviderConfig,
    messages: List[Dict[str, str]],
    *,
    model: Optional[str],
    response_json: bool,
    max_tokens: int,
    temperature: float,
) -> Dict[str, Any]:
    api_key, selected_model, base_url = _ensure_configured(cfg, model)
    system, converted = _anthropic_messages(messages)
    payload: Dict[str, Any] = {
        "model": selected_model,
        "messages": converted,
        "max_tokens": max_tokens,
        "temperature": temperature,
    }
    if system:
        payload["system"] = system
    if response_json:
        payload["messages"][-1]["content"] += "\n\nReturn valid JSON only."

    anthropic_base = base_url.rstrip("/")
    anthropic_endpoint = f"{anthropic_base}/messages" if anthropic_base.endswith("/v1") else f"{anthropic_base}/v1/messages"
    data = await _post_json(
        anthropic_endpoint,
        {
            "x-api-key": api_key,
            "anthropic-version": "2023-06-01",
            "Content-Type": "application/json",
        },
        payload,
        cfg,
        selected_model,
    )
    content_parts = data.get("content") or []
    content = "".join(part.get("text", "") for part in content_parts if isinstance(part, dict))
    return {
        "provider": cfg.id,
        "model": data.get("model", selected_model),
        "content": content,
        "reasoning_content": "",
        "json": _extract_json(content) if response_json else None,
        "usage": data.get("usage", {}),
        "finish_reason": data.get("stop_reason"),
    }


def _gemini_contents(messages: List[Dict[str, str]]) -> List[Dict[str, Any]]:
    system_parts: List[str] = []
    contents: List[Dict[str, Any]] = []
    for msg in messages:
        role = (msg.get("role") or "user").lower()
        content = msg.get("content") or ""
        if role in {"system", "developer"}:
            system_parts.append(content)
            continue
        contents.append({
            "role": "model" if role == "assistant" else "user",
            "parts": [{"text": content}],
        })
    if system_parts:
        prefix = "\n\n".join(system_parts)
        if contents and contents[0]["role"] == "user":
            contents[0]["parts"][0]["text"] = f"{prefix}\n\n{contents[0]['parts'][0]['text']}"
        else:
            contents.insert(0, {"role": "user", "parts": [{"text": prefix}]})
    if not contents:
        contents.append({"role": "user", "parts": [{"text": "Continue."}]})
    return contents


async def _gemini_chat(
    cfg: ProviderConfig,
    messages: List[Dict[str, str]],
    *,
    model: Optional[str],
    response_json: bool,
    max_tokens: int,
    temperature: float,
) -> Dict[str, Any]:
    api_key, selected_model, base_url = _ensure_configured(cfg, model)
    payload: Dict[str, Any] = {
        "contents": _gemini_contents(messages),
        "generationConfig": {
            "maxOutputTokens": max_tokens,
            "temperature": temperature,
        },
    }
    if response_json:
        payload["generationConfig"]["responseMimeType"] = "application/json"
    # SECURITY fix: send the API key in the x-goog-api-key header instead of the
    # URL query string (?key=...). Query-string keys leak into server/proxy access
    # logs and browser history. Gemini supports both; the header is the safe form.
    url = f"{base_url.rstrip('/')}/models/{selected_model}:generateContent"
    data = await _post_json(url, {"Content-Type": "application/json", "x-goog-api-key": api_key},
                            payload, cfg, selected_model)
    candidate = (data.get("candidates") or [{}])[0]
    parts = ((candidate.get("content") or {}).get("parts") or [])
    content = "".join(part.get("text", "") for part in parts if isinstance(part, dict))
    return {
        "provider": cfg.id,
        "model": selected_model,
        "content": content,
        "reasoning_content": "",
        "json": _extract_json(content) if response_json else None,
        "usage": data.get("usageMetadata", {}),
        "finish_reason": candidate.get("finishReason"),
    }


async def ai_chat(
    messages: List[Dict[str, str]],
    *,
    provider: Optional[str] = None,
    model: Optional[str] = None,
    response_json: bool = False,
    max_tokens: int = 1800,
    temperature: float = 0.2,
) -> Dict[str, Any]:
    cfg = _provider(provider)
    if cfg.kind == "anthropic":
        return await _anthropic_chat(
            cfg,
            messages,
            model=model,
            response_json=response_json,
            max_tokens=max_tokens,
            temperature=temperature,
        )
    if cfg.kind == "gemini":
        return await _gemini_chat(
            cfg,
            messages,
            model=model,
            response_json=response_json,
            max_tokens=max_tokens,
            temperature=temperature,
        )
    return await _openai_chat(
        cfg,
        messages,
        model=model,
        response_json=response_json,
        max_tokens=max_tokens,
        temperature=temperature,
    )


async def ai_probe(provider: Optional[str] = None) -> Dict[str, Any]:
    settings = ai_settings(provider)
    result = await ai_chat(
        [
            {
                "role": "system",
                "content": "Return only a compact JSON health object.",
            },
            {
                "role": "user",
                "content": 'Return {"ok": true, "capability": "crypto_investigation_synthesis"}.',
            },
        ],
        provider=provider,
        response_json=True,
        max_tokens=120,
        temperature=0,
    )
    return {
        **settings,
        "ok": True,
        "model": result.get("model") or settings["model"],
        "usage": result.get("usage", {}),
        "sample": result.get("json") or result.get("content", "")[:180],
    }


def deepseek_configured() -> bool:
    return ai_configured()


def deepseek_settings() -> Dict[str, Any]:
    return ai_settings()


async def deepseek_chat(
    messages: List[Dict[str, str]],
    *,
    model: Optional[str] = None,
    response_json: bool = False,
    max_tokens: int = 1800,
    temperature: float = 0.2,
) -> Dict[str, Any]:
    return await ai_chat(
        messages,
        model=model,
        response_json=response_json,
        max_tokens=max_tokens,
        temperature=temperature,
    )


async def deepseek_probe() -> Dict[str, Any]:
    return await ai_probe()


def compact_evidence(obj: Any, max_chars: int = 18000) -> str:
    text = json.dumps(obj, ensure_ascii=False, default=str, indent=2)
    if len(text) <= max_chars:
        return text
    return text[:max_chars] + "\n...TRUNCATED..."
