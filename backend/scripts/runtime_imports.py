"""Print every module pianke imports (stdlib and third-party), one
per line. The frozen runtime is built with these as hidden imports, since
pianke itself is not frozen into it and PyInstaller can't see its imports."""

import ast
import sys
from pathlib import Path

root = Path(__file__).resolve().parents[1] / "pianke"
mods = set()
for f in root.rglob("*.py"):
    for node in ast.walk(ast.parse(f.read_text(), str(f))):
        # full dotted names: "concurrent" alone doesn't bring concurrent.futures
        if isinstance(node, ast.Import):
            mods |= {a.name for a in node.names}
        elif isinstance(node, ast.ImportFrom) and node.level == 0 and node.module:
            mods.add(node.module)
mods = {m for m in mods if m.split(".")[0] not in ("pianke", "__future__")}
# httpx loads these only when a SOCKS proxy is set (Clash exports one)
mods |= {"socksio"}
print("\n".join(sorted(mods)))
sys.exit(0)
