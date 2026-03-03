from __future__ import annotations

import json
import os
import re
from pathlib import Path
from typing import Any


ENV_SENTINEL = "ENV"


_TRUE = {"1", "true", "yes", "y", "on"}
_FALSE = {"0", "false", "no", "n", "off"}


def _parse_env_value(raw: str) -> Any:
    s = raw.strip()
    if not s:
        return ""

    low = s.lower()
    if low in _TRUE:
        return True
    if low in _FALSE:
        return False

    # Allow JSON literals in env (lists/objects/quoted strings).
    if s[0] in "{[\"" and (s[-1] in "}]" or (s[0] == '"' and s[-1] == '"')):
        try:
            return json.loads(s)
        except Exception:
            pass

    # int/float
    if re.fullmatch(r"-?\d+", s):
        try:
            return int(s)
        except Exception:
            return s
    if re.fullmatch(r"-?\d+\.\d+", s):
        try:
            return float(s)
        except Exception:
            return s

    return s


def _set_path(cfg: dict, path: list[str], value: Any) -> None:
    cur: dict = cfg
    for k in path[:-1]:
        if k not in cur or not isinstance(cur.get(k), dict):
            cur[k] = {}
        cur = cur[k]
    cur[path[-1]] = value


def _load_defaults() -> dict:
    # Keep a non-secret default config in-repo; user-specific config.json becomes optional.
    p = Path("config.example.json")
    if p.exists():
        return json.loads(p.read_text(encoding="utf-8"))
    return {}


def load_config(config_arg: str | None) -> dict:
    """Load config from (1) file if provided, otherwise (2) defaults, then apply env overrides.

    - If config_arg is ENV (case-insensitive) or missing/non-existent, we do not require any config file.
    - Env overrides support:
      - Top-level keys: e.g. TTS_PROVIDER=elevenlabs, VOICE=...
      - Nested keys: e.g. YOUTUBE__PRIVACY_STATUS=private
      - Prefixed nested keys: SA__YOUTUBE__PRIVACY_STATUS=private
      - Convenience secrets: OPENAI_API_KEY, PEXELS_API_KEY, ELEVENLABS_API_KEY, ELEVENLABS_VOICE_ID, ELEVENLABS_MODEL_ID
    """
    cfg: dict
    if config_arg and config_arg.strip() and config_arg.strip().upper() != ENV_SENTINEL:
        p = Path(config_arg)
        if p.exists():
            cfg = json.loads(p.read_text(encoding="utf-8"))
        else:
            cfg = _load_defaults()
    else:
        cfg = _load_defaults()

    # Convenience secrets (override regardless of defaults).
    if os.environ.get("OPENAI_API_KEY"):
        cfg["openai_api_key"] = os.environ["OPENAI_API_KEY"].strip()
    if os.environ.get("PEXELS_API_KEY"):
        cfg["pexels_api_key"] = os.environ["PEXELS_API_KEY"].strip()
    if os.environ.get("ELEVENLABS_API_KEY"):
        cfg["elevenlabs_api_key"] = os.environ["ELEVENLABS_API_KEY"].strip()
    if os.environ.get("ELEVENLABS_VOICE_ID"):
        cfg["elevenlabs_voice_id"] = os.environ["ELEVENLABS_VOICE_ID"].strip()
    if os.environ.get("ELEVENLABS_MODEL_ID"):
        cfg["elevenlabs_model_id"] = os.environ["ELEVENLABS_MODEL_ID"].strip()

    # Override top-level scalar keys directly via env var matching (KEY -> key).
    for k, v in list(cfg.items()):
        if isinstance(v, dict):
            continue
        env_k = k.upper()
        if env_k in os.environ:
            cfg[k] = _parse_env_value(os.environ[env_k])

    # Nested overrides: PREFIX__SUBKEY__... (also support SA__ prefix).
    for env_k, env_v in os.environ.items():
        key = env_k
        if key.startswith("SA__"):
            key = key[len("SA__") :]
        if "__" not in key:
            continue
        parts = [p.strip().lower() for p in key.split("__") if p.strip()]
        if not parts:
            continue
        _set_path(cfg, parts, _parse_env_value(env_v))

    return cfg

