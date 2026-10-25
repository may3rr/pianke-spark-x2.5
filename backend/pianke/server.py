"""Local HTTP service for the desktop app. Binds 127.0.0.1 only; every
request but /health carries the per-launch token the Electron main process
generated."""

from __future__ import annotations

import asyncio
import json
import os
import threading
from concurrent.futures import ThreadPoolExecutor
from contextlib import asynccontextmanager
from typing import Any, Callable, Iterator

from fastapi import Depends, FastAPI, Header, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from pydantic import BaseModel
from sse_starlette.sse import EventSourceResponse

from .catalog import library
from .catalog import search as catalog
from .config import DATA_DIR, USER_DB
from .domains import DOMAINS, PASS_REASONS, WORDS, reason_label
from .flows import auto
from .flows import feedback as feedback_flow
from .flows import interview as interview_flow
from .flows import profile as profile_flow
from .flows import recommend as rec_flow
from .llm import client as llm_client
from .llm import settings as llm_settings
from .llm.runtime import runtime
from .lookup import covers, net, online, web
from .memory import store

TOKEN = os.environ.get("PIANKE_TOKEN")


@asynccontextmanager
async def lifespan(_: FastAPI):
    store.init()
    if os.environ.get("PIANKE_NO_PARENT_WATCH") != "1":
        runtime.watch_parent()
    if os.environ.get("PIANKE_NO_MODELS") != "1":
        runtime.start_all()
    if store.get_pref("onboarded", False) and os.environ.get("PIANKE_NO_PREFETCH") != "1":
        # covers for the records and past picks, so the shelves open with art
        ids = [i["id"] for i in store.items()]
        ids += [p["id"] for r in store.recs(60) for p in r["picks"]]
        interview_flow.warm_covers(list(dict.fromkeys(ids)))
    if not store.get_pref("onboarded", False) and os.environ.get("PIANKE_NO_PREFETCH") != "1":
        # first launch: the walls come ~30 s in; fetch their covers meanwhile,
        # one lane per shelf so books don't queue behind films
        for d in ("film", "book", "music"):
            interview_flow.warm_covers([t["id"] for t in interview_flow.wall_pool(d)])
    auto.schedule()
    yield
    if os.environ.get("PIANKE_KEEP_MODELS") != "1":
        runtime.stop_all()


app = FastAPI(lifespan=lifespan)
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)


def auth(x_pianke_token: str | None = Header(default=None)) -> None:
    if TOKEN and x_pianke_token != TOKEN:
        raise HTTPException(401, "bad token")


def auth_q(t: str | None = Query(default=None)) -> None:
    """<img> can't send headers; covers take the token as ?t=."""
    if TOKEN and t != TOKEN:
        raise HTTPException(401, "bad token")


def sse(gen_fn: Callable[[], Iterator[dict]]) -> EventSourceResponse:
    """Run a blocking generator in a thread and stream its dicts as SSE.
    When the client goes away (the user pressed 取消) the generator is
    closed at its next step, so a cancelled recommendation is not saved."""
    q: asyncio.Queue = asyncio.Queue()
    loop = asyncio.get_running_loop()
    sentinel = object()
    gone = threading.Event()

    def worker() -> None:
        gen = gen_fn()
        try:
            for ev in gen:
                if gone.is_set():
                    gen.close()
                    break
                loop.call_soon_threadsafe(q.put_nowait, ev)
        except Exception as e:  # surfaced to the UI as an error event
            loop.call_soon_threadsafe(
                q.put_nowait, {"type": "error", "message": _friendly(e)}
            )
        finally:
            loop.call_soon_threadsafe(q.put_nowait, sentinel)

    threading.Thread(target=worker, daemon=True).start()

    async def events():
        try:
            while True:
                ev = await q.get()
                if ev is sentinel:
                    break
                yield {"data": json.dumps(ev, ensure_ascii=False)}
        finally:
            gone.set()

    return EventSourceResponse(events(), ping=10)


