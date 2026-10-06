"""Read-only access to the local film catalog (built from IMDb datasets).

Two jobs: resolve a title the user or the model mentioned to a real catalog
row (so nothing invented ever reaches the screen), and pull candidates by
structured filters for the model to choose from.

A title the catalog lacks can be looked up online (use_online): TMDB, then
Douban. Finds are kept as ext records (tt… when TMDB knows the IMDb id,
fm:tmdb… / fm:db… otherwise) and read back by get()."""

from __future__ import annotations

import math
import re
import sqlite3
import threading
import unicodedata
from functools import lru_cache

from rapidfuzz import fuzz

from ..config import CATALOG_DB

GENRE_ZH = {
    "Action": "动作", "Adventure": "冒险", "Animation": "动画", "Biography": "传记",
    "Comedy": "喜剧", "Crime": "犯罪", "Documentary": "纪录", "Drama": "剧情",
    "Family": "家庭", "Fantasy": "奇幻", "Film-Noir": "黑色电影", "History": "历史",
    "Horror": "恐怖", "Music": "音乐", "Musical": "歌舞", "Mystery": "悬疑",
    "News": "新闻", "Reality-TV": "真人秀", "Romance": "爱情", "Sci-Fi": "科幻",
    "Sport": "运动", "Talk-Show": "脱口秀", "Thriller": "惊悚", "War": "战争",
    "Western": "西部", "Game-Show": "游戏节目", "Short": "短片", "Adult": "成人",
}
ZH_GENRE = {v: k for k, v in GENRE_ZH.items()}
KIND_ZH = {"movie": "电影", "series": "剧集", "miniseries": "迷你剧"}

_local = threading.local()


def _con() -> sqlite3.Connection:
    c = getattr(_local, "con", None)
    if c is None:
        c = sqlite3.connect(f"{CATALOG_DB.as_uri()}?mode=ro", uri=True, check_same_thread=False)
        c.row_factory = sqlite3.Row
        _local.con = c
    return c


def available() -> bool:
    return CATALOG_DB.exists()


@lru_cache(maxsize=1)
def _has_aliases() -> bool:
    """Catalogs built before Chinese aliases were kept lack the column."""
    return "aliases" in {c[1] for c in _con().execute("pragma table_info(titles)")}


def _names(r: sqlite3.Row) -> list[str]:
    """Every name a row answers to, normalised: Chinese title and aliases,
    English and original titles."""
    extra = (r["aliases"] or "").split("|") if _has_aliases() else []
    return [n for n in (_norm(x) for x in (r["zh"] or "", r["title"], r["original"], *extra)) if n]


def _row(r: sqlite3.Row) -> dict:
    genres = [g for g in (r["genres"] or "").split(",") if g]
    return {
        "id": r["id"],
        "domain": "film",
        "kind": r["kind"],
        "title": r["title"],
        "original": r["original"],
        "zh": r["zh"],
        "name": r["zh"] or r["title"],
        "year": r["year"],
        "end_year": r["end_year"],
        "runtime": r["runtime"],
        "genres": genres,
        "genres_zh": [GENRE_ZH.get(g, g) for g in genres],
        "rating": r["rating"],
        "votes": r["votes"],
        "directors": [d for d in (r["directors"] or "").split("|") if d],
        "cast": list(dict.fromkeys(d for d in (r["actors"] or "").split("|") if d)),
    }


def domain_of(item_id: str) -> str:
    return "book" if item_id.startswith("bk:") else "music" if item_id.startswith("mu:") else "film"


def get(title_id: str) -> dict | None:
    got = get_many([title_id])
    return got[0] if got else None


def get_many(ids: list[str]) -> list[dict]:
    """Any work by id: films from the IMDb catalog, books and albums from
    the library (see library.py)."""
    if not ids:
        return []
    films = [i for i in ids if domain_of(i) == "film"]
    by: dict[str, dict] = {}
    if films:
        q = ",".join("?" * len(films))
        rows = _con().execute(f"select * from titles where id in ({q})", films).fetchall()
        by = {r["id"]: _row(r) for r in rows}
        missing = [i for i in films if i not in by]
        if missing:  # found online (see find_film)
            from ..lookup import net

            by.update(net.load_ext(missing))
    others = [i for i in ids if i not in by and domain_of(i) != "film"]
    if others:
        from . import library

        by.update({t["id"]: t for t in library.get_many(others)})
    return [by[i] for i in ids if i in by]


def stats() -> dict:
    if not available():
        return {"available": False}
    meta = dict(_con().execute("select key, value from meta").fetchall())
    return {"available": True, **meta}


# ---------------------------------------------------------------- resolve

def _norm(s: str) -> str:
    s = unicodedata.normalize("NFKC", s or "").lower()
    s = re.sub(r"[《》「」『』“”\"'’‘:：·・,，.。!！?？\-–—()（）\[\]]", " ", s)
    return re.sub(r"\s+", " ", s).strip()


