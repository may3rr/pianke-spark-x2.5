"""All model calls go through here. Structured calls use llama-server's
JSON-schema grammar, so the output always parses; each call's timings are
logged so the app can show what ran on this Mac and how fast.

In API mode the same calls go to an OpenAI-compatible endpoint. Hosted APIs
differ in what they accept (max_tokens vs max_completion_tokens, fixed
temperature, json_schema vs json_object), so a 400 that names a parameter
teaches us to drop or rename it, and that is remembered per endpoint. There
is no grammar there, so the schema also goes into the prompt and the parsed
output is coerced to its shape; the flows already check every id against
the catalog and the store."""

from __future__ import annotations

import json
import re
import time
from typing import Any, Iterator

import httpx

from ..memory import store
from .runtime import ServerState, runtime

# Spark-X2.5 card: temperature 1.0 / top_p 0.95 for open generation.
# Structured picking runs cooler so the same profile gives stable picks.
GEN = {"temperature": 1.0, "top_p": 0.95}
STRUCT = {"temperature": 0.4, "top_p": 0.95}

# the flows size max_tokens for a 4B model that only writes the answer;
# hosted reasoning models spend tokens thinking first
REMOTE_MIN_TOKENS = 4096


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


# ---------------------------------------------------------------- API mode

# endpoint+model -> what it rejected: "max_tokens", "temperature", "top_p",
# "stream_options", "json_schema", "json_object"
_quirks: dict[str, set[str]] = {}


def _remote_body(
    st: ServerState,
    messages: list[dict],
    *,
    schema: dict | None,
    max_tokens: int,
    sampling: dict,
    stream: bool = False,
) -> dict:
    q = _quirks.setdefault(f"{st.base_url}|{st.name}", set())
    if schema is not None:
        messages = _with_schema_hint(messages, schema)
    body: dict[str, Any] = {
        "model": st.name,
        "messages": messages,
        "stream": stream,
        **{k: v for k, v in sampling.items() if k not in q},
    }
    tokens = max(max_tokens, REMOTE_MIN_TOKENS)
    body["max_completion_tokens" if "max_tokens" in q else "max_tokens"] = tokens
    if stream and "stream_options" not in q:
        body["stream_options"] = {"include_usage": True}
    if schema is not None and "json_schema" not in q:
        body["response_format"] = {
            "type": "json_schema",
            # not strict: strict mode rejects schemas with long enums or
            # maxLength, and _conform covers what a loose model gets wrong
            "json_schema": {"name": "out", "schema": schema, "strict": False},
        }
    elif schema is not None and "json_object" not in q:
        body["response_format"] = {"type": "json_object"}
    return body


def _learn(st: ServerState, body: dict, err: str) -> bool:
    """Record what a 400 complained about. False when it named nothing we
    can change, so the error should reach the user."""
    q = _quirks.setdefault(f"{st.base_url}|{st.name}", set())
    t = err.lower()
    for p in ("max_tokens", "temperature", "top_p", "stream_options"):
        if p in body and p in t and p not in q:
            q.add(p)
            return True
    fmt = (body.get("response_format") or {}).get("type")
    if fmt and any(w in t for w in ("response_format", "json", "schema")):
        q.add(fmt)
        return True
    return False


def _remote_post(st: ServerState, body: dict, timeout: float) -> dict:
    for _ in range(6):
        r = httpx.post(
            f"{st.base_url}/chat/completions", json=body, headers=_headers(st), timeout=timeout
        )
        if r.status_code in (400, 422) and _learn(st, body, r.text):
            body = _rebuild(st, body)
            continue
        _raise_for(st, r.status_code, r.text)
        return r.json()
    _raise_for(st, r.status_code, r.text)
    raise AssertionError("unreachable")


def _rebuild(st: ServerState, body: dict) -> dict:
    """Re-apply the quirks to a body built before we learned them."""
    q = _quirks[f"{st.base_url}|{st.name}"]
    if "max_tokens" in q and "max_tokens" in body:
        body["max_completion_tokens"] = body["max_tokens"]
    body = {k: v for k, v in body.items() if k not in q}
    fmt = (body.get("response_format") or {}).get("type")
    if fmt == "json_schema" and "json_schema" in q:
        body["response_format"] = {"type": "json_object"}
        fmt = "json_object"
    if fmt == "json_object" and "json_object" in q:
        body.pop("response_format")
    return body


