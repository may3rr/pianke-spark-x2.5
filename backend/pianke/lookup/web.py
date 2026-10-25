"""Web search through Exa or Tavily, whichever the user gave a key for.
Off (every call returns []) when no key is set, so the flows can call it
unconditionally.

Three uses, all in the recommendation flows:
  discover  queries the model writes from the request, to find recent or
            niche works the local shelves don't have
  verify    a book or album no lookup source knows: does it exist?
  reviews   what people say about each final pick, for a concrete reason
"""

from __future__ import annotations

import hashlib
import re
from concurrent.futures import ThreadPoolExecutor

from rapidfuzz import fuzz

from ..llm import settings
from . import net, online

EXA = "https://api.exa.ai/search"
TAVILY = "https://api.tavily.com/search"


def enabled() -> bool:
    return bool(settings.search_key(settings.load()))


def provider() -> str:
    s = settings.load()
    return {"exa": "Exa", "tavily": "Tavily"}.get(s["search_provider"], "") if enabled() else ""


def search(query: str, n: int = 5, lane: str = "fg") -> list[dict]:
    """[{title, url, text, date}], text trimmed to a few hundred characters.
    Cached for a day; [] on any failure or when search is off."""
    s = settings.load()
    key = settings.search_key(s)
    query = query.strip()
    if not key or not query:
        return []
    if s["search_provider"] == "exa":
        data = net.get_json(
            EXA, {}, lane=lane, ttl=86400, headers={"x-api-key": key},
            body={"query": query, "numResults": n, "type": "auto",
                  "contents": {"text": {"maxCharacters": 700}}},
        )
        rows = (data or {}).get("results") or []
        out = [{"title": r.get("title") or "", "url": r.get("url") or "",
                "text": r.get("text") or "", "date": (r.get("publishedDate") or "")[:10]} for r in rows]
    else:
        data = net.get_json(
            TAVILY, {}, lane=lane, ttl=86400, headers={"Authorization": f"Bearer {key}"},
            body={"query": query, "max_results": n, "search_depth": "basic"},
        )
        rows = (data or {}).get("results") or []
        out = [{"title": r.get("title") or "", "url": r.get("url") or "",
                "text": r.get("content") or "", "date": (r.get("published_date") or "")[:10]} for r in rows]
    for r in out:
        r["text"] = re.sub(r"\s+", " ", r["text"]).strip()[:700]
    return out


def search_many(queries: list[str], n: int = 5) -> list[list[dict]]:
    with ThreadPoolExecutor(3) as ex:
        return list(ex.map(lambda q: search(q, n), queries))


def block(results: list[dict], limit: int = 8, chars: int = 300) -> str:
    """Results as prompt text, deduplicated by URL."""
    seen, lines = set(), []
    for r in results:
        if r["url"] in seen or not (r["title"] or r["text"]):
            continue
        seen.add(r["url"])
        date = f"（{r['date']}）" if r["date"] else ""
        lines.append(f"- {r['title']}{date}：{r['text'][:chars]}")
        if len(lines) >= limit:
            break
    return "\n".join(lines)


# ---------------------------------------------------------------- verify

WORD = {"book": "书", "album": "专辑"}


def find_work(kind: str, title: str, creator: str | None, year: int | None) -> dict | None:
    """Last resort for a book or album no lookup source knows: accept it when
    a search result names both the title and the creator. Saved as an ext
    record (bk:web… / mu:web…) so the rest of the app treats it like any
    online find; the snippet is kept as its summary."""
    if not enabled() or not title:
        return None
    rows = search(f"{title} {creator or ''} {WORD[kind]}".strip(), n=5, lane="bg")
    nt = online._norm(title)
    for r in rows:
        hay = online._norm(f"{r['title']} {r['text']}")
        if fuzz.partial_ratio(nt, hay) < 92:
            continue
        if creator and fuzz.partial_ratio(online._norm(creator), hay) < 85:
            continue
        prefix = "bk" if kind == "book" else "mu"
        h = hashlib.sha1(f"{nt}|{online._norm(creator or '')}".encode()).hexdigest()[:12]
        zh = title if re.search(r"[一-鿿]", title) else None
        work = {
            "id": f"{prefix}:web{h}", "kind": kind, "zh": zh, "title": title, "original": title,
            "year": year, "creators": [creator] if creator else [], "genres": [], "lang": "",
            "region": "", "pages": None, "popularity": 0,
            "ext": {"web": r["url"], "summary": r["text"][:300]},
        }
        net.save_ext(work["id"], kind, work)
        return work
    return None