def _friendly(e: Exception) -> str:
    msg = str(e)
    remote = runtime.servers["big"].remote
    if "ConnectError" in type(e).__name__ or "Connection refused" in msg:
        if remote:
            return f"连不上 {remote['host']}。检查接口地址和网络。"
        return "本机模型还没有准备好。稍等几秒再试一次。"
    if "Timeout" in type(e).__name__ and remote:
        return f"{remote['host']} 太久没有回应。稍后再试一次。"
    return msg or type(e).__name__


# ---------------------------------------------------------------- status

@app.get("/health")
def health() -> dict:
    return {"ok": True}


@app.get("/status", dependencies=[Depends(auth)])
def status() -> dict:
    prof = store.profile()
    its = store.items()
    return {
        "models": runtime.public(),
        "llm": llm_settings.public(llm_settings.load()),
        "catalog": catalog.stats(),
        "library": library.stats(),
        "onboarded": bool(store.get_pref("onboarded", False)),
        "domains_onboarded": interview_flow.onboarded_domains(),
        "name": store.get_pref("name", ""),
        "counts": {
            s: sum(1 for i in its if i["status"] == s)
            for s in ("watched", "dropped", "want", "rejected")
        },
        "domain_counts": {
            d: {s: sum(1 for i in its if i["status"] == s and i["domain"] == d)
                for s in ("watched", "dropped", "want", "rejected")}
            for d in DOMAINS
        },
        "covers_online": bool(store.get_pref("covers_online", True)),
        "words": WORDS,
        "pass_reasons": {d: [{"key": k, "label": reason_label(d, k), "effect": v["effect"]}
                             for k, v in PASS_REASONS.items()] for d in DOMAINS},
        "profile_version": prof["version"] if prof else None,
        "stale": store.get_pref("stale", 0),
        "profile_auto": auto.running,
        "profile_unseen": bool(store.get_pref("profile_unseen", False)),
        "talked": interview_flow.talked(),
        "data_path": str(USER_DB),
    }


@app.get("/usage", dependencies=[Depends(auth)])
def usage() -> dict:
    bench_path = os.path.join(os.path.dirname(USER_DB), "bench_speed.json")
    repo_bench = str(DATA_DIR / "bench_speed.json")
    bench = None
    for p in (bench_path, repo_bench):
        if os.path.exists(p):
            with open(p) as f:
                bench = json.load(f)
            break
    return {**store.llm_summary(), "bench": bench, "big_ctx": runtime.servers["big"].ctx}


# ---------------------------------------------------------------- models

@app.get("/llm", dependencies=[Depends(auth)])
def get_llm() -> dict:
    return llm_settings.public(llm_settings.load())


class LlmIn(BaseModel):
    mode: str
    base_url: str = ""
    api_key: str | None = None  # None keeps the saved key
    big_model: str = ""
    small_model: str = ""
    ctx: int = 131072


@app.put("/llm", dependencies=[Depends(auth)])
def put_llm(body: LlmIn) -> dict:
    s = llm_settings.save(body.model_dump())
    runtime.apply(s)
    return llm_settings.public(s)


class ServicesIn(BaseModel):
    tmdb_key: str | None = None  # None keeps the saved key
    search_provider: str | None = None
    exa_key: str | None = None
    tavily_key: str | None = None


@app.put("/services", dependencies=[Depends(auth)])
def put_services(body: ServicesIn) -> dict:
    before = llm_settings.load()["tmdb_key"]
    s = llm_settings.save(body.model_dump())
    if s["tmdb_key"] != before:
        # posters that weren't found before may be on TMDB
        with net.cache() as c:
            c.execute("delete from covers where ok=0")
    return llm_settings.public(s)


@app.post("/services/test", dependencies=[Depends(auth)])
def test_services() -> dict:
    out = {}
    if llm_settings.load()["tmdb_key"]:
        out["tmdb"] = bool(online.tmdb_poster("tt0118694"))  # 花样年华
    if web.enabled():
        rows = web.search("花样年华 影评", n=2)
        out["search"] = rows[0]["title"] if rows else ""
    return out


