"""Cold start, in two halves: recognise, then talk.

1. Cover wall: the user taps works they love (once) or didn't like (twice).
   Picking from covers is far cheaper than recalling titles, and every tap
   is already a verified id — nothing to extract or resolve.
2. A short conversation built from those taps: why the loved ones landed,
   what went wrong with the disliked ones (or the contrast question when
   there are none), and — on the first run only — habits and hard no's.
   The model replies to each answer in a sentence that shows it understood.

The first run covers whichever shelves the user chose; a shelf they skipped
gets the same wall + two questions the first time they open it."""

from __future__ import annotations

import threading
from typing import Iterator

from ..catalog import library
from ..catalog import search as catalog
from ..domains import WORDS
from ..llm import client
from ..lookup import covers
from ..memory import store
from . import profile as profile_flow

FIRST_Q = {
    "film": "先聊一部片吧。最近看过、到现在还会想起来的一部是什么？它哪里打动你？",
    "book": "先聊一本书吧。最近读过、到现在还会想起来的一本是什么？它哪里打动你？",
    "music": "先聊聊音乐。最近反复在听的一张专辑或一位歌手是谁？它哪里吸引你？",
}
CONTRAST_Q = {
    "film": "有没有一部大家都夸，你却没看下去的？说说为什么。",
    "book": "有没有一本大家都夸，你却读不下去的？说说为什么。",
    "music": "有没有大家都爱、你却听不进去的歌手或专辑？说说为什么。",
}
HABIT_VERB = {"film": "看片", "book": "读书", "music": "听歌"}
AVOID_Q = "最后，有没有你绝对不想碰的东西？比如太血腥、太压抑，或者节奏太慢。"

REPLY_SYSTEM = """你是「片刻」，一个住在用户 Mac 上、陪他看片、读书、听歌的伙伴，正在认识用户。
用户刚回答了你的一个问题。用一到两句话回应，最多 50 个字：
- 说出你从回答里听到的具体东西，比如他在意的是哪种感觉，不要复述作品清单。
- 语气平实、温和，像朋友聊天，不夸张，不用感叹号，不用表情。
- 不要提问，不要推荐任何作品，下一个问题会由界面给出。
- 如果用户说不知道或跳过，就简单接一句“没关系”之类的话。"""


def _names(ids: list[str], k: int = 3) -> str:
    ts = catalog.get_many(ids[:k])
    names = [f"《{t['name']}》" for t in ts]
    if len(names) <= 1:
        return "".join(names)
    return "、".join(names[:-1]) + "和" + names[-1]


# ---------------------------------------------------------------- wall

def wall_pool(domain: str, page: int = 0, exclude: set[str] | None = None, n: int = 24) -> list[dict]:
    """Twice as many candidates as the wall shows, so works whose covers
    are already on disk can fill it."""
    seen = {i["id"] for i in store.items(domain=domain)}
    ex = (exclude or set()) | seen
    if domain == "film":
        return catalog.wall(n=2 * n, page=page, exclude=ex)
    return library.wall(domain, n=2 * n, page=page, exclude=ex)


_warming: set[str] = set()
_warm_lock = threading.Lock()


def warm_covers(ids: list[str]) -> None:
    """Fetch covers in the background, each id once at a time."""
    with _warm_lock:
        ids = [i for i in ids if i not in _warming]
        _warming.update(ids)
    if not ids:
        return

    def run() -> None:
        try:
            covers.prefetch(ids)
        finally:
            with _warm_lock:
                _warming.difference_update(ids)

    threading.Thread(target=run, daemon=True).start()


def wall(domain: str, page: int = 0, exclude: set[str] | None = None, n: int = 24) -> list[dict]:
    """Covers people can recognise at a glance: works with a cover on disk
    come first, then ones not looked up yet, and works known to have no
    cover last. The rest of the pool is fetched for the next batch."""
    pool = wall_pool(domain, page, exclude, n)
    st = covers.state([t["id"] for t in pool])
    rank = {"ok": 0, "unknown": 1, "miss": 2}
    picked = sorted(pool, key=lambda t: rank[st[t["id"]]])[:n]
    warm_covers([t["id"] for t in pool if st[t["id"]] == "unknown"])
    return picked


