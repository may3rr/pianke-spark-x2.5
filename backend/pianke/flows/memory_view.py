"""Turns stored memory into prompt text. This is where the layered design
lives: recommendation reads a bounded slice (L2 profile + L3 recent + the
few L1 records that matter); consolidation reads everything."""

from __future__ import annotations

import time
from datetime import datetime

from ..catalog import search as catalog
from ..domains import WORDS, tag
from ..memory import store


def status_zh(domain: str, status: str | None) -> str:
    w = WORDS[domain]
    return {"watched": w["done"], "dropped": w["dropped"], "want": f"想{w['verb']}",
            "rejected": f"不想{w['verb']}"}.get(status or "", status or "")


def stars(r: float | None) -> str:
    if r is None:
        return ""
    return f"{r:g}/5"


def _date(ts: float) -> str:
    return datetime.fromtimestamp(ts).strftime("%Y-%m-%d")


def record_line(it: dict, t: dict | None, *, words_limit: int | None = 160) -> str:
    dom = it.get("domain") or "film"
    name = t["name"] if t else it["id"]
    year = f"（{t['year']}）" if t and t.get("year") else ""
    by = f" {'、'.join(t['creators'][:2])}" if t and t.get("creators") else ""
    status = status_zh(dom, it["status"])
    if it.get("reason"):
        status += f"（{it['reason']}）"
    bits = [f"[{it['id']}] 〔{tag(dom)}〕{name}{year}{by}", status]
    if it.get("rating") is not None:
        bits.append(stars(it["rating"]))
    if it["liked"]:
        bits.append("喜欢：" + "、".join(it["liked"]))
    if it["disliked"]:
        bits.append("不喜欢：" + "、".join(it["disliked"]))
    ctx = it.get("context") or {}
    if ctx.get("stance"):
        how = "在封面墙上点了" if it.get("source") == "onboard" else "说"
        bits.append(f"{how}{ctx['stance']}")
    c = "，".join(v for v in (ctx.get("mood"), ctx.get("with"), ctx.get("when")) if v)
    if c:
        bits.append(f"当时：{c}")
    words = (it.get("words") or "").replace("\n", " / ")
    if words:
        if words_limit and len(words) > words_limit:
            words = words[:words_limit] + "…"
        bits.append(f"原话：“{words}”")
    bits.append(it.get("done_on") or _date(it["updated"]))
    return " ｜ ".join(bits)


def profile_text(p: dict | None) -> str:
    if not p:
        return "（还没有口味画像）"
    doc = p["doc"]
    out = [f"一句话：{doc.get('summary', '')}"]
    for sec in doc.get("sections", []):
        if not sec.get("claims"):
            continue
        out.append(f"【{sec['title']}】")
        for c in sec["claims"]:
            ev = "，".join(c.get("evidence") or [])
            out.append(f"- {c['text']}" + (f"（依据 {ev}）" if ev else ""))
    return "\n".join(out)


def recent_text(days: float = 14, limit: int = 8) -> str:
    """L3: what the user has been watching, reading, listening to and
    feeling lately — including picks they passed on "not right now", which
    is the only place those land."""
    since = time.time() - days * 86400
    its = [i for i in store.items() if i["updated"] >= since and i["status"] in ("watched", "dropped")]
    its = its[:limit]
    passes = [e for e in store.events(since, ("pass",)) if e.get("effect") == "moment"][-4:]
    if not its and not passes:
        return "（最近两周没有新的记录）"
    ids = [i["id"] for i in its] + [e["id"] for e in passes]
    ts = {t["id"]: t for t in catalog.get_many(ids)}
    lines = [record_line(i, ts.get(i["id"]), words_limit=80) for i in its]
    for e in passes:
        t = ts.get(e["id"])
        note = f"，说：“{e['words']}”" if e.get("words") else ""
        lines.append(f"{_date(e['ts'])} 跳过了{t['name'] if t else e['id']}（{e['reason']}，只是当时不合适{note}）")
    return "\n".join(lines)


def relevant_records(pool: list[dict], k: int = 10) -> list[dict]:
    """The L1 records most related to this shortlist: same-shelf records
    with the strongest feelings and genre overlap, plus a few of the
    strongest from the other shelves (taste carries across)."""
    mem = [i for i in store.items() if i["status"] in ("watched", "dropped", "rejected")]
    if not mem:
        return []
    dom = pool[0].get("domain", "film") if pool else "film"
    ts = {t["id"]: t for t in catalog.get_many([i["id"] for i in mem])}
    pool_genres: dict[str, int] = {}
    for t in pool:
        for g in t["genres"]:
            pool_genres[g] = pool_genres.get(g, 0) + 1

    stance_r = {"很爱": 5, "喜欢": 4, "不喜欢": 2, "弃了": 1}

    def score(i: dict) -> float:
        t = ts.get(i["id"])
        overlap = sum(pool_genres.get(g, 0) for g in (t["genres"] if t else []))
        r = i["rating"] if i["rating"] is not None else stance_r.get((i.get("context") or {}).get("stance"), 3)
        strength = abs(r - 3) + (1 if i["words"] else 0)
        return strength * 2 + overlap / max(1, len(pool))

    same = sorted((i for i in mem if i["domain"] == dom), key=score, reverse=True)
    other = sorted((i for i in mem if i["domain"] != dom and i["words"]), key=score, reverse=True)
    n_other = min(3, len(other), max(0, k - len(same)) + 2)
    return same[: k - n_other] + other[:n_other]


def all_records_text() -> tuple[str, int]:
    mem = store.items()
    ts = {t["id"]: t for t in catalog.get_many([i["id"] for i in mem])}
    lines = [record_line(i, ts.get(i["id"]), words_limit=None) for i in reversed(mem)]
    return "\n".join(lines), len(lines)


def interview_text() -> str:
    t = store.turns()
    if not t:
        return ""
    return "\n".join(f"{'片刻' if x['role'] == 'assistant' else '用户'}：{x['text']}" for x in t)
