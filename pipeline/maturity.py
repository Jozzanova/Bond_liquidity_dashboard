"""Outstanding stock of each market's nominal government bonds by remaining
maturity: the "market-weighted" maturity profile offered as the default
holding distribution on the Profile tab.

Shares are nominal amounts outstanding in the five common buckets (0-3y,
3-5y, 5-7y, 7-10y, 10y+) by remaining maturity on the as-of date, for the
universe that the turnover data of the market covers (nominal coupon bonds:
no bills, no inflation-linked bonds, no retail bonds, no strips).

Sources (downloaded into rawData/maturity/ when missing or with --refresh):
  USD   Treasury Monthly Statement of the Public Debt, table 3 (marketable
        securities by CUSIP) via the Fiscal Data API; Notes and Bonds.
  EUR-DE Finanzagentur, monthly itemised list of outstanding Federal
        securities (einzelaufstellung_en.xlsx); Schatz, Bobl, Bund incl. green,
        latest column.
  EUR-FR Agence France Tresor, "OATs debt outstanding" page (nominal OATs by
        line, as published at fetch time).
  JPY   Ministry of Finance, outstanding balance by issue of general bonds
        (maturity.xlsx, end of the latest fiscal year); 2y to 40y coupon JGBs
        incl. climate transition bonds.
Manual (the sites sit behind a bot check):
  GBP   DMO "Gilts in issue" report D1A saved as rawData/maturity/gilts*.xls*
        (conventional gilts: redemption date and nominal amount in issue).
  CNY   ChinaBond English site > Advanced Bond Info Searching, bond type
        Book-Entry Treasury Bonds, Excel download (needs a ChinaBond login)
        saved as rawData/maturity/cny_cgb.xls; or a CSV maturity_date,amount.
Any market can be overridden with rawData/maturity/<CODE>_issues.csv
(columns maturity_date,amount) where CODE is USD, GBP, EUR-DE, EUR-FR, JPY or CNY.
"""
from __future__ import annotations

import csv
import datetime as dt
import json
import re
import warnings
from pathlib import Path

import pandas as pd
import requests

from common import COMMON_BUCKETS, RAW

FOLDER = RAW / "maturity"
EDGES = [(0, 3), (3, 5), (5, 7), (7, 10), (10, 500)]
HDR = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/130 Safari/537.36", "Accept-Language": "en"}

US_API = "https://api.fiscaldata.treasury.gov/services/api/fiscal_service/v1/debt/mspd/mspd_table_3_market"
DE_URL = "https://www.deutsche-finanzagentur.de/fileadmin/user_upload/Institutionelle-investoren/berichtswesen/einzelaufstellung_en.xlsx"
FR_URL = "https://www.aft.gouv.fr/en/encours-detaille-oat"
JP_URL = "https://www.mof.go.jp/jgbs/reference/appendix/maturity.xlsx"

MON = {m: i + 1 for i, m in enumerate(["january", "february", "march", "april", "may", "june", "july", "august", "september", "october", "november", "december"])}


# ---------------------------------------------------------------- helpers
def _meta_path(f: Path) -> Path:
    return f.with_suffix(f.suffix + ".meta.json")


def _save(f: Path, content: bytes):
    FOLDER.mkdir(parents=True, exist_ok=True)
    f.write_bytes(content)
    _meta_path(f).write_text(json.dumps({"fetched": dt.date.today().isoformat()}), encoding="utf-8")


def _fetched(f: Path) -> str | None:
    p = _meta_path(f)
    if p.exists():
        return json.loads(p.read_text(encoding="utf-8")).get("fetched")
    return dt.date.fromtimestamp(f.stat().st_mtime).isoformat() if f.exists() else None


def _get(url: str, f: Path, refresh: bool):
    if refresh or not f.exists():
        r = requests.get(url, headers=HDR, timeout=90)
        r.raise_for_status()
        _save(f, r.content)
        print(f"maturity: downloaded {f.name}")


