"""Build data/library.sqlite: the local shelf of books and albums.

Source: Wikidata (CC0). Notable works only (enough Wikipedia sitelinks to be
widely known), plus a lower bar for Chinese-language works so the shelf is
not only translated classics and Western albums. Sitelink count stands in
for popularity.

The library is what recommendation filters and cold-start walls draw from.
Anything the user or the model names outside it is verified online at run
time (pianke/lookup), so it does not need to be complete.

    python scripts/build_library.py            # ~5 minutes over the network
"""

from __future__ import annotations

import json
import re
import sqlite3
import sys
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import httpx
from opencc import OpenCC

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from pianke.catalog.vocab import ALBUM_GENRES, BOOK_GENRES, map_genres

REPO = Path(__file__).resolve().parents[2]
OUT = REPO / "data" / "library.sqlite"
UA = {"User-Agent": "PiankeLibraryBuilder/0.2 (offline-first personal recommender; one-off build) httpx"}
SPARQL = "https://query.wikidata.org/sparql"
API = "https://www.wikidata.org/w/api.php"
t2s = OpenCC("t2s").convert

BOOK_TYPES = "wd:Q7725634 wd:Q8261 wd:Q47461344 wd:Q571 wd:Q49084 wd:Q1667921 wd:Q5185279 wd:Q35760 wd:Q8274 wd:Q725377"
ZH_PLACES = "wd:Q148 wd:Q865 wd:Q8646 wd:Q14773 wd:Q334 wd:Q833"

# (search, how many top results by incoming links, minimum sitelinks)
# Wikidata's own search index, sorted by how many items link to each work.
# (The SPARQL endpoint was throttled to one query a minute when this was
# written; the search API is not.)
LISTS = {
    "book": [
        ("haswbstatement:P31=Q7725634", 6000, 8),
        ("haswbstatement:P31=Q8261", 5000, 8),
        ("haswbstatement:P31=Q47461344", 3000, 8),
        ("haswbstatement:P31=Q571", 3000, 10),
        ("haswbstatement:P31=Q7725634 haswbstatement:P407=Q7850", 3000, 2),
        ("haswbstatement:P31=Q8261 haswbstatement:P407=Q7850", 2000, 2),
        ("haswbstatement:P31=Q7725634 haswbstatement:P407=Q5287", 1500, 4),
        ("haswbstatement:P31=Q8261 haswbstatement:P495=Q17", 1500, 4),
    ],
    "album": [
        ("haswbstatement:P31=Q482994", 10000, 8),
        ("haswbstatement:P31=Q482994 haslabel:zh", 5000, 2),
        ("haswbstatement:P31=Q482994 haswbstatement:P495=Q17", 2000, 4),
        ("haswbstatement:P31=Q482994 haswbstatement:P495=Q884", 1500, 4),
    ],
}


def search_list(q: str, n: int) -> list[str]:
    import hashlib

    CACHE.mkdir(parents=True, exist_ok=True)
    f = CACHE / ("search-" + hashlib.sha1(f"{q}|{n}".encode()).hexdigest() + ".json")
    if f.exists():
        return json.loads(f.read_text())
    out: list[str] = []
    complete = True
    for offset in range(0, min(n, 10000), 500):
        hits = None
        for attempt in range(10):
            time.sleep(2)  # this IP gets throttled easily; go slow
            try:
                r = httpx.get(API, params={"action": "query", "list": "search", "srsearch": q,
                                           "srsort": "incoming_links_desc", "srlimit": 500,
                                           "sroffset": offset, "srprop": "", "format": "json"},
                              headers=UA, timeout=60)
                if r.status_code == 429:
                    wait = float(r.headers.get("retry-after", 30))
                    print(f"  429, waiting {wait:.0f}s", file=sys.stderr)
                    time.sleep(wait)
                    continue
                r.raise_for_status()
                hits = r.json().get("query", {}).get("search", [])
                break
            except Exception as e:  # noqa: BLE001
                print(f"  search retry {attempt + 1}: {type(e).__name__}", file=sys.stderr)
                time.sleep(5 + attempt * 5)
        if hits is None:  # gave up: keep what we have but don't cache a partial list
            complete = False
            break
        out += [h["title"] for h in hits]
        if len(hits) < 500:
            break
    if complete:
        f.write_text(json.dumps(out))
    return out


LANGS = "zh-hans|zh-cn|zh|zh-hant|zh-tw|zh-hk|en|ja|ko|fr|de|es|ru|it|pt"

