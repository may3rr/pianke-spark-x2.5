"""Find works online when the local shelf doesn't have them, and the public
pages covers come from. Inputs are titles / creators / years only.

  books   Douban book suggest (best coverage of Chinese editions)
  albums  iTunes Search (Chinese and Western catalogues, artwork)
  films   TMDB by IMDb id when the user set a key, else Douban movie
          suggest; posters only — films resolve locally
  covers  NetEase Cloud Music album search (no key, fast) before iTunes

A work found online is saved as an ext record (bk:db… / mu:it…) so the rest
of the app can treat it like a shelf entry."""

from __future__ import annotations

import re
import unicodedata

from opencc import OpenCC
from rapidfuzz import fuzz

from ..catalog.vocab import ALBUM_GENRES, map_genres
from ..llm import settings
from . import net

t2s = OpenCC("t2s").convert
DOUBAN_SUGGEST = "https://{sub}.douban.com/j/subject_suggest"
ITUNES = "https://itunes.apple.com/search"


def _norm(s: str) -> str:
    s = unicodedata.normalize("NFKC", s or "").lower()
    s = re.sub(r"[\[［(（【][^\]］)）】]{0,6}[\]］)）】]", " ", s)  # [英] 石黑一雄
    s = re.sub(r"[《》「」『』“”\"'’‘:：·・,，.。!！?？\-–—()（）\[\]]", " ", s)
    return re.sub(r"\s+", " ", s).strip()


def _year(s: str | None) -> int | None:
    m = re.match(r"(\d{4})", s or "")
    return int(m.group(1)) if m else None


def douban(sub: str, q: str, lane: str = "bg") -> list[dict]:
    q = (q or "").strip()[:60]
    if not q:
        return []
    data = net.get_json(DOUBAN_SUGGEST.format(sub=sub), {"q": q}, referer=f"https://{sub}.douban.com/", lane=lane)
    return data if isinstance(data, list) else []


def itunes_books(q: str, limit: int = 8, lane: str = "bg") -> list[dict]:
    q = (q or "").strip()[:80]
    if not q:
        return []
    data = net.get_json(ITUNES, {"term": q, "media": "ebook", "limit": limit, "country": "us"}, lane=lane)
    return (data or {}).get("results") or []


def itunes_albums(q: str, limit: int = 10, lane: str = "bg") -> list[dict]:
    q = (q or "").strip()[:80]
    if not q:
        return []
    out: list[dict] = []
    for country in ("tw", "us"):
        data = net.get_json(ITUNES, {"term": q, "entity": "album", "limit": limit,
                                     "country": country, "lang": "en_us"}, lane=lane)
        rows = (data or {}).get("results") or []
        out += [r for r in rows if r.get("collectionId") not in {x.get("collectionId") for x in out}]
        if len(rows) >= 3:
            break
    return out


# ---------------------------------------------------------------- books

def _book_from_douban(r: dict) -> dict:
    author = re.sub(r"^\s*[\[［(（【][^\]］)）】]*[\]］)）】]\s*", "", r.get("author_name") or "").strip()
    return {
        "id": f"bk:db{r['id']}",
        "kind": "book",
        "zh": r.get("title") or "",
        "title": r.get("title") or "",
        "original": r.get("title") or "",
        "year": _year(r.get("year")),
        "creators": [a for a in re.split(r"\s*[/、,]\s*", author) if a][:3],
        "genres": [],
        "lang": "",
        "region": "",
        "pages": None,
        "popularity": 0,
        "ext": {"douban": r["id"], "cover": (r.get("pic") or "").replace("/s/public/", "/m/public/")},
    }


def _book_from_itunes(r: dict) -> dict:
    name = t2s(r.get("trackName") or "")
    name = re.sub(r"\s*[(（][^)）]*[)）]\s*$", "", name) or name
    return {
        "id": f"bk:it{r['trackId']}",
        "kind": "book",
        "zh": name if re.search(r"[\u4e00-\u9fff]", name) else None,
        "title": name,
        "original": name,
        "year": _year(r.get("releaseDate")),
        "creators": [t2s(r.get("artistName") or "")],
        "genres": [],
        "lang": "",
        "region": "",
        "pages": None,
        "popularity": 0,
        "ext": {"itunes": r["trackId"], "cover": (r.get("artworkUrl100") or "").replace("100x100bb", "600x600bb")},
    }