def save_marks(domain: str, marks: dict[str, str]) -> dict:
    """marks: id → love | dislike. A tap is a stance, not a rating: it is
    stored as such and the profile reads it that way."""
    stance = {"love": "喜欢", "dislike": "不喜欢"}
    prev = store.get_pref(f"wall:{domain}", {})
    for item_id in set(prev) - set(marks):  # un-tapped since last save
        it = store.item(item_id)
        if it and it["source"] == "onboard" and not it["words"]:
            store.delete_item(item_id)
    for item_id, m in marks.items():
        if m not in stance:
            continue
        store.upsert_item(item_id, status="watched", context={"stance": stance[m]},
                          source="onboard", origin="onboard")
    store.set_pref(f"wall:{domain}", marks)
    store.event("wall", {"domain": domain, "marks": marks})
    return {"saved": len(marks)}


# ---------------------------------------------------------------- talk

def _plan(domains: list[str], first_run: bool) -> list[str]:
    marks: dict[str, str] = {}
    for d in domains:
        marks.update(store.get_pref(f"wall:{d}", {}))
    loved = [i for i, m in marks.items() if m == "love"]
    disliked = [i for i, m in marks.items() if m == "dislike"]
    main = domains[0]
    qs = []
    if loved:
        qs.append(f"你点了{_names(loved)}。挑一个说说，它哪里打动你？")
    else:
        qs.append(FIRST_Q[main])
    if disliked:
        qs.append(f"你对{_names(disliked, 1)}点了不喜欢。是哪里不对胃口？")
    else:
        qs.append(CONTRAST_Q[main])
    if first_run:
        verbs = "、".join(HABIT_VERB[d] for d in domains)
        qs.append(f"你一般什么时候{verbs}？一个人，还是和谁一起？")
        qs.append(AVOID_Q)
    return qs


def _questions() -> list[str]:
    return store.get_pref("interview_plan", {}).get("questions") or [FIRST_Q["film"]]


def state() -> dict:
    turns = store.turns()
    qs = _questions()
    answered = sum(1 for t in turns if t["role"] == "user")
    return {
        "turns": turns,
        "answered": answered,
        "total": len(qs),
        "next_question": qs[answered] if answered < len(qs) else None,
        "domains": store.get_pref("interview_plan", {}).get("domains", ["film"]),
    }


def talked() -> bool:
    """Whether the user has had the full talk (habits, things to avoid).
    The first run now ends at the cover wall; the talk is offered later.
    People set up before that had it during onboarding."""
    return bool(store.get_pref("talked", store.get_pref("onboarded", False)))


def start(domains: list[str] | None = None) -> dict:
    domains = [d for d in (domains or ["film"]) if d in WORDS] or ["film"]
    first_run = not talked()
    qs = _plan(domains, first_run)
    store.set_pref("interview_plan", {"domains": domains, "questions": qs, "first_run": first_run})
    store.clear_interview()
    store.add_turn("assistant", qs[0])
    return state()


def answer(text: str) -> Iterator[dict]:
    """Stream the model's reply to one answer, then the next question."""
    qs = _questions()
    turns = store.turns()
    answered = sum(1 for t in turns if t["role"] == "user")
    question = qs[min(answered, len(qs) - 1)]
    store.add_turn("user", text)
    store.event("interview_answer", {"question": question, "answer": text})
    msgs = [
        {"role": "system", "content": REPLY_SYSTEM},
        {"role": "user", "content": f"你问：{question}\n用户答：{text}"},
    ]
    reply = ""
    try:
        for d in client.stream("big", msgs, task="interview_reply", max_tokens=120,
                               sampling={"temperature": 0.7, "top_p": 0.95}):
            reply += d
            yield {"type": "delta", "text": d}
    except Exception as e:  # noqa: BLE001 — the answer is saved; keep the talk going
        store.event("interview_reply_failed", {"error": str(e)[:200]})
        if not reply:
            reply = "记下了。"
            yield {"type": "delta", "text": reply}
    reply = reply.strip()
    store.add_turn("assistant", reply)
    nxt = answered + 1
    if nxt < len(qs):
        store.add_turn("assistant", qs[nxt])
        yield {"type": "question", "text": qs[nxt], "index": nxt}
    else:
        yield {"type": "complete"}