LANG_ZH = {
    "Q7850": "中文", "Q727694": "中文", "Q9186": "中文", "Q37041": "中文", "Q5287": "日文",
    "Q1860": "英文", "Q150": "法文", "Q7737": "俄文", "Q1321": "西班牙文", "Q188": "德文",
    "Q652": "意大利文", "Q5146": "葡萄牙文", "Q9176": "韩文", "Q9027": "瑞典文",
    "Q809": "波兰文", "Q9056": "捷克文", "Q256": "土耳其文", "Q13955": "阿拉伯文",
}
REGION = {  # country of origin / citizenship → region bucket for albums
    "Q148": "华语", "Q865": "华语", "Q8646": "华语", "Q14773": "华语", "Q334": "华语", "Q833": "华语",
    "Q17": "日本", "Q884": "韩国", "Q30": "欧美", "Q145": "欧美", "Q16": "欧美", "Q408": "欧美",
    "Q142": "欧美", "Q183": "欧美", "Q27": "欧美", "Q34": "欧美", "Q20": "欧美", "Q35": "欧美",
    "Q55": "欧美", "Q31": "欧美", "Q29": "欧美", "Q38": "欧美", "Q664": "欧美", "Q33": "欧美",
    "Q155": "拉美", "Q96": "拉美", "Q414": "拉美", "Q241": "拉美", "Q298": "拉美", "Q739": "拉美",
}


def sparql(q: str) -> list[dict]:
    """Big result sets get cut off mid-stream, so queries with a plain
    "?s >= N" bar are split into sitelink bands and fetched as CSV."""
    import csv
    import io

    m = re.search(r"FILTER\(\?s >= (\d+)\)", q)
    if m and int(m.group(1)) >= 8:
        lo = int(m.group(1))
        bands = [(lo, lo + 2), (lo + 2, lo + 6), (lo + 6, lo + 16), (lo + 16, 100000)]
        out: list[dict] = []
        for a, b in bands:
            out += sparql(q.replace(m.group(0), f"FILTER(?s >= {a} && ?s < {b})"))
        return out
    import hashlib

    CACHE.mkdir(parents=True, exist_ok=True)
    f = CACHE / ("sparql-" + hashlib.sha1(q.encode()).hexdigest() + ".csv")
    text = f.read_text() if f.exists() else None
    for attempt in range(6):
        if text is not None:
            break
        # WDQS may throttle to one query a minute; space them out
        wait = _last_sparql[0] + 62 - time.time()
        if wait > 0:
            time.sleep(wait)
        _last_sparql[0] = time.time()
        try:
            r = httpx.get(SPARQL, params={"query": q}, headers={**UA, "Accept": "text/csv"}, timeout=180)
            r.raise_for_status()
            text = r.text
            f.write_text(text)
        except Exception as e:  # noqa: BLE001
            print(f"  sparql retry {attempt + 1}: {str(e)[:120]}", file=sys.stderr)
    if text is None:
        return []
    rows = list(csv.DictReader(io.StringIO(text)))
    return [{"x": {"value": row["x"]}, "s": {"value": row["s"]}} for row in rows if row.get("s")]


_last_sparql = [0.0]


CACHE = REPO / "data" / "raw" / "wikidata"


def entities(ids: list[str], props: str = "labels|claims|sitelinks", sitefilter: str | None = None) -> dict:
    """wbgetentities in batches of 50, two at a time (Wikidata rate-limits
    harder than that). Every batch is cached on disk so a rerun resumes."""
    CACHE.mkdir(parents=True, exist_ok=True)
    out: dict = {}
    batches = [ids[i : i + 50] for i in range(0, len(ids), 50)]

    def one(b: list[str]) -> dict:
        import hashlib

        f = CACHE / (hashlib.sha1(("|".join(b) + props + (sitefilter or "")).encode()).hexdigest() + ".json")
        if f.exists():
            return json.loads(f.read_text())
        for attempt in range(10):
            try:
                params = {"action": "wbgetentities", "ids": "|".join(b), "props": props,
                          "languages": LANGS, "format": "json", "maxlag": 5}
                if sitefilter:
                    params["sitefilter"] = sitefilter
                r = httpx.get(API, params=params, headers=UA, timeout=90)
                if r.status_code == 429 or "maxlag" in r.text[:200]:
                    time.sleep(float(r.headers.get("retry-after", 15 + attempt * 10)))
                    continue
                r.raise_for_status()
                d = r.json().get("entities", {})
                f.write_text(json.dumps(d, ensure_ascii=False))
                return d
            except Exception as e:  # noqa: BLE001
                print(f"  api retry {attempt + 1}: {type(e).__name__}", file=sys.stderr)
                time.sleep(3 + attempt * 3)
        print(f"  gave up on a batch starting {b[0]}", file=sys.stderr)
        return {}

    with ThreadPoolExecutor(4) as ex:
        for i, d in enumerate(ex.map(one, batches)):
            out.update(d)
            if i % 20 == 0:
                print(f"  {i * 50}/{len(ids)}", file=sys.stderr)
    return out


