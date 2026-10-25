"""API mode against a fake OpenAI-compatible endpoint that behaves like the
picky ones: rejects max_tokens, rejects json_schema, wraps JSON in prose."""

from __future__ import annotations

import contextlib
import importlib
import json

import httpx
import pytest


@pytest.fixture()
def api(tmp_path, monkeypatch):
    monkeypatch.setenv("PIANKE_HOME", str(tmp_path))
    import pianke.config as config
    import pianke.memory.store as st

    importlib.reload(config)
    importlib.reload(st)
    st.init()
    from pianke.llm import client, settings
    from pianke.llm.runtime import runtime

    monkeypatch.setattr(settings, "PATH", tmp_path / "settings.json")
    client._quirks.clear()
    s = settings.save({"mode": "api", "base_url": "https://api.example.com/v1/",
                       "api_key": "sk-test-123456789", "big_model": "big-m", "small_model": ""})
    runtime.apply(s)
    yield client, runtime, settings, st
    for srv in runtime.servers.values():  # back to local without launching llama-server
        srv.remote, srv.status, srv.error = None, "stopped", None


class Fake:
    def __init__(self, reply: str, reject: tuple[str, ...] = ("max_tokens", "json_schema")):
        self.reply = reply
        self.reject = reject
        self.bodies: list[dict] = []

    def check(self, body: dict) -> httpx.Response | None:
        self.bodies.append(body)
        if "max_tokens" in self.reject and "max_tokens" in body:
            return httpx.Response(400, json={"error": {"message": "Unsupported parameter: 'max_tokens'. Use 'max_completion_tokens' instead."}})
        fmt = (body.get("response_format") or {}).get("type")
        if "json_schema" in self.reject and fmt == "json_schema":
            return httpx.Response(400, json={"error": {"message": "This response_format type is unavailable now"}})
        return None

    def post(self, url, json=None, headers=None, timeout=None):  # noqa: A002
        assert url == "https://api.example.com/v1/chat/completions"
        assert headers == {"Authorization": "Bearer sk-test-123456789"}
        bad = self.check(json)
        if bad is not None:
            return bad
        return httpx.Response(200, json={
            "choices": [{"message": {"content": self.reply}, "finish_reason": "stop"}],
            "usage": {"prompt_tokens": 10, "completion_tokens": 5},
        })

    @contextlib.contextmanager
    def stream(self, method, url, json=None, headers=None, timeout=None):  # noqa: A002
        bad = self.check(json)
        if bad is not None:
            yield bad
            return
        chunks = ["<thi", "nk>hmm</think>", "你好", "，片刻"]
        lines = [f"data: {_dumps({'choices': [{'delta': {'content': c}}]})}" for c in chunks]
        yield httpx.Response(200, content="\n".join([*lines, "data: [DONE]"]).encode(),
                             request=httpx.Request(method, url))


def _dumps(o):
    return json.dumps(o, ensure_ascii=False)


SCHEMA = {
    "type": "object",
    "properties": {
        "direction": {"type": "string"},
        "kinds": {"type": "array", "items": {"type": "string", "enum": ["movie", "series"]}, "maxItems": 2},
        "year_min": {"type": "integer"},
        "seeds": {"type": "array", "items": {"type": "object", "properties": {"title": {"type": "string"}}}},
    },
    "required": ["direction", "kinds", "year_min", "seeds"],
}


def test_structured_call_adapts_and_conforms(api, monkeypatch):
    client, runtime, _, st = api
    fake = Fake('好的：```json\n{"direction": "安静的", "kinds": ["movie", "anime", "series", "movie"], '
                '"seeds": [{"title": "花样年华"}, "junk"]}\n```')
    monkeypatch.setattr(client.httpx, "post", fake.post)
    out, stats = client.chat("big", [{"role": "system", "content": "sys"}, {"role": "user", "content": "u"}],
                             task="t", schema=SCHEMA, max_tokens=900)
    assert out == {"direction": "安静的", "kinds": ["movie", "series"], "year_min": 0,
                   "seeds": [{"title": "花样年华"}]}
    final = fake.bodies[-1]
    assert final["model"] == "big-m"
    assert final["max_completion_tokens"] == client.REMOTE_MIN_TOKENS and "max_tokens" not in final
    assert final["response_format"] == {"type": "json_object"}
    assert "chat_template_kwargs" not in final and "cache_prompt" not in final
    assert "JSON Schema" in final["messages"][0]["content"]
    assert stats["model"] == "big-m"
    # learned once: the next call goes right the first time
    n = len(fake.bodies)
    client.chat("small", [{"role": "user", "content": "u"}], task="t", schema=SCHEMA)
    assert len(fake.bodies) == n + 1


def test_stream_hides_inline_thinking(api, monkeypatch):
    client, *_ = api
    fake = Fake("", reject=("max_tokens",))
    monkeypatch.setattr(client.httpx, "stream", fake.stream)
    assert "".join(client.stream("big", [{"role": "user", "content": "u"}], task="t")) == "你好，片刻"


def test_auth_error_is_readable(api, monkeypatch):
    client, *_ = api
    monkeypatch.setattr(client.httpx, "post", lambda *a, **k: httpx.Response(401, text="bad key"))
    with pytest.raises(RuntimeError, match="API Key"):
        client.chat("big", [{"role": "user", "content": "u"}], task="t")


def test_settings_file_private_and_key_masked(api):
    _, runtime, settings, _ = api
    assert oct(settings.PATH.stat().st_mode & 0o777) == "0o600"
    pub = settings.public(settings.load())
    assert "api_key" not in pub and pub["has_key"] and pub["key_hint"] == "sk-…6789"
    assert pub["base_url"] == "https://api.example.com/v1" and not pub["on_device"]
    # saving without a key keeps the old one
    settings.save({"api_key": None, "big_model": "other"})
    assert settings.load()["api_key"] == "sk-test-123456789"
    assert settings.on_device({**settings.load(), "base_url": "http://localhost:11434/v1"})
    m = {x["key"]: x for x in runtime.public()}
    assert m["big"]["provider"] == "api" and m["small"]["name"] == "big-m" and m["big"]["status"] == "ready"


def test_profile_token_estimate(api):
    client, *_ = api
    assert client.tokenize_count("big", "你好世界abcdefgh") == 6


def test_local_models_wait_for_first_use(tmp_path, monkeypatch):
    from pianke.llm import runtime as rt
    from pianke.llm import settings

    monkeypatch.setattr(settings, "PATH", tmp_path / "settings.json")
    monkeypatch.delenv("PIANKE_PRELOAD", raising=False)
    r = rt.Runtime()
    started = []
    monkeypatch.setattr(r, "_start", lambda key: started.append(key))
    r.start_all()
    assert [s.status for s in r.servers.values()] == ["idle", "idle"] and not started
    with r._lock:
        r._ensure(r.servers["big"])
        r._ensure(r.servers["big"])  # a second caller must not launch a twin
    import time
    time.sleep(0.05)
    assert started == ["big"] and r.servers["small"].status == "idle"