def _headers(st: ServerState) -> dict:
    key = st.remote["api_key"] if st.remote else ""
    return {"Authorization": f"Bearer {key}"} if key else {}


def _raise_for(st: ServerState, code: int, text: str) -> None:
    if code < 400:
        return
    detail = text.strip().replace("\n", " ")[:300]
    if code in (401, 403):
        raise RuntimeError(f"{st.remote['host']} 拒绝了这个 API Key（{code}）。去设置里检查一下。")
    if code == 404:
        raise RuntimeError(
            f"{st.remote['host']} 找不到这个接口或模型（404）。接口地址一般以 /v1 结尾，模型名要和服务商写的一致。{detail}"
        )
    if code == 429:
        raise RuntimeError(f"{st.remote['host']} 说请求太频繁或额度用完了（429）。{detail}")
    raise RuntimeError(f"{st.remote['host']} 返回了错误（{code}）：{detail}")


def _compact(schema: Any) -> Any:
    """The schema as shown in the prompt: long id enums become a note, the
    ids themselves are already in the prompt text."""
    if isinstance(schema, dict):
        out = {k: _compact(v) for k, v in schema.items()}
        if len(schema.get("enum") or []) > 40:
            out.pop("enum")
            out["description"] = "只能填上文出现过的编号"
        return out
    if isinstance(schema, list):
        return [_compact(v) for v in schema]
    return schema


def _with_schema_hint(messages: list[dict], schema: dict) -> list[dict]:
    hint = (
        "\n\n只输出一个 JSON 对象，不要输出任何别的文字，不要用代码块包起来。"
        "它必须符合这个 JSON Schema：\n" + json.dumps(_compact(schema), ensure_ascii=False)
    )
    msgs = [dict(m) for m in messages]
    if msgs and msgs[0]["role"] == "system":
        msgs[0]["content"] += hint
    else:
        msgs.insert(0, {"role": "system", "content": hint.strip()})
    return msgs


def _conform(v: Any, s: dict) -> Any:
    """Coerce parsed JSON to the schema's shape: missing fields get empty
    values, arrays are capped, enum arrays lose values outside the enum."""
    t = s.get("type")
    if t == "object":
        v = v if isinstance(v, dict) else {}
        return {k: _conform(v.get(k), ps) for k, ps in (s.get("properties") or {}).items()}
    if t == "array":
        it = s.get("items") or {}
        items = v if isinstance(v, list) else []
        if it.get("type") == "object":
            items = [x for x in items if isinstance(x, dict)]
        items = [_conform(x, it) for x in items]
        if "enum" in it:
            items = [x for x in items if x in it["enum"]]
        return items[: s["maxItems"]] if "maxItems" in s else items
    if t == "string":
        if isinstance(v, (int, float)) and not isinstance(v, bool):
            return str(v)
        return v if isinstance(v, str) else ""
    if t in ("integer", "number"):
        try:
            return int(v) if t == "integer" else float(v)
        except (TypeError, ValueError):
            return 0
    if t == "boolean":
        return bool(v)
    return v


_THINK = re.compile(r"<think>.*?</think>", re.S)


def _parse_json(s: str) -> Any:
    s = _strip_fence(_THINK.sub("", s))
    try:
        return json.loads(s)
    except json.JSONDecodeError:
        # some models still wrap the object in a sentence
        a, b = s.find("{"), s.rfind("}")
        if a >= 0 and b > a:
            return json.loads(s[a : b + 1])
        raise


# ---------------------------------------------------------------- calls