def _dist(items: list[tuple[dt.date, float]], ref: dt.date) -> dict:
    """items: (maturity date, amount). Returns shares and amounts per bucket."""
    amt = [0.0] * len(EDGES)
    for md, a in items:
        y = (md - ref).days / 365.25
        for i, (lo, hi) in enumerate(EDGES):
            if lo <= y < hi:
                amt[i] += a
                break
    tot = sum(amt)
    return {"amounts": amt, "total": tot, "n_issues": len(items), "shares": [a / tot if tot else None for a in amt]}


def _pack(code: str, items, ref: dt.date, unit_div: float, **meta) -> dict:
    d = _dist(items, ref)
    out = {"available": True, "as_of": ref.isoformat(), "n_issues": d["n_issues"],
           "total_bn": d["total"] / unit_div, "amounts_bn": [a / unit_div for a in d["amounts"]],
           "shares": d["shares"], "buckets": COMMON_BUCKETS}
    out.update(meta)
    return out


def _csv_items(f: Path) -> list[tuple[dt.date, float]]:
    items = []
    with f.open(encoding="utf-8-sig", newline="") as fh:
        for row in csv.DictReader(fh):
            md = row.get("maturity_date") or row.get("maturity") or row.get("redemption_date")
            a = row.get("amount") or row.get("nominal") or row.get("outstanding")
            if not md or not a:
                continue
            items.append((dt.date.fromisoformat(md.strip()[:10]), float(str(a).replace(",", ""))))
    return items


# ---------------------------------------------------------------- USD
def _us(refresh: bool) -> dict:
    f = FOLDER / "us_mspd_table3.json"
    if refresh or not f.exists():
        latest = requests.get(US_API, params={"page[size]": 1, "sort": "-record_date", "fields": "record_date"}, headers=HDR, timeout=60).json()["data"][0]["record_date"]
        rows, page = [], 1
        while True:
            r = requests.get(US_API, params={"filter": f"record_date:eq:{latest}", "page[size]": 10000, "page[number]": page,
                                             "fields": "record_date,security_class1_desc,security_class2_desc,maturity_date,outstanding_amt"}, headers=HDR, timeout=120).json()
            rows += r["data"]
            if page >= r["meta"]["total-pages"]:
                break
            page += 1
        _save(f, json.dumps({"record_date": latest, "rows": rows}).encode("utf-8"))
        print(f"maturity: MSPD {latest}, {len(rows)} rows")
    d = json.loads(f.read_text(encoding="utf-8"))
    ref = dt.date.fromisoformat(d["record_date"])
    items, totals = [], {}
    for x in d["rows"]:
        c1, c2 = x["security_class1_desc"], x["security_class2_desc"]
        if c2 in ("Total Unmatured Treasury Notes", "Total Unmatured Treasury Bonds"):
            totals[c2] = float(x["outstanding_amt"])
            continue
        if c1 not in ("Notes", "Bonds"):
            continue
        try:
            md, a = dt.date.fromisoformat(x["maturity_date"]), float(x["outstanding_amt"])
        except (TypeError, ValueError):
            continue   # continuation lines of reopened issues carry no outstanding amount
        if a > 0:
            items.append((md, a))
    out = _pack("USD", items, ref, 1000.0,
                source="US Treasury, Monthly Statement of the Public Debt, table 3 (marketable Treasury securities by CUSIP), Fiscal Data API",
                source_url="https://fiscaldata.treasury.gov/datasets/monthly-statement-public-debt/",
                universe="nominal Treasury notes and bonds outstanding (no bills, TIPS or FRNs)", unit="USD bn", fetched=_fetched(f))
    chk = sum(totals.values())
    out["check"] = f"sum of issues {out['total_bn']:,.0f} bn vs reported total unmatured notes + bonds {chk / 1000:,.0f} bn" if totals else "no total rows found"
    out["check_ok"] = bool(totals) and abs(out["total_bn"] * 1000 / chk - 1) < 0.005
    return out