def label(e: dict, prefer: tuple[str, ...] = ("zh-hans", "zh-cn", "zh", "zh-hant", "zh-tw", "zh-hk")) -> str:
    labels = e.get("labels", {})
    for lang in prefer:
        if lang in labels:
            v = labels[lang]["value"]
            return t2s(v) if lang.startswith("zh") else v
    return ""


def en_label(e: dict) -> str:
    labels = e.get("labels", {})
    if "en" in labels:
        return labels["en"]["value"]
    return next((v["value"] for v in labels.values()), "")


def claim_ids(e: dict, p: str) -> list[str]:
    out = []
    for c in e.get("claims", {}).get(p, []):
        v = c.get("mainsnak", {}).get("datavalue", {}).get("value")
        if isinstance(v, dict) and "id" in v:
            out.append(v["id"])
    return out


def claim_str(e: dict, p: str) -> str:
    for c in e.get("claims", {}).get(p, []):
        v = c.get("mainsnak", {}).get("datavalue", {}).get("value")
        if isinstance(v, str):
            return v
        if isinstance(v, dict) and "text" in v:
            return v["text"]
        if isinstance(v, dict) and "amount" in v:
            return v["amount"].lstrip("+")
    return ""


def year_of(e: dict) -> int | None:
    years = []
    for c in e.get("claims", {}).get("P577", []):
        v = c.get("mainsnak", {}).get("datavalue", {}).get("value")
        if isinstance(v, dict) and "time" in v:
            m = re.match(r"([+-]\d+)-", v["time"])
            if m:
                years.append(int(m.group(1)))
    return min(years) if years else None


SEEDS = Path(__file__).with_name("seeds.json")


def seed_rows() -> list[tuple]:
    """Hand-picked works, each verified online (Douban / iTunes) before it
    goes on the shelf. The curated genre / language / region are kept; the
    id, title and creator come from what the lookup found."""
    from pianke.lookup import online

    data = json.loads(SEEDS.read_text())
    rows = []
    for kind in ("book", "album"):
        found = missed = 0
        for title, creator, year, genres, place in data[kind]:
            title = title.removeprefix(creator).strip() or title
            hit = (online.find_book if kind == "book" else online.find_album)(title, creator, year)
            if hit is None:
                missed += 1
                continue
            found += 1
            rows.append((
                hit["id"], kind, hit.get("zh") or (title if re.search(r"[\u4e00-\u9fff]", title) else None),
                hit["title"], hit["original"], year, json.dumps(hit["creators"] or [creator], ensure_ascii=False),
                json.dumps(genres, ensure_ascii=False), place if kind == "book" else "",
                place if kind == "album" else "", None, 40,
                json.dumps(hit.get("ext") or {}, ensure_ascii=False),
            ))
        print(f"[seeds] {kind}: {found} verified, {missed} not found", file=sys.stderr)
    return rows


