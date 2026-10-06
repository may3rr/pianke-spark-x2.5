"""Build data/catalog.sqlite from the IMDb non-commercial datasets.

    python scripts/build_catalog.py [--raw ../data/raw] [--min-votes 3000]

Keeps feature films, series and mini-series with enough votes to be
recognisable, attaches a simplified-Chinese title from title.akas (CN first,
then HK/TW/SG converted with OpenCC), the directors, and the top-billed cast.
The result is fully local: recommendation never needs the network.
"""

from __future__ import annotations

import argparse
import csv
import gzip
import sqlite3
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

csv.field_size_limit(sys.maxsize)

KINDS = {"movie": "movie", "tvSeries": "series", "tvMiniSeries": "miniseries"}
ZH_REGIONS = ["CN", "HK", "TW", "SG", "MO"]


def rows(path: Path):
    with gzip.open(path, "rt", encoding="utf-8", newline="") as f:
        r = csv.reader(f, delimiter="\t", quoting=csv.QUOTE_NONE)
        header = next(r)
        for row in r:
            yield dict(zip(header, row))


def nz(v: str) -> str | None:
    return None if v == "\\N" or v == "" else v


def log(msg: str) -> None:
    print(f"[{time.strftime('%H:%M:%S')}] {msg}", flush=True)


def main() -> None:
    here = Path(__file__).resolve()
    ap = argparse.ArgumentParser()
    ap.add_argument("--raw", default=str(here.parents[2] / "data" / "raw"))
    ap.add_argument("--out", default=str(here.parents[2] / "data" / "catalog.sqlite"))
    ap.add_argument("--min-votes", type=int, default=3000)
    a = ap.parse_args()
    raw = Path(a.raw)

    log("ratings")
    ratings: dict[str, tuple[float, int]] = {}
    for r in rows(raw / "title.ratings.tsv.gz"):
        v = int(r["numVotes"])
        if v >= a.min_votes:
            ratings[r["tconst"]] = (float(r["averageRating"]), v)
    log(f"  {len(ratings)} titles above {a.min_votes} votes")

    log("basics")
    titles: dict[str, dict] = {}
    for r in rows(raw / "title.basics.tsv.gz"):
        tid = r["tconst"]
        if tid not in ratings or r["titleType"] not in KINDS or r["isAdult"] == "1":
            continue
        rating, votes = ratings[tid]
        titles[tid] = {
            "id": tid,
            "kind": KINDS[r["titleType"]],
            "title": r["primaryTitle"],
            "original": r["originalTitle"],
            "year": int(r["startYear"]) if nz(r["startYear"]) else None,
            "end_year": int(r["endYear"]) if nz(r["endYear"]) else None,
            "runtime": int(r["runtimeMinutes"]) if nz(r["runtimeMinutes"]) and r["runtimeMinutes"].isdigit() else None,
            "genres": nz(r["genres"]) or "",
            "rating": rating,
            "votes": votes,
            "zh": None,
            "directors": [],
            "cast": [],
        }
    log(f"  kept {len(titles)}")

    log("akas (Chinese titles)")
    from opencc import OpenCC

    t2s = OpenCC("t2s")
    best: dict[str, tuple[int, str]] = {}
    for r in rows(raw / "title.akas.tsv.gz"):
        tid = r["titleId"]
        if tid not in titles:
            continue
        region = r["region"]
        lang = r["language"]
        if region in ZH_REGIONS:
            rank = ZH_REGIONS.index(region)
        elif lang in ("zh", "cmn", "yue"):
            rank = len(ZH_REGIONS)
        else:
            continue
        types = r["types"]
        if "working" in types or "alternative" in types:
            rank += 10
        if tid not in best or rank < best[tid][0]:
            best[tid] = (rank, r["title"])
    for tid, (_, t) in best.items():
        titles[tid]["zh"] = t2s.convert(t)
    log(f"  {len(best)} have a Chinese title")

    log("crew (directors)")
    director_ids: dict[str, list[str]] = {}
    for r in rows(raw / "title.crew.tsv.gz"):
        tid = r["tconst"]
        if tid in titles and nz(r["directors"]):
            director_ids[tid] = r["directors"].split(",")[:3]

    log("principals (top-billed cast)")
    cast_ids: dict[str, list[tuple[int, str]]] = {}
    for r in rows(raw / "title.principals.tsv.gz"):
        tid = r["tconst"]
        if tid not in titles or r["category"] not in ("actor", "actress", "self"):
            continue
        lst = cast_ids.setdefault(tid, [])
        if len(lst) < 4:
            lst.append((int(r["ordering"]), r["nconst"]))

    need = {n for v in director_ids.values() for n in v} | {
        n for v in cast_ids.values() for _, n in v
    }
    log(f"names ({len(need)} people)")
    names: dict[str, str] = {}
    for r in rows(raw / "name.basics.tsv.gz"):
        if r["nconst"] in need:
            names[r["nconst"]] = r["primaryName"]
    for tid, ids in director_ids.items():
        titles[tid]["directors"] = [names[n] for n in ids if n in names]
    for tid, lst in cast_ids.items():
        titles[tid]["cast"] = [names[n] for _, n in sorted(lst) if n in names]

    out = Path(a.out)
    tmp = out.with_suffix(".building")
    tmp.unlink(missing_ok=True)
    db = sqlite3.connect(tmp)
    db.executescript(
        """
        create table titles(
          id text primary key, kind text, title text, original text, zh text,
          year int, end_year int, runtime int, genres text,
          rating real, votes int, directors text, actors text
        );
        create index titles_votes on titles(votes desc);
        create index titles_year on titles(year);
        create virtual table titles_fts using fts5(
          id unindexed, title, original, zh, directors, actors,
          tokenize = 'trigram'
        );
        create table meta(key text primary key, value text);
        """
    )
    db.executemany(
        "insert into titles values(:id,:kind,:title,:original,:zh,:year,:end_year,"
        ":runtime,:genres,:rating,:votes,:directors,:cast)",
        [
            {**t, "directors": "|".join(t["directors"]), "cast": "|".join(t["cast"])}
            for t in titles.values()
        ],
    )
    db.execute(
        "insert into titles_fts select id, title, original, coalesce(zh,''),"
        " directors, actors from titles"
    )
    counts = {k: sum(1 for t in titles.values() if t["kind"] == k) for k in KINDS.values()}
    meta = {
        "source": "IMDb Non-Commercial Datasets (datasets.imdbws.com)",
        "built_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "min_votes": str(a.min_votes),
        "total": str(len(titles)),
        "with_zh": str(len(best)),
        **{f"count_{k}": str(v) for k, v in counts.items()},
    }
    db.executemany("insert into meta values(?,?)", list(meta.items()))
    db.commit()
    db.execute("vacuum")
    db.close()
    tmp.replace(out)
    log(f"wrote {out} ({out.stat().st_size / 1e6:.1f} MB): {meta}")


if __name__ == "__main__":
    main()
