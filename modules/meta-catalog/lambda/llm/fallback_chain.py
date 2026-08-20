from __future__ import annotations
import os
import time
from typing import Any, Callable
from logging_utils import log_event
from .providers import gemini
from .providers.common import ProviderError

DEFAULT_ORDER = ("gemini",)
PROVIDERS: dict[str, Callable[[str, dict[str, Any], float, list[str] | None], dict[str, Any]]] = {
    "gemini": gemini.extract,
}

def _provider_config(name: str) -> dict[str, Any]:
    from aws_secrets import get_secret_json, get_secret_value
    env_name = "GEMINI_SECRET_ID" if name == "gemini" else f"{name.upper()}_SECRET_ID"
    raw = get_secret_value(env_name)
    if not raw:
        return {}
    try:
        import json
        return json.loads(raw)
    except Exception:
        return {"api_key": raw}

def extract_property(
    text: str,
    *,
    image_urls: list[str] | None = None,
    order: tuple[str, ...] | None = None,
    provider_configs: dict[str, dict[str, Any]] | None = None,
    providers: dict[str, Callable[[str, dict[str, Any], float, list[str] | None], dict[str, Any]]] | None = None,
) -> dict[str, Any]:
    selected = order or tuple(
        item.strip().lower()
        for item in os.environ.get("LLM_PROVIDER_ORDER", ",".join(DEFAULT_ORDER)).split(",")
        if item.strip()
    )
    provider_map = providers or PROVIDERS
    configs = provider_configs or {}
    attempt_timeout = float(os.environ.get("LLM_ATTEMPT_TIMEOUT_SECONDS", "15"))
    total_timeout = float(os.environ.get("LLM_TOTAL_TIMEOUT_SECONDS", "45"))
    started_total = time.monotonic()
    errors: list[str] = []

    for name in selected:
        if name not in provider_map:
            errors.append(f"{name}: unsupported provider")
            continue
        elapsed = time.monotonic() - started_total
        if elapsed >= total_timeout:
            break
        started = time.monotonic()
        try:
            config = configs.get(name) or _provider_config(name)
            result = provider_map[name](text, config, min(attempt_timeout, total_timeout - elapsed), image_urls)
            log_event("llm_attempt", provider=name, status="success", latency_ms=round((time.monotonic() - started) * 1000))
            return result
        except Exception as exc:
            errors.append(f"{name}: {exc}")
            log_event("llm_attempt", provider=name, status="failed", latency_ms=round((time.monotonic() - started) * 1000), error=str(exc))

    raise ProviderError("All LLM providers failed: " + " | ".join(errors))
