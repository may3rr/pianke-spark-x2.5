"""Tonight's three picks.

  read       L2 profile + L3 recent state (bounded, independent of history size)
  direction  4B turns profile + tonight's request into catalog filters, plus a
             few titles it has in mind
  search     the catalog verifies those titles (unverifiable ones are dropped
             and shown as such) and pulls filtered candidates
  pick       4B chooses three. The JSON grammar only admits ids from the
             shortlist and the user's own records, so a pick can never be an
             invented film, and every "because" points at something the user
             really said.

mode lets the evaluation script swap the memory strategy:
  layered (default) | full (every record in the prompt) | none (no memory)

The same pipeline serves films, books and albums. What differs per shelf —
the filters the model may ask for, how a seed is verified, the wording —
sits in the small adapters at the bottom of this file. Books and albums are
verified on the local shelf first and then online, by title only.

With a web search key (lookup/web.py) two steps grow: direction also writes
search queries, and what they find becomes more seeds (verified like the
rest); after picking, each pick's reviews are searched and the reasons
rewritten around a concrete detail from them.
"""

from __future__ import annotations

import time
from concurrent.futures import ThreadPoolExecutor
from typing import Iterator

from ..catalog import library
from ..catalog import search as catalog
from ..catalog.vocab import ALBUM_GENRE_NAMES, ALBUM_REGIONS, BOOK_GENRE_NAMES, BOOK_LANGS
from ..domains import WORDS
from ..llm import client
from ..lookup import web
from ..memory import store
from . import memory_view

GENRES_ZH = sorted(set(catalog.GENRE_ZH.values()) - {"成人", "短片", "新闻", "脱口秀", "游戏节目", "真人秀"})

DIRECTION_SCHEMA = {
    "type": "object",
    "properties": {
        "direction": {"type": "string"},
        "kinds": {
            "type": "array",
            "items": {"type": "string", "enum": ["movie", "series", "miniseries"]},
            "minItems": 1,
            "maxItems": 3,
        },
        "genres_any": {"type": "array", "items": {"type": "string", "enum": GENRES_ZH}, "maxItems": 4},
        "genres_avoid": {"type": "array", "items": {"type": "string", "enum": GENRES_ZH}, "maxItems": 4},
        "year_min": {"type": "integer"},
        "year_max": {"type": "integer"},
        "runtime_max": {"type": "integer"},
        "seeds": {
            "type": "array",
            "maxItems": 8,
            "items": {
                "type": "object",
                "properties": {
                    "title": {"type": "string"},
                    "original": {"type": "string"},
                    "year": {"type": "integer"},
                },
                "required": ["title", "original", "year"],
            },
        },
    },
    "required": ["direction", "kinds", "genres_any", "genres_avoid", "year_min",
                 "year_max", "runtime_max", "seeds"],
}

DIRECTION_SYSTEM = """你是「片刻」，用户 Mac 上的观影伙伴。你要为用户今晚挑片，先定方向。
读用户的口味画像、最近的状态和今晚的要求，输出：
- direction：对用户说的一句话，说明今晚适合看什么样的片，不超过 30 个字，用“你”称呼，不提具体片名。
- kinds：movie 电影 / series 剧集 / miniseries 迷你剧。用户没说要剧，就只选 movie。
- genres_any：今晚可以考虑的类型，最多 4 个；genres_avoid：今晚要避开的类型。
- year_min / year_max：年代范围，不限就填 0。
- runtime_max：时长上限（分钟），用户累了或时间少就给 100 左右，不限填 0。
- seeds：你想到的、确定真实存在的 4 到 8 部候选，写清中文名、原名和年份。不要选用户已经看过或不想看的。
不要选用户明确说过不想看的东西。"""

PICK_SYSTEM = """你是「片刻」。从候选清单里为用户挑出今晚最合适的三部。
要求：
- 三部之间要有区别，不要三部都是同一种感觉。
- 优先符合今晚的要求和状态，其次符合长期口味。和今晚状态明显冲突的不要选，比如用户累了、想看暖的，就不要选紧张的犯罪片或沉重的战争片。
- name：这部片在清单里的名字，和 id 对应。
- reason：对用户说为什么是它，40 到 80 个字，用“你”称呼。先用半句话说这部片具体讲什么或好在哪里（不剧透），再把它和用户说过的某句话、某部他喜欢的片或今晚的状态连起来。
  三条 reason 的开头和句式要不一样。不要重复今晚的方向那句话，不要用“契合”“符合你的偏好”“氛围安静克制”这类空话。
- because：这部片和用户记录里的哪几部有关（填记录编号，最多 2 个），没有就留空。
只能从候选清单里选 id。"""