@lru_cache(maxsize=4096)
def _candidates(q: str) -> tuple[sqlite3.Row, ...]:
    c = _con()
    rows: list[sqlite3.Row] = []
    if len(q) >= 3:
        try:
            rows = c.execute(
                "select t.* from titles_fts f join titles t on t.id=f.id"
                " where titles_fts match ? order by t.votes desc limit 60",
                ('"' + q.replace('"', " ") + '"',),
            ).fetchall()
        except sqlite3.OperationalError:
            rows = []
    if not rows:
        like = f"%{q}%"
        alias = " or aliases like ?" if _has_aliases() else ""
        rows = c.execute(
            f"select * from titles where zh like ? or title like ? or original like ?{alias}"
            " order by votes desc limit 60",
            (like, like, like, *([like] if alias else [])),
        ).fetchall()
    return tuple(rows)


def resolve(title: str, year: int | None = None, original: str | None = None, *,
            use_online: bool = False) -> dict | None:
    """Best catalog match for a free-form title, or None if nothing is
    close enough. Score = string similarity + year agreement + popularity.
    use_online: when the catalog has no match, try TMDB and Douban."""
    hit = _resolve_local(title, year, original)
    if hit or not use_online:
        return hit
    from ..lookup import online

    return online.find_film(title, original, year, local=get)


def _resolve_local(title: str, year: int | None, original: str | None) -> dict | None:
    queries = [q for q in {_norm(title), _norm(original or "")} if q]
    best: tuple[float, sqlite3.Row] | None = None
    for q in queries:
        for r in _candidates(q):
            names = _names(r)
            sim = max(fuzz.ratio(q, n) for n in names) / 100
            # "小森林" for "小森林 夏秋篇": a whole-word prefix counts as close
            if any(n.startswith(q + " ") for n in names) and len(q) >= 2:
                sim = max(sim, 0.88)
            if sim < 0.6:
                continue
            score = sim
            if year and r["year"]:
                d = abs(year - r["year"])
                score += 0.25 if d == 0 else 0.1 if d == 1 else -0.15 if d > 3 else 0
            score += 0.04 * math.log10(max(r["votes"], 10))
            if best is None or score > best[0]:
                best = (score, r)
    if best is None or best[0] < 0.85:
        return None
    out = _row(best[1])
    out["match_score"] = round(best[0], 3)
    return out


def search(q: str, limit: int = 12, *, use_online: bool = False) -> list[dict]:
    raw, q = q, _norm(q)
    if not q:
        return []
    rows = list(_candidates(q))
    scored = []
    for r in rows:
        sim = max(fuzz.partial_ratio(q, n) for n in _names(r)) / 100
        scored.append((sim + 0.05 * math.log10(max(r["votes"], 10)), r))
    scored.sort(key=lambda x: -x[0])
    out = [_row(r) for _, r in scored[:limit]]
    exact = any(q in _names(r) for _, r in scored[:limit])
    if use_online and len(out) < 5 and not exact:
        from ..lookup import online

        have = {t["id"] for t in out}
        names = {_norm(t["name"]) for t in out}
        for f in online.search_films(raw):
            # a Douban hit may well be in the catalog under its IMDb id
            local = get(f["id"]) if f["id"].startswith("tt") else _resolve_local(f["name"], f["year"], f["original"])
            t = local or f
            if t["id"] in have or _norm(t["name"]) in names:
                continue
            have.add(t["id"])
            out.append(t)
    return out[:limit]


# ---------------------------------------------------------------- filter

