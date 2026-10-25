"""Films the catalog lacks: TMDB first (mapped back to IMDb ids), then
Douban, with fake answers instead of the network."""

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
    from pianke.lookup import net, online

    monkeypatch.setattr(settings, "PATH", tmp_path / "settings.json")
    monkeypatch.setattr(net, "CACHE_DB", tmp_path / "cache.sqlite")
    asked = []

    def fake_get_json(url, params, **kw):
        asked.append(url)
        if url == online.TMDB_SEARCH:
            return {"results": [
                {"media_type": "movie", "id": 1, "title": "推拿", "original_title": "推拿",
                 "release_date": "2014-04-04", "poster_path": "/p.jpg", "overview": "盲人推拿师"},
                {"media_type": "person", "id": 9, "name": "娄烨"},
            ]}
        if "external_ids" in url:
            return {"imdb_id": "tt3469964"}
        if "douban" in url:
            return [{"id": "1296272", "title": "跛豪", "sub_title": "跛豪", "year": "1991",
                     "type": "movie", "episode": "", "img": "https://img.doubanio.com/s_ratio_poster/x.jpg"}]
        return None

    monkeypatch.setattr(net, "get_json", fake_get_json)
    yield settings, online, net, asked


def test_tmdb_hit_keeps_imdb_id(env):
    settings, online, net, asked = env
    settings.save({"tmdb_key": "k" * 32})
    f = online.find_film("推拿", None, 2014)
    assert f["id"] == "tt3469964" and f["zh"] == "推拿" and f["ext"]["cover"].endswith("/p.jpg")
    assert net.load_ext(["tt3469964"])["tt3469964"]["name"] == "推拿"
    assert not any("douban" in u for u in asked)  # TMDB answered, Douban never asked


def test_tmdb_hit_maps_to_local_row(env):
    settings, online, _, _ = env
    settings.save({"tmdb_key": "k" * 32})
    local = {"tt3469964": {"id": "tt3469964", "name": "推拿（本地）"}}
    assert online.find_film("推拿", None, 2014, local=local.get)["name"] == "推拿（本地）"


def test_douban_without_tmdb_key(env):
    _, online, _, asked = env
    f = online.find_film("跛豪", None, 1991)
    assert f["id"] == "fm:db1296272" and f["year"] == 1991 and "m_ratio_poster" in f["ext"]["cover"]
    assert not any("themoviedb" in u for u in asked)
    assert online.find_film("跛豪", None, 2005) is None  # wrong year: not the same film


def test_catalog_reads_online_finds(env):
    _, online, _, _ = env
    online.find_film("跛豪", None, 1991)
    from pianke.catalog import search

    t = search.get("fm:db1296272")
    assert t["domain"] == "film" and t["name"] == "跛豪"
    assert "IMDb" not in search.brief(t)  # no rating for online finds