# ---------------------------------------------------------------- EUR-DE
def _de(refresh: bool) -> dict:
    f = FOLDER / "de_einzelaufstellung_en.xlsx"
    _get(DE_URL, f, refresh)
    with warnings.catch_warnings():
        warnings.simplefilter("ignore")
        df = pd.read_excel(f, header=None)
    hdr_i = next(i for i in range(len(df)) if str(df.iloc[i, 0]).strip().upper() == "TYPE OF SECURITY")
    hdr = df.iloc[hdr_i].tolist()
    date_cols = [(j, pd.Timestamp(h).date()) for j, h in enumerate(hdr) if re.fullmatch(r"\d{4}-\d{2}-\d{2}", str(h).strip()[:10]) or isinstance(h, (pd.Timestamp, dt.datetime))]
    j, ref = max(date_cols, key=lambda t: t[1])
    body = df.iloc[hdr_i + 1:].copy()
    body[0] = body[0].ffill()
    body = body[body[1].astype(str).str.startswith("DE")]
    excl = re.compile(r"strip|inflation|discount|bubill", re.I)
    kept = body[~body[0].astype(str).str.contains(excl)]
    items = [(pd.Timestamp(r[4]).date(), float(r[j])) for _, r in kept.iterrows() if pd.notna(r[j]) and float(r[j]) > 0]
    return _pack("EUR-DE", items, ref, 1e9,
                 source="Deutsche Finanzagentur, monthly itemised list of outstanding Federal securities (nominal values)",
                 source_url="https://www.deutsche-finanzagentur.de/en/federal-securities/types-of-federal-securities/overview-federal-securities",
                 universe="Federal Treasury notes (Schatz), Federal notes (Bobl) and Federal bonds (Bund) incl. green issues; no strips, inflation-linked bonds or Bubills",
                 unit="EUR bn", fetched=_fetched(f), types=sorted(set(kept[0].astype(str))))


# ---------------------------------------------------------------- EUR-FR
def _fr(refresh: bool) -> dict:
    f = FOLDER / "fr_encours_oat.html"
    _get(FR_URL, f, refresh)
    t = re.sub(r"\s+", " ", f.read_text(encoding="utf-8", errors="replace"))
    rows = re.findall(r"(FR\d{10})\s*</[^>]*>.*?(OAT[^<]*?(\d{1,2}) (\w+) (\d{4}))[^<]*<.*?([\d,]+\.\d\d)", t)
    items = [(dt.date(int(y), MON[mo.lower()], int(d)), float(a.replace(",", ""))) for _, _, d, mo, y, a in rows]
    if not items:
        raise ValueError("maturity: no OAT lines parsed from the AFT page")
    ref = dt.date.fromisoformat(_fetched(f))
    return _pack("EUR-FR", items, ref, 1e9,
                 source="Agence France Tresor, OATs debt outstanding (nominal, by line)", source_url=FR_URL,
                 universe="nominal OATs (no OATi/OATei, no BTFs); remaining maturity measured from the fetch date, the page carries no as-of date",
                 unit="EUR bn", fetched=_fetched(f))


# ---------------------------------------------------------------- JPY
def _jp(refresh: bool) -> dict:
    f = FOLDER / "jp_maturity.xlsx"
    _get(JP_URL, f, refresh)
    with warnings.catch_warnings():
        warnings.simplefilter("ignore")
        sheets = pd.read_excel(f, sheet_name=None, header=None)
    df = max(sheets.values(), key=len)
    title = str(df.iloc[0, 0])
    m = re.search(r"令和(\d+)年(\d+)月末", title)
    if not m:
        raise ValueError(f"maturity: cannot read the as-of date from {title!r}")
    y, mo = 2018 + int(m.group(1)), int(m.group(2))
    ref = (dt.date(y, mo, 28) + dt.timedelta(days=4)).replace(day=1) - dt.timedelta(days=1)
    items, kept = [], set()
    for _, r in df.iterrows():
        if not isinstance(r[0], (pd.Timestamp, dt.datetime)):
            continue
        name = str(r[1])
        if "利付国庫債券" not in name and "トランジション" not in name:
            continue   # skip T-bills (割引短期), retail (個人向け)
        if "物価連動" in name:
            continue   # inflation-indexed
        kept.add(name.split("　")[-1].strip())
        items.append((pd.Timestamp(r[0]).date(), float(r[3]) * 100))   # 100 mn yen -> JPY mn
    return _pack("JPY", items, ref, 1e6,
                 source="Ministry of Finance Japan, outstanding balance by issue of general bonds (end of fiscal year)",
                 source_url="https://www.mof.go.jp/jgbs/reference/appendix/index.htm",
                 universe="2y to 40y coupon JGBs incl. climate transition bonds; no T-bills, retail JGBs or inflation-indexed bonds",
                 unit="JPY trn", fetched=_fetched(f), types=sorted(kept))