def search_books(q: str, limit: int = 8, lane: str = "bg") -> list[dict]:
    """Douban first (Chinese editions); when it has nothing — or is
    throttling us — iTunes Books."""
    rows = [r for r in douban("book", q, lane) if r.get("type") == "b" and r.get("id")]
    cands = [_book_from_douban(r) for r in rows]
    if not cands:
        # iTunes matches loosely; keep books whose title carries a word of the query
        words = [w for w in _norm(q).split() if len(w) >= 2] or [_norm(q)]
        cands = [
            b for b in (_book_from_itunes(r) for r in itunes_books(q, lane=lane) if r.get("trackId"))
            if max(fuzz.partial_ratio(w, _norm(t2s(b["title"]))) for w in words) >= 80
        ]
    seen, out = set(), []
    for b in cands:
        key = (_norm(t2s(b["title"])), tuple(_norm(t2s(c)) for c in b["creators"][:1]))
        if key in seen:  # editions of the same book: keep the first (most popular)
            continue
        seen.add(key)
        out.append(b)
    return out[:limit]


def find_book(title: str, author: str | None = None, year: int | None = None) -> dict | None:
    q = f"{title} {author or ''}".strip()
    best: tuple[float, dict] | None = None
    for b in search_books(q) or search_books(title):
        sim = fuzz.ratio(_norm(title), _norm(b["title"])) / 100
        if sim < 0.6:
            continue
        score = sim
        if author and b["creators"]:
            score += 0.15 if any(fuzz.partial_ratio(_norm(author), _norm(c)) >= 80 for c in b["creators"]) else -0.2
        if best is None or score > best[0]:
            best = (score, b)
    if best is None or best[0] < 0.8:
        return None
    net.save_ext(best[1]["id"], "book", best[1])
    return best[1]


# ---------------------------------------------------------------- albums

_SUFFIX = re.compile(r"\s*[-–(（\[].*?(single|ep|deluxe|remaster|edition|live|版|記念|纪念).*$", re.I)


def _album_from_itunes(r: dict) -> dict:
    name = t2s(r.get("collectionName") or "")
    clean = _SUFFIX.sub("", name).strip() or name
    return {
        "id": f"mu:it{r['collectionId']}",
        "kind": "album",
        "zh": clean if re.search(r"[一-鿿]", clean) else None,
        "title": clean,
        "original": clean,
        "year": _year(r.get("releaseDate")),
        "creators": [t2s(r.get("artistName") or "")],
        "genres": map_genres([r.get("primaryGenreName") or ""], ALBUM_GENRES),
        "lang": "",
        "region": "",
        "pages": None,
        "popularity": 0,
        "tracks": r.get("trackCount"),
        "ext": {"itunes": r["collectionId"],
                "cover": (r.get("artworkUrl100") or "").replace("100x100bb", "600x600bb")},
    }


def search_albums(q: str, limit: int = 8, lane: str = "bg") -> list[dict]:
    out = []
    for r in itunes_albums(q, limit=15, lane=lane):
        if r.get("collectionType") != "Album" or not r.get("collectionId"):
            continue
        if re.search(r"\b(single|ep)\b", r.get("collectionName") or "", re.I) and (r.get("trackCount") or 9) < 5:
            continue
        out.append(_album_from_itunes(r))
    return out[:limit]


def find_album(title: str, artist: str | None = None, year: int | None = None) -> dict | None:
    best: tuple[float, dict] | None = None
    for a in search_albums(f"{title} {artist or ''}".strip()) or search_albums(title):
        sim = fuzz.ratio(_norm(title), _norm(a["title"])) / 100
        if sim < 0.6:
            continue
        score = sim
        if artist:
            score += 0.15 if fuzz.partial_ratio(_norm(artist), _norm(a["creators"][0])) >= 80 else -0.25
        if year and a["year"]:
            score += 0.05 if abs(year - a["year"]) <= 1 else 0
        if best is None or score > best[0]:
            best = (score, a)
    if best is None or best[0] < 0.8:
        return None
    net.save_ext(best[1]["id"], "album", best[1])
    return best[1]


# ---------------------------------------------------------------- Wikipedia

WIKIDATA_API = "https://www.wikidata.org/w/api.php"
ENWIKI_API = "https://en.wikipedia.org/w/api.php"