@app.post("/llm/test", dependencies=[Depends(auth)])
def test_llm() -> dict:
    """One short structured call per distinct model, so a wrong key, URL or
    model name shows up here rather than in the middle of a recommendation."""
    out = []
    seen = set()
    for key in ("big", "small"):
        name = runtime.servers[key].name
        if name in seen:
            continue
        seen.add(name)
        try:
            data, stats = llm_client.chat(
                key,
                [{"role": "user", "content": "用一个词回答：天空通常是什么颜色？"}],
                task="connection_test",
                schema={"type": "object", "properties": {"answer": {"type": "string"}},
                        "required": ["answer"]},
                max_tokens=64,
                sampling={"temperature": 0.2},
            )
            out.append({"model": name, "ok": True, "answer": data["answer"], "seconds": stats["seconds"]})
        except Exception as e:  # shown next to the form
            out.append({"model": name, "ok": False, "error": _friendly(e)})
    return {"results": out}


class NameIn(BaseModel):
    name: str


@app.put("/name", dependencies=[Depends(auth)])
def put_name(body: NameIn) -> dict:
    store.set_pref("name", body.name.strip()[:24])
    return {"ok": True}


# ---------------------------------------------------------------- interview

class StartIn(BaseModel):
    domains: list[str] = ["film"]


@app.post("/interview/start", dependencies=[Depends(auth)])
def interview_start(body: StartIn | None = None) -> dict:
    return interview_flow.start(body.domains if body else None)


@app.get("/coldstart/wall", dependencies=[Depends(auth)])
def coldstart_wall(domain: str = "film", page: int = 0, exclude: str = "") -> list[dict]:
    if domain not in DOMAINS:
        raise HTTPException(400, "unknown domain")
    return interview_flow.wall(domain, page, {i for i in exclude.split(",") if i})


class MarksIn(BaseModel):
    domain: str
    marks: dict[str, str]


@app.post("/coldstart/marks", dependencies=[Depends(auth)])
def coldstart_marks(body: MarksIn) -> dict:
    return interview_flow.save_marks(body.domain, body.marks)


@app.get("/interview", dependencies=[Depends(auth)])
def interview_state() -> dict:
    return interview_flow.state()


class TextIn(BaseModel):
    text: str


@app.post("/interview/answer", dependencies=[Depends(auth)])
async def interview_answer(body: TextIn):
    return sse(_busy(lambda: interview_flow.answer(body.text)))


@app.post("/interview/finish", dependencies=[Depends(auth)])
async def interview_finish():
    def run() -> Iterator[dict]:
        with auto.consolidating():
            yield from interview_flow.finish()
    return sse(_busy(run))


# ---------------------------------------------------------------- recommend

class RecIn(BaseModel):
    text: str = ""
    chips: dict[str, str] = {}
    mode: str = "layered"
    domain: str = "film"
    from_list: bool = False


def _busy(gen_fn: Callable[[], Iterator[dict]]) -> Callable[[], Iterator[dict]]:
    """Foreground model work; background consolidation waits for it."""
    def run() -> Iterator[dict]:
        with auto.busy():
            yield from gen_fn()
    return run


@app.post("/recommend", dependencies=[Depends(auth)])
async def recommend(body: RecIn):
    req = {"text": body.text, "chips": body.chips, "domain": body.domain}
    if body.from_list:
        req["from_list"] = True
    return sse(_busy(lambda: rec_flow.run(req, mode=body.mode)))


@app.get("/recs", dependencies=[Depends(auth)])
def recs() -> list[dict]:
    out = store.recs()
    ch = feedback_flow.chosen()
    for r in out:
        r["domain"] = r["request"].get("domain") or "film"
        r["chosen"] = ch.get(str(r["id"]))
    return out


class ChooseIn(BaseModel):
    item_id: str


