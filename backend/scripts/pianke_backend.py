"""PyInstaller entry for the packaged app's backend (see app/scripts/build-backend.sh).

The frozen runtime holds Python and the third-party libraries only. pianke
itself ships beside it as plain source (Resources/backend-src, passed in
PIANKE_SRC), so an update that touches only our code replaces ~0.2 MB
instead of the ~40 MB runtime."""

import os
import sys

src = os.environ.get("PIANKE_SRC")
if src:
    sys.path.insert(0, src)

if sys.argv[1:] == ["--check"]:
    # build-backend.sh runs this: every pianke module must import in the
    # frozen runtime, or a missing library would only show up for the user
    import importlib
    import pkgutil

    import pianke

    for m in pkgutil.walk_packages(pianke.__path__, "pianke."):
        importlib.import_module(m.name)
    print("runtime check ok")
    sys.exit(0)

from pianke.__main__ import main  # noqa: E402

main()
