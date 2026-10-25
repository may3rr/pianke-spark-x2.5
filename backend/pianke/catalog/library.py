"""Books and albums: the local shelf (data/library.sqlite, from Wikidata)
plus works found online and cached (bk:db… / mu:it…).

Same two jobs as the film catalog: resolve a name to a real work, and pull
candidates by filters. resolve() tries the shelf first and only then asks
the network, with the title and creator as the only payload."""

from __future__ import annotations

import json
import math
import random
import re
import sqlite3
import threading
from functools import lru_cache

from rapidfuzz import fuzz

from ..config import LIBRARY_DB
from ..lookup import net, online, web
from .vocab import ALBUM_REGIONS  # noqa: F401  (re-exported for schemas)

_local = threading.local()
KIND_OF = {"book": "book", "music": "album"}
DOMAIN_OF = {"book": "book", "album": "music"}


def _con() -> sqlite3.Connection | None:
    """None until a built library exists (an empty or half-written file
    counts as missing; books and albums then resolve online only)."""
    c = getattr(_local, "con", None)
    if c is None:
        if not available():
            return None
        c = sqlite3.connect(f"{LIBRARY_DB.as_uri()}?mode=ro", uri=True, check_same_thread=False)
        c.row_factory = sqlite3.Row
        try:
            c.execute("select 1 from works limit 1")
        except sqlite3.DatabaseError:
            c.close()
            return None
        _local.con = c
    return c


def available() -> bool:
    return LIBRARY_DB.exists() and LIBRARY_DB.stat().st_size > 0


def stats() -> dict:
    c = _con()
    if c is None:
        return {"available": False}
    try:
        return {"available": True, **dict(c.execute("select key, value from meta").fetchall())}
    except sqlite3.DatabaseError:
        return {"available": False}


def _shape(d: dict) -> dict:
    """Common title shape shared with films (the UI and prompts read it)."""
    kind = d["kind"]
    genres = d.get("genres") or []
    return {
        "id": d["id"],
        "domain": DOMAIN_OF[kind],
        "kind": kind,
        "title": d.get("title") or d.get("zh") or "",
        "original": d.get("original") or d.get("title") or "",
        "zh": d.get("zh"),
        "name": d.get("zh") or d.get("title") or "",
        "year": d.get("year"),
        "creators": d.get("creators") or [],
        "genres": genres,
        "genres_zh": genres,
        "lang": d.get("lang") or "",
        "region": d.get("region") or "",
        "pages": d.get("pages"),
        "tracks": d.get("tracks"),
        "popularity": d.get("popularity") or 0,
        "ext": d.get("ext") or {},
    }


def _row(r: sqlite3.Row) -> dict:
    return _shape({
        "id": r["id"], "kind": r["kind"], "zh": r["zh"], "title": r["title"],
        "original": r["original"], "year": r["year"],
        "creators": json.loads(r["creators"] or "[]"), "genres": json.loads(r["genres"] or "[]"),
        "lang": r["lang"], "region": r["region"], "pages": r["pages"],
        "popularity": r["popularity"], "ext": json.loads(r["ext"] or "{}"),
    })


def get(item_id: str) -> dict | None:
    got = get_many([item_id])
    return got[0] if got else None


def get_many(ids: list[str]) -> list[dict]:
    if not ids:
        return []
    by: dict[str, dict] = {}
    local = [i for i in ids if re.match(r"^(bk|mu):", i)]
    c = _con()
    if local and c is not None:
        q = ",".join("?" * len(local))
        for r in c.execute(f"select * from works where id in ({q})", local).fetchall():
            by[r["id"]] = _row(r)
    for k, d in net.load_ext([i for i in ids if i not in by]).items():
        by[k] = _shape(d)
    return [by[i] for i in ids if i in by]


# ---------------------------------------------------------------- resolve

def _norm(s: str) -> str:
    return online._norm(s)