def _log(model: str, task: str, data: dict, wall: float) -> dict:
    t = data.get("timings") or {}
    u = data.get("usage") or {}
    gen = u.get("completion_tokens") or t.get("predicted_n")
    rec = {
        "model": model,
        "task": task,
        "prompt_tokens": u.get("prompt_tokens") or t.get("prompt_n"),
        "completion_tokens": gen,
        "cached_tokens": t.get("cache_n"),
        "prompt_tps": t.get("prompt_per_second"),
        # hosted APIs report no timings; wall-clock rate is close enough
        "gen_tps": t.get("predicted_per_second") or (round(gen / wall, 1) if gen and wall else None),
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
    st = runtime.servers[model]
    sampling = sampling or (STRUCT if schema else GEN)
    for attempt in range(2):
        t0 = time.time()
        if st.remote:
            body = _remote_body(st, messages, schema=schema, max_tokens=max_tokens, sampling=sampling)
            data = _remote_post(st, body, timeout)
        else:
            body = _body(messages, think=think, schema=schema, max_tokens=max_tokens, sampling=sampling)
            r = httpx.post(f"{runtime.url(model)}/v1/chat/completions", json=body, timeout=timeout)
            r.raise_for_status()
            data = r.json()
        stats = _log(st.name, task, data, time.time() - t0)
        choice = data["choices"][0]
        msg = choice["message"]
        content = msg.get("content") or ""
        stats["reasoning"] = msg.get("reasoning_content") or ""
        if schema is None:
            return _THINK.sub("", content).strip(), stats
        try:
            out = _parse_json(content)
            return (_conform(out, schema) if st.remote else out), stats
        except json.JSONDecodeError:
            # grammar output only breaks when cut off at max_tokens: give it
            # room once, then surface a readable error
            if attempt == 0:
                max_tokens *= 2
                continue
            who = st.name if st.remote else "本机模型"
            raise RuntimeError(
                f"{who}这次的输出不完整（{task}，结束原因 {choice.get('finish_reason')}）。再试一次。"
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
    st = runtime.servers[model]
    if st.remote:
        url = f"{st.base_url}/chat/completions"
        body = _remote_body(
            st, messages, schema=None, max_tokens=max_tokens, sampling=sampling or GEN, stream=True
        )
    else:
        url = f"{runtime.url(model)}/v1/chat/completions"
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
    hide = _ThinkFilter()
    for _ in range(6):
        with httpx.stream("POST", url, json=body, headers=_headers(st), timeout=600) as r:
            if st.remote and r.status_code >= 400:
                text = r.read().decode("utf-8", "replace")
                if r.status_code in (400, 422) and _learn(st, body, text):
                    body = _rebuild(st, body)
                    continue
                _raise_for(st, r.status_code, text)
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
                    d = hide((ch.get("delta") or {}).get("content") or "")
                    if d:
                        yield d
        break
    _log(st.name, task, last, time.time() - t0)


class _ThinkFilter:
    """Drops a leading <think>…</think> block from a stream; some hosted
    reasoning models put their thinking inline instead of in a separate field."""

    def __init__(self) -> None:
        self.buf = ""
        self.state = "start"  # start | think | pass

    def __call__(self, d: str) -> str:
        if self.state == "pass":
            return d
        self.buf += d
        if self.state == "start":
            head = self.buf.lstrip()
            if not head or "<think>".startswith(head):
                return ""
            if not head.startswith("<think>"):
                self.state = "pass"
                out, self.buf = self.buf, ""
                return out
            self.state = "think"
        end = self.buf.find("</think>")
        if end < 0:
            return ""
        self.state = "pass"
        out, self.buf = self.buf[end + len("</think>") :].lstrip(), ""
        return out


def _strip_fence(s: str) -> str:
    s = s.strip()
    if s.startswith("```"):
        s = s.split("\n", 1)[1] if "\n" in s else s
        s = s.rsplit("```", 1)[0]
    return s.strip()


def tokenize_count(model: str, text: str) -> int:
    if runtime.servers[model].remote:
        # hosted APIs have no tokenizer endpoint: about one token per CJK
        # character, four characters per token otherwise
        cjk = sum(1 for ch in text if ord(ch) >= 0x2E80)
        return cjk + (len(text) - cjk) // 4
    r = httpx.post(f"{runtime.url(model)}/tokenize", json={"content": text}, timeout=60)
    r.raise_for_status()
    return len(r.json()["tokens"])
