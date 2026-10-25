"""Which models answer — the two local Spark-X2.5 servers (default), or any
OpenAI-compatible endpoint (OpenAI, DeepSeek, OpenRouter, Ollama, LM Studio…)
— and the optional online services: TMDB for posters, Exa or Tavily for web
search.

Kept in HOME/settings.json rather than user.sqlite, so clearing the memory
keeps it and exporting the memory never includes a key. The file is chmod 600
and keys never go back to the UI, only a hint."""

from __future__ import annotations

import json
import os
from urllib.parse import urlparse

from ..config import HOME, ensure_home

PATH = HOME / "settings.json"

DEFAULTS: dict = {
    "mode": "local",  # local | api
    "base_url": "",  # e.g. https://api.openai.com/v1
    "api_key": "",
    "big_model": "",  # direction, picking, interview, profile
    "small_model": "",  # feedback structuring; empty = same as big_model
    "ctx": 131072,  # context window to assume for the long profile read
    "tmdb_key": "",  # v3 API key or v4 read token
    "search_provider": "",  # "" | exa | tavily
    "exa_key": "",
    "tavily_key": "",
}

SECRETS = ("api_key", "tmdb_key", "exa_key", "tavily_key")

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
        if k not in DEFAULTS or v is None:
            continue
        s[k] = v.strip() if isinstance(v, str) else v
    if s["mode"] not in ("local", "api"):
        s["mode"] = "local"
    if s["search_provider"] not in ("", "exa", "tavily"):
        s["search_provider"] = ""
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


def _hint(key: str) -> str:
    return f"{key[:3]}…{key[-4:]}" if len(key) > 10 else ("已填写" if key else "")


def search_key(s: dict) -> str:
    """The key for the chosen search provider; empty means search is off."""
    return s.get(f"{s['search_provider']}_key", "") if s["search_provider"] else ""


def public(s: dict) -> dict:
    return {
        **{k: v for k, v in s.items() if k not in SECRETS},
        "has_key": bool(s["api_key"]),
        "key_hint": _hint(s["api_key"]),
        "keys": {k: _hint(s[k]) for k in SECRETS if k != "api_key"},
        "search_on": bool(search_key(s)),
        "host": host(s),
        "on_device": on_device(s),
    }