EXTRACT_SCHEMA = {
    "type": "object",
    "properties": {
        "titles": {
            "type": "array",
            "maxItems": 14,
            "items": {
                "type": "object",
                "properties": {
                    "domain": {"type": "string", "enum": ["film", "book", "music"]},
                    "title": {"type": "string"},
                    "original": {"type": "string"},
                    "creator": {"type": "string"},
                    "year": {"type": "integer"},
                    "stance": {"type": "string", "enum": ["loved", "liked", "disliked", "dropped"]},
                    "liked": {"type": "array", "items": {"type": "string"}, "maxItems": 4},
                    "disliked": {"type": "array", "items": {"type": "string"}, "maxItems": 4},
                    "quote": {"type": "string"},
                },
                "required": ["domain", "title", "original", "creator", "year", "stance", "liked", "disliked", "quote"],
            },
        },
        "avoid": {"type": "array", "items": {"type": "string"}, "maxItems": 6},
        "when": {"type": "string"},
        "with": {"type": "string"},
    },
    "required": ["titles", "avoid", "when", "with"],
}

EXTRACT_SYSTEM = """把用户在访谈里说的话整理成结构化数据。
- titles：用户提到的每一部作品。domain：电影或剧集 film，书 book，专辑、歌手或歌曲 music（提到歌手或歌曲时，title 填他最可能指的那张专辑，不确定就填歌手名）。
  title 用用户写的名字；original 填你确定的原名，不确定就填空字符串；creator 填导演、作者或歌手，不确定填空字符串；year 填你确定的年份，不确定填 0。
  stance：很爱 loved，喜欢 liked，不喜欢 disliked，看不下去、读不下去、听不进去或弃了 dropped。
  liked / disliked：用户对这部作品喜欢或不喜欢的具体方面，每条不超过 8 个字，比如“节奏克制”“配乐太满”。
  quote：从用户原话里原样摘一句最能代表他对这部作品感受的话，一个字都不要改。
- avoid：用户明确不想碰的东西，每条不超过 8 个字。
- when / with：用户一般什么时候看、读、听，和谁一起，用他的说法，没提到就填空字符串。
不要编造用户没说过的作品或感受。用户在封面墙上点过的作品列在最前面，他提到时用同样的名字。"""


def _resolve(t: dict) -> dict | None:
    if t["domain"] == "film":
        return catalog.resolve(t["title"], t["year"] or None, t["original"] or None, use_online=True)
    return library.resolve(t["domain"], t["title"], t["creator"] or None, t["year"] or None,
                           t["original"] or None)


def finish() -> Iterator[dict]:
    """Extract → resolve (films locally; books and albums on the shelf, then
    online by title) → seed L1 → build L2. The model steps are best-effort:
    if one fails onboarding still counts as done, so a missing or broken
    model can't trap the user in the flow — the profile can be built later
    from the profile page. The error itself propagates, so server.sse words
    it for the UI ("本机模型还没有准备好…") instead of showing a raw one."""
    plan = store.get_pref("interview_plan", {})
    domains = plan.get("domains", ["film"])
    if not store.get_pref("onboarded", False) and "talked" not in _prefs_set():
        store.set_pref("talked", False)
    if any(t["role"] == "user" for t in store.turns()) and plan.get("first_run"):
        store.set_pref("talked", True)
    try:
        yield from _finish_steps()
    finally:
        store.set_pref("onboarded", True)
        store.set_pref("domains_onboarded", sorted(set(onboarded_domains()) | set(domains)))
    yield {"type": "complete"}


