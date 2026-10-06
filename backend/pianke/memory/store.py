"""The user's memory, in one local SQLite file.

L0 events   append-only log of everything the user said or did (source of truth)
L1 items    one structured record per work (film, book or album): status,
            rating (0–5 in half stars, null = not rated), liked/disliked
            aspects, context, the user's own words verbatim, when it happened
L2 profile  versioned natural-language taste profile; every claim cites items
L3 recent   derived on read from the last weeks of events (no table)
"""

from __future__ import annotations

import json
import sqlite3
import threading
import time
from contextlib import contextmanager
from typing import Any, Iterator

from ..config import USER_DB, ensure_home

_lock = threading.RLock()

SCHEMA = """
create table if not exists events(
  id integer primary key, ts real, kind text, payload text
);
create table if not exists items(
  id text primary key,          -- IMDb tconst | bk:… | mu:…
  status text,                  -- watched | dropped | want | rejected
  rating real,                  -- 0..5 in 0.5 steps, null if not rated
  liked text, disliked text,    -- json arrays of short aspects
  context text,                 -- json {mood, with, when, energy}
  words text,                   -- the user's own words, verbatim
  source text,                  -- interview | onboard | feedback | rec | manual | checkin
  created real, updated real
);
create table if not exists recs(
  id integer primary key, ts real, request text, direction text,
  picks text, stats text
);
create table if not exists profile(
  version integer primary key, ts real, doc text, stats text
);
create table if not exists interview(
  id integer primary key, ts real, role text, text text
);
create table if not exists prefs(key text primary key, value text);
create table if not exists llm_log(
  id integer primary key, ts real, model text, task text,
  prompt_tokens int, completion_tokens int, cached_tokens int,
  prompt_tps real, gen_tps real, seconds real
);
"""


@contextmanager
def db() -> Iterator[sqlite3.Connection]:
    with _lock:
        ensure_home()
        con = sqlite3.connect(USER_DB)
        con.row_factory = sqlite3.Row
        try:
            yield con
            con.commit()
        finally:
            con.close()


# columns added after the first release; ALTER on open keeps old data
EXTRA_COLS = {
    "domain": "text",   # film | book | music
    "origin": "text",   # rec (followed a pick) | past (already seen) | onboard
    "done_on": "text",  # YYYY-MM-DD the user finished it (editable)
    "reason": "text",   # why not: 不感兴趣 / 听说过，不对胃口 …
}


def init() -> None:
    with db() as c:
        c.executescript(SCHEMA)
        have = {r["name"] for r in c.execute("pragma table_info(items)")}
        for col, typ in EXTRA_COLS.items():
            if col not in have:
                c.execute(f"alter table items add column {col} {typ}")
        c.execute("update items set domain='film' where domain is null")


# ---------------------------------------------------------------- L0

def event(kind: str, payload: dict) -> None:
    with db() as c:
        c.execute(
            "insert into events(ts, kind, payload) values(?,?,?)",
            (time.time(), kind, json.dumps(payload, ensure_ascii=False)),
        )


def events(since: float = 0, kinds: tuple[str, ...] | None = None) -> list[dict]:
    with db() as c:
        rows = c.execute(
            "select * from events where ts >= ? order by ts", (since,)
        ).fetchall()
    out = [
        {"ts": r["ts"], "kind": r["kind"], **json.loads(r["payload"])} for r in rows
    ]
    return [e for e in out if not kinds or e["kind"] in kinds]


# ---------------------------------------------------------------- L1

def domain_of(item_id: str) -> str:
    return "book" if item_id.startswith("bk:") else "music" if item_id.startswith("mu:") else "film"