# ---------------------------------------------------------------- GBP (manual)
def _gb() -> dict:
    files = sorted(FOLDER.glob("gilts*.xls*")) if FOLDER.exists() else []
    if not files:
        return {"available": False,
                "source": "DMO, Gilts in issue (report D1A), downloaded by hand",
                "source_url": "https://www.dmo.gov.uk/data/gilt-market/gilts-in-issue",
                "how_to": "dmo.gov.uk > Data > Gilt market > Gilts in issue: export to Excel and save it as rawData/maturity/gilts-in-issue.xlsx (conventional gilts: redemption date and total amount in issue)."}
    f = files[-1]
    with warnings.catch_warnings():
        warnings.simplefilter("ignore")
        sheets = pd.read_excel(f, sheet_name=None, header=None)
    items = []
    for df in sheets.values():
        hdr_i = next((i for i in range(len(df)) if any("redemption" in str(v).lower() for v in df.iloc[i]) and any("amount" in str(v).lower() for v in df.iloc[i])), None)
        if hdr_i is None:
            continue
        hdr = [str(v).lower() for v in df.iloc[hdr_i]]
        jd = next(j for j, h in enumerate(hdr) if "redemption" in h)
        ja = next(j for j, h in enumerate(hdr) if "amount" in h and "issue" in h) if any("amount" in h and "issue" in h for h in hdr) else next(j for j, h in enumerate(hdr) if "amount" in h)
        for i in range(hdr_i + 1, len(df)):
            r = df.iloc[i]
            cell = " ".join(str(v) for v in r if pd.notna(v)).lower()
            if "index-linked" in cell or "index linked" in cell:
                break
            try:
                md = pd.Timestamp(r[jd]).date()
                a = float(str(r[ja]).replace(",", ""))
            except (TypeError, ValueError):
                continue
            if a > 0:
                items.append((md, a))
        if items:
            break
    if not items:
        raise ValueError(f"maturity: could not parse conventional gilts from {f.name}")
    ref = dt.date.fromisoformat(_fetched(f))
    head = " ".join(str(v) for df in sheets.values() for v in df.head(8).values.ravel() if pd.notna(v))
    m = re.search(r"IN ISSUE ON (\d{1,2}) (\w+) (\d{4})", head, re.I)
    if m:
        ref = dt.date(int(m.group(3)), MON[m.group(2).lower()], int(m.group(1)))   # the file's own as-of date
    return _pack("GBP", items, ref, 1000.0, source="DMO, Gilts in issue (report D1A), downloaded by hand",
                 source_url="https://www.dmo.gov.uk/data/gilt-market/gilts-in-issue",
                 universe="conventional gilts (no index-linked gilts, no strips); remaining maturity from the file's own as-of date",
                 unit="GBP bn", fetched=_fetched(f), file=f.name)


# ---------------------------------------------------------------- CNY (manual)
CN_URL = "https://www.chinabond.com.cn/chinaBond_en/dtcx/zqzlfhcx/"
CN_HOWTO = ("ChinaBond (English site) > Advanced Bond Info Searching: tick Bond Type > Government Bonds > Book-Entry Treasury Bonds, "
            "leave the issue date empty, submit, then use the download button (needs a free ChinaBond login) and save the file "
            "'ChinaBond-Bond information query results.xls' as rawData/maturity/cny_cgb.xls. The parser keeps the bonds whose maturity "
            "date lies after the file date and reads 'Total Planned Amount (RMB 100 million)'. A CSV with columns maturity_date,amount works too.")


