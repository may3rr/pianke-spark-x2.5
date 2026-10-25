"""Covers and posters, fetched once by public title and kept on disk.

  films    TMDB by IMDb id (with a key); Douban by name and year; Wikipedia
  books    Douban (Chinese editions), Wikipedia lead image, Open Library
  albums   NetEase, Wikipedia lead image, Cover Art Archive by MBID, iTunes

Douban comes first where Chinese editions matter, but it answers bursts
with empty lists, so every shelf has a fallback. A miss is remembered for
a few hours so it doesn't cost a request on every render. The UI draws a
typographic cover meanwhile."""

from __future__ import annotations

import hashlib
import time
from pathlib import Path

from ..config import COVERS_DIR
from ..memory import store
from . import net, online

MISS_TTL = 6 * 3600


def _path(item_id: str) -> Path:
    return COVERS_DIR / (hashlib.sha1(item_id.encode()).hexdigest()[:20] + ".jpg")


def cached(item_id: str) -> Path | None:
    p = _path(item_id)
    return p if p.exists() else None


def _sources(t: dict):
    """Yield (image url, referer) candidates, best first, resolving each
    lazily so a hit on the first source costs no further lookups. Each
    lookup sends only the work's public name / creator / year / id."""
    ext = t.get("ext") or {}
    if ext.get("cover"):
        yield ext["cover"], ("https://book.douban.com/" if "doubanio" in ext["cover"] else None)
    dom = t.get("domain", "film")
    by = (t.get("creators") or [None])[0]
    if dom == "film":
        url = online.tmdb_poster(t["id"])
        if url:
            yield url, None
        url = online.film_poster(t["name"], t.get("original") or t.get("title") or "", t.get("year"))
        if url:
            yield url, "https://movie.douban.com/"
        url = online.film_wiki_poster(t["id"])
        if url:
            yield url, None
    elif dom == "book" and not ext.get("cover"):
        def douban_book():
            for name in dict.fromkeys(x for x in (t.get("zh"), t.get("title")) if x):
                hit = online.find_book(name, by, t.get("year"))
                if hit and hit["ext"].get("cover"):
                    return hit["ext"]["cover"]
            return None

        chinese = t.get("lang") == "中文" or not ext.get("enwiki")
        if chinese:
            url = douban_book()
            if url:
                yield url, "https://book.douban.com/"
        url = online.wiki_image(ext.get("enwiki", ""))
        if url:
            yield url, None
        if ext.get("olid"):
            yield f"https://covers.openlibrary.org/b/olid/{ext['olid']}-M.jpg?default=false", None
        if ext.get("isbn"):
            yield f"https://covers.openlibrary.org/b/isbn/{ext['isbn'].replace('-', '')}-M.jpg?default=false", None
        if not chinese:
            url = douban_book()
            if url:
                yield url, "https://book.douban.com/"
    elif dom == "music" and not ext.get("cover"):
        for name in dict.fromkeys(x for x in (t.get("title"), t.get("original")) if x):
            url = online.netease_cover(name, by)
            if url:
                yield url, None
                break
        url = online.wiki_image(ext.get("enwiki", ""))
        if url:
            yield url, None
        if ext.get("mbid"):
            yield f"https://coverartarchive.org/release-group/{ext['mbid']}/front-500", None
        for name in dict.fromkeys(x for x in (t.get("title"), t.get("zh")) if x):
            hit = online.find_album(name, by, t.get("year"))
            if hit and hit["ext"].get("cover"):
                yield hit["ext"]["cover"], None
                break


def cover(item_id: str) -> Path | None:
    p = cached(item_id)
    if p:
        return p
    with net.cache() as c:
        r = c.execute("select ok, ts from covers where id=?", (item_id,)).fetchone()
    if r and not r["ok"] and time.time() - r["ts"] < MISS_TTL:
        return None
    if not store.get_pref("covers_online", True):
        return None
    from ..catalog import search as catalog

    t = catalog.get(item_id)
    if not t:
        return None
    net.reset_failures()
    for url, ref in _sources(t):
        data = net.get_bytes(url, referer=ref)
        if data and len(data) > 1500:  # placeholders are tiny
            COVERS_DIR.mkdir(parents=True, exist_ok=True)
            p = _path(item_id)
            p.write_bytes(data)
            with net.cache() as c:
                c.execute("insert or replace into covers values(?,?,?,?,?)",
                          (item_id, p.name, url, 1, time.time()))
            return p
    if net.failures():  # couldn't ask everyone: try again on the next render
        return None
    with net.cache() as c:
        c.execute("insert or replace into covers values(?,?,?,?,?)", (item_id, "", "", 0, time.time()))
    return None


def state(ids: list[str]) -> dict[str, str]:
    """id → "ok" (on disk), "miss" (looked up recently, none found) or
    "unknown". Cheap: one disk check each and one query."""
    out = {i: "ok" if cached(i) else "unknown" for i in ids}
    rest = [i for i, v in out.items() if v == "unknown"]
    if rest:
        with net.cache() as c:
            rows = c.execute(
                f"select id, ts from covers where ok=0 and id in ({','.join('?' * len(rest))})", rest
            ).fetchall()
        for r in rows:
            if time.time() - r["ts"] < MISS_TTL:
                out[r["id"]] = "miss"
    return out


def prefetch(ids: list[str]) -> None:
    """Warm the cache slowly in the background (cold-start walls)."""
    for i in ids:
        if not store.get_pref("covers_online", True):
            return
        try:
            cover(i)
        except Exception:  # noqa: BLE001 — best effort
            pass
