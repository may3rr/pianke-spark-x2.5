"""The only place 片刻 talks to the internet (model APIs aside).

Lookups carry a work's title, creator, year or a public id. Web search (Exa
or Tavily, only when the user configured a key) also carries search queries
the model writes from the user's request. Keys go in headers or in params
that are kept out of the cache key.

Responses are cached in cache.sqlite (public data only, safe to delete)."""

from __future__ import annotations

import json
import sqlite3
import threading
import time
from contextlib import contextmanager
from typing import Any, Iterator
from urllib.parse import urlparse

import httpx

from ..config import CACHE_DB, ensure_home

UA = "Mozilla/5.0 (Macintosh; Intel Mac OS X 14_0) Pianke/0.2"
_lock = threading.RLock()
_client: httpx.Client | None = None
# per-host politeness: at most N in flight, min gap between requests
# Douban answers bursts with empty lists, iTunes allows ~20 searches a minute
_HOST_LIMIT = {"douban.com": (1, 1.2), "doubanio.com": (3, 0.0), "itunes.apple.com": (1, 3.0),
               "wikipedia.org": (2, 0.1), "wikidata.org": (2, 0.2),
               # TMDB allows ~50/s; image CDNs take plenty
               "api.themoviedb.org": (6, 0.0), "image.tmdb.org": (8, 0.0),
               "music.163.com": (2, 0.2), "music.126.net": (8, 0.0),
               "api.exa.ai": (3, 0.0), "api.tavily.com": (3, 0.0)}
_sems: dict[str, threading.Semaphore] = {}
# per-thread count of requests that failed (offline, throttled), so callers
# can tell "nothing exists" from "couldn't ask"
_fails = threading.local()


# hosts that just refused to connect are skipped for a while instead of
# costing a timeout on every cover
_down: dict[str, float] = {}
DOWN_FOR = 300


def _is_down(url: str) -> bool:
    return time.time() - _down.get(_host_key(url), 0) < DOWN_FOR


def _mark(url: str, e: Exception) -> None:
    if isinstance(e, (httpx.ConnectError, httpx.ConnectTimeout, httpx.ProxyError)):
        _down[_host_key(url)] = time.time()


def failures() -> int:
    return getattr(_fails, "n", 0)


def reset_failures() -> None:
    _fails.n = 0
_last: dict[str, float] = {}

SCHEMA = """
create table if not exists http(key text primary key, body text, ts real);
create table if not exists ext(id text primary key, kind text, data text, ts real);
create table if not exists covers(id text primary key, file text, src text, ok integer, ts real);
"""


@contextmanager
def cache() -> Iterator[sqlite3.Connection]:
    with _lock:
        ensure_home()
        con = sqlite3.connect(CACHE_DB)
        con.row_factory = sqlite3.Row
        con.executescript(SCHEMA)
        try:
            yield con
            con.commit()
        finally:
            con.close()


def _http() -> httpx.Client:
    global _client
    if _client is None:
        _client = httpx.Client(timeout=8, follow_redirects=True, headers={"User-Agent": UA})
    return _client


def _host_key(url: str) -> str:
    host = urlparse(url).hostname or ""
    for k in _HOST_LIMIT:
        if host.endswith(k):
            return k
    return host


@contextmanager
def _polite(url: str, lane: str = "bg") -> Iterator[None]:
    """lane "fg" (something the user is waiting on, like a search) gets its
    own queue so it never waits behind a wall of background cover fetches."""
    host = _host_key(url)
    n, gap = _HOST_LIMIT.get(host, (4, 0.0))
    k = f"{host}:{lane}"
    with _lock:
        sem = _sems.setdefault(k, threading.Semaphore(n))
    with sem:
        if gap:
            with _lock:
                wait = _last.get(k, 0) + gap - time.time()
                _last[k] = max(time.time(), _last.get(k, 0) + gap)
            if wait > 0:
                time.sleep(wait)
        yield


def get_json(url: str, params: dict[str, Any], *, referer: str | None = None,
             ttl: float = 30 * 86400, lane: str = "bg", headers: dict | None = None,
             auth: dict | None = None, body: dict | None = None) -> Any:
    """GET (or, with body, POST) a JSON endpoint, cached. Returns None on any
    failure. headers and auth (extra params) carry keys and stay out of the
    cache key."""
    key = url + "?" + json.dumps(params, sort_keys=True, ensure_ascii=False)
    if body is not None:
        key += "#" + json.dumps(body, sort_keys=True, ensure_ascii=False)
    with cache() as c:
        r = c.execute("select body, ts from http where key=?", (key,)).fetchone()
    if r:
        # an empty answer may just be throttling: trust it for an hour only
        empty = r["body"] in ("[]", "{}") or '"resultCount": 0' in r["body"][:40]
        if time.time() - r["ts"] < (3600 if empty else ttl):
            return json.loads(r["body"])
    if _is_down(url):
        _fails.n = failures() + 1
        return json.loads(r["body"]) if r else None
    try:
        hdrs = {**({"Referer": referer} if referer else {}), **(headers or {})} or None
        with _polite(url, lane):
            if body is not None:
                resp = _http().post(url, params={**params, **(auth or {})}, json=body, headers=hdrs,
                                    timeout=20)
            else:
                resp = _http().get(url, params={**params, **(auth or {})}, headers=hdrs)
        resp.raise_for_status()
        data = resp.json()
    except Exception as e:  # noqa: BLE001 — offline or blocked: callers fall back
        _mark(url, e)
        _fails.n = failures() + 1
        return json.loads(r["body"]) if r else None
    with cache() as c:
        c.execute("insert or replace into http values(?,?,?)",
                  (key, json.dumps(data, ensure_ascii=False), time.time()))
    return data


def get_bytes(url: str, *, referer: str | None = None) -> bytes | None:
    if _is_down(url):
        _fails.n = failures() + 1
        return None
    try:
        with _polite(url):
            resp = _http().get(url, headers={"Referer": referer} if referer else None)
        if resp.status_code != 200 or not resp.headers.get("content-type", "").startswith("image"):
            return None
        return resp.content
    except Exception as e:  # noqa: BLE001
        _mark(url, e)
        _fails.n = failures() + 1
        return None


# ---------------------------------------------------------------- ext titles

def save_ext(item_id: str, kind: str, data: dict) -> None:
    with cache() as c:
        c.execute("insert or replace into ext values(?,?,?,?)",
                  (item_id, kind, json.dumps(data, ensure_ascii=False), time.time()))


def load_ext(ids: list[str]) -> dict[str, dict]:
    if not ids:
        return {}
    with cache() as c:
        q = ",".join("?" * len(ids))
        rows = c.execute(f"select id, data from ext where id in ({q})", ids).fetchall()
    return {r["id"]: json.loads(r["data"]) for r in rows}
