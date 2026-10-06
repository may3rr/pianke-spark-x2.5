"""After-the-fact feedback, for films, books and albums alike.

log()   "看过了": the user's stars (explicit, never guessed when given), an
        optional review in their own words, and when. If there is a review,
        the 1.7B model adds structure next to it (liked / disliked aspects,
        mood, company); the words themselves are stored verbatim.
pass_() "没看": one reason, and each reason writes somewhere different —
        the list, a taste record, or only the recent layer."""

from __future__ import annotations

import time
from datetime import date

from ..catalog import search as catalog
from ..domains import PASS_REASONS, WORDS, reason_label
from ..llm import client
from ..memory import store

SCHEMA = {
    "type": "object",
    "properties": {
        "status": {"type": "string", "enum": ["watched", "dropped"]},
        "rating": {"type": "integer", "enum": [0, 1, 2, 3, 4, 5]},
        "liked": {"type": "array", "items": {"type": "string"}, "maxItems": 4},
        "disliked": {"type": "array", "items": {"type": "string"}, "maxItems": 4},
        "mood": {"type": "string"},
        "with": {"type": "string"},
        "quote": {"type": "string"},
    },
    "required": ["status", "rating", "liked", "disliked", "mood", "with", "quote"],
}

SYSTEM = """用户刚{verb}完（或没{verb}完）一{unit}{noun}，说了几句感受。把它整理成结构化数据。
- status：{verb}完了 watched；没{verb}完、{verb}到一半、睡着了、关掉了、弃了，都是 dropped。
  例：“还行吧，打发时间可以” → watched；“{verb}了一小会儿就放下了” → dropped。
- rating：从语气判断 1 到 5 分，5 是很爱，1 是很讨厌；判断不了填 0。
- liked / disliked：喜欢或不喜欢的具体方面，每条不超过 8 个字，比如{examples}。没有就留空。
- mood：只有用户明确说了自己当时的状态（比如“累了”“心情不好”）才填，原样用他的说法；没说就填空字符串，不要从感受里推测。
- with：和谁一起，没提到就填空字符串。
- quote：从用户原话里原样摘一句最能代表他感受的话，一个字都不要改。
不要添加用户没说过的内容。"""

EXAMPLES = {
    "film": "“结尾克制”“配乐太吵”",
    "book": "“语言干净”“中段拖沓”",
    "music": "“编曲耐听”“人声太腻”",
}


def system_for(domain: str) -> str:
    w = WORDS[domain]
    return SYSTEM.format(verb=w["verb"], unit=w["unit"], noun=w["noun"], examples=EXAMPLES[domain])


def _extract(item_id: str, text: str) -> tuple[dict, dict]:
    dom = store.domain_of(item_id)
    t = catalog.get(item_id)
    name = t["name"] if t else item_id
    w = WORDS[dom]
    system = system_for(dom)
    data, stats = client.chat(
        "small",
        [
            {"role": "system", "content": system},
            {"role": "user", "content": f"{w['work']}：{name}\n用户说：{text}"},
        ],
        task="feedback_extract",
        schema=SCHEMA,
        max_tokens=400,
        sampling={"temperature": 0.2, "top_p": 0.9},
    )
    # context the user never said is dropped: it must share two characters in
    # a row with their words (the 1.7B model likes to infer a mood)
    for k in ("mood", "with"):
        v = data[k]
        if v and not any(v[i : i + 2] in text for i in range(max(1, len(v) - 1))):
            data[k] = ""
    return data, stats


def _bump_stale() -> int:
    stale = store.get_pref("stale", 0) + 1
    store.set_pref("stale", stale)
    return stale


def log(
    item_id: str,
    *,
    status: str = "watched",
    rating: float | None = None,
    text: str = "",
    origin: str | None = None,
    done_on: str | None = None,
    replace_words: bool = False,
) -> dict:
    """Record that the user finished (or gave up on) a work."""
    text = (text or "").strip()
    if rating is not None:
        rating = max(0.0, min(5.0, round(float(rating) * 2) / 2))
    data: dict = {"status": status, "rating": 0, "liked": [], "disliked": [], "mood": "", "with": "", "quote": ""}
    stats: dict = {}
    if text:
        data, stats = _extract(item_id, text)
        # the buttons the user pressed win over what the model read
        data["status"] = status
    fields: dict = dict(
        status=status,
        rating=rating if rating is not None else (data["rating"] or None) if text else None,
        origin=origin,
        done_on=done_on or date.today().isoformat(),
        source="feedback",
        reason=None,
    )
    replace: tuple[str, ...] = ("reason",)
    if text:
        fields.update(
            liked=data["liked"],
            disliked=data["disliked"],
            context={k: v for k, v in (("mood", data["mood"]), ("with", data["with"])) if v},
            words=text,
        )
        if replace_words:
            replace += ("words", "liked", "disliked")
    it = store.upsert_item(item_id, replace=replace, **fields)
    store.event("feedback", {"id": item_id, "status": status, "rating": rating, "text": text,
                             "origin": origin, "extracted": data if text else None})
    quote_ok = bool(data["quote"]) and data["quote"] in text
    return {
        "item": it,
        "extracted": {**data, "rating": it["rating"] or 0},
        "quote": data["quote"] if quote_ok else "",
        "stats": {k: stats.get(k) for k in ("seconds", "gen_tps", "model")},
        "stale": _bump_stale(),
    }


