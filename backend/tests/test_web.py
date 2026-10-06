"""Web search wiring with fake Exa / Tavily answers and a stubbed model."""

from __future__ import annotations

import importlib

import pytest


@pytest.fixture()
def env(tmp_path, monkeypatch):
    monkeypatch.setenv("PIANKE_HOME", str(tmp_path))
    import pianke.config as config
    import pianke.memory.store as st

    importlib.reload(config)
    importlib.reload(st)
    st.init()
    from pianke.llm import settings
    from pianke.lookup import net, web

    monkeypatch.setattr(settings, "PATH", tmp_path / "settings.json")
    monkeypatch.setattr(net, "CACHE_DB", tmp_path / "cache.sqlite")
    calls = []

    def fake_get_json(url, params, **kw):
        calls.append((url, kw))
        if url == web.EXA:
            return {"results": [{"title": "书讯", "url": "https://e.x/1",
                                 "text": "《长夜行》是 林间 的第三本小说，写一个夜班司机。", "publishedDate": "2025-03-01T00:00"}]}
        return {"results": [{"title": "评测", "url": "https://t.x/1", "content": "林间 新书《长夜行》节奏很慢"}]}

    monkeypatch.setattr(net, "get_json", fake_get_json)
    yield settings, web, calls


def test_off_without_key(env):
    settings, web, calls = env
    settings.save({"search_provider": "exa"})  # provider but no key
    assert not web.enabled() and web.search("x") == [] and not calls


def test_exa_and_tavily_shapes(env):
    settings, web, calls = env
    settings.save({"search_provider": "exa", "exa_key": "exa-secret-123456"})
    r = web.search("长夜行")
    assert r[0]["date"] == "2025-03-01" and "夜班司机" in r[0]["text"]
    assert calls[-1][1]["headers"] == {"x-api-key": "exa-secret-123456"}
    settings.save({"search_provider": "tavily", "tavily_key": "tvly-secret-123456"})
    r = web.search("长夜行")
    assert r[0]["text"].startswith("林间") and calls[-1][1]["headers"]["Authorization"] == "Bearer tvly-secret-123456"
    pub = settings.public(settings.load())
    assert pub["search_on"] and pub["keys"]["exa_key"] == "exa…3456"
    assert "exa_key" not in pub and "tavily_key" not in pub


def test_find_work_needs_title_and_creator(env):
    settings, web, _ = env
    settings.save({"search_provider": "exa", "exa_key": "exa-secret-123456"})
    w = web.find_work("book", "长夜行", "林间", 2025)
    assert w and w["id"].startswith("bk:web") and w["ext"]["web"] == "https://e.x/1"
    from pianke.catalog import library

    assert library.get(w["id"])["name"] == "长夜行"  # resolvable like any online find
    assert web.find_work("book", "长夜行", "别的作者", None) is None


def test_recommend_helpers(env, monkeypatch):
    settings, web, _ = env
    from pianke.flows import recommend

    assert recommend._with_queries(recommend.DIRECTION_SCHEMA) is recommend.DIRECTION_SCHEMA
    settings.save({"search_provider": "exa", "exa_key": "exa-secret-123456"})
    sch = recommend._with_queries(recommend.DIRECTION_SCHEMA)
    assert "queries" in sch["required"] and "queries" not in recommend.DIRECTION_SCHEMA["properties"]

    seen = []

    def fake_chat(model, messages, *, task, schema=None, **kw):
        seen.append((task, messages[-1]["content"]))
        if task.startswith("rec_web_seeds"):
            return {"seeds": [{"title": "长夜行", "original": "", "author": "林间", "year": 2025}]}, {}
        return {"reasons": [{"id": "bk:1", "reason": "新的理由"}]}, {}

    monkeypatch.setattr(recommend.client, "chat", fake_chat)
    seeds, note = recommend._web_seeds("book", recommend._shelf_direction_schema("book"),
                                       {"direction": "慢", "queries": ["慢节奏 小说"]}, "ctx")
    assert seeds[0]["title"] == "长夜行" and "联网搜到 1 本" in note
    assert "夜班司机" in seen[-1][1]
    picks = [{"id": "bk:1", "name": "长夜行", "year": 2025, "creators": ["林间"], "reason": "旧", "because": []}]
    assert recommend._review_reasons("book", picks, "ctx", "慢") == 1
    assert picks[0]["reason"] == "新的理由"
