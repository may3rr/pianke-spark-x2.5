"""All model calls go through here. Structured calls use llama-server's
JSON-schema grammar, so the output always parses; each call's timings are
logged so the app can show what ran on this Mac and how fast."""

from __future__ import annotations

import json
import time
from typing import Any, Iterator

import httpx

from ..memory import store
from .runtime import runtime

# Spark-X2.5 card: temperature 1.0 / top_p 0.95 for open generation.
# Structured picking runs cooler so the same profile gives stable picks.
GEN = {"temperature": 1.0, "top_p": 0.95}
STRUCT = {"temperature": 0.4, "top_p": 0.95}


def _body(
    messages: list[dict],
    *,
    think: bool,
    schema: dict | None,
    max_tokens: int,
    sampling: dict,
    stream: bool = False,
) -> dict:
    body: dict[str, Any] = {
        "messages": messages,
        "max_tokens": max_tokens,
        "chat_template_kwargs": {"enable_thinking": think},
        "stream": stream,
        "cache_prompt": True,
        **sampling,
    }
    if schema is not None:
        body["response_format"] = {
            "type": "json_schema",
            "json_schema": {"name": "out", "schema": schema, "strict": True},
        }
    if stream:
        body["stream_options"] = {"include_usage": True}
    return body


def _log(model: str, task: str, data: dict, wall: float) -> dict:
    t = data.get("timings") or {}
    u = data.get("usage") or {}
    rec = {
        "model": model,
        "task": task,
        "prompt_tokens": u.get("prompt_tokens") or t.get("prompt_n"),
        "completion_tokens": u.get("completion_tokens") or t.get("predicted_n"),
        "cached_tokens": t.get("cache_n"),
        "prompt_tps": t.get("prompt_per_second"),
        "gen_tps": t.get("predicted_per_second"),
        "seconds": round(wall, 2),
    }
    store.log_llm(rec)
    return rec


def chat(
    model: str,
    messages: list[dict],
    *,
    task: str,
    think: bool = False,
    schema: dict | None = None,
    max_tokens: int = 1024,
    sampling: dict | None = None,
    timeout: float = 600,
) -> tuple[str | dict, dict]:
    """Returns (content, stats). With a schema, content is the parsed dict."""
    runtime.wait(model)
    body = _body(
        messages,
        think=think,
        schema=schema,
        max_tokens=max_tokens,
        sampling=sampling or (STRUCT if schema else GEN),
    )
    for attempt in range(2):
        t0 = time.time()
        r = httpx.post(f"{runtime.url(model)}/v1/chat/completions", json=body, timeout=timeout)
        r.raise_for_status()
        data = r.json()
        stats = _log(runtime.servers[model].spec.name, task, data, time.time() - t0)
        choice = data["choices"][0]
        msg = choice["message"]
        content = msg.get("content") or ""
        stats["reasoning"] = msg.get("reasoning_content") or ""
        if schema is None:
            return content.strip(), stats
        try:
            return json.loads(_strip_fence(content)), stats
        except json.JSONDecodeError:
            # grammar output only breaks when cut off at max_tokens: give it
            # room once, then surface a readable error
            if attempt == 0:
                body["max_tokens"] = max_tokens * 2
                continue
            raise RuntimeError(
                f"本机模型这次的输出不完整（{task}，结束原因 {choice.get('finish_reason')}）。再试一次。"
            )
    raise AssertionError("unreachable")


def stream(
    model: str,
    messages: list[dict],
    *,
    task: str,
    think: bool = False,
    max_tokens: int = 512,
    sampling: dict | None = None,
) -> Iterator[str]:
    """Yields content deltas; logs timings when the stream ends."""
    runtime.wait(model)
    body = _body(
        messages,
        think=think,
        schema=None,
        max_tokens=max_tokens,
        sampling=sampling or GEN,
        stream=True,
    )
    t0 = time.time()
    last: dict = {}
    with httpx.stream(
        "POST", f"{runtime.url(model)}/v1/chat/completions", json=body, timeout=600
    ) as r:
        r.raise_for_status()
        for line in r.iter_lines():
            if not line.startswith("data:"):
                continue
            payload = line[5:].strip()
            if payload == "[DONE]":
                break
            chunk = json.loads(payload)
            if chunk.get("timings"):
                last["timings"] = chunk["timings"]
            if chunk.get("usage"):
                last["usage"] = chunk["usage"]
            for ch in chunk.get("choices") or []:
                d = (ch.get("delta") or {}).get("content")
                if d:
                    yield d
    _log(runtime.servers[model].spec.name, task, last, time.time() - t0)


def _strip_fence(s: str) -> str:
    s = s.strip()
    if s.startswith("```"):
        s = s.split("\n", 1)[1] if "\n" in s else s
        s = s.rsplit("```", 1)[0]
    return s.strip()


def tokenize_count(model: str, text: str) -> int:
    r = httpx.post(f"{runtime.url(model)}/tokenize", json={"content": text}, timeout=60)
    r.raise_for_status()
    return len(r.json()["tokens"])
