"""One-command update of the dashboard.

    python -X utf8 update.py            (or double-click update.bat)

What it does
  1. Shows which hand-downloaded datasets are due and opens their download pages in your browser.
  2. Watches your Downloads folder. Every file you download from those pages is recognised by its
     name or by what is inside it, given the name the pipeline expects and copied into rawData/.
     Press Enter when you are done (or wait for the time limit).
  3. Runs the pipeline with --refresh (all automatic sources), rebuilds the page and deploys it.

The downloads themselves stay manual: the DMO and ChinaBond sites serve their files behind bot checks
that a script must not try to get around. Everything else is automated.

Options
  --no-open        do not open the download pages
  --wait MIN       minutes to watch the Downloads folder (default 20; 0 = import what is there and go on)
  --downloads DIR  folder to watch (default: the Windows Downloads folder)
  --no-deploy      rebuild only, do not publish
  --dry-run        import files and stop (no pipeline, build or deploy)
  --raw DIR        rawData folder to write into (for tests)
"""
from __future__ import annotations

import argparse
import datetime as dt
import json
import os
import re
import shutil
import subprocess
import sys
import threading
import time
import webbrowser
from pathlib import Path

ROOT = Path(__file__).resolve().parent
PAGES = {
    "dmo_turnover": ("UK gilts: DMO turnover", "https://www.dmo.gov.uk/data/gilt-market/turnover-data/",
                     "download 'GEMM turnover by maturity band' (xlsx), 'All GEMMs turnover' (xls) and the latest 'Annual turnover report' (xls)"),
    "dmo_gilts_in_issue": ("UK gilts: Gilts in issue", "https://www.dmo.gov.uk/data/gilt-market/gilts-in-issue/",
                           "export the 'Gilts in issue' list to Excel"),
    "ccdc": ("CGBs: CCDC monthly settlement statistics", "https://www.chinabond.com.cn/zzsj/zzsj_tjsj/tjsj_tjyb/",
             "for each new month open table 7 'CIBM Bond Settlement (By Bond Type)' and table 8 '(By Investor Type)' and choose Excel"),
}
MON = {m: i for i, m in enumerate(["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"], 1)}


def downloads_dir() -> Path:
    try:
        import winreg
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, r"Software\Microsoft\Windows\CurrentVersion\Explorer\User Shell Folders") as k:
            v = winreg.QueryValueEx(k, "{374DE290-123F-4565-9164-39C4925E467B}")[0]
            return Path(os.path.expandvars(v))
    except Exception:
        return Path.home() / "Downloads"


def first_cells(path: Path, rows: int = 4) -> list[str]:
    """First cell of the first rows of an Excel file (xls or xlsx), for recognising files by content."""
    try:
        with open(path, "rb") as fh:
            head = fh.read(8)
        if head.startswith(bytes([0xD0, 0xCF, 0x11, 0xE0])):   # real BIFF .xls (DMO files)
            import xlrd
            sh = xlrd.open_workbook(str(path)).sheet_by_index(0)
            return [str(sh.cell_value(r, 0)) for r in range(min(rows, sh.nrows))]
        if not head.startswith(b"PK"):                 # neither BIFF nor zip: let pandas sniff (HTML tables named .xls)
            import pandas as pd
            df = pd.read_excel(path, header=None, nrows=rows)
            return ["" if pd.isna(v) else str(v) for v in df.iloc[:, 0].tolist()]
        import openpyxl                                 # zip container: xlsx whatever the extension says (ChinaBond exports)
        import io as _io
        ws = openpyxl.load_workbook(_io.BytesIO(path.read_bytes()), read_only=True).worksheets[0]   # by content, not by extension
        out = []
        for i, row in enumerate(ws.iter_rows(min_row=1, max_row=rows, values_only=True)):
            out.append("" if not row or row[0] is None else str(row[0]))
        return out
    except Exception:
        return []


def header_cells(path: Path, rows: int = 30) -> str:
    """All cell text of the first rows joined, lower case (for the ChinaBond export)."""
    try:
        import pandas as pd
        df = pd.read_excel(path, header=None, nrows=rows)
        return " ".join(str(v) for v in df.values.flatten()).lower()
    except Exception:
        return ""


def classify(path: Path) -> tuple[str, Path] | None:
    """Returns (dataset key, target path under rawData) for a downloaded file, or None."""
    n = path.name.lower()
    if n.endswith((".crdownload", ".tmp", ".part")):
        return None
    if n.startswith("gemm-turnover-by-maturity-band") and n.endswith(".xlsx"):
        return "dmo_turnover", Path("dmo_gilts") / path.name
    if n.startswith("all-gemms-turnover") and n.endswith((".xls", ".xlsx")):
        return "dmo_turnover", Path("dmo_gilts") / path.name
    if n.startswith("annual-turnover-report") and n.endswith((".xls", ".xlsx")):
        return "dmo_turnover", Path("dmo_gilts") / path.name
    if not n.endswith((".xls", ".xlsx", ".csv")):
        return None
    cells = first_cells(path)
    if cells and cells[0].strip().lower().startswith("data date:") or "gilts in issue" in n or "gilts-in-issue" in n:
        return "dmo_gilts_in_issue", Path("maturity") / ("gilts-in-issue" + path.suffix.lower())
    if cells:
        m = re.match(r"\s*(7|8)\s*\.?\s*CIBM Bond Settlement \(By (Bond|Investor) Type\)", cells[0], re.I)
        if m:
            mm = None
            for c in cells[1:]:
                d = re.search(r"([A-Z][a-z]{2})-(\d{4})", c)
                if d and d.group(1) in MON:
                    mm = f"{d.group(2)}{MON[d.group(1)]:02d}"
                    break
            if mm:
                kind = "Bond Type" if m.group(2).lower() == "bond" else "Investor Type"
                return "ccdc", Path("ccdc_cgb") / f"CIBM Bond Settlement (By {kind})_{mm}{path.suffix.lower()}"
    if n.endswith((".xls", ".xlsx")):
        h = header_cells(path)
        if "maturity date" in h and "amount" in h and ("bond code" in h or "planned" in h):
            return "chinabond_issues", Path("maturity") / ("cny_cgb" + path.suffix.lower())
    return None