def edit(item_id: str, *, rating: float | None = None, clear_rating: bool = False,
         done_on: str | None = None, status: str | None = None, words: str | None = None) -> dict:
    """Notion-style edits from the record page. A rewritten review is
    re-read by the 1.7B model so the aspects stay in step with it."""
    if words is not None:
        cur = store.item(item_id) or {}
        if words.strip() != (cur.get("words") or "").strip():
            out = log(item_id, status=status or cur.get("status") or "watched",
                      rating=rating if rating is not None else cur.get("rating"),
                      text=words, origin=cur.get("origin"), done_on=done_on or cur.get("done_on"),
                      replace_words=True)
            if not words.strip():
                store.upsert_item(item_id, replace=("words", "liked", "disliked"), words="", liked=[], disliked=[])
            return store.item(item_id) or out["item"]
    replace: tuple[str, ...] = ("rating",) if clear_rating else ()
    if rating is not None:
        rating = max(0.0, min(5.0, round(float(rating) * 2) / 2))
    it = store.upsert_item(item_id, replace=replace, rating=None if clear_rating else rating,
                           done_on=done_on, status=status)
    store.event("edit", {"id": item_id, "rating": rating, "clear_rating": clear_rating,
                         "done_on": done_on, "status": status})
    _bump_stale()
    return it


def pass_(item_id: str, reason: str, words: str | None = None, rec_id: int | None = None) -> dict:
    """The user didn't watch / read / listen. What we store depends on why."""
    if reason not in PASS_REASONS:
        raise ValueError(reason)
    dom = store.domain_of(item_id)
    effect = PASS_REASONS[reason]["effect"]
    label = reason_label(dom, reason)
    words = (words or "").strip() or None
    store.event("pass", {"id": item_id, "reason": label, "key": reason, "effect": effect,
                         "words": words, "rec_id": rec_id})
    if effect == "want":
        it = store.upsert_item(item_id, status="want", words=words, source="rec")
    elif effect == "taste":
        it = store.upsert_item(item_id, status="rejected", reason=label, words=words, source="rec")
        _bump_stale()
    else:  # moment: nothing long-term; recently_recommended keeps it out for a while
        it = store.item(item_id) or {"id": item_id, "domain": dom, "status": None}
    return {"item": it, "effect": effect, "reason": label}


def set_status(item_id: str, status: str, words: str | None = None) -> dict:
    it = store.upsert_item(item_id, status=status, words=words or None, source="rec")
    store.event("status", {"id": item_id, "status": status, "words": words})
    return it


# ---------------------------------------------------------------- check-ins

def _asked() -> set[str]:
    return set(store.get_pref("checked", []))


def checkins(domain: str | None = None) -> list[dict]:
    """Picks the user may have gotten to since: ones they put on the list
    from a recommendation, and the latest night's picks when nothing was
    done with them. Each is asked about once."""
    from ..domains import CHECKIN_DAYS

    asked = _asked()
    out: list[dict] = []
    now = time.time()
    for dom in ([domain] if domain else list(CHECKIN_DAYS)):
        window = CHECKIN_DAYS[dom] * 86400
        recs = [r for r in store.recs_since(now - window)
                if (r["request"].get("domain") or "film") == dom and now - r["ts"] > 4 * 3600]
        seen_ids: set[str] = set()
        for i, r in enumerate(recs):
            states = {p["id"]: (store.item(p["id"]) or {}).get("status") for p in r["picks"]}
            untouched = all(s is None for s in states.values())
            for p in r["picks"]:
                if p["id"] in asked or p["id"] in seen_ids:
                    continue
                s = states[p["id"]]
                if s == "want" or (untouched and i == 0):
                    seen_ids.add(p["id"])
                    out.append({"id": p["id"], "domain": dom, "rec_id": r["id"], "ts": r["ts"],
                                "on_list": s == "want", "title": catalog.get(p["id"])})
    return [o for o in out if o["title"]][:4]


def dismiss_checkin(item_id: str) -> None:
    asked = _asked()
    asked.add(item_id)
    store.set_pref("checked", sorted(asked)[-500:])