@app.post("/recs/{rec_id}/choose", dependencies=[Depends(auth)])
def rec_choose(rec_id: int, body: ChooseIn) -> dict:
    """"就看这部": tonight's pick. The check-in asks about this one only."""
    feedback_flow.choose(rec_id, body.item_id)
    return {"ok": True, "chosen": body.item_id}


@app.get("/checkins", dependencies=[Depends(auth)])
def checkins(domain: str | None = None) -> list[dict]:
    return feedback_flow.checkins(domain)


@app.post("/checkins/{item_id}/dismiss", dependencies=[Depends(auth)])
def checkin_dismiss(item_id: str) -> dict:
    feedback_flow.dismiss_checkin(item_id)
    store.event("checkin_dismiss", {"id": item_id})
    return {"ok": True}


@app.post("/checkins/{item_id}/snooze", dependencies=[Depends(auth)])
def checkin_snooze(item_id: str) -> dict:
    out = feedback_flow.snooze_checkin(item_id)
    store.event("checkin_snooze", {"id": item_id, **out})
    return out


@app.post("/checkins/night/{rec_id}/dismiss", dependencies=[Depends(auth)])
def checkin_night_dismiss(rec_id: int) -> dict:
    """"都没看": the whole night is answered; nothing goes into the profile."""
    feedback_flow.dismiss_night(rec_id)
    store.event("checkin_night", {"rec_id": rec_id})
    return {"ok": True}


# ---------------------------------------------------------------- items

def _with_title(it: dict) -> dict:
    return {**it, "title": catalog.get(it["id"])}


@app.get("/items", dependencies=[Depends(auth)])
def items(status: str | None = None, domain: str | None = None) -> list[dict]:
    its = store.items(status, domain)
    ts = {t["id"]: t for t in catalog.get_many([i["id"] for i in its])}
    return [{**i, "title": ts.get(i["id"])} for i in its]


def _known(item_id: str) -> None:
    if not catalog.get(item_id):
        raise HTTPException(404, "找不到这部作品")


@app.post("/items/{item_id}/feedback", dependencies=[Depends(auth)])
def item_feedback(item_id: str, body: TextIn) -> dict:
    _known(item_id)
    out = feedback_flow.log(item_id, text=body.text)
    out["item"] = _with_title(out["item"])
    return out


class LogIn(BaseModel):
    status: str = "watched"
    rating: float | None = None
    text: str = ""
    origin: str | None = None
    done_on: str | None = None


@app.post("/items/{item_id}/log", dependencies=[Depends(auth)])
def item_log(item_id: str, body: LogIn) -> dict:
    _known(item_id)
    if body.status not in ("watched", "dropped"):
        raise HTTPException(400, "unknown status")
    out = feedback_flow.log(item_id, status=body.status, rating=body.rating, text=body.text,
                            origin=body.origin, done_on=body.done_on)
    feedback_flow.dismiss_checkin(item_id)
    auto.schedule()
    out["item"] = _with_title(out["item"])
    return out


class PassIn(BaseModel):
    reason: str
    words: str | None = None
    rec_id: int | None = None


@app.post("/items/{item_id}/pass", dependencies=[Depends(auth)])
def item_pass(item_id: str, body: PassIn) -> dict:
    _known(item_id)
    if body.reason not in PASS_REASONS:
        raise HTTPException(400, "unknown reason")
    out = feedback_flow.pass_(item_id, body.reason, body.words, body.rec_id)
    # "save it for later" is exactly what the check-in asks about later
    if out["effect"] != "want":
        feedback_flow.dismiss_checkin(item_id)
    auto.schedule()
    out["item"] = _with_title(out["item"])
    return out


class EditIn(BaseModel):
    rating: float | None = None
    clear_rating: bool = False
    done_on: str | None = None
    status: str | None = None
    words: str | None = None