def _sse_step(key: str, status: str, **kw) -> dict:
    return {"type": "step", "key": key, "status": status, **kw}


def run(request: dict, mode: str = "layered") -> Iterator[dict]:
    domain = request.get("domain") or "film"
    if domain != "film":
        yield from run_shelf(request, domain, mode)
        return
    t_start = time.time()
    text = (request.get("text") or "").strip()
    chips = request.get("chips") or {}
    tonight = "；".join(
        x for x in [text, *(f"{k}：{v}" for k, v in chips.items() if v)] if x
    ) or "没有特别要求"

    # ------------------------------------------------------------- read
    yield _sse_step("read", "running")
    prof = store.profile()
    seen, want_ids = _split_seen("film")
    wanted = catalog.get_many(want_ids)
    from_list = bool(request.get("from_list")) and len(wanted) >= 3
    if mode == "none":
        memory_block = "（不读取用户记忆）"
        n_records = 0
    elif mode == "full":
        recs_txt, n_records = memory_view.all_records_text()
        memory_block = f"## 全部观影记录\n{recs_txt}"
    else:
        n_records = len(seen)
        memory_block = (
            f"## 口味画像\n{memory_view.profile_text(prof)}\n\n"
            f"## 最近两周\n{memory_view.recent_text()}"
        )
    avoid = store.get_pref("avoid", []) if mode != "none" else []
    habits = store.get_pref("habits", {}) if mode != "none" else {}
    seen_names = [t["name"] for t in catalog.get_many(list(seen)[:60])]
    context = (
        f"{memory_block}\n\n"
        + (f"已经看过或不想看（不要再选）：{'、'.join(seen_names)}\n" if seen_names and mode != "none" else "")
        + 
        f"明确不想看：{'、'.join(avoid) or '（未说明）'}\n"
        f"看片习惯：{habits.get('when') or '未说明'} {habits.get('with') or ''}\n\n"
        f"## 今晚\n{tonight}"
        + ("（这次只从用户自己的片单里挑）" if from_list else "")
    )
    yield _sse_step(
        "read", "done",
        detail=(f"第 {prof['version']} 版画像，{n_records} 条记忆" if prof and mode == "layered"
                else f"{n_records} 条记忆" if mode == "full" else "不读记忆"),
    )

    # ------------------------------------------------------------- direction
    yield _sse_step("direction", "running")
    d, st1 = client.chat(
        "big",
        [{"role": "system", "content": DIRECTION_SYSTEM + _queries_hint()}, {"role": "user", "content": context}],
        task="rec_direction",
        schema=_with_queries(DIRECTION_SCHEMA),
        max_tokens=900,
        sampling={"temperature": 0.7, "top_p": 0.95},
    )
    d["direction"] = d["direction"].replace("您", "你")
    yield _sse_step("direction", "done", detail=d["direction"], direction=d["direction"])

    # ------------------------------------------------------------- search
    yield _sse_step("search", "running")
    web_seeds, web_note = ([], "") if from_list else _web_seeds("film", DIRECTION_SCHEMA, d, context)
    seeds = [] if from_list else d["seeds"] + web_seeds
    exclude = seen | store.recently_recommended()
    verified: list[dict] = []
    for s in seeds:
        hit = catalog.resolve(s["title"], s["year"] or None, s["original"] or None, use_online=True)
        ok = hit is not None and hit["id"] not in exclude
        yield {
            "type": "seed",
            "name": hit["name"] if hit else s["title"],
            "year": (hit or {}).get("year") or s["year"] or None,
            "status": "verified" if ok else ("seen" if hit else "missing"),
        }
        if ok and all(v["id"] != hit["id"] for v in verified):
            verified.append(hit)
    en = lambda zs: [catalog.ZH_GENRE[g] for g in zs if g in catalog.ZH_GENRE]  # noqa: E731
    filt = dict(
        kinds=d["kinds"] or ["movie"],
        genres_any=en(d["genres_any"]),
        genres_avoid=en(d["genres_avoid"]),
        year_min=d["year_min"] or None,
        year_max=d["year_max"] or None,
        runtime_max=d["runtime_max"] or None,
        exclude=exclude | {v["id"] for v in verified},
    )
    relaxed = []
    if from_list:
        pool = wanted[:36]
        detail = f"从你的片单里挑，一共 {len(pool)} 部"
    else:
        pool = catalog.candidates(**filt, limit=30)
        for drop in ("genres_any", "year_min", "year_max", "runtime_max"):
            if len(pool) >= 12:
                break
            filt[drop] = None
            relaxed.append(drop)
            pool = catalog.candidates(**filt, limit=30)
        listed = _listed(wanted, verified, pool)
        pool = (verified + listed + _without(pool, listed))[:36]
        detail = (f"模型想到 {len(d['seeds'])} 部{web_note}，片库核实 {len(verified)} 部；"
                  f"按条件再找 {len(pool) - len(verified) - len(listed)} 部"
                  + (f"，加上片单里的 {len(listed)} 部" if listed else ""))
    yield _sse_step("search", "done", detail=detail, pool=len(pool))
    if len(pool) < 3:
        yield {"type": "error", "message": "片库里没有找到足够的候选。换个说法再试一次。"}
        return

    # ------------------------------------------------------------- pick
    yield _sse_step("pick", "running")
    rel = memory_view.relevant_records(pool) if mode == "layered" else (
        store.items() if mode == "full" else [])
    rel_ids = [r["id"] for r in rel]
    rel_titles = {t["id"]: t for t in catalog.get_many(rel_ids)}
    rel_block = "\n".join(memory_view.record_line(r, rel_titles.get(r["id"])) for r in rel) if mode == "layered" else ""
    pool_block = "\n".join(catalog.brief(t) + _list_mark(t, want_ids) for t in pool)
    pick_schema = {
        "type": "object",
        "properties": {
            "picks": {
                "type": "array",
                "minItems": 3,
                "maxItems": 3,
                "items": {
                    "type": "object",
                    "properties": {
                        "id": {"type": "string", "enum": [t["id"] for t in pool]},
                        # writing the name right after the id keeps the
                        # reason about this film, not a neighbour on the list
                        "name": {"type": "string"},
                        "reason": {"type": "string"},
                        "because": (
                            {"type": "array", "maxItems": 2, "items": {"type": "string", "enum": rel_ids}}
                            if rel_ids else {"type": "array", "maxItems": 0, "items": {"type": "string"}}
                        ),
                    },
                    "required": ["id", "name", "reason", "because"],
                },
            }
        },
        "required": ["picks"],
    }
    pick_prompt = (
        f"{context}\n\n"
        + (f"## 和候选相关的观影记录\n{rel_block}\n\n" if rel_block else "")
        + f"## 今晚的方向\n{d['direction']}\n\n## 候选清单（{len(pool)} 部）\n{pool_block}"
    )
    out, st2 = client.chat(
        "big",
        [{"role": "system", "content": PICK_SYSTEM + _list_note("film", pool, want_ids)},
         {"role": "user", "content": pick_prompt}],
        task="rec_pick",
        schema=pick_schema,
        max_tokens=900,
        sampling={"temperature": 0.6, "top_p": 0.95},
    )
    by_id = {t["id"]: t for t in pool}
    by_name = {t["name"]: t["id"] for t in pool}
    picks, used = [], set()
    for p in out["picks"]:
        # if the id and the name disagree, the name is what the reason is about
        named = by_name.get(p.get("name", "").strip("《》 "))
        if named and named != p["id"]:
            p["id"] = named
        if p["id"] in used or p["id"] not in by_id:
            continue
        used.add(p["id"])
        picks.append(_present(by_id[p["id"]], p, rel_titles))
    for t in pool:  # grammar guarantees 3, duplicates are the only gap
        if len(picks) >= 3:
            break
        if t["id"] not in used:
            used.add(t["id"])
            picks.append(_present(t, {"reason": "", "because": []}, rel_titles))
    for p in picks:
        p["on_list"] = p["id"] in want_ids
    reviewed = 0
    if web.enabled():
        yield _sse_step("pick", "running", detail="读网上的评价")
        reviewed = _review_reasons(picks[0].get("domain") or "film", picks, context, d["direction"])
    stats = {
        "mode": mode,
        "seconds": round(time.time() - t_start, 1),
        "prompt_tokens": (st1.get("prompt_tokens") or 0) + (st2.get("prompt_tokens") or 0),
        "gen_tps": st2.get("gen_tps"),
        "pool": len(pool),
        "seeds": len(seeds),
        "web_seeds": len(web_seeds),
        "reviews": reviewed,
        "verified": len(verified),
        "relaxed": relaxed,
    }
    # yield before saving: a run cancelled during the last model call stops
    # here (server.sse closes the generator) and leaves no history entry
    yield _sse_step("pick", "done", detail=f"用时 {stats['seconds']} 秒")
    rec_id = store.save_rec(request, d["direction"], picks, stats) if mode == "layered" else None
    store.event("rec", {"rec_id": rec_id, "request": request, "picks": [p["id"] for p in picks]})
    yield {"type": "result", "rec_id": rec_id, "direction": d["direction"], "picks": picks, "stats": stats,
           "domain": "film"}