def wiki_image(enwiki_title: str) -> str | None:
    """Lead image of an English Wikipedia article (posters, jackets and
    album covers are usually there)."""
    if not enwiki_title:
        return None
    data = net.get_json(ENWIKI_API, {"action": "query", "titles": enwiki_title, "prop": "pageimages",
                                     "piprop": "thumbnail", "pithumbsize": 500, "pilicense": "any",
                                     "format": "json", "redirects": 1})
    for page in ((data or {}).get("query") or {}).get("pages", {}).values():
        src = (page.get("thumbnail") or {}).get("source")
        if src:
            return src.split("?")[0]
    return None


def film_wiki_poster(imdb_id: str) -> str | None:
    data = net.get_json(WIKIDATA_API, {"action": "query", "list": "search", "srlimit": 1, "format": "json",
                                       "srsearch": f"haswbstatement:P345={imdb_id}"})
    hits = ((data or {}).get("query") or {}).get("search") or []
    if not hits:
        return None
    qid = hits[0]["title"]
    ent = net.get_json(WIKIDATA_API, {"action": "wbgetentities", "ids": qid, "props": "sitelinks",
                                      "sitefilter": "enwiki", "format": "json"})
    title = (((ent or {}).get("entities") or {}).get(qid, {}).get("sitelinks") or {}).get("enwiki", {}).get("title")
    return wiki_image(title) if title else None


# ---------------------------------------------------------------- film posters

def film_poster(name: str, original: str, year: int | None) -> str | None:
    for q in dict.fromkeys(x for x in (name, original) if x):
        rows = [r for r in douban("movie", q) if r.get("img")]
        for r in rows:
            y = _year(r.get("year"))
            names = [_norm(r.get("title", "")), _norm(r.get("sub_title", ""))]
            close = max(fuzz.ratio(_norm(q), n) for n in names) >= 70
            if close and (not year or not y or abs(y - year) <= 1):
                return r["img"].replace("s_ratio_poster", "m_ratio_poster")
    return None


# ---------------------------------------------------------------- TMDB

TMDB_FIND = "https://api.themoviedb.org/3/find/{id}"
TMDB_IMG = "https://image.tmdb.org/t/p/w342"


def _tmdb_auth() -> dict | None:
    key = settings.load()["tmdb_key"]
    if not key:
        return None
    # v4 read access tokens are JWTs; v3 keys go in the query string
    return {"headers": {"Authorization": f"Bearer {key}"}} if key.startswith("eyJ") else {"auth": {"api_key": key}}


def tmdb_film(imdb_id: str, lane: str = "bg") -> dict | None:
    """TMDB's record for an IMDb id, Chinese title and overview where TMDB
    has them. One request, no search, so it is exact and fast."""
    auth = _tmdb_auth()
    if not auth or not imdb_id.startswith("tt"):
        return None
    data = net.get_json(TMDB_FIND.format(id=imdb_id), {"external_source": "imdb_id", "language": "zh-CN"},
                        lane=lane, **auth)
    for k in ("movie_results", "tv_results"):
        rows = (data or {}).get(k) or []
        if rows:
            return rows[0]
    return None


def tmdb_poster(imdb_id: str) -> str | None:
    r = tmdb_film(imdb_id)
    return f"{TMDB_IMG}{r['poster_path']}" if r and r.get("poster_path") else None


# ---------------------------------------------------------------- NetEase

NETEASE_SEARCH = "https://music.163.com/api/search/get"


def netease_cover(title: str, artist: str | None) -> str | None:
    """Album art from NetEase Cloud Music's search: no key, ~0.2 s, strong on
    Chinese and Western catalogues alike. Strict on title and artist, since a
    wrong cover is worse than the typographic one."""
    q = f"{artist or ''} {title}".strip()
    data = net.get_json(NETEASE_SEARCH, {"s": q, "type": 10, "limit": 8}, referer="https://music.163.com/")
    for r in ((data or {}).get("result") or {}).get("albums") or []:
        if fuzz.ratio(_norm(title), _norm(t2s(r.get("name") or ""))) < 85:
            continue
        name = t2s((r.get("artist") or {}).get("name") or "")
        if artist and fuzz.partial_ratio(_norm(artist), _norm(name)) < 80:
            continue
        if r.get("picUrl"):
            return r["picUrl"].replace("http://", "https://") + "?param=600y600"
    return None


# ---------------------------------------------------------------- films

