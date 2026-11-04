"""Shared settings and helpers for the bond liquidity pipeline.

Every number that is an
assumption rather than data is set here and carried into data/liquidity.json
so the page can show it.
"""
from __future__ import annotations

import datetime as dt
import json
import math
import os
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
RAW = ROOT / "rawData"
DATA = ROOT / "data"
DATA.mkdir(exist_ok=True)

# Common maturity grid for entering exposures (remaining maturity).
COMMON_BUCKETS = ["0-3y", "3-5y", "5-7y", "7-10y", "10y+"]

# Window lengths for the averages used in the liquidity profile
TRACE_WINDOW = 12      # months
DMO_WINDOW = 4         # quarters
JPY_WINDOW = 12        # months
CNY_WINDOW = 12        # months

# Finanzagentur (EUR): TARGET trading days per year and the OAT/Bund scale for
# France. eur_fr_scale is provisional: AFT monthly bulletin SVT-reported daily
# volume (roughly EUR 20 bn) against Finanzagentur MLT gross per day (about
# EUR 26 bn). Verify from the AFT statistical report before relying on it.
EUR_TRADING_DAYS = 255
EUR_FR_SCALE = 0.75
# Independent reference for France: approximate 2025 daily OAT turnover, gross
# (SVT-reported), EUR mn per day, probably including index-linked OATs. Shown on
# the page next to the proxy; not used in the calculation.
FR_REFERENCE_TOTAL_MN = 24000
FR_REFERENCE_NOTE = "approximate 2025 average of SVT-reported daily OAT turnover, gross, probably including OATi/OATei (own estimate from AFT material, early 2026)"

# JSDA (JPY): whether the "Others" investor category (which includes members'
# auction allotments) counts as customer flow.
JPY_INCLUDE_OTHERS = False

# Bond Connect (CNY): level definition. "bond_connect" = CGB turnover through
# Bond Connect only; "all_foreign" = divided by Bond Connect's share of foreign
# turnover in the CIBM (HKMA, July 2026: over 64 %).
# Whole-market CGB cash turnover for the total segment comes from the CCDC
# monthly statistics files in rawData/ccdc_cgb (cny_ccdc.py). The figure below
# is the user's own earlier estimate; it is shown as a reference next to the
# CCDC figure and used for the total segment only if no CCDC files are present.
CNY_CHANNEL = "all_foreign"
CNY_BONDCONNECT_SHARE = 0.64
CNY_D2C_ADV_BN_OVERRIDE = None   # CNY bn per day. Set to replace the Bond Connect based estimate of foreign-investor CGB turnover
                                 # (dealer-to-customer pool) with a better figure, e.g. a CFETS/ChinaBond series by counterparty from a terminal
CNY_D2C_OVERRIDE_NOTE = ""       # where the override comes from (shown on the page)
CNY_5_10_SPLIT = 0.4             # share of the ADB 5-10y maturity bucket assigned to 5-7y, the rest to 7-10y (assumption; only used without a ChinaBond file)
CNY_MARKET_CGB_ADV_BN = 415
CNY_MARKET_CGB_NOTE = "daily average July 2025 to June 2026, read from charts in monthly market reports, user's own estimate from early 2026; the PBoC monthly release itself gives no CGB split"

# Trading-day calendars (typed in; verify against SIFMA, gov.uk and JPX).
SIFMA_HOLIDAYS = {dt.date.fromisoformat(d) for d in [
    "2023-01-02", "2023-01-16", "2023-02-20", "2023-04-07", "2023-05-29", "2023-06-19",
    "2023-07-04", "2023-09-04", "2023-10-09", "2023-11-10", "2023-11-23", "2023-12-25",
    "2024-01-01", "2024-01-15", "2024-02-19", "2024-03-29", "2024-05-27", "2024-06-19",
    "2024-07-04", "2024-09-02", "2024-10-14", "2024-11-11", "2024-11-28", "2024-12-25",
    "2025-01-01", "2025-01-09", "2025-01-20", "2025-02-17", "2025-04-18", "2025-05-26", "2025-06-19",
    "2025-07-04", "2025-09-01", "2025-10-13", "2025-11-11", "2025-11-27", "2025-12-25",
    "2026-01-01", "2026-01-19", "2026-02-16", "2026-04-03", "2026-05-25", "2026-06-19",
    "2026-07-03", "2026-09-07", "2026-10-12", "2026-11-11", "2026-11-26", "2026-12-25"]}