def _present(t: dict, p: dict, rel_titles: dict) -> dict:
    """Attach the user's own words for each 'because' — read verbatim from
    the store, never paraphrased by the model."""
    quotes = []
    for rid in p.get("because") or []:
        it = store.item(rid)
        if not it:
            continue
        rt = rel_titles.get(rid) or catalog.get(rid)
        quotes.append({
            "id": rid,
            "name": rt["name"] if rt else rid,
            "domain": it["domain"],
            "stance": (it.get("context") or {}).get("stance", ""),
            "onboard": it.get("source") == "onboard",
            "words": (it["words"] or "").split("\n")[-1],
            "liked": it["liked"],
            "rating": it["rating"],
        })
    return {**t, "reason": p.get("reason", "").strip().replace("您", "你"), "because": quotes}


# ================================================================ the list

def _split_seen(domain: str) -> tuple[set[str], list[str]]:
    """What not to pick again, and the user's list (newest first). Works on
    the list are candidates, not exclusions: the user saved them to get to."""
    its = store.items(domain=domain)
    seen = {i["id"] for i in its if i["status"] != "want"}
    want = [i["id"] for i in sorted(its, key=lambda i: -i["updated"]) if i["status"] == "want"]
    return seen, want


def _listed(wanted: list[dict], verified: list[dict], pool: list[dict], n: int = 8) -> list[dict]:
    have = {t["id"] for t in verified}
    return [t for t in wanted[:n] if t["id"] not in have]