def _finish_steps() -> Iterator[dict]:
    plan = store.get_pref("interview_plan", {})
    domains = plan.get("domains", ["film"])
    turns = store.turns()
    user_text = "\n".join(t["text"] for t in turns if t["role"] == "user")
    marked = []
    for d in domains:
        marked += list(store.get_pref(f"wall:{d}", {}).items())
    wall_ts = {t["id"]: t for t in catalog.get_many([i for i, _ in marked])}
    wall_txt = "；".join(
        f"《{wall_ts[i]['name']}》（{WORDS[wall_ts[i].get('domain', 'film')]['label']}，{'喜欢' if m == 'love' else '不喜欢'}）"
        for i, m in marked if i in wall_ts
    )
    # a question nobody answered (onboarding now can end at the wall) is noise
    answered = [t for i, t in enumerate(turns)
                if t["role"] == "user" or any(u["role"] == "user" for u in turns[i + 1:])]
    transcript = (
        (f"封面墙上点过：{wall_txt}\n\n" if wall_txt else "")
        + "\n".join(f"{'问' if t['role'] == 'assistant' else '答'}：{t['text']}" for t in answered)
    )
    yield {"type": "step", "key": "extract", "status": "running"}
    data, stats = client.chat(
        "big",
        [{"role": "system", "content": EXTRACT_SYSTEM}, {"role": "user", "content": transcript}],
        task="interview_extract",
        schema=EXTRACT_SCHEMA,
        max_tokens=1800,
    )
    yield {"type": "step", "key": "extract", "status": "done",
           "detail": f"听到 {len(data['titles'])} 部作品" + (f"，封面墙上点了 {len(marked)} 个" if marked else "")}

    yield {"type": "step", "key": "resolve", "status": "running"}
    for i, m in marked:
        t = wall_ts.get(i)
        if t:
            yield {"type": "title", "name": t["name"], "year": t.get("year"), "id": i, "found": True,
                   "domain": t.get("domain", "film"), "wall": m}
    from ..lookup.online import _norm, t2s

    # a work the user tapped on the wall is the same work when they talk
    # about it — don't look it up again (the lookup may land on another edition)
    by_name = {(wall_ts[i].get("domain", "film"), _norm(t2s(wall_ts[i]["name"]))): wall_ts[i] for i, _ in marked if i in wall_ts}
    found, missing = [], []
    for t in data["titles"]:
        hit = by_name.get((t["domain"], _norm(t2s(t["title"])))) or _resolve(t)
        if hit is None:
            missing.append(t["title"])
            yield {"type": "title", "name": t["title"], "found": False, "domain": t["domain"]}
            continue
        quote = t["quote"] if t["quote"] and t["quote"] in user_text else ""
        # stars are only ever what the user gives; what they said is a stance
        stance = {"loved": "很爱", "liked": "喜欢", "disliked": "不喜欢", "dropped": "弃了"}[t["stance"]]
        status = "dropped" if t["stance"] == "dropped" else "watched"
        prev = store.item(hit["id"])
        on_wall = hit["id"] in wall_ts
        store.upsert_item(
            hit["id"],
            status=status if not on_wall else None,
            context=None if on_wall else {"stance": stance},
            liked=t["liked"],
            disliked=t["disliked"],
            words=quote or None,
            source=prev["source"] if prev else "interview",
            origin="past",
        )
        found.append(hit)
        if hit["id"] not in wall_ts:
            yield {"type": "title", "name": hit["name"], "year": hit.get("year"), "id": hit["id"],
                   "found": True, "domain": hit.get("domain", "film")}
    store.set_pref("avoid", list(dict.fromkeys(store.get_pref("avoid", []) + data["avoid"])))
    if data["when"] or data["with"]:
        store.set_pref("habits", {"when": data["when"], "with": data["with"]})
    store.event("interview_done", {"domains": domains, "found": [h["id"] for h in found], "missing": missing})
    yield {"type": "step", "key": "resolve", "status": "done",
           "detail": f"核实了 {len(found) + len(marked)} 部" + (f"，{len(missing)} 部没找到" if missing else "")}

    yield from profile_flow.consolidate(reason="interview")


def onboarded_domains() -> list[str]:
    got = store.get_pref("domains_onboarded", None)
    if got is None:  # set up before books and music existed: films only
        return ["film"] if store.get_pref("onboarded", False) else []
    return got


def _prefs_set() -> set[str]:
    with store.db() as c:
        return {r["key"] for r in c.execute("select key from prefs")}