def candidates(
    *,
    kinds: list[str] | None = None,
    genres_any: list[str] | None = None,
    genres_avoid: list[str] | None = None,
    year_min: int | None = None,
    year_max: int | None = None,
    runtime_max: int | None = None,
    rating_min: float | None = None,
    exclude: set[str] | None = None,
    limit: int = 40,
) -> list[dict]:
    """Well-regarded titles matching the filters, mixing the most-voted with
    a slice of lesser-known ones so the shortlist isn't only blockbusters."""
    where, args = ["1=1"], []
    if kinds:
        where.append(f"kind in ({','.join('?' * len(kinds))})")
        args += kinds
    if year_min:
        where.append("year >= ?")
        args.append(year_min)
    if year_max:
        where.append("year <= ?")
        args.append(year_max)
    if runtime_max:
        where.append("(runtime is null or runtime <= ?)")
        args.append(runtime_max)
    where.append("rating >= ?")
    args.append(rating_min or 6.8)
    if genres_any:
        where.append("(" + " or ".join("genres like ?" for _ in genres_any) + ")")
        args += [f"%{g}%" for g in genres_any]
    for g in genres_avoid or []:
        where.append("genres not like ?")
        args.append(f"%{g}%")
    sql = f"select * from titles where {' and '.join(where)}"
    rows = _con().execute(sql + " order by votes desc limit 400", args).fetchall()
    ex = exclude or set()
    rows = [r for r in rows if r["id"] not in ex]
    # quality-weighted: rating matters more than raw popularity
    rows.sort(key=lambda r: -(r["rating"] * 2 + 1.5 * math.log10(r["votes"])))
    head = rows[: limit * 2 // 3]
    tail = rows[limit * 2 // 3 :]
    # lesser-known but strong: from the rest, highest rating first
    tail.sort(key=lambda r: -r["rating"])
    picked = head + tail[: limit - len(head)]
    return [_row(r) for r in picked]


# IMDb's original titles for Chinese films are romanised, so the catalog
# can't tell them apart; the wall draws its Chinese share from this list.
ZH_WALL = [
    ("霸王别姬", 1993), ("活着", 1994), ("花样年华", 2000), ("无间道", 2002), ("重庆森林", 1994),
    ("春光乍泄", 1997), ("一一", 2000), ("卧虎藏龙", 2000), ("让子弹飞", 2010), ("饮食男女", 1994),
    ("大话西游之大圣娶亲", 1995), ("牯岭街少年杀人事件", 1991), ("鬼子来了", 2000), ("阳光灿烂的日子", 1994),
    ("我不是药神", 2018), ("少年的你", 2019), ("甜蜜蜜", 1996), ("喜剧之王", 1999), ("功夫", 2004),
    ("色，戒", 2007), ("英雄", 2002), ("阿飞正传", 1990), ("悲情城市", 1989), ("海上花", 1998),
    ("东邪西毒", 1994), ("流浪地球", 2019), ("步履不停", 2008), ("请回答1988", 2015), ("千与千寻", 2001),
    ("情书", 1995), ("小偷家族", 2018), ("寄生虫", 2019), ("燃烧", 2018), ("饮食男女", 1994),
    ("推拿", 2014), ("白日焰火", 2014), ("地球最后的夜晚", 2018), ("隐入尘烟", 2022), ("爱情神话", 2021),
]


@lru_cache(maxsize=1)
def _zh_wall() -> tuple[dict, ...]:
    out = []
    for name, year in dict.fromkeys(ZH_WALL):
        hit = resolve(name, year)
        if hit:
            out.append(hit)
    return tuple(out)


def wall(n: int = 24, page: int = 0, exclude: set[str] | None = None) -> list[dict]:
    """Cold-start cover wall for films: well-known, well-liked, spread over
    genres, with Chinese-language films given a fair share."""
    import random

    rows = _con().execute(
        "select * from titles where kind in ('movie','series','miniseries') and votes >= 80000"
        " and rating >= 7.0 and zh is not null and zh != '' order by votes desc limit 1200"
    ).fetchall()
    ex = exclude or set()
    rows = [r for r in rows if r["id"] not in ex]
    zh_ids = {t["id"] for t in _zh_wall()}
    # sorted: set order follows string hashing, which changes every launch
    zh_rows = [_con().execute("select * from titles where id=?", (i,)).fetchone() for i in sorted(zh_ids - ex)]
    rng = random.Random(f"film:{page}")
    picked: list[sqlite3.Row] = []
    per_genre: dict[str, int] = {}

    def take(pool: list[sqlite3.Row], k: int) -> None:
        pool = pool[: 150 + page * 80]
        rng.shuffle(pool)
        for r in pool:
            if len(picked) >= k:
                return
            if r in picked:
                continue
            g = (r["genres"] or "?").split(",")[0]
            if per_genre.get(g, 0) >= max(2, n // 5):
                continue
            picked.append(r)
            per_genre[g] = per_genre.get(g, 0) + 1

    take([r for r in zh_rows if r is not None], n // 4)
    take(rows, n)
    return [_row(r) for r in picked]


def brief(t: dict) -> str:
    """One compact line per title for model prompts."""
    if t.get("domain", "film") != "film":
        from . import library

        return library.brief(t)
    parts = [t["id"], t["name"]]
    if t["zh"] and t["original"] != t["zh"]:
        parts.append(t["original"])
    span = str(t["year"] or "")
    if t["kind"] != "movie":
        span += f"–{t['end_year'] or ''} {KIND_ZH.get(t['kind'], '')}"
    parts.append(span)
    if t["runtime"]:
        parts.append(f"{t['runtime']}分钟")
    parts.append("/".join(t["genres_zh"]))
    if t["directors"]:
        parts.append("导演 " + "、".join(t["directors"][:2]))
    if t["cast"]:
        parts.append("主演 " + "、".join(t["cast"][:3]))
    if t["rating"]:
        parts.append(f"IMDb {t['rating']}")
    return " | ".join(p for p in parts if p)
