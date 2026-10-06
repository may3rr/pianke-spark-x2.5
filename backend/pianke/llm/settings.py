"""Which models answer: the two local Spark-X2.5 servers (default), or any
OpenAI-compatible endpoint (OpenAI, DeepSeek, OpenRouter, Ollama, LM Studio…).

Kept in HOME/llm.json rather than user.sqlite, so clearing the memory keeps
it and exporting the memory never includes the key. The file is chmod 600."""

from __future__ import annotations

import json
import os
from urllib.parse import urlparse

from ..config import HOME, ensure_home

PATH = HOME / "llm.json"

DEFAULTS: dict = {
    "mode": "local",  # local | api
    "base_url": "",  # e.g. https://api.openai.com/v1
    "api_key": "",
    "big_model": "",  # direction, picking, interview, profile
    "small_model": "",  # feedback structuring; empty = same as big_model
    "ctx": 131072,  # context window to assume for the long profile read
}

LOOPBACK = {"localhost", "127.0.0.1", "::1", "0.0.0.0"}


def load() -> dict:
    try:
        data = json.loads(PATH.read_text())
    except (OSError, ValueError):
        data = {}
    return {**DEFAULTS, **{k: v for k, v in data.items() if k in DEFAULTS}}


def save(patch: dict) -> dict:
    s = load()
    for k, v in patch.items():
        # an omitted key means "keep the saved one"; the UI never sees it
        if k not in DEFAULTS or (k == "api_key" and v is None):
            continue
        s[k] = v.strip() if isinstance(v, str) else v
    if s["mode"] not in ("local", "api"):
        s["mode"] = "local"
    s["base_url"] = s["base_url"].rstrip("/")
    s["ctx"] = int(s["ctx"] or DEFAULTS["ctx"])
    ensure_home()
    tmp = PATH.with_suffix(".tmp")
    fd = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(fd, "w") as f:
        json.dump(s, f, ensure_ascii=False, indent=2)
    os.replace(tmp, PATH)
    return s


def host(s: dict) -> str:
    return urlparse(s["base_url"]).hostname or ""


def on_device(s: dict) -> bool:
    """True when nothing the user says leaves this Mac: local mode, or an
    OpenAI-compatible server on loopback (Ollama, LM Studio)."""
    return s["mode"] == "local" or host(s) in LOOPBACK


def public(s: dict) -> dict:
    key = s["api_key"]
    return {
        **{k: v for k, v in s.items() if k != "api_key"},
        "has_key": bool(key),
        "key_hint": f"{key[:3]}…{key[-4:]}" if len(key) > 10 else ("已填写" if key else ""),
        "host": host(s),
        "on_device": on_device(s),
    }
