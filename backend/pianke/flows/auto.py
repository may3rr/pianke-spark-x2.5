"""Background profile consolidation. New records are folded into the profile
on their own once the app has been quiet for a while, so the user never has
to remember to press "整理". Recommendation and onboarding take priority:
while either runs, consolidation waits.

  3 or more new records   → after 2 quiet minutes
  1 or 2                  → after 10 quiet minutes
"""

from __future__ import annotations

import os
import threading
import time
from contextlib import contextmanager
from typing import Iterator

from ..memory import store

SOON, LATER, RETRY = 120.0, 600.0, 60.0

_lock = threading.Lock()  # one consolidation at a time, manual or automatic
_timer: threading.Timer | None = None
_busy = 0
_busy_lock = threading.Lock()
running = False


def enabled() -> bool:
    return os.environ.get("PIANKE_NO_AUTO_PROFILE") != "1"


@contextmanager
def busy() -> Iterator[None]:
    """Wrap a foreground model job; consolidation won't start meanwhile."""
    global _busy
    with _busy_lock:
        _busy += 1
    try:
        yield
    finally:
        with _busy_lock:
            _busy -= 1


@contextmanager
def consolidating() -> Iterator[None]:
    global running
    with _lock:
        running = True
        try:
            yield
        finally:
            running = False


def run(steps: Iterator[dict]) -> Iterator[dict]:
    """Drive one consolidation; records added while it ran stay counted."""
    before = store.get_pref("stale", 0)
    yield from steps
    store.set_pref("stale", max(0, store.get_pref("stale", 0) - before))


def schedule(delay: float | None = None) -> None:
    """Call after anything that adds to the stale count. Restarts the timer:
    the profile is rebuilt once the user has stopped adding records."""
    global _timer
    if not enabled():
        return
    stale = store.get_pref("stale", 0)
    if stale <= 0:
        return
    if _timer:
        _timer.cancel()
    _timer = threading.Timer(delay if delay is not None else (SOON if stale >= 3 else LATER), _fire)
    _timer.daemon = True
    _timer.start()


def _fire() -> None:
    if _busy or running or not store.get_pref("onboarded", False):
        schedule(RETRY)
        return
    if store.get_pref("stale", 0) <= 0:
        return
    from . import profile as profile_flow

    t0 = time.time()
    try:
        with consolidating():
            for _ in run(profile_flow.consolidate(reason="auto")):
                pass
            store.set_pref("profile_unseen", True)
    except Exception as e:  # noqa: BLE001 — try again later, the records are safe
        store.event("auto_profile_failed", {"error": str(e)[:200], "seconds": round(time.time() - t0, 1)})
        schedule(LATER)
