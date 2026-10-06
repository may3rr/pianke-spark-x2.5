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
.venv/bin/pip install -q --upgrade pip
# dependencies only; PyInstaller reads pianke from this folder (--paths),
# it can't follow an editable install
.venv/bin/pip install -q . pyinstaller
.venv/bin/pip uninstall -q -y pianke

rm -rf ../app/build/backend ../app/build/pyi
.venv/bin/pyinstaller -y --clean --log-level WARN \
  --name pianke-backend \
  --distpath ../app/build/backend \
  --workpath ../app/build/pyi \
  --specpath ../app/build/pyi \
  --paths "$(pwd)" \
  --collect-submodules uvicorn \
  --collect-submodules pianke \
  --collect-data opencc \
  "$(pwd)/scripts/pianke_backend.py"
rm -rf ../app/build/pyi
echo "backend: app/build/backend/pianke-backend"
