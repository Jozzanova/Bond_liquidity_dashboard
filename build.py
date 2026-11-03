"""Build site/index.html from template.html and data/liquidity.json.

    python -X utf8 build.py [--open]
"""
from __future__ import annotations

import datetime as dt
import json
import sys
import webbrowser
from pathlib import Path

ROOT = Path(__file__).resolve().parent
data_file = ROOT / "data" / "liquidity.json"
if not data_file.exists():
    sys.exit("data/liquidity.json missing: run  python -X utf8 pipeline/run_all.py  first")
data = json.loads(data_file.read_text(encoding="utf-8"))
data["built"] = dt.datetime.now().strftime("%Y-%m-%d %H:%M")

from export_data import export  # noqa: E402
data["downloads"] = export(data, ROOT / "site" / "data")
print(f"wrote {len(data['downloads'])} data files to site/data")

tpl = (ROOT / "template.html").read_text(encoding="utf-8")
marker = "/*__DATA__*/"
assert tpl.count(marker) == 1, "template must contain the data marker exactly once"
payload = json.dumps(data, ensure_ascii=False, separators=(",", ":")).replace("</", "<\\/")
html = tpl.replace(marker, payload)
out = ROOT / "site" / "index.html"
out.parent.mkdir(exist_ok=True)
out.write_text(html, encoding="utf-8")
print(f"wrote {out.relative_to(ROOT)} ({out.stat().st_size // 1024} kB), markets: {', '.join(data['markets'])}")
if "--open" in sys.argv:
    webbrowser.open(out.as_uri())