def import_file(path: Path, raw: Path) -> tuple[str, Path] | None:
    c = classify(path)
    if not c:
        return None
    key, rel = c
    target = raw / rel
    target.parent.mkdir(parents=True, exist_ok=True)
    if target.exists() and target.stat().st_size == path.stat().st_size and abs(target.stat().st_mtime - path.stat().st_mtime) < 2:
        return None
    shutil.copy2(path, target)
    return key, target


def status_lines() -> list[str]:
    f = ROOT / "data" / "liquidity.json"
    if not f.exists():
        return []
    d = json.loads(f.read_text(encoding="utf-8"))
    out = []
    for x in d.get("status", []):
        if x.get("mode") == "manual":
            out.append(f"  {x['title']:60s} latest {x.get('latest') or '-':22s} next expected {x.get('next_expected') or '-':12s} {x['status']}")
    return out


def run(cmd: list[str], env=None) -> int:
    print("\n> " + " ".join(cmd))
    return subprocess.call(cmd, cwd=str(ROOT), env=env)


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--no-open", action="store_true")
    ap.add_argument("--wait", type=float, default=20)
    ap.add_argument("--downloads", type=str, default=None)
    ap.add_argument("--no-deploy", action="store_true")
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--raw", type=str, default=None)
    a = ap.parse_args()
    raw = Path(a.raw) if a.raw else ROOT / "rawData"
    dl = Path(a.downloads) if a.downloads else downloads_dir()
    print("Bond liquidity dashboard: update\n")
    st = status_lines()
    if st:
        print("Hand-downloaded datasets as of the last pipeline run:")
        print("\n".join(st))
    print(f"\nWatching {dl} for new files. Download what is due; files are recognised and filed automatically.")
    for key, (title, url, how) in PAGES.items():
        print(f"  - {title}: {how}\n      {url}")
        if not a.no_open:
            webbrowser.open(url)
    # files already in Downloads that are newer than what rawData has are imported too
    imported: list[tuple[str, Path]] = []
    seen = set()

    def sweep():
        for p in sorted(dl.glob("*")):
            if not p.is_file() or p in seen:
                continue
            try:
                age = time.time() - p.stat().st_mtime
            except OSError:
                continue
            if age > 3 * 24 * 3600:
                seen.add(p)
                continue
            r = import_file(p, raw)
            seen.add(p)
            if r:
                imported.append(r)
                print(f"  filed {p.name}  ->  {r[1].relative_to(raw.parent) if raw.parent in r[1].parents else r[1]}")
    sweep()
    if a.wait > 0:
        done = threading.Event()
        threading.Thread(target=lambda: (sys.stdin.readline(), done.set()), daemon=True).start()
        print(f"\nPress Enter when you have finished downloading (or wait {a.wait:g} min).")
        end = time.time() + a.wait * 60
        while time.time() < end and not done.is_set():
            time.sleep(2)
            sweep()
    sweep()
    print(f"\n{len(imported)} file(s) filed." if imported else "\nNo new hand-downloaded files; the automatic sources will still be refreshed.")
    if a.dry_run:
        return 0
    if run([sys.executable, "-X", "utf8", "pipeline/run_all.py", "--refresh"]) != 0:
        print("pipeline failed; nothing deployed"); return 1
    if run([sys.executable, "-X", "utf8", "build.py"]) != 0:
        print("build failed; nothing deployed"); return 1
    print("\nAfter the run:")
    print("\n".join(status_lines()))
    if a.no_deploy:
        print("\nBuilt, not deployed (--no-deploy)."); return 0
    env = dict(os.environ)
    node = Path(os.environ.get("LOCALAPPDATA", "")) / "Programs" / "node-v22.23.3-win-x64"
    if node.exists():
        env["PATH"] = str(node) + os.pathsep + env.get("PATH", "")
    env.setdefault("CLOUDFLARE_ACCOUNT_ID", "2ebd6821cc00c02ed06223a90488785c")
    npx = "npx.cmd" if os.name == "nt" else "npx"
    for p in (ROOT / "site").glob("_*.html"):
        p.unlink()
    rc = run([npx, "--yes", "wrangler@latest", "deploy"], env=env)
    print("\nDeployed." if rc == 0 else "\nDeploy failed; the local build is up to date, run 'npx wrangler deploy' by hand.")
    return rc


if __name__ == "__main__":
    sys.exit(main())