def _item(r: sqlite3.Row) -> dict:
    keys = r.keys()
    return {
        "id": r["id"],
        "domain": (r["domain"] if "domain" in keys else None) or domain_of(r["id"]),
        "status": r["status"],
        "rating": r["rating"],
        "liked": json.loads(r["liked"] or "[]"),
        "disliked": json.loads(r["disliked"] or "[]"),
        "context": json.loads(r["context"] or "{}"),
        "words": r["words"] or "",
        "source": r["source"],
        "origin": r["origin"] if "origin" in keys else None,
        "done_on": r["done_on"] if "done_on" in keys else None,
        "reason": r["reason"] if "reason" in keys else None,
        "created": r["created"],
        "updated": r["updated"],
    }


FIELDS = ("status", "rating", "liked", "disliked", "context", "words", "source",
          "origin", "done_on", "reason")


def upsert_item(item_id: str, *, replace: tuple[str, ...] = (), **fields: Any) -> dict:
    """Merge fields into a record. None means "leave as is". words are
    appended (every thing the user said is kept) unless listed in replace;
    rating may be cleared by passing it in replace with None."""
    now = time.time()
    with db() as c:
        row = c.execute("select * from items where id=?", (item_id,)).fetchone()
        cur = _item(row) if row else {
            "id": item_id, "domain": domain_of(item_id), "status": None, "rating": None,
            "liked": [], "disliked": [], "context": {}, "words": "", "source": None,
            "origin": None, "done_on": None, "reason": None, "created": now, "updated": now,
        }
        for k, v in fields.items():
            if k not in FIELDS:
                raise KeyError(k)
            if v is None and k not in replace:
                continue
            if k == "words" and k not in replace and cur["words"] and v not in cur["words"]:
                # keep every thing the user said about a title, oldest first
                v = f"{cur['words']}\n{v}"
            if k == "context" and v is not None and k not in replace:
                v = {**cur["context"], **v}
            cur[k] = v
        cur["updated"] = now
        c.execute(
            "insert or replace into items(id, status, rating, liked, disliked, context, words,"
            " source, created, updated, domain, origin, done_on, reason)"
            " values(?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
            (
                item_id, cur["status"], cur["rating"],
                json.dumps(cur["liked"], ensure_ascii=False),
                json.dumps(cur["disliked"], ensure_ascii=False),
                json.dumps(cur["context"], ensure_ascii=False),
                cur["words"] or "", cur["source"], cur["created"], cur["updated"],
                cur["domain"] or domain_of(item_id), cur["origin"], cur["done_on"], cur["reason"],
            ),
        )
    return cur


def items(status: str | None = None, domain: str | None = None) -> list[dict]:
    where, args = [], []
    if status:
        where.append("status=?")
        args.append(status)
    if domain:
        where.append("domain=?")
        args.append(domain)
    sql = "select * from items" + (f" where {' and '.join(where)}" if where else "")
    with db() as c:
        rows = c.execute(sql + " order by updated desc", args).fetchall()
    return [_item(r) for r in rows]


def item(item_id: str) -> dict | None:
    with db() as c:
        r = c.execute("select * from items where id=?", (item_id,)).fetchone()
    return _item(r) if r else None


def delete_item(item_id: str) -> None:
    with db() as c:
        c.execute("delete from items where id=?", (item_id,))


# ---------------------------------------------------------------- L2

def save_profile(doc: dict, stats: dict) -> int:
    with db() as c:
        cur = c.execute(
            "insert into profile(ts, doc, stats) values(?,?,?)",
            (time.time(), json.dumps(doc, ensure_ascii=False), json.dumps(stats)),
        )
        return int(cur.lastrowid)


def profile() -> dict | None:
    with db() as c:
        r = c.execute("select * from profile order by version desc limit 1").fetchone()
    if not r:
        return None
    return {
        "version": r["version"],
        "ts": r["ts"],
        "doc": json.loads(r["doc"]),
        "stats": json.loads(r["stats"] or "{}"),
    }


def profile_history(limit: int = 20) -> list[dict]:
    with db() as c:
        rows = c.execute(
            "select version, ts, stats from profile order by version desc limit ?",
            (limit,),
        ).fetchall()
    return [
        {"version": r["version"], "ts": r["ts"], "stats": json.loads(r["stats"] or "{}")}
        for r in rows
    ]