TMDB_SEARCH = "https://api.themoviedb.org/3/search/multi"
TMDB_EXTERNAL = "https://api.themoviedb.org/3/{kind}/{id}/external_ids"


def _film(id_: str, kind: str, zh: str | None, title: str, original: str, year: int | None,
          ext: dict) -> dict:
    """A film found online, in the catalog's row shape."""
    return {
        "id": id_, "domain": "film", "kind": kind, "title": title or zh or "", "original": original or title,
        "zh": zh, "name": zh or title, "year": year, "end_year": None, "runtime": None,
        "genres": [], "genres_zh": [], "rating": None, "votes": 0, "directors": [], "cast": [],
        "ext": ext,
    }


def _film_score(q: str, names: list[str], year: int | None, y: int | None) -> float:
    sim = max((fuzz.ratio(_norm(q), _norm(n)) for n in names if n), default=0) / 100
    if year and y:
        # remakes share titles: more than two years apart is another film
        d = abs(year - y)
        sim += 0.1 if d <= 1 else -0.05 if d == 2 else -0.5
    return sim


def tmdb_search_films(q: str, lane: str = "bg") -> list[dict]:
    """TMDB multi-search in Chinese; each hit carries its IMDb id when TMDB
    knows it, so it can be matched back to the local catalog."""
    auth = _tmdb_auth()
    if not auth or not q.strip():
        return []
    data = net.get_json(TMDB_SEARCH, {"query": q, "language": "zh-CN", "include_adult": "false"},
                        lane=lane, **auth)
    out = []
    for r in ((data or {}).get("results") or [])[:6]:
        kind = {"movie": "movie", "tv": "series"}.get(r.get("media_type"))
        if not kind:
            continue
        ids = net.get_json(TMDB_EXTERNAL.format(kind="movie" if kind == "movie" else "tv", id=r["id"]),
                           {}, lane=lane, **auth) or {}
        zh = r.get("title") or r.get("name") or ""
        orig = r.get("original_title") or r.get("original_name") or ""
        poster = f"{TMDB_IMG}{r['poster_path']}" if r.get("poster_path") else ""
        out.append(_film(
            ids.get("imdb_id") or f"fm:tmdb{r['id']}", kind,
            zh if re.search(r"[一-鿿]", zh) else None, zh, orig,
            _year(r.get("release_date") or r.get("first_air_date")),
            {"tmdb": r["id"], "cover": poster, "summary": (r.get("overview") or "")[:300]},
        ))
    return out


def douban_search_films(q: str, lane: str = "bg") -> list[dict]:
    """Douban's suggest box: the best coverage of Chinese titles, no ids
    shared with IMDb, so finds become fm:db… records."""
    out = []
    for r in douban("movie", q, lane):
        if not r.get("id") or r.get("type") not in (None, "movie"):
            continue
        title = r.get("title") or ""
        out.append(_film(
            f"fm:db{r['id']}", "series" if r.get("episode") else "movie",
            title if re.search(r"[一-鿿]", title) else None, title,
            r.get("sub_title") or title, _year(r.get("year")),
            {"douban": r["id"], "cover": (r.get("img") or "").replace("s_ratio_poster", "m_ratio_poster")},
        ))
    return out


def find_film(title: str, original: str | None = None, year: int | None = None,
              local=None) -> dict | None:
    """A film the local catalog doesn't have: TMDB (when the user set a key),
    then Douban. `local(imdb_id)` maps a TMDB hit back to the catalog row so
    the rest of the app keeps using IMDb ids where it can."""
    for search in (tmdb_search_films, douban_search_films):
        best: tuple[float, dict] | None = None
        for q in dict.fromkeys(x for x in (title, original) if x):
            for f in search(q):
                score = _film_score(q, [f["zh"] or "", f["title"], f["original"]], year, f["year"])
                if score >= 0.8 and (best is None or score > best[0]):
                    best = (score, f)
            if best:
                break
        if best:
            f = best[1]
            if local and f["id"].startswith("tt"):
                hit = local(f["id"])
                if hit:
                    return hit
            net.save_ext(f["id"], "film", f)
            return f
    return None


def search_films(q: str, lane: str = "fg") -> list[dict]:
    """Films for the search box when the catalog has few matches."""
    out = tmdb_search_films(q, lane) or douban_search_films(q, lane)
    for f in out:
        net.save_ext(f["id"], "film", f)
    return out
