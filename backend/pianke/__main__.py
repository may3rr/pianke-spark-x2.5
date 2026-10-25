"""`python -m pianke --port N`: the entry point the packaged app runs (the
frozen backend has no `python -m uvicorn` to call)."""

from __future__ import annotations

import argparse

import uvicorn

from .server import app


def main() -> None:
    ap = argparse.ArgumentParser(prog="pianke")
    ap.add_argument("--port", type=int, default=18740)
    a = ap.parse_args()
    uvicorn.run(app, host="127.0.0.1", port=a.port, log_level="info")


if __name__ == "__main__":
    main()