ABO_PAGE = "https://asianbondsonline.adb.org/china/data/"
ABO_CSV = "https://asianbondsonline.adb.org/downloads/standard_download_csv.php?code=Govt_Sec_Mat_Local_Ccy&economies=CN&years={years}"
CNY_5_10_SPLIT = 0.4   # share of the ADB 5-10y bucket assigned to 5-7y; the rest goes to 7-10y (assumption, see _cn_abo)
ABO_FILE = "cny_abo_maturity_profile.csv"


def _cn_abo(refresh: bool) -> dict:
    """Fallback without a ChinaBond login: the ADB AsianBondsOnline quarterly maturity profile of China's local-currency
    sovereign debt securities (Treasury instruments with more than one year left), as shares of the total in the buckets
    >1-3, >3-5, >5-10 and >10 years. Mapped to the common buckets: 0-3y <- 1-3y (bills and the last year to maturity
    are outside the ADB universe), 3-5y as is, 5-10y split CNY_5_10_SPLIT / (1 - CNY_5_10_SPLIT) between 5-7y and 7-10y
    (CGB benchmark issuance is heavier in 10-year than in 7-year bonds, so more of the bucket sits in 7-10y), 10y+ <- >10y.
    Shares only: the ADB file carries no amounts."""
    y = dt.date.today().year
    f = FOLDER / ABO_FILE
    _get(ABO_CSV.format(years=f"{y - 2},{y - 1},{y}"), f, refresh)
    rows = []
    with f.open(encoding="utf-8-sig", newline="") as fh:
        for line in fh:
            p = [c.strip().strip('"') for c in line.strip().split(",")]
            if len(p) >= 6 and p[0] == "CN" and re.match(r"\d{4}-\d{2}-\d{2}$", p[1]):
                rows.append((p[1], [float(v) for v in p[2:6]]))
    if not rows:
        raise ValueError(f"maturity: no CN rows in {f.name}")
    as_of, (s13, s35, s510, s10) = sorted(rows)[-1]
    raw = [s13, s35, s510 * CNY_5_10_SPLIT, s510 * (1 - CNY_5_10_SPLIT), s10]
    tot = sum(raw)
    return {"available": True, "as_of": as_of, "n_issues": None, "total_bn": None, "amounts_bn": [None] * 5,
            "shares": [v / tot for v in raw], "buckets": COMMON_BUCKETS, "mode": "automatic",
            "source": "ADB AsianBondsOnline, local currency sovereign debt securities outstanding maturity profile (quarterly)",
            "source_url": ABO_PAGE, "unit": "shares only",
            "universe": (f"Treasury instruments with more than one year to maturity, shares of the total in ADB buckets >1-3, >3-5, >5-10 and >10 years "
                         f"(bills and bonds inside their last year are not covered, so 0-3y is understated); the >5-10 bucket is split "
                         f"{CNY_5_10_SPLIT:.0%} / {1 - CNY_5_10_SPLIT:.0%} between 5-7y and 7-10y by assumption, not data. "
                         f"A ChinaBond per-issue export saved as rawData/maturity/cny_cgb.xls replaces this with exact figures"),
            "fetched": _fetched(f), "file": f.name, "how_to": CN_HOWTO}


