"""CCDC (ChinaBond) monthly statistics: interbank cash-bond settlement of
Chinese government bonds, whole market.

Source: https://www.chinabond.com.cn/chinaBond_en/A147249680/A147253508/A147253972/ (Data > Statistics >
Monthly Bulletin of Statistics). Pick year and month, click the table title,
choose Excel. Two tables are used:
  7. CIBM Bond Settlement (By Bond Type)      -> "CIBM Bond Settlement (By Bond Type)_YYYYMM.xls"
  8. CIBM Bond Settlement (By Investor Type)  -> "CIBM Bond Settlement (By Investor Type)_YYYYMM.xls"
The files are xlsx inside despite the .xls name. Units RMB 100 million, face
value, settlement date, interbank market only (no exchange, no counter).
Table 7 counts each trade once; table 8 counts each side (its total is twice
table 7), so an investor type's figure is that type's own gross buy+sell.
The site serves the files through a POST endpoint that the sandbox would not
let the pipeline call, so the files are downloaded by hand like the DMO ones.
"""
from __future__ import annotations

import datetime as dt
import re
import warnings

import pandas as pd

from common import CN_HOLIDAYS, CN_WORKDAYS, CNY_MARKET_CGB_ADV_BN, CNY_MARKET_CGB_NOTE, CNY_WINDOW, RAW, clean_num, month_end, trading_days_between

FOLDER = RAW / "ccdc_cgb"
MON = {m: i + 1 for i, m in enumerate(["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"])}


def _read(path):
    with warnings.catch_warnings():
        warnings.simplefilter("ignore")
        df = pd.read_excel(path, header=None, engine="openpyxl")
    lab, unit = str(df.iloc[2, 0]), str(df.iloc[2, 1])
    m = re.match(r"([A-Z][a-z]{2})-(\d{4})", lab)
    if not m or "100 Million" not in unit or str(df.iloc[3, 1]).strip() != "Cash Bond" or str(df.iloc[4, 1]).strip() != "Current Month":
        raise ValueError(f"CCDC: unexpected layout in {path.name}: {lab!r} {unit!r}")
    month = dt.date(int(m.group(2)), MON[m.group(1)], 1)
    rows = {}
    for i in range(5, len(df)):
        k = str(df.iloc[i, 0]).strip()
        k = re.sub(r"^\d+\.\s*", "", k)
        v = pd.to_numeric(df.iloc[i, 1], errors="coerce")
        if k and k != "nan":
            rows[k] = float(v) * 100 if pd.notna(v) else None   # RMB 100 mn -> RMB mn
    return month, rows


def load():
    by_type, by_inv = {}, {}
    for f in sorted(FOLDER.glob("*.xls*")):
        month, rows = _read(f)
        (by_type if "Bond Type" in f.name else by_inv)[month] = rows
    return by_type, by_inv


def build(data) -> dict | None:
    by_type, by_inv = data
    if not by_type:
        return None
    months = sorted(by_type)
    out = []
    for mth in months:
        t = by_type[mth]
        inv = by_inv.get(mth, {})
        td = trading_days_between(mth, month_end(mth), CN_HOLIDAYS, CN_WORKDAYS)
        if "China Government Bonds" not in t or "Total" not in t:
            raise ValueError(f"CCDC: rows missing for {mth}")
        r = dict(month=mth.isoformat(), trading_days=td,
                 cgb_mn=t["China Government Bonds"], all_mn=t["Total"],
                 pbb_mn=t.get("Policy Bank Bonds"), lgb_mn=t.get("Local Government Bonds"),
                 foreign_mn=inv.get("Foreign Investors"), inv_total_mn=inv.get("Total"))
        r["cgb_adv_mn"] = r["cgb_mn"] / td
        r["all_adv_mn"] = r["all_mn"] / td
        r["cgb_share"] = r["cgb_mn"] / r["all_mn"]
        r["foreign_adv_mn"] = r["foreign_mn"] / td if r["foreign_mn"] else None
        # table 8 counts both sides, so an investor type's share of all trading = its figure / (2 x table-7 total)
        r["foreign_share"] = r["foreign_mn"] / (2 * r["all_mn"]) if r["foreign_mn"] else None
        r["double_count_ok"] = (abs(r["inv_total_mn"] / (2 * r["all_mn"]) - 1) < 0.002) if r["inv_total_mn"] else None
        out.append(r)
    recent = out[-CNY_WINDOW:]
    n = len(recent)
    w = {k: sum(r[k] for r in recent) / n for k in ("cgb_adv_mn", "all_adv_mn")}
    w["cgb_mn_per_month"] = sum(r["cgb_mn"] for r in recent) / n
    fr = [r for r in recent if r["foreign_adv_mn"]]
    w["foreign_adv_mn"] = sum(r["foreign_adv_mn"] for r in fr) / len(fr) if fr else None
    w["foreign_share"] = sum(r["foreign_mn"] for r in fr) / (2 * sum(r["all_mn"] for r in fr)) if fr else None
    w["cgb_share"] = sum(r["cgb_mn"] for r in recent) / sum(r["all_mn"] for r in recent)
    w["trading_days"] = sum(r["trading_days"] for r in recent)
    first, last = dt.date.fromisoformat(recent[0]["month"]), dt.date.fromisoformat(recent[-1]["month"])
    return {
        "source": "CCDC (China Central Depository & Clearing), Monthly Bulletin of Statistics, tables 7 and 8 (CIBM bond settlement by bond type / by investor type)",
        "source_url": "https://www.chinabond.com.cn/chinaBond_en/A147249680/A147253508/A147253972/",
        "counting": "cash-bond settlement in the interbank market by settlement date, face value, RMB; by bond type each trade counts once; by investor type each side counts, so an investor type's figure is its own gross purchases plus sales",
        "coverage": "bonds registered at CCDC (CGBs, local government, policy bank, government-backed agency, commercial bank, enterprise bonds, ABS); interbank market only, no exchange or counter trading; the Bond Connect and CIBM Direct trades of foreign investors are included",
        "trading_days_note": "Trading days are weekdays less State Council holidays plus the adjusted weekend working days, which the interbank market observes; checked against the days implied by the Bond Connect reports",
        "months": [r["month"] for r in out],
        "monthly": [{k: (clean_num(v) if isinstance(v, float) else v) for k, v in r.items()} for r in out],
        "window": {"from": recent[0]["month"], "to": recent[-1]["month"], "n": n, "label": f"{first:%b %Y} to {last:%b %Y}"},
        "window_avg": {k: clean_num(v) for k, v in w.items()},
        "reference_bn": CNY_MARKET_CGB_ADV_BN, "reference_note": CNY_MARKET_CGB_NOTE,
        "files": [f.name for f in sorted(FOLDER.glob("*.xls*"))],
    }


if __name__ == "__main__":
    d = build(load())
    if d:
        print(d["window"], d["window_avg"])
        for r in d["monthly"]:
            print(r["month"], r["trading_days"], round(r["cgb_adv_mn"] / 1000, 1), round(r["all_adv_mn"] / 1000, 1), round(100 * r["cgb_share"], 1), r["foreign_adv_mn"] and round(r["foreign_adv_mn"] / 1000, 1), r["double_count_ok"])
    else:
        print("no CCDC files")
