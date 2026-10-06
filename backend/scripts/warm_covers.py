"""Fetch the cover-wall covers ahead of time, e.g. before recording a demo,
so the first walls show posters instead of typographic stand-ins.

    PIANKE_HOME=/tmp/pianke-demo python scripts/warm_covers.py [pages] [film book music]

Only public names, creators, years and ids leave the machine, the same
requests the app makes when a wall is shown."""

from __future__ import annotations

import sys
import threading
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from pianke.flows import interview  # noqa: E402
from pianke.lookup import covers  # noqa: E402
from pianke.memory import store  # noqa: E402


def main() -> None:
    pages = int(sys.argv[1]) if len(sys.argv) > 1 else 1
    store.init()
    t0 = time.time()

    def lane(domain: str) -> None:
        for page in range(pages):
            ids = [t["id"] for t in interview.wall_pool(domain, page)]
            covers.prefetch(ids)
            st = covers.state(ids)
            ok = sum(v == "ok" for v in st.values())
            print(f"{domain} page {page}: {ok}/{len(ids)} covers, {time.time() - t0:.0f}s", flush=True)

    domains = sys.argv[2:] or ["film", "book", "music"]
    threads = [threading.Thread(target=lane, args=(d,)) for d in domains]
    for t in threads:
        t.start()
    for t in threads:
        t.join()


if __name__ == "__main__":
    main()
