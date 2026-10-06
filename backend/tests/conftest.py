"""Tests never start llama-server: a stray launch loads several GB of
weights and outlives pytest."""

from __future__ import annotations

import pytest


@pytest.fixture(autouse=True)
def no_llama_server(monkeypatch):
    from pianke.llm import runtime

    def refuse(*a, **k):
        raise AssertionError("tests must not launch llama-server")

    monkeypatch.setattr(runtime.subprocess, "Popen", refuse)