def _without(pool: list[dict], drop: list[dict]) -> list[dict]:
    ids = {t["id"] for t in drop}
    return [t for t in pool if t["id"] not in ids]


def _list_mark(t: dict, want_ids: list[str]) -> str:
    return " 〔在片单里〕" if t["id"] in want_ids else ""


def _list_note(domain: str, pool: list[dict], want_ids: list[str]) -> str:
    if not any(t["id"] in want_ids for t in pool):
        return ""
    w = WORDS[domain]
    return (f"\n候选后面标了〔在片单里〕的，是用户自己存下、想{w['verb']}的。"
            f"合适就优先考虑，reason 里可以提一句它在你的{w['list']}里；不合适不必勉强。")


# ================================================================ web search

def _queries_hint() -> str:
    if not web.enabled():
        return ""
    return ("\n另外输出 queries：1 到 2 个联网搜索词，用来找符合这次要求、你不一定记得的作品，"
            "尤其是最近几年的新作和冷门佳作，比如“2024 年 节奏慢 治愈 日本电影 推荐”。")


def _with_queries(schema: dict) -> dict:
    if not web.enabled():
        return schema
    return {
        **schema,
        "properties": {**schema["properties"],
                       "queries": {"type": "array", "items": {"type": "string"}, "maxItems": 2}},
        "required": [*schema["required"], "queries"],
    }


WEB_SEEDS = """你是「片刻」。下面是为这次推荐联网搜到的结果。从中找出符合方向、确实存在的{noun}，最多 6 {unit}。
只写搜索结果里明确出现的{noun}，写清名字、原名和年份{creator}。用户已经{verb}过或不想{verb}的不要写。没有合适的就留空数组。"""