@lru_cache(maxsize=4096)
def _local_candidates(kind: str, q: str) -> tuple[sqlite3.Row, ...]:
    c = _con()
    if c is None or not q:
        return ()
    rows: list[sqlite3.Row] = []
    if len(q) >= 3:
        try:
            rows = c.execute(
                "select w.* from works_fts f join works w on w.id=f.id"
                " where works_fts match ? and w.kind=? order by w.popularity desc limit 60",
                ('"' + q.replace('"', " ") + '"', kind),
            ).fetchall()
        except sqlite3.OperationalError:
            rows = []
    if not rows:
        like = f"%{q}%"
        rows = c.execute(
            "select * from works where kind=? and (zh like ? or title like ? or original like ?)"
            " order by popularity desc limit 60",
            (kind, like, like, like),
        ).fetchall()
    return tuple(rows)


def _local_resolve(kind: str, title: str, creator: str | None, year: int | None,
                   original: str | None) -> dict | None:
    best: tuple[float, sqlite3.Row] | None = None
    for q in {_norm(title), _norm(original or "")} - {""}:
        for r in _local_candidates(kind, q):
            names = [_norm(r["zh"] or ""), _norm(r["title"]), _norm(r["original"])]
            sim = max(fuzz.ratio(q, n) for n in names if n) / 100
            if sim < 0.6:
                continue
            score = sim
            creators = json.loads(r["creators"] or "[]")
            if creator and creators:
                hit = any(fuzz.partial_ratio(_norm(creator), _norm(c)) >= 80 for c in creators)
                score += 0.15 if hit else -0.1
            if year and r["year"]:
                d = abs(year - r["year"])
                score += 0.1 if d <= 1 else -0.1 if d > 5 else 0
            score += 0.03 * math.log10(max(r["popularity"], 1))
            if best is None or score > best[0]:
                best = (score, r)
    if best is None or best[0] < 0.85:
        return None
    return _row(best[1])


def resolve(domain: str, title: str, creator: str | None = None, year: int | None = None,
            original: str | None = None, *, use_online: bool = True) -> dict | None:
    kind = KIND_OF[domain]
    hit = _local_resolve(kind, title, creator, year, original)
    if hit or not use_online:
        return hit
    found = (online.find_book if kind == "book" else online.find_album)(title, creator, year)
    if found is None and original and original != title:
        found = (online.find_book if kind == "book" else online.find_album)(original, creator, year)
    if found is None:  # only when the user set a search key
        found = web.find_work(kind, title, creator, year)
    return _shape(found) if found else None


def search(domain: str, q: str, limit: int = 12, *, use_online: bool = True) -> list[dict]:
    kind = KIND_OF[domain]
    nq = _norm(q)
    if not nq:
        return []
    scored = []
    for r in _local_candidates(kind, nq):
        names = [_norm(r["zh"] or ""), _norm(r["title"]), _norm(r["original"]), _norm(r["creators"])]
        sim = max(fuzz.partial_ratio(nq, n) for n in names if n) / 100
        scored.append((sim + 0.05 * math.log10(max(r["popularity"], 1)), _row(r)))
    scored.sort(key=lambda x: -x[0])
    # a creator's name lists their works: the shelf holds only the best-known
    # few (two of 伊坂幸太郎's), so those searches always ask online too
    by_creator = any(nq == _norm(c) for _, t in scored for c in t["creators"])
    if by_creator:
        limit = max(limit, 30)
    out = [t for _, t in scored[:limit]]
    # an exact local hit answers the search; the network is only for misses
    exact = any(nq in (_norm(t["name"]), _norm(t["original"])) for t in out)
    if use_online and ((len(out) < 5 and not exact) or by_creator):
        more = online.search_books(q, lane="fg") if kind == "book" else online.search_albums(q, lane="fg")
        # 《解憂雜貨店》 and 《解忧杂货店》 are one book
        same = lambda name, by: (_norm(online.t2s(name)), _norm(online.t2s(by)))  # noqa: E731
        names = {same(t["name"], (t["creators"] or [""])[0]) for t in out}
        for m in more:
            key = same(m["zh"] or m["title"], (m["creators"] or [""])[0])
            if key in names:
                continue
            names.add(key)
            net.save_ext(m["id"], kind, m)
            out.append(_shape(m))
    return out[:limit]


# ---------------------------------------------------------------- filter