def main() -> None:
    seeds_only = "--seeds-only" in sys.argv
    OUT.parent.mkdir(parents=True, exist_ok=True)
    tmp = OUT.with_suffix(".tmp")
    tmp.unlink(missing_ok=True)
    con = sqlite3.connect(tmp)
    con.executescript(
        """
        create table works(
          id text primary key,     -- bk:Q… | mu:Q…
          kind text,               -- book | album
          zh text, title text, original text,
          year integer,
          creators text,           -- json [names]
          genres text,             -- json [zh genre]
          lang text,               -- books: original language (zh)
          region text,             -- albums: 华语 / 日本 / 韩国 / 欧美 / 拉美 / 其他
          pages integer,
          popularity integer,      -- Wikipedia sitelinks
          ext text                 -- json {mbid, olid, isbn, zhwiki}
        );
        create table meta(key text primary key, value text);
        """
    )
    for kind, queries in ({} if seeds_only else LISTS).items():
        print(f"[{kind}] listing", file=sys.stderr)
        need: dict[str, int] = {}  # qid → lowest sitelink bar among the lists it came from
        for q, n, bar in queries:
            got = search_list(q, n)
            for qid in got:
                need[qid] = min(need.get(qid, 10**6), bar)
            print(f"  {q}: {len(got)} → {len(need)}", file=sys.stderr)
        # sitelinks alone are small: count them first, fetch details only
        # for works known widely enough
        sl = entities(list(need), props="sitelinks")
        pop = {qid: len(e.get("sitelinks", {})) for qid, e in sl.items()}
        keep = [qid for qid in need if pop.get(qid, 0) >= need[qid]]
        print(f"[{kind}] {len(keep)} pass the sitelink bar", file=sys.stderr)
        ents = entities(keep, props="labels|claims|sitelinks", sitefilter="zhwiki|enwiki")
        # names of genres (labels only) and creators (albums also need the
        # performer's country for the region bucket, which means claims)
        cp = "P50" if kind == "book" else "P175"
        genres = sorted({g for e in ents.values() for g in claim_ids(e, "P136")[:6]})
        people = sorted({c for e in ents.values() for c in claim_ids(e, cp)[:2]})
        print(f"[{kind}] {len(genres)} genres, {len(people)} creators", file=sys.stderr)
        ref = entities(genres, props="labels")
        ref.update(entities(people, props="labels|claims" if kind == "album" else "labels"))
        rows = []
        for qid, e in ents.items():
            if "missing" in e:
                continue
            zh = label(e)
            en = en_label(e)
            original = claim_str(e, "P1476") or en
            if not (zh or en):
                continue
            creators_e = [ref.get(c, {}) for c in claim_ids(e, cp)[:3]]
            creators = [label(c) or en_label(c) for c in creators_e if c]
            creators = [c for c in creators if c]
            gnames = [en_label(ref.get(g, {})) for g in claim_ids(e, "P136")[:6]]
            vocab = BOOK_GENRES if kind == "book" else ALBUM_GENRES
            genres = map_genres([g for g in gnames if g], vocab)
            lang = next((LANG_ZH[l] for l in claim_ids(e, "P407") if l in LANG_ZH), "")
            region = ""
            if kind == "album":
                places = claim_ids(e, "P495") + [p for c in creators_e for p in claim_ids(c, "P27") + claim_ids(c, "P495")]
                region = next((REGION[p] for p in places if p in REGION), "其他" if places else "")
                if not region and zh and re.search(r"[一-鿿]", zh) and not en:
                    region = "华语"
            else:
                if not lang:
                    places = claim_ids(e, "P495") + [p for c in creators_e for p in claim_ids(c, "P27")]
                    if any(p in ("Q148", "Q865", "Q8646", "Q13426199", "Q29520") for p in places):
                        lang = "中文"
            pages = claim_str(e, "P1104")
            sl = e.get("sitelinks", {})
            ext = {k: v for k, v in {
                "mbid": claim_str(e, "P436"),
                "olid": claim_str(e, "P648"),
                "isbn": claim_str(e, "P212") or claim_str(e, "P957"),
                "zhwiki": sl.get("zhwiki", {}).get("title", ""),
                "enwiki": sl.get("enwiki", {}).get("title", ""),
            }.items() if v}
            prefix = "bk" if kind == "book" else "mu"
            rows.append((
                f"{prefix}:{qid}", kind, zh or None, en or zh, original or en or zh,
                year_of(e), json.dumps(creators, ensure_ascii=False),
                json.dumps(genres, ensure_ascii=False), lang, region,
                int(float(pages)) if pages and re.match(r"^\d+(\.\d+)?$", pages) else None,
                pop[qid], json.dumps(ext, ensure_ascii=False),
            ))
        con.executemany("insert or replace into works values(?,?,?,?,?,?,?,?,?,?,?,?,?)", rows)
        con.execute("insert or replace into meta values(?,?)", (f"count_{kind}", str(len(rows))))
        print(f"[{kind}] wrote {len(rows)}", file=sys.stderr)
    seeds = seed_rows()
    # a seed found on Wikidata too keeps the Wikidata row (richer metadata)
    have = {(r[0], r[1]) for r in con.execute("select coalesce(zh, title), kind from works")}
    seeds = [r for r in seeds if (r[2] or r[3], r[1]) not in have]
    con.executemany("insert or replace into works values(?,?,?,?,?,?,?,?,?,?,?,?,?)", seeds)
    for kind in ("book", "album"):
        n = con.execute("select count(*) from works where kind=?", (kind,)).fetchone()[0]
        con.execute("insert or replace into meta values(?,?)", (f"count_{kind}", str(n)))
    con.executescript(
        """
        create index works_kind on works(kind, popularity desc);
        create virtual table works_fts using fts5(id unindexed, zh, title, original, creators, tokenize='trigram');
        insert into works_fts select id, coalesce(zh,''), title, original, creators from works;
        """
    )
    con.execute("insert or replace into meta values('built_at', ?)", (time.strftime("%Y-%m-%d"),))
    con.execute("insert or replace into meta values('source', ?)",
                ("hand-picked seeds, verified online" if seeds_only else "Wikidata (CC0) + hand-picked seeds",))
    con.commit()
    con.close()
    tmp.replace(OUT)
    print(f"done → {OUT}", file=sys.stderr)


if __name__ == "__main__":
    main()