def _web_seeds(domain: str, schema: dict, d: dict, context: str) -> tuple[list[dict], str]:
    """Run the model's search queries and turn what they find into seeds."""
    queries = [q for q in (d.get("queries") or []) if q.strip()][:2]
    if not queries or not web.enabled():
        return [], ""
    results = [r for rs in web.search_many(queries) for r in rs]
    if not results:
        return [], "，联网没搜到"
    w = WORDS[domain]
    creator = {"book": "和作者", "music": "和歌手"}.get(domain, "")
    try:
        out = _web_seed_call(domain, schema, d, context, results, w, creator)
    except Exception:  # noqa: BLE001 — the model's own seeds still go ahead
        return [], ""
    return out["seeds"], f"，联网搜到 {len(out['seeds'])} {w['unit']}"


def _web_seed_call(domain, schema, d, context, results, w, creator) -> dict:
    out, _ = client.chat(
        "big",
        [{"role": "system", "content": WEB_SEEDS.format(noun=w["noun"], unit=w["unit"], creator=creator,
                                                        verb=w["verb"])},
         {"role": "user", "content": f"{context}\n\n## 方向\n{d['direction']}\n\n"
                                     f"## 联网搜索结果\n{web.block(results, limit=10)}"}],
        task=f"rec_web_seeds_{domain}",
        schema={"type": "object", "required": ["seeds"], "properties": {
            "seeds": {"type": "array", "maxItems": 6, "items": schema["properties"]["seeds"]["items"]}}},
        max_tokens=700,
        sampling={"temperature": 0.4, "top_p": 0.95},
    )
    return out


REVIEW_WORD = {"film": "影评", "book": "书评", "music": "乐评"}

REVIEW_SYSTEM = """你是「片刻」。下面是已经为用户挑好的作品，每部附有原来的推荐理由和网上搜到的评价。
重写每部的 reason：40 到 80 个字，用“你”称呼。从网上的评价里取一个具体的细节（常被提到的场面、写法、编曲、口碑），再把它和用户说过的话、喜欢的作品或这次的状态连起来。
不剧透，不编造评价里没有的事实，不要写“网上说”“有评论认为”这类话。几条的开头和句式要不一样。没搜到评价的，保留原来的理由。"""


def _review_reasons(domain: str, picks: list[dict], context: str, direction: str) -> int:
    """Search each pick's reviews and rewrite its reason around them; returns
    how many picks had any. Reasons stay as they were if this fails."""
    def query(p: dict) -> str:
        by = (p.get("directors") or p.get("creators") or [""])[0]
        return f"{p['name']} {p.get('year') or ''} {by} {REVIEW_WORD.get(domain, '评价')}"

    found = web.search_many([query(p) for p in picks], n=4)
    n = sum(1 for rs in found if rs)
    if not n:
        return 0
    blocks = "\n\n".join(
        f"### {p['name']}（id {p['id']}）\n原来的理由：{p['reason'] or '（无）'}\n"
        f"网上的评价：\n{web.block(rs, limit=4, chars=250) or '（没搜到）'}"
        for p, rs in zip(picks, found)
    )
    ids = [p["id"] for p in picks]
    try:
        out, _ = client.chat(
            "big",
            [{"role": "system", "content": REVIEW_SYSTEM},
             {"role": "user", "content": f"{context}\n\n## 方向\n{direction}\n\n## 挑好的作品\n{blocks}"}],
            task=f"rec_reviews_{domain}",
            schema={"type": "object", "required": ["reasons"], "properties": {"reasons": {
                "type": "array", "minItems": len(ids), "maxItems": len(ids),
                "items": {"type": "object", "required": ["id", "reason"], "properties": {
                    "id": {"type": "string", "enum": ids}, "reason": {"type": "string"}}}}}},
            max_tokens=900,
            sampling={"temperature": 0.6, "top_p": 0.95},
        )
    except Exception:  # noqa: BLE001 — the first reasons are still good
        return 0
    by_id = {r["id"]: r["reason"].strip().replace("您", "你") for r in out["reasons"] if r["reason"].strip()}
    for p in picks:
        if p["id"] in by_id:
            p["reason"] = by_id[p["id"]]
    return n


# ================================================================ books, albums

