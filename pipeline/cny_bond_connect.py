"""Bond Connect monthly Flash Reports (CNY, CGBs). Port of cny_bond_connect.R.

Source: https://www.chinabondconnect.com/en/Resource/Flash-Report.html
Each report states Northbound monthly trading volume (RMB bn), average daily
turnover (RMB bn) and the shares of the two most traded bond types. The pages
are saved in rawData/cny_bond_connect and the highlights sentence parsed.
"""
from __future__ import annotations

import re
import sys
import datetime as dt

import lxml.html
import requests

from common import (CNY_BONDCONNECT_SHARE, CNY_CHANNEL, CNY_MARKET_CGB_ADV_BN, CNY_MARKET_CGB_NOTE, CNY_WINDOW, COMMON_BUCKETS, RAW, clean_num)

INDEX = "https://www.chinabondconnect.com/en/Resource/Flash-Report.html"
FOLDER = RAW / "cny_bond_connect"
MONTHS = ["January", "February", "March", "April", "May", "June", "July", "August", "September", "October", "November", "December"]

# Embedded fallback (read from the Flash Reports, 2026-08-26)
FALLBACK = [
    ("2025-08-01", 750.1, 35.7, 0.38, 0.41), ("2025-09-01", 581.0, 25.3, None, None), ("2025-10-01", 572.3, 31.8, None, None),
    ("2025-11-01", 667.8, 33.4, None, None), ("2025-12-01", 639.5, 27.8, 0.39, 0.49), ("2026-01-01", 942.5, 44.9, 0.34, 0.51),
    ("2026-02-01", 805.5, 50.3, None, None), ("2026-03-01", 1224.1, 55.6, 0.24, 0.59), ("2026-04-01", 984.8, 46.9, 0.22, 0.58),
    ("2026-05-01", 893.1, 47.0, None, None), ("2026-06-01", 864.9, 41.2, None, None), ("2026-07-01", 858.6, 37.3, 0.22, 0.59)]


def download(refresh=False):
    FOLDER.mkdir(parents=True, exist_ok=True)
    r = requests.get(INDEX, timeout=60, headers={"User-Agent": "Mozilla/5.0"})
    r.raise_for_status()
    (FOLDER / "flash_index.html").write_text(r.text, encoding="utf-8")
    links = sorted(set(re.findall(r"/en/Resource/Flash-Report/Bond-Connect-Flash-Report[^\"' ]*\.html", r.text)))
    for p in links:
        f = FOLDER / p.rsplit("/", 1)[1]
        if f.exists() and not refresh:
            continue
        rr = requests.get("https://www.chinabondconnect.com" + p, timeout=60, headers={"User-Agent": "Mozilla/5.0"})
        if rr.status_code == 200:
            f.write_text(rr.text, encoding="utf-8")
            print("CNY: saved", f.name)


def parse_report(path):
    txt = lxml.html.fromstring(path.read_text(encoding="utf-8")).text_content()
    txt = re.sub(r"\s+", " ", txt)
    m = re.search(r"Bond Connect Flash Report - (\w+) (\d{4})", txt)
    if not m:
        return None
    month = dt.date(int(m.group(2)), MONTHS.index(m.group(1)) + 1, 1)
    def num(p):
        mm = re.search(p, txt)
        return float(mm.group(1).replace(",", "")) if mm else None
    vol = num(r"monthly trading volume (?:of \w+ |for \w+ )?(?:was|stood at) RMB ([0-9,\.]+) billion")
    adt = num(r"average daily turnover stood at RMB ([0-9,\.]+) billion")
    sh = re.search(r"(Policy financial bond|Chinese government bond) and (Policy financial bond|Chinese government bond) were the most popular bond types, accounting for ([0-9]+)% and ([0-9]+)%", txt, re.I)
    cgb = pfb = None
    if sh:
        p1, p2 = int(sh.group(3)) / 100, int(sh.group(4)) / 100
        first_cgb = "government" in sh.group(1).lower()
        cgb, pfb = (p1, p2) if first_cgb else (p2, p1)
    return dict(month=month, volume_bn=vol, adt_bn=adt, cgb_share=cgb, pfb_share=pfb, file=path.name)


def load():
    rows = [parse_report(f) for f in sorted(FOLDER.glob("Bond-Connect-Flash-Report*.html"))]
    rows = [r for r in rows if r and r["adt_bn"]]
    origin = "Flash Report pages"
    if not rows:
        rows = [dict(month=dt.date.fromisoformat(m), volume_bn=v, adt_bn=a, cgb_share=c, pfb_share=p, file="fallback")
                for m, v, a, c, p in FALLBACK]
        origin = "embedded fallback (Aug 2025 to Jul 2026)"
    rows.sort(key=lambda r: r["month"])
    return rows, origin