def _cn(refresh: bool = False) -> dict:
    files = [p for p in sorted(FOLDER.glob("cny_*.xls*")) + sorted(FOLDER.glob("cny_*.csv")) if p.name != ABO_FILE] if FOLDER.exists() else []
    if not files:
        return _cn_abo(refresh)
    f = files[-1]
    ref = dt.date.fromisoformat(_fetched(f))
    if f.suffix.lower() == ".csv":
        items = _csv_items(f)
        unit_div, unit, note = 1.0, "file units, bn", "as supplied"
    else:
        with warnings.catch_warnings():
            warnings.simplefilter("ignore")
            sheets = pd.read_excel(f, sheet_name=None, header=None)
        items, note = [], ""
        for df in sheets.values():
            hdr_i = next((i for i in range(min(len(df), 30)) if any("maturity date" in str(v).lower() for v in df.iloc[i]) and any("amount" in str(v).lower() for v in df.iloc[i])), None)
            if hdr_i is None:
                continue
            hdr = [str(v).lower() for v in df.iloc[hdr_i]]
            jd = next(j for j, h in enumerate(hdr) if "maturity date" in h)
            ja = next(j for j, h in enumerate(hdr) if "amount" in h)
            jc = next((j for j, h in enumerate(hdr) if "bond code" in h), None)
            by_code = {}
            for i in range(hdr_i + 1, len(df)):
                r = df.iloc[i]
                try:
                    md = pd.Timestamp(r[jd]).date()
                    a = float(str(r[ja]).replace(",", ""))
                except (TypeError, ValueError):
                    continue
                if not (a > 0) or md <= ref:
                    continue   # matured or empty
                key = str(r[jc]).strip() if jc is not None else f"{i}"
                if key in by_code:
                    by_code[key] = (md, max(by_code[key][1], a))   # reopenings repeat the bond with its updated total
                else:
                    by_code[key] = (md, a)
            items = list(by_code.values())
            note = "one row per bond code (largest amount kept where a code repeats); bonds matured by the file date dropped"
            break
        if not items:
            raise ValueError(f"maturity: no 'Maturity Date' / 'Amount' table found in {f.name}")
        unit_div, unit = 10.0, "RMB bn"   # RMB 100 mn -> bn
    return _pack("CNY", items, ref, unit_div, source="ChinaBond Advanced Bond Info Searching (book-entry Treasury bonds), downloaded by hand",
                 source_url=CN_URL, universe=f"book-entry CGBs outstanding on the file date as listed by ChinaBond; {note}; remaining maturity from the file date",
                 unit=unit, fetched=_fetched(f), file=f.name)


# ---------------------------------------------------------------- build
def build(refresh: bool = False) -> dict:
    out = {}
    for code, fn in [("USD", lambda: _us(refresh)), ("GBP", _gb), ("EUR-DE", lambda: _de(refresh)), ("EUR-FR", lambda: _fr(refresh)), ("JPY", lambda: _jp(refresh)), ("CNY", lambda: _cn(refresh))]:
        ov = FOLDER / f"{code}_issues.csv"
        try:
            if ov.exists():
                items = _csv_items(ov)
                out[code] = _pack(code, items, dt.date.fromisoformat(_fetched(ov)), 1.0, source=f"issue list supplied by hand ({ov.name})", source_url="",
                                  universe="as supplied; remaining maturity from the file date", unit="file units, bn", fetched=_fetched(ov), file=ov.name)
            else:
                out[code] = fn()
        except Exception as e:   # a failed source must not stop the build; the page shows the market as not available
            out[code] = {"available": False, "source": "", "source_url": "", "error": f"{type(e).__name__}: {e}"}
            print(f"maturity: {code} failed: {e}")
    for code, m in out.items():
        if m.get("available"):
            m["shares_pct"] = [round(100 * s, 1) for s in m["shares"]]
    return {"note": "Nominal amounts outstanding by remaining maturity on the as-of date, in the five common buckets, for the nominal coupon bonds that the market's turnover data covers. Used as the market-weighted maturity profile of a holding when the maturity option is switched on.",
            "buckets": COMMON_BUCKETS, "markets": out}


if __name__ == "__main__":
    import sys
    d = build("--refresh" in sys.argv)
    for k, m in d["markets"].items():
        if m.get("available"):
            print(f"{k:7s} as of {m['as_of']}  {m['n_issues'] or 0:4d} issues  total {m['total_bn'] or 0:>10,.1f} {m['unit']:8s}", m["shares_pct"], m.get("check", ""))
        else:
            print(f"{k:7s} not available: {m.get('error') or m.get('how_to')}")
