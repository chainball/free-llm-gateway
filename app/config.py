"""Configuration: YAML defaults + env-var API keys + runtime settings overrides."""
from __future__ import annotations

import os
import re
from dataclasses import dataclass, field, replace
from pathlib import Path
from typing import Any

import yaml

_ENV_RE = re.compile(r"\$\{([A-Z0-9_]+)\}")


@dataclass
class ProviderConfig:
    name: str
    base_url: str
    api_key: str = ""
    models: list[str] = field(default_factory=list)
    enabled: bool = True
    concurrency: int = 2
    rpm: int = 15
    tpm: int = 100_000
    max_retries: int = 3
    cooldown: float = 120.0
    weight: int = 1
    keys: list[str] = field(default_factory=list)  # multiple keys, round-robin

    @property
    def key_list(self) -> list[str]:
        if self.keys:
            return [k for k in self.keys if k]
        return [self.api_key] if self.api_key else []


# Built-in defaults so the gateway runs even without config.yaml.
# API keys must be provided via environment variables.
_DEFAULTS: dict[str, dict[str, Any]] = {
    "glm": {
        "base_url": "https://open.bigmodel.cn/api/paas/v4",
        "models": ["glm-4-flash"],
        "env": ["GLM_API_KEY"],
        "concurrency": 2,
        "rpm": 15,
        "tpm": 100_000,
        "weight": 1,
    },
    "siliconflow": {
        "base_url": "https://api.siliconflow.cn/v1",
        "models": ["Qwen/Qwen3-8B"],
        "env": ["SILICONFLOW_API_KEY"],
        "concurrency": 2,
        "rpm": 15,
        "tpm": 100_000,
        "weight": 1,
    },
    "baidu": {
        "base_url": "https://qianfan.baidubce.com/v2",
        "models": ["ernie-speed-128k"],
        "env": ["BAIDU_API_KEY"],
        "concurrency": 2,
        "rpm": 15,
        "tpm": 100_000,
        "weight": 1,
    },
}


def _resolve_env(value: str) -> str:
    def sub(m: re.Match) -> str:
        return os.environ.get(m.group(1), "")

    return _ENV_RE.sub(sub, value)


def _load_yaml(path: Path | None) -> dict[str, Any]:
    if path is None:
        path = Path(os.environ.get("GATEWAY_CONFIG", "config.yaml"))
    if not path.exists():
        return {}
    with path.open("r", encoding="utf-8") as f:
        data = yaml.safe_load(f) or {}
    return data or {}


def build_providers(config_path: Path | None = None) -> list[ProviderConfig]:
    """Merge YAML config over built-in defaults, resolving env keys."""
    data = _load_yaml(config_path)
    providers_raw: dict[str, dict[str, Any]] = data.get("providers", {})

    result: list[ProviderConfig] = []
    for name, default in _DEFAULTS.items():
        cfg = dict(default)
        override = providers_raw.get(name, {})
        cfg.update({k: v for k, v in override.items() if v is not None})

        env_vars = cfg.pop("env", [])
        keys = override.get("keys") or []
        api_key = override.get("api_key", "")

        # resolve keys: explicit keys list first, else env vars
        if keys:
            keys = [_resolve_env(k) if _ENV_RE.search(k) else k for k in keys]
            keys = [k for k in keys if k]
        elif api_key:
            api_key = _resolve_env(api_key)
        else:
            api_key = next((os.environ.get(e, "") for e in env_vars), "")

        enabled = cfg.get("enabled", True)
        if not keys and not api_key:
            # no key configured -> disable rather than crash
            enabled = False

        result.append(
            ProviderConfig(
                name=name,
                base_url=cfg["base_url"].rstrip("/"),
                api_key=api_key,
                models=cfg.get("models", []),
                enabled=bool(enabled),
                concurrency=int(cfg.get("concurrency", 2)),
                rpm=int(cfg.get("rpm", 15)),
                tpm=int(cfg.get("tpm", 100_000)),
                max_retries=int(cfg.get("max_retries", 3)),
                cooldown=float(cfg.get("cooldown", 120.0)),
                weight=int(cfg.get("weight", 1)),
                keys=keys,
            )
        )
    return result


def apply_settings_overrides(
    providers: list[ProviderConfig], settings: dict[str, str]
) -> list[ProviderConfig]:
    """Apply web-editable overrides (enable/rpm/tpm/concurrency) from settings store."""
    out: list[ProviderConfig] = []
    for p in providers:
        prefix = f"provider.{p.name}."
        if f"{prefix}enabled" in settings:
            p = replace(p, enabled=settings[f"{prefix}enabled"].lower() == "true")
        if f"{prefix}rpm" in settings:
            p = replace(p, rpm=int(settings[f"{prefix}rpm"]))
        if f"{prefix}tpm" in settings:
            p = replace(p, tpm=int(settings[f"{prefix}tpm"]))
        if f"{prefix}concurrency" in settings:
            p = replace(p, concurrency=int(settings[f"{prefix}concurrency"]))
        out.append(p)
    return out