def build(rows, origin, ccdc=None) -> dict:
    known = [r for r in rows if r["cgb_share"] is not None]
    fill = sum(r["cgb_share"] * r["adt_bn"] for r in known) / sum(r["adt_bn"] for r in known)
    for r in rows:
        r["cgb_share_used"] = r["cgb_share"] if r["cgb_share"] is not None else fill
        r["cgb_adt_bn"] = r["adt_bn"] * r["cgb_share_used"]
        r["trading_days"] = round(r["volume_bn"] / r["adt_bn"]) if r["volume_bn"] else None
    recent = rows[-CNY_WINDOW:]
    adt = sum(r["adt_bn"] for r in recent) / len(recent)
    cgb_adt = sum(r["cgb_adt_bn"] for r in recent) / len(recent)
    bc_cgb_mn = cgb_adt * 1000
    foreign_mn = bc_cgb_mn / CNY_BONDCONNECT_SHARE
    d2c_mn = bc_cgb_mn if CNY_CHANNEL == "bond_connect" else foreign_mn
    if ccdc:
        total_mn = ccdc["window_avg"]["cgb_adv_mn"]
        market_bn, market_note = total_mn / 1000, f"CCDC monthly statistics, interbank cash settlement of CGBs, {ccdc['window']['label']}, face value, each trade counted once, divided by interbank trading days"
        total_note = f"CNY {market_bn:.0f} bn per day, {market_note}; all counterparties, mostly domestic banks and interbank trading; not used for the dealer-to-customer segments"
    else:
        total_mn = None if CNY_MARKET_CGB_ADV_BN is None else CNY_MARKET_CGB_ADV_BN * 1000
        market_bn, market_note = CNY_MARKET_CGB_ADV_BN, CNY_MARKET_CGB_NOTE
        total_note = (f"CNY {CNY_MARKET_CGB_ADV_BN} bn per day, {CNY_MARKET_CGB_NOTE}; entered by hand as CNY_MARKET_CGB_ADV_BN; all counterparties, mostly domestic banks and interbank trading; not used for the dealer-to-customer segments" if CNY_MARKET_CGB_ADV_BN else "not available until a figure is entered as CNY_MARKET_CGB_ADV_BN")
    return {
        "code": "CNY", "name": "Chinese government bonds", "currency": "CNY", "unit": "CNY mn per trading day",
        "source": "Bond Connect Company Limited, monthly Flash Reports (Northbound)",
        "source_url": INDEX, "origin": origin,
        "counting": "Northbound average daily turnover as reported (foreign investors' trades with onshore market makers), times the CGB share of volume",
        "maturity_basis": "none (one group)",
        "groups": ["all"], "group_map": {b: "all" for b in COMMON_BUCKETS},
        "months": [r["month"].isoformat() for r in rows],
        "monthly": [{k: (clean_num(v) if isinstance(v, (int, float)) else v) for k, v in r.items() if k != "month"} | {"month": r["month"].isoformat()} for r in rows],
        "window": {"from": recent[0]["month"].isoformat(), "to": recent[-1]["month"].isoformat(), "n": len(recent),
                   "label": f"{recent[0]['month']:%b %Y} to {recent[-1]['month']:%b %Y}"},
        "channel": CNY_CHANNEL, "bondconnect_share": CNY_BONDCONNECT_SHARE, "fill_cgb_share": clean_num(fill),
        "adt_bn": clean_num(adt), "cgb_adt_bn": clean_num(cgb_adt), "market_cgb_adv_bn": clean_num(market_bn), "market_cgb_note": market_note,
        "market_cgb_from_ccdc": bool(ccdc), "ccdc": ccdc,
        "segments": {
            "d2c_base": {"key": "d2c_base", "label": "Foreign-investor CGB turnover" + (" (all channels, estimated)" if CNY_CHANNEL == "all_foreign" else " (Bond Connect only)"),
                         "note": (f"Bond Connect Northbound ADT x CGB share / {CNY_BONDCONNECT_SHARE} = all-foreign CGB turnover estimate incl. CIBM Direct (HKMA share)" if CNY_CHANNEL == "all_foreign" else "Bond Connect Northbound ADT x CGB share") + "; no on/off-the-run split so d2c_base = d2c_all; single group, no maturity data"},
            "d2c_all": {"key": "d2c_all", "label": "Foreign-investor CGB turnover", "note": "same as d2c_base"},
            "d2d": {"key": "d2d", "label": "Not observable", "note": "interbank dealer-to-dealer CGB turnover is not published by counterparty type in the sources used"},
            "total": {"key": "total", "label": "Whole-market CGB cash turnover (onshore interbank)", "note": total_note},
        },
        "window_adv": {"d2c_base": {"all": clean_num(d2c_mn)}, "d2c_all": {"all": clean_num(d2c_mn)},
                       "d2d": {"all": None}, "total": {"all": clean_num(total_mn)}},
        "bond_connect_cgb_adv_mn": clean_num(bc_cgb_mn), "all_foreign_cgb_adv_mn": clean_num(foreign_mn),
    }


if __name__ == "__main__":
    if "--refresh" in sys.argv:
        download()
    rows, origin = load()
    d = build(rows, origin)
    print(origin, d["window"], d["window_adv"], d["cgb_adt_bn"])