# ---------------------------------------------------------------- recs

def save_rec(request: dict, direction: str, picks: list[dict], stats: dict) -> int:
    with db() as c:
        cur = c.execute(
            "insert into recs(ts, request, direction, picks, stats) values(?,?,?,?,?)",
            (
                time.time(),
                json.dumps(request, ensure_ascii=False),
                direction,
                json.dumps(picks, ensure_ascii=False),
                json.dumps(stats, ensure_ascii=False),
            ),
        )
        return int(cur.lastrowid)


def recs(limit: int = 30) -> list[dict]:
    with db() as c:
        rows = c.execute("select * from recs order by ts desc limit ?", (limit,)).fetchall()
    return [
        {
            "id": r["id"],
            "ts": r["ts"],
            "request": json.loads(r["request"]),
            "direction": r["direction"],
            "picks": json.loads(r["picks"]),
            "stats": json.loads(r["stats"] or "{}"),
        }
        for r in rows
    ]


def recs_since(ts: float) -> list[dict]:
    return [r for r in recs(60) if r["ts"] >= ts]


def recently_recommended(days: float = 21) -> set[str]:
    since = time.time() - days * 86400
    with db() as c:
        rows = c.execute("select picks from recs where ts >= ?", (since,)).fetchall()
    return {p["id"] for r in rows for p in json.loads(r["picks"])}


# ---------------------------------------------------------------- interview

def add_turn(role: str, text: str) -> None:
    with db() as c:
        c.execute(
            "insert into interview(ts, role, text) values(?,?,?)",
            (time.time(), role, text),
        )


def turns() -> list[dict]:
    with db() as c:
        rows = c.execute("select role, text from interview order by id").fetchall()
    return [{"role": r["role"], "text": r["text"]} for r in rows]


def clear_interview() -> None:
    with db() as c:
        c.execute("delete from interview")


# ---------------------------------------------------------------- prefs

def get_pref(key: str, default: Any = None) -> Any:
    with db() as c:
        r = c.execute("select value from prefs where key=?", (key,)).fetchone()
    return json.loads(r["value"]) if r else default


def set_pref(key: str, value: Any) -> None:
    with db() as c:
        c.execute(
            "insert or replace into prefs values(?,?)",
            (key, json.dumps(value, ensure_ascii=False)),
        )


# ---------------------------------------------------------------- llm log

def log_llm(rec: dict) -> None:
    with db() as c:
        c.execute(
            "insert into llm_log(ts, model, task, prompt_tokens, completion_tokens,"
            " cached_tokens, prompt_tps, gen_tps, seconds) values(?,?,?,?,?,?,?,?,?)",
            (
                time.time(), rec["model"], rec["task"], rec["prompt_tokens"],
                rec["completion_tokens"], rec["cached_tokens"], rec["prompt_tps"],
                rec["gen_tps"], rec["seconds"],
            ),
        )


def llm_summary() -> dict:
    with db() as c:
        rows = c.execute(
            "select model, count(*) n, sum(prompt_tokens) p, sum(completion_tokens) g,"
            " sum(seconds) s, avg(gen_tps) gt, avg(prompt_tps) pt"
            " from llm_log group by model"
        ).fetchall()
        recent = c.execute(
            "select * from llm_log order by id desc limit 30"
        ).fetchall()
    return {
        "by_model": [
            {
                "model": r["model"], "calls": r["n"], "prompt_tokens": r["p"] or 0,
                "completion_tokens": r["g"] or 0, "seconds": round(r["s"] or 0, 1),
                "avg_gen_tps": round(r["gt"] or 0, 1),
                "avg_prompt_tps": round(r["pt"] or 0, 1),
            }
            for r in rows
        ],
        "recent": [dict(r) for r in recent],
    }


def wipe() -> None:
    with db() as c:
        for t in ("events", "items", "recs", "profile", "interview", "prefs", "llm_log"):
            c.execute(f"delete from {t}")
