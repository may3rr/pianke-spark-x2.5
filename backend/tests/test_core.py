"""Model-free tests: catalog grounding, memory store, profile edits."""

from __future__ import annotations

import importlib
import os

import pytest


@pytest.fixture()
def store(tmp_path, monkeypatch):
    monkeypatch.setenv("PIANKE_HOME", str(tmp_path))
    import pianke.config as config
    import pianke.memory.store as st

    importlib.reload(config)
    importlib.reload(st)
    st.init()
    yield st


catalog_ready = pytest.mark.skipif(
    not os.path.exists(os.path.join(os.path.dirname(__file__), "..", "..", "data", "catalog.sqlite")),
    reason="catalog not built",
)


@catalog_ready
@pytest.mark.parametrize(
    "q,year,expect",
    [
        ("花样年华", 2000, "tt0118694"),
        ("The Secret Life of Walter Mitty", 2013, "tt0359950"),
        ("白日梦想家", None, "tt0359950"),
        ("寄生虫", 2019, "tt6751668"),
        ("爱乐之城", None, "tt3783958"),
    ],
)
def test_resolve_known_titles(q, year, expect):
    from pianke.catalog import search

    hit = search.resolve(q, year)
    assert hit is not None and hit["id"] == expect


@catalog_ready
def test_resolve_rejects_invented_title():
    from pianke.catalog import search

    assert search.resolve("镰仓月光下的第七封信", 2017) is None


@catalog_ready
def test_candidates_respect_filters():
    from pianke.catalog import search

    rows = search.candidates(kinds=["movie"], genres_avoid=["Horror"], runtime_max=100, limit=20)
    assert rows
    assert all("Horror" not in r["genres"] for r in rows)
    assert all(r["runtime"] is None or r["runtime"] <= 100 for r in rows)


def test_item_words_are_appended_verbatim(store):
    store.upsert_item("tt0000001", status="watched", words="第一句话")
    it = store.upsert_item("tt0000001", words="第二句话")
    assert it["words"] == "第一句话\n第二句话"


def test_user_edited_claims_marked_and_kept(store, monkeypatch):
    import pianke.flows.profile as profile

    importlib.reload(profile)
    doc = {
        "summary": "s",
        "sections": [{"key": "love", "title": "你偏爱的", "claims": [{"text": "原来的", "evidence": []}]}],
    }
    store.save_profile(doc, {})
    edited = {
        "summary": "s",
        "sections": [{"key": "love", "title": "你偏爱的", "claims": [{"text": "我自己改的", "evidence": []}]}],
    }
    p = profile.edit(edited)
    claim = p["doc"]["sections"][0]["claims"][0]
    assert claim["text"] == "我自己改的" and claim.get("user") is True
    assert profile._user_claims(p)["love"][0]["text"] == "我自己改的"


def test_recently_recommended(store):
    store.save_rec({"text": ""}, "d", [{"id": "tt1"}, {"id": "tt2"}], {})
    assert store.recently_recommended() == {"tt1", "tt2"}


# ---------------------------------------------------------------- shelves, feedback, check-ins

def test_ids_route_to_domains(store):
    assert store.domain_of("tt0118694") == "film"
    assert store.domain_of("bk:Q123") == "book"
    assert store.domain_of("mu:it42") == "music"
    it = store.upsert_item("bk:Q123", status="want")
    assert it["domain"] == "book"
    assert [i["id"] for i in store.items(domain="book")] == ["bk:Q123"]
    assert store.items(domain="film") == []


def test_half_star_rating_and_zero_is_not_unrated(store):
    it = store.upsert_item("tt0000002", status="watched", rating=0.0)
    assert it["rating"] == 0.0
    it = store.upsert_item("tt0000002", rating=4.5)
    assert store.item("tt0000002")["rating"] == 4.5
    store.upsert_item("tt0000002", replace=("rating",), rating=None)
    assert store.item("tt0000002")["rating"] is None


def _flows():
    import pianke.flows.feedback as fb

    importlib.reload(fb)
    return fb


def test_pass_reasons_write_to_different_places(store):
    fb = _flows()
    fb.pass_("tt0000010", "want")
    assert store.item("tt0000010")["status"] == "want"
    fb.pass_("tt0000011", "not_my_taste", words="太闷")
    it = store.item("tt0000011")
    assert it["status"] == "rejected" and it["reason"] == "知道它，不对胃口"
    # "not right now" leaves no long-term record, only an event for L3
    fb.pass_("tt0000012", "not_now")
    assert store.item("tt0000012") is None
    assert any(e["id"] == "tt0000012" and e["effect"] == "moment" for e in store.events(kinds=("pass",)))


def test_log_without_review_keeps_explicit_stars(store):
    fb = _flows()
    out = fb.log("tt0000020", status="watched", rating=3.7, origin="rec", done_on="2026-10-04")
    it = out["item"]
    assert it["rating"] == 3.5 and it["origin"] == "rec" and it["done_on"] == "2026-10-04"


def test_checkins_ask_once(store):
    import time

    fb = _flows()
    picks = [{"id": "tt0338564", "name": "a"}, {"id": "tt0118694", "name": "b"}, {"id": "tt6751668", "name": "c"}]
    rid = store.save_rec({"text": "", "chips": {}, "domain": "film"}, "d", picks, {})
    with store.db() as c:
        c.execute("update recs set ts=? where id=?", (time.time() - 5 * 3600, rid))
    ids = lambda: [x["id"] for x in fb.checkins("film")]  # noqa: E731
    if not os.path.exists(os.path.join(os.path.dirname(__file__), "..", "..", "data", "catalog.sqlite")):
        pytest.skip("catalog not built")
    assert ids() == ["tt0338564", "tt0118694", "tt6751668"]  # untouched night: all three
    fb.pass_("tt0118694", "want")
    assert ids() == ["tt0118694"]  # once one is acted on, only the listed one
    fb.dismiss_checkin("tt0118694")
    assert ids() == []
    assert fb.checkins("book") == []


@catalog_ready
def test_saving_for_later_keeps_the_checkin(store):
    import time

    fb = _flows()
    import pianke.server as server

    importlib.reload(server)
    picks = [{"id": "tt0338564", "name": "a"}, {"id": "tt0118694", "name": "b"}, {"id": "tt6751668", "name": "c"}]
    rid = store.save_rec({"text": "", "chips": {}, "domain": "film"}, "d", picks, {})
    with store.db() as c:
        c.execute("update recs set ts=? where id=?", (time.time() - 5 * 3600, rid))
    server.item_pass("tt0118694", server.PassIn(reason="want", rec_id=rid))
    server.item_pass("tt0338564", server.PassIn(reason="not_now", rec_id=rid))
    assert [x["id"] for x in fb.checkins("film")] == ["tt0118694"]  # the listed one is asked about later


def test_wall_puts_cached_covers_first(store, monkeypatch):
    from pianke.flows import interview

    pool = [{"id": f"w{i}"} for i in range(8)]
    have = {"w5", "w7"}
    missing = {"w0"}
    monkeypatch.setattr(interview, "wall_pool", lambda *a, **k: pool)
    monkeypatch.setattr(
        interview.covers, "state",
        lambda ids: {i: "ok" if i in have else "miss" if i in missing else "unknown" for i in ids},
    )
    warmed: list[list[str]] = []
    monkeypatch.setattr(interview, "warm_covers", warmed.append)

    got = [t["id"] for t in interview.wall("film", n=4)]
    assert got == ["w5", "w7", "w1", "w2"]
    assert "w0" not in warmed[0] and "w5" not in warmed[0]