@app.patch("/items/{item_id}", dependencies=[Depends(auth)])
def item_edit(item_id: str, body: EditIn) -> dict:
    if not store.item(item_id):
        raise HTTPException(404, "没有这条记录")
    if body.status and body.status not in ("watched", "dropped", "want", "rejected"):
        raise HTTPException(400, "unknown status")
    it = feedback_flow.edit(item_id, rating=body.rating, clear_rating=body.clear_rating,
                            done_on=body.done_on, status=body.status, words=body.words)
    auto.schedule()
    return _with_title(it)


# cover fetches wait on per-site rate limits; give them their own threads so
# a wall of 24 covers can't starve the rest of the API
_cover_pool = ThreadPoolExecutor(6, thread_name_prefix="cover")


@app.get("/cover/{item_id}", dependencies=[Depends(auth_q)])
async def cover(item_id: str):
    p = await asyncio.get_running_loop().run_in_executor(_cover_pool, covers.cover, item_id)
    if not p:
        raise HTTPException(404, "no cover")
    return FileResponse(p, media_type="image/jpeg", headers={"Cache-Control": "max-age=604800"})


class StatusIn(BaseModel):
    status: str
    words: str | None = None
    source: str = "rec"


@app.post("/items/{item_id}/status", dependencies=[Depends(auth)])
def item_status(item_id: str, body: StatusIn) -> dict:
    _known(item_id)
    if body.status not in ("want", "rejected", "watched", "dropped"):
        raise HTTPException(400, "unknown status")
    if body.source not in ("rec", "manual"):
        raise HTTPException(400, "unknown source")
    return _with_title(feedback_flow.set_status(item_id, body.status, body.words, source=body.source))


@app.delete("/items/{item_id}", dependencies=[Depends(auth)])
def item_delete(item_id: str) -> dict:
    store.delete_item(item_id)
    store.event("delete", {"id": item_id})
    return {"ok": True}


@app.get("/search", dependencies=[Depends(auth)])
def search(q: str, domain: str = "film") -> list[dict]:
    if domain == "film":
        return catalog.search(q, use_online=True)
    return library.search(domain, q)


@app.get("/titles", dependencies=[Depends(auth)])
def titles(ids: str) -> list[dict]:
    return catalog.get_many([i for i in ids.split(",") if i])


# ---------------------------------------------------------------- profile

@app.get("/profile", dependencies=[Depends(auth)])
def get_profile() -> dict[str, Any]:
    p = store.profile()
    if not p:
        return {"profile": None, "history": [], "titles": {}}
    ids = sorted({e for s in p["doc"]["sections"] for c in s["claims"] for e in c["evidence"]})
    return {
        "profile": p,
        "history": store.profile_history(),
        "titles": {t["id"]: t for t in catalog.get_many(ids)},
    }


@app.post("/profile/consolidate", dependencies=[Depends(auth)])
async def consolidate():
    def run():
        with auto.consolidating():
            yield from auto.run(profile_flow.consolidate(reason="manual"))

    return sse(run)


@app.put("/profile/seen", dependencies=[Depends(auth)])
def profile_seen() -> dict:
    store.set_pref("profile_unseen", False)
    return {"ok": True}


class ProfileIn(BaseModel):
    doc: dict


@app.put("/profile", dependencies=[Depends(auth)])
def put_profile(body: ProfileIn) -> dict:
    return profile_flow.edit(body.doc)


# ---------------------------------------------------------------- data

class PrefIn(BaseModel):
    covers_online: bool


@app.put("/prefs", dependencies=[Depends(auth)])
def put_prefs(body: PrefIn) -> dict:
    store.set_pref("covers_online", body.covers_online)
    return {"ok": True}


@app.get("/export", dependencies=[Depends(auth)])
def export() -> dict:
    return {
        "items": store.items(),
        "profile": store.profile(),
        "recs": store.recs(500),
        "events": store.events(),
    }


@app.post("/reset", dependencies=[Depends(auth)])
def reset() -> dict:
    store.wipe()
    return {"ok": True}