def _shelf_direction_schema(domain: str) -> dict:
    genres = BOOK_GENRE_NAMES if domain == "book" else ALBUM_GENRE_NAMES
    creator = "author" if domain == "book" else "artist"
    props: dict = {
        "direction": {"type": "string"},
        "genres_any": {"type": "array", "items": {"type": "string", "enum": genres}, "maxItems": 4},
        "genres_avoid": {"type": "array", "items": {"type": "string", "enum": genres}, "maxItems": 4},
        "year_min": {"type": "integer"},
        "year_max": {"type": "integer"},
        "seeds": {
            "type": "array",
            "maxItems": 10,
            "items": {
                "type": "object",
                "properties": {
                    "title": {"type": "string"},
                    "original": {"type": "string"},
                    creator: {"type": "string"},
                    "year": {"type": "integer"},
                },
                "required": ["title", "original", creator, "year"],
            },
        },
    }
    if domain == "book":
        props["langs_any"] = {"type": "array", "items": {"type": "string", "enum": BOOK_LANGS}, "maxItems": 3}
    else:
        props["regions_any"] = {"type": "array", "items": {"type": "string", "enum": ALBUM_REGIONS}, "maxItems": 3}
    return {"type": "object", "properties": props, "required": list(props)}


SHELF_DIRECTION = {
    "book": """你是「片刻」，住在用户 Mac 上的读书伙伴，也了解他看片、听歌的口味。你要为用户挑下一本书，先定方向。
读用户的口味画像（里面可能有影视和音乐的偏好，口味常常相通）、最近的状态和这次的要求，输出：
- direction：对用户说的一句话，说明接下来适合读什么样的书，不超过 30 个字，用“你”称呼，不提具体书名。
- genres_any：可以考虑的类型，最多 4 个；genres_avoid：要避开的类型。
- langs_any：原文语种，用户没提就留空数组。
- year_min / year_max：成书年代范围，不限就填 0。
- seeds：你想到的、确定真实存在的 6 到 10 本书，写清中文书名、原名、作者和首次出版年份。不要选用户已经读过或不想读的。
用户累了或时间少，就偏向篇幅短、好读的；不要选用户明确说过不想碰的东西。""",
    "music": """你是「片刻」，住在用户 Mac 上的听歌伙伴，也了解他看片、读书的口味。你要为用户挑接下来听的专辑，先定方向。
读用户的口味画像（里面可能有影视和书的偏好，口味常常相通）、最近的状态和这次的要求，输出：
- direction：对用户说的一句话，说明现在适合听什么样的音乐，不超过 30 个字，用“你”称呼，不提具体专辑名。
- genres_any：可以考虑的风格，最多 4 个；genres_avoid：要避开的风格。
- regions_any：华语 / 日本 / 韩国 / 欧美 / 拉美 / 其他，用户没提就留空数组。
- year_min / year_max：发行年代范围，不限就填 0。
- seeds：你想到的、确定真实存在的 6 到 10 张专辑（完整专辑，不要单曲），写清专辑名、原名、歌手或乐队、发行年份。不要选用户已经听过或不想听的。
场景很重要：工作专注要少人声、不抢注意力；运动要有推进感；睡前要安静。""",
}

SHELF_PICK = """你是「片刻」。从候选清单里为用户挑出{when}最合适的三{unit}{noun}。
要求：
- 三{unit}之间要有区别，不要三{unit}都是同一种感觉。
- 优先符合这次的要求和状态，其次符合长期口味。和状态明显冲突的不要选。
- name：这{unit}{noun}在清单里的名字，和 id 对应。
- reason：对用户说为什么是它，40 到 80 个字，用“你”称呼。先用半句话说这{unit}{noun}具体是什么、好在哪里（不剧透），再把它和用户说过的某句话、某部他喜欢的作品（可以是电影、书或专辑）或现在的状态连起来。
  三条 reason 的开头和句式要不一样。不要重复方向那句话，不要用“契合”“符合你的偏好”这类空话。
- because：这{unit}{noun}和用户记录里的哪几条有关（填记录编号，最多 2 个），没有就留空。
只能从候选清单里选 id。"""


