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
    assert ids() == [f"night:{rid}"]  # untouched night: one question about the night
    fb.pass_("tt0118694", "want")
    assert ids() == ["tt0118694"]  # once one is acted on, only the listed one
    fb.dismiss_checkin("tt0118694")
    assert ids() == []
    assert fb.checkins("book") == []


@catalog_ready
def test_checkin_asks_only_about_the_chosen_pick(store):
    import time

    fb = _flows()
    picks = [{"id": "tt0338564", "name": "a"}, {"id": "tt0118694", "name": "b"}, {"id": "tt6751668", "name": "c"}]
    rid = store.save_rec({"text": "", "chips": {}, "domain": "film"}, "d", picks, {})
    with store.db() as c:
        c.execute("update recs set ts=? where id=?", (time.time() - 5 * 3600, rid))
    fb.choose(rid, "tt6751668")
    got = fb.checkins("film")
    assert [x["id"] for x in got] == ["tt6751668"] and got[0]["chosen"]
    # "还没顾上" brings it back later, twice at most
    assert fb.snooze_checkin("tt6751668")["again"]
    assert fb.checkins("film") == []
    sn = store.get_pref("snooze")
    sn["tt6751668"]["until"] = 0
    store.set_pref("snooze", sn)
    assert [x["id"] for x in fb.checkins("film")] == ["tt6751668"]
    fb.snooze_checkin("tt6751668")
    assert not fb.snooze_checkin("tt6751668")["again"]
    assert fb.checkins("film") == []


@catalog_ready
def test_night_dismissed_once(store):
    import time

    fb = _flows()
    picks = [{"id": "tt0338564", "name": "a"}, {"id": "tt0118694", "name": "b"}, {"id": "tt6751668", "name": "c"}]
    rid = store.save_rec({"text": "", "chips": {}, "domain": "film"}, "d", picks, {})
    with store.db() as c:
        c.execute("update recs set ts=? where id=?", (time.time() - 5 * 3600, rid))
    fb.dismiss_night(rid)
    assert fb.checkins("film") == []


@catalog_ready
def test_listed_before_is_not_a_checkin(store):
    """A pick that was already on the list (chosen from it) isn't asked about
    as if it had been saved that night."""
    import time

    fb = _flows()
    for pid in ("tt0338564", "tt0118694", "tt6751668"):
        fb.set_status(pid, "want", source="manual")
    picks = [{"id": "tt0338564", "name": "a"}, {"id": "tt0118694", "name": "b"}, {"id": "tt6751668", "name": "c"}]
    rid = store.save_rec({"text": "", "chips": {}, "domain": "film"}, "d", picks, {})
    with store.db() as c:
        c.execute("update recs set ts=? where id=?", (time.time() - 5 * 3600, rid))
    assert fb.checkins("film") == []
    fb.choose(rid, "tt0118694")
    assert [x["id"] for x in fb.checkins("film")] == ["tt0118694"]


def test_list_is_a_candidate_not_an_exclusion(store):
    from pianke.flows import recommend

    store.upsert_item("tt0000031", status="watched")
    store.upsert_item("tt0000032", status="want")
    store.upsert_item("tt0000033", status="rejected")
    seen, want = recommend._split_seen("film")
    assert seen == {"tt0000031", "tt0000033"} and want == ["tt0000032"]


def test_auto_profile_keeps_records_added_meanwhile(store, monkeypatch):
    from pianke.flows import auto

    store.set_pref("stale", 3)

    def steps():
        store.set_pref("stale", store.get_pref("stale", 0) + 1)  # a record lands mid-run
        yield {"type": "step"}

    list(auto.run(steps()))
    assert store.get_pref("stale") == 1


def test_onboarding_without_talk_offers_it_later(store, monkeypatch):
    import pianke.flows.interview as iv

    importlib.reload(iv)
    monkeypatch.setattr(iv, "_finish_steps", lambda: iter(()))
    iv.start(["film"])
    list(iv.finish())  # straight from the cover wall
    assert store.get_pref("onboarded") is True and iv.talked() is False
    assert len(iv.start(["film"])["turns"]) == 1 and iv.state()["total"] == 4  # the full talk
    store.add_turn("user", "喜欢花样年华")
    list(iv.finish())
    assert iv.talked() is True


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


def test_finish_survives_model_failure(store, monkeypatch):
    """Onboarding must complete even when the model call fails: the user can
    be stranded in the flow otherwise (profile can be built later)."""
    import pianke.flows.interview as iv

    importlib.reload(iv)
    store.set_pref("interview_plan", {"domains": ["film"]})
    store.add_turn("user", "我喜欢花样年华")
    store.add_turn("assistant", "它哪里打动你？")

    def boom(*a, **k):
        raise RuntimeError("模型不可用")

    monkeypatch.setattr(iv.client, "chat", boom)
    # the error still reaches server.sse (which words it for the UI) ...
    with pytest.raises(RuntimeError):
        list(iv.finish())
    # ... but onboarding is marked done, so the app opens next time
    assert store.get_pref("onboarded") is True
    assert "film" in store.get_pref("domains_onboarded")