def candidates(
    domain: str,
    *,
    genres_any: list[str] | None = None,
    genres_avoid: list[str] | None = None,
    langs_any: list[str] | None = None,
    regions_any: list[str] | None = None,
    year_min: int | None = None,
    year_max: int | None = None,
    exclude: set[str] | None = None,
    limit: int = 30,
) -> list[dict]:
    """Known works matching the filters: mostly the widely-read/heard, plus a
    random slice from further down so the list isn't only the canon."""
    c = _con()
    if c is None:
        return []
    where, args = ["kind = ?"], [KIND_OF[domain]]
    if year_min:
        where.append("year >= ?")
        args.append(year_min)
    if year_max:
        where.append("year <= ?")
        args.append(year_max)
    if genres_any:
        where.append("(" + " or ".join("genres like ?" for _ in genres_any) + ")")
        args += [f'%"{g}"%' for g in genres_any]
    for g in genres_avoid or []:
        where.append("genres not like ?")
        args.append(f'%"{g}"%')
    if langs_any:
        where.append(f"lang in ({','.join('?' * len(langs_any))})")
        args += langs_any
    if regions_any:
        where.append(f"region in ({','.join('?' * len(regions_any))})")
        args += regions_any
    rows = c.execute(
        f"select * from works where {' and '.join(where)} order by popularity desc limit 400", args
    ).fetchall()
    ex = exclude or set()
    rows = [r for r in rows if r["id"] not in ex]
    head = rows[: limit * 2 // 3]
    tail = rows[limit * 2 // 3 :]
    random.shuffle(tail)
    return [_row(r) for r in head + tail[: limit - len(head)]]


WALL_SKIP = {"社会", "历史", "哲学", "科普"}


def wall(domain: str, n: int = 24, page: int = 0, exclude: set[str] | None = None) -> list[dict]:
    """Cold-start cover wall: recognisable works spread over genres. Chinese-
    language works get a fair share; page turns the batch."""
    c = _con()
    if c is None:
        return []
    kind = KIND_OF[domain]
    rows = c.execute(
        "select * from works where kind=? and genres != '[]'"
        # books: modern, dated works only, so the wall isn't the classical canon
        + (" and year >= 1850" if kind == "book" else "")
        + " order by popularity desc limit 1500", (kind,)
    ).fetchall()
    ex = exclude or set()
    rows = [r for r in rows if r["id"] not in ex]
    if kind == "book":  # the wall is for taste: stories and essays, not reference works
        rows = [r for r in rows if not set(json.loads(r["genres"])) <= WALL_SKIP]
    zh_rows = [r for r in rows if (r["lang"] == "中文" or r["region"] == "华语") and r["zh"]]
    rng = random.Random(f"{domain}:{page}")
    picked: list[sqlite3.Row] = []
    seen_genre: dict[str, int] = {}
    seen_creator: set[str] = set()

    def take(pool: list[sqlite3.Row], k: int) -> None:
        pool = pool[: 120 + page * 60]
        rng.shuffle(pool)
        for r in pool:
            if len(picked) >= k:
                return
            if r in picked:
                continue
            g = (json.loads(r["genres"]) or ["?"])[0]
            cr = (json.loads(r["creators"]) or [""])[0]
            if seen_genre.get(g, 0) >= max(2, n // 6) or (cr and cr in seen_creator):
                continue
            picked.append(r)
            seen_genre[g] = seen_genre.get(g, 0) + 1
            if cr:
                seen_creator.add(cr)

    take(zh_rows, n // 3)
    take(rows, n)
    return [_row(r) for r in picked]


def brief(t: dict) -> str:
    parts = [t["id"], t["name"]]
    if t["original"] and t["original"] != t["name"]:
        parts.append(t["original"])
    if t["year"]:
        parts.append(str(t["year"]))
    if t["creators"]:
        parts.append(("作者 " if t["kind"] == "book" else "") + "、".join(t["creators"][:2]))
    if t["genres"]:
        parts.append("/".join(t["genres"][:3]))
    if t["kind"] == "book" and t["lang"]:
        parts.append(f"原文{t['lang']}")
    if t["kind"] == "book" and t["pages"]:
        parts.append(f"{t['pages']}页")
    if t["kind"] == "album" and t["region"]:
        parts.append(t["region"])
    return " | ".join(p for p in parts if p)