def run_shelf(request: dict, domain: str, mode: str = "layered") -> Iterator[dict]:
    t_start = time.time()
    w = WORDS[domain]
    text = (request.get("text") or "").strip()
    chips = request.get("chips") or {}
    now_req = "；".join(
        x for x in [text, *(f"{k}：{v}" for k, v in chips.items() if v)] if x
    ) or "没有特别要求"

    # ------------------------------------------------------------- read
    yield _sse_step("read", "running")
    prof = store.profile()
    seen, want_ids = _split_seen(domain)
    wanted = catalog.get_many(want_ids)
    from_list = bool(request.get("from_list")) and len(wanted) >= 3
    if mode == "none":
        memory_block, n_records = "（不读取用户记忆）", 0
    elif mode == "full":
        recs_txt, n_records = memory_view.all_records_text()
        memory_block = f"## 全部记录\n{recs_txt}"
    else:
        n_records = len(store.items())
        memory_block = (
            f"## 口味画像\n{memory_view.profile_text(prof)}\n\n"
            f"## 最近两周\n{memory_view.recent_text()}"
        )
    avoid = store.get_pref("avoid", []) if mode != "none" else []
    seen_names = [t["name"] for t in catalog.get_many(list(seen)[:60])]
    context = (
        f"{memory_block}\n\n"
        + (f"已经{w['verb']}过或不想{w['verb']}（不要再选）：{'、'.join(seen_names)}\n" if seen_names and mode != "none" else "")
        + f"明确不想碰：{'、'.join(avoid) or '（未说明）'}\n\n"
        f"## 这次的要求\n{now_req}"
        + (f"（这次只从用户自己的{w['list']}里挑）" if from_list else "")
    )
    yield _sse_step(
        "read", "done",
        detail=(f"第 {prof['version']} 版画像，{n_records} 条记忆" if prof and mode == "layered"
                else f"{n_records} 条记忆" if mode == "full" else "不读记忆"),
    )

    # ------------------------------------------------------------- direction
    yield _sse_step("direction", "running")
    d, st1 = client.chat(
        "big",
        [{"role": "system", "content": SHELF_DIRECTION[domain] + _queries_hint()},
         {"role": "user", "content": context}],
        task=f"rec_direction_{domain}",
        schema=_with_queries(_shelf_direction_schema(domain)),
        max_tokens=1100,
        sampling={"temperature": 0.7, "top_p": 0.95},
    )
    d["direction"] = d["direction"].replace("您", "你")
    yield _sse_step("direction", "done", detail=d["direction"], direction=d["direction"])

    # ------------------------------------------------------------- search
    yield _sse_step("search", "running")
    exclude = seen | store.recently_recommended()
    creator_key = "author" if domain == "book" else "artist"

    def verify(s: dict) -> dict | None:
        return library.resolve(domain, s["title"], s.get(creator_key) or None, s["year"] or None,
                               s["original"] or None)

    web_seeds, web_note = ([], "") if from_list else _web_seeds(domain, _shelf_direction_schema(domain), d, context)
    seeds = [] if from_list else d["seeds"][:10] + web_seeds
    with ThreadPoolExecutor(4) as ex:
        hits = list(ex.map(verify, seeds))
    verified: list[dict] = []
    for s, hit in zip(seeds, hits):
        ok = hit is not None and hit["id"] not in exclude
        yield {
            "type": "seed",
            "name": hit["name"] if hit else s["title"],
            "year": (hit or {}).get("year") or s["year"] or None,
            "status": "verified" if ok else ("seen" if hit else "missing"),
            "online": bool(hit) and ":Q" not in hit["id"],
        }
        if ok and all(v["id"] != hit["id"] for v in verified):
            verified.append(hit)
    filt = dict(
        genres_any=d["genres_any"],
        genres_avoid=d["genres_avoid"],
        langs_any=d.get("langs_any") or None,
        regions_any=d.get("regions_any") or None,
        year_min=d["year_min"] or None,
        year_max=d["year_max"] or None,
        exclude=exclude | {v["id"] for v in verified},
    )
    relaxed = []
    if from_list:
        pool = wanted[:32]
        detail = f"从你的{w['list']}里挑，一共 {len(pool)} {w['unit']}"
    else:
        pool = library.candidates(domain, **filt, limit=24)
        for drop in ("genres_any", "year_min", "year_max", "langs_any", "regions_any"):
            if len(pool) >= 10:
                break
            filt[drop] = None
            relaxed.append(drop)
            pool = library.candidates(domain, **filt, limit=24)
        listed = _listed(wanted, verified, pool)
        pool = (verified + listed + _without(pool, listed))[:32]
        detail = (f"模型想到 {len(d['seeds'][:10])} {w['unit']}{web_note}，核实 {len(verified)} {w['unit']}；"
                  f"按条件再找 {len(pool) - len(verified) - len(listed)} {w['unit']}"
                  + (f"，加上{w['list']}里的 {len(listed)} {w['unit']}" if listed else ""))
    yield _sse_step("search", "done", detail=detail, pool=len(pool))
    if len(pool) < 3:
        yield {"type": "error", "message": "没有找到足够的候选。换个说法再试一次。"}
        return

    # ------------------------------------------------------------- pick
    yield _sse_step("pick", "running")
    rel = memory_view.relevant_records(pool) if mode == "layered" else (
        store.items() if mode == "full" else [])
    rel_ids = [r["id"] for r in rel]
    rel_titles = {t["id"]: t for t in catalog.get_many(rel_ids)}
    rel_block = "\n".join(memory_view.record_line(r, rel_titles.get(r["id"])) for r in rel) if mode == "layered" else ""
    pool_block = "\n".join(library.brief(t) + _list_mark(t, want_ids) for t in pool)
    pick_schema = {
        "type": "object",
        "properties": {
            "picks": {
                "type": "array", "minItems": 3, "maxItems": 3,
                "items": {
                    "type": "object",
                    "properties": {
                        "id": {"type": "string", "enum": [t["id"] for t in pool]},
                        "name": {"type": "string"},
                        "reason": {"type": "string"},
                        "because": (
                            {"type": "array", "maxItems": 2, "items": {"type": "string", "enum": rel_ids}}
                            if rel_ids else {"type": "array", "maxItems": 0, "items": {"type": "string"}}
                        ),
                    },
                    "required": ["id", "name", "reason", "because"],
                },
            }
        },
        "required": ["picks"],
    }
    pick_prompt = (
        f"{context}\n\n"
        + (f"## 和候选相关的记录\n{rel_block}\n\n" if rel_block else "")
        + f"## 方向\n{d['direction']}\n\n## 候选清单（{len(pool)} {w['unit']}）\n{pool_block}"
    )
    out, st2 = client.chat(
        "big",
        [{"role": "system", "content": SHELF_PICK.format(when=w["when"], unit=w["unit"], noun=w["noun"])
          + _list_note(domain, pool, want_ids)},
         {"role": "user", "content": pick_prompt}],
        task=f"rec_pick_{domain}",
        schema=pick_schema,
        max_tokens=900,
        sampling={"temperature": 0.6, "top_p": 0.95},
    )
    by_id = {t["id"]: t for t in pool}
    by_name = {t["name"]: t["id"] for t in pool}
    picks, used = [], set()
    for p in out["picks"]:
        named = by_name.get(p.get("name", "").strip("《》 "))
        if named and named != p["id"]:
            p["id"] = named
        if p["id"] in used or p["id"] not in by_id:
            continue
        used.add(p["id"])
        picks.append(_present(by_id[p["id"]], p, rel_titles))
    for t in pool:
        if len(picks) >= 3:
            break
        if t["id"] not in used:
            used.add(t["id"])
            picks.append(_present(t, {"reason": "", "because": []}, rel_titles))
    for p in picks:
        p["on_list"] = p["id"] in want_ids
    reviewed = 0
    if web.enabled():
        yield _sse_step("pick", "running", detail="读网上的评价")
        reviewed = _review_reasons(picks[0].get("domain") or "film", picks, context, d["direction"])
    stats = {
        "mode": mode,
        "seconds": round(time.time() - t_start, 1),
        "prompt_tokens": (st1.get("prompt_tokens") or 0) + (st2.get("prompt_tokens") or 0),
        "gen_tps": st2.get("gen_tps"),
        "pool": len(pool),
        "seeds": len(seeds),
        "web_seeds": len(web_seeds),
        "reviews": reviewed,
        "verified": len(verified),
        "relaxed": relaxed,
    }
    # yield before saving: a run cancelled during the last model call stops
    # here (server.sse closes the generator) and leaves no history entry
    yield _sse_step("pick", "done", detail=f"用时 {stats['seconds']} 秒")
    rec_id = store.save_rec(request, d["direction"], picks, stats) if mode == "layered" else None
    store.event("rec", {"rec_id": rec_id, "request": request, "picks": [p["id"] for p in picks]})
    yield {"type": "result", "rec_id": rec_id, "direction": d["direction"], "picks": picks,
           "stats": stats, "domain": domain}
