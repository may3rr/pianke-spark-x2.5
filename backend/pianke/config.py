"""Paths and runtime settings. Everything the app writes lives under HOME;
the catalog and model weights are read-only inputs."""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]

HOME = Path(
    os.environ.get(
        "PIANKE_HOME",
        Path.home() / "Library" / "Application Support" / "Pianke",
    )
)
# read-only inputs: the repo's data/ in development, the app bundle's
# Resources/data when installed (the Electron main process sets PIANKE_DATA)
DATA_DIR = Path(os.environ.get("PIANKE_DATA", REPO / "data"))
MODELS_DIR = Path(os.environ.get("PIANKE_MODELS", REPO / "models"))
CATALOG_DB = Path(os.environ.get("PIANKE_CATALOG", DATA_DIR / "catalog.sqlite"))
LIBRARY_DB = Path(os.environ.get("PIANKE_LIBRARY", DATA_DIR / "library.sqlite"))
USER_DB = HOME / "user.sqlite"
# public lookups (covers, titles found online) — no user data, safe to delete
CACHE_DB = HOME / "cache.sqlite"
COVERS_DIR = HOME / "covers"


@dataclass(frozen=True)
class ModelSpec:
    key: str  # "big" | "small"
    name: str
    file: str
    port: int
    ctx: int  # context window we ask llama-server to allocate


# 4B reasons (direction, picking, profile consolidation); 1.7B does the
# high-volume, low-stakes structuring (feedback extraction, title parsing).
BIG = ModelSpec(
    key="big",
    name="Spark-X2.5-4B",
    file=os.environ.get("PIANKE_BIG_FILE", "Spark-X2.5-4B-Q4_K_M.gguf"),
    port=int(os.environ.get("PIANKE_BIG_PORT", "18741")),
    ctx=int(os.environ.get("PIANKE_BIG_CTX", "131072")),
)
SMALL = ModelSpec(
    key="small",
    name="Spark-X2.5-1.7B",
    file=os.environ.get("PIANKE_SMALL_FILE", "Spark-X2.5-1.7B-Q4_K_M.gguf"),
    port=int(os.environ.get("PIANKE_SMALL_PORT", "18742")),
    ctx=int(os.environ.get("PIANKE_SMALL_CTX", "16384")),
)
MODELS = {m.key: m for m in (BIG, SMALL)}

def _llama_server() -> str:
    if os.environ.get("PIANKE_LLAMA_SERVER"):
        return os.environ["PIANKE_LLAMA_SERVER"]
    import shutil

    # apps launched from Finder don't inherit the shell PATH
    for c in (shutil.which("llama-server"), "/opt/homebrew/bin/llama-server", "/usr/local/bin/llama-server"):
        if c and Path(c).exists():
            return c
    return "llama-server"


LLAMA_SERVER = _llama_server()
# set to an http://host:port base to use an already-running server for both
# roles (tests, or a machine where the weights live elsewhere)
EXTERNAL_LLM = os.environ.get("PIANKE_EXTERNAL_LLM")


def ensure_home() -> None:
    HOME.mkdir(parents=True, exist_ok=True)
