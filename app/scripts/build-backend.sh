#!/bin/sh
# Freeze the Python backend into app/build/backend/pianke-backend (a folder
# with an executable and its libraries), so the installed app needs no Python.
#
#   PIANKE_PYTHON=/path/to/python3.11 ./scripts/build-backend.sh
#
# Uses its own venv (backend/.venv) so the Python you point it at is untouched.
set -eu
cd "$(dirname "$0")/../../backend"
PY="${PIANKE_PYTHON:-python3}"
"$PY" -c 'import sys; assert sys.version_info >= (3, 11), "needs Python 3.11+"'

[ -x .venv/bin/python ] || "$PY" -m venv .venv
# reinstall only when the dependencies change: it needs the network, and a
# flaky proxy shouldn't fail a build that has everything already
DEPS=$(shasum -a 256 pyproject.toml | cut -c1-16)
if [ "$(cat .venv/.deps 2>/dev/null)" != "$DEPS" ]; then
  .venv/bin/pip install -q --upgrade pip
  # dependencies only: pianke ships as source (see scripts/pianke_backend.py)
  .venv/bin/pip install -q . pyinstaller
  .venv/bin/pip uninstall -q -y pianke
  echo "$DEPS" > .venv/.deps
fi

# pianke is not frozen in (it ships as source, see scripts/pianke_backend.py),
# so every module it imports is passed as a hidden import
IMPORTS=$(.venv/bin/python scripts/runtime_imports.py)
HIDDEN=""
for m in $IMPORTS; do HIDDEN="$HIDDEN --hidden-import $m"; done

rm -rf ../app/build/backend ../app/build/pyi
# shellcheck disable=SC2086
.venv/bin/pyinstaller -y --clean --log-level ERROR \
  --name pianke-backend \
  --distpath ../app/build/backend \
  --workpath ../app/build/pyi \
  --specpath ../app/build/pyi \
  --exclude-module pianke \
  --collect-submodules uvicorn \
  --collect-data opencc \
  $HIDDEN \
  "$(pwd)/scripts/pianke_backend.py"
rm -rf ../app/build/pyi
PIANKE_SRC="$(pwd)" PIANKE_HOME="$(mktemp -d)" ../app/build/backend/pianke-backend/pianke-backend --check

# PyInstaller output differs byte for byte between builds, so the updater
# can't hash it. This key names what's inside instead: same key, same runtime.
{
  .venv/bin/python -c 'import sys; print(sys.version)'
  .venv/bin/pip freeze --exclude-editable | grep -v '^pianke'
  echo "$IMPORTS"
} | shasum -a 256 | cut -c1-16 > ../app/build/backend/runtime.key
echo "backend: app/build/backend/pianke-backend (runtime $(cat ../app/build/backend/runtime.key))"