UK_HOLIDAYS = {dt.date.fromisoformat(d) for d in [
    "2022-01-03", "2022-04-15", "2022-04-18", "2022-05-02", "2022-06-02", "2022-06-03", "2022-08-29",
    "2022-09-19", "2022-12-26", "2022-12-27",
    "2023-01-02", "2023-04-07", "2023-04-10", "2023-05-01", "2023-05-08", "2023-05-29", "2023-08-28",
    "2023-12-25", "2023-12-26",
    "2024-01-01", "2024-03-29", "2024-04-01", "2024-05-06", "2024-05-27", "2024-08-26", "2024-12-25", "2024-12-26",
    "2025-01-01", "2025-04-18", "2025-04-21", "2025-05-05", "2025-05-26", "2025-08-25", "2025-12-25", "2025-12-26",
    "2026-01-01", "2026-04-03", "2026-04-06", "2026-05-04", "2026-05-25", "2026-08-31", "2026-12-25", "2026-12-28"]}
JP_HOLIDAYS = {dt.date.fromisoformat(d) for d in [   # JGB market closures incl. 2-3 Jan and 31 Dec
    "2025-01-01", "2025-01-02", "2025-01-03", "2025-01-13", "2025-02-11", "2025-02-24", "2025-03-20",
    "2025-04-29", "2025-05-05", "2025-05-06", "2025-07-21", "2025-08-11", "2025-09-15", "2025-09-23",
    "2025-10-13", "2025-11-03", "2025-11-24", "2025-12-31",
    "2026-01-01", "2026-01-02", "2026-01-12", "2026-02-11", "2026-02-23", "2026-03-20", "2026-04-29",
    "2026-05-04", "2026-05-05", "2026-05-06", "2026-07-20", "2026-08-11", "2026-09-21", "2026-09-22",
    "2026-09-23", "2026-10-12", "2026-11-03", "2026-11-23", "2026-12-31"]}


# China: State Council public holidays falling on weekdays, and the adjusted
# weekend working days, which the interbank bond market observes (the
# exchanges do not). Verify against the yearly State Council notice.
CN_HOLIDAYS = {dt.date.fromisoformat(d) for d in [
    "2025-01-01", "2025-01-28", "2025-01-29", "2025-01-30", "2025-01-31", "2025-02-03", "2025-02-04",
    "2025-04-04", "2025-05-01", "2025-05-02", "2025-05-05", "2025-06-02",
    "2025-10-01", "2025-10-02", "2025-10-03", "2025-10-06", "2025-10-07", "2025-10-08",
    "2026-01-01", "2026-01-02", "2026-02-16", "2026-02-17", "2026-02-18", "2026-02-19", "2026-02-20", "2026-02-23",
    "2026-04-06", "2026-05-01", "2026-05-04", "2026-05-05", "2026-06-19", "2026-09-25",
    "2026-10-01", "2026-10-02", "2026-10-05", "2026-10-06", "2026-10-07"]}
CN_WORKDAYS = {dt.date.fromisoformat(d) for d in [   # weekend days worked
    "2025-01-26", "2025-02-08", "2025-04-27", "2025-09-28", "2025-10-11",
    "2026-01-04", "2026-02-14", "2026-02-28", "2026-05-09", "2026-09-20", "2026-10-10"]}


def trading_days_between(start: dt.date, end: dt.date, holidays: set, workdays: set = frozenset()) -> int:
    n = 0
    d = start
    while d <= end:
        if (d.weekday() < 5 and d not in holidays) or d in workdays:
            n += 1
        d += dt.timedelta(days=1)
    return n


def month_end(first: dt.date) -> dt.date:
    nxt = (first.replace(day=28) + dt.timedelta(days=4)).replace(day=1)
    return nxt - dt.timedelta(days=1)


def clean_num(x):
    """Return a JSON-safe float (None for NaN/inf), rounded to 6 significant-ish digits."""
    if x is None:
        return None
    try:
        v = float(x)
    except (TypeError, ValueError):
        return None
    if math.isnan(v) or math.isinf(v):
        return None
    return round(v, 4)


def dump_json(obj, path: Path):
    path.write_text(json.dumps(obj, ensure_ascii=False, indent=1), encoding="utf-8")
    print(f"wrote {path.relative_to(ROOT)} ({path.stat().st_size // 1024} kB)")


def latest_file(folder: Path, pattern: str):
    files = sorted(p for p in folder.glob("*") if re.match(pattern, p.name))
    return files[-1] if files else None
