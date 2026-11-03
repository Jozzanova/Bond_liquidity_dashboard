"""FINRA TRACE Treasury monthly aggregates (USD).

Source: https://cdn.finra.org/trace/treasury-aggregates/monthly/ts-monthly-aggregates-YYYY-MM.xlsx
Par value in USD bn for the month, single-counted per trade. Venues: "ATS &
Interdealer" (dealer-to-dealer), "Dealer to Customer", "Total". Nominal coupons
and TIPS are split by REMAINING maturity with on/off-the-run sub-rows.
"""
from __future__ import annotations

import datetime as dt
import re
import sys
from pathlib import Path

import pandas as pd
import requests

from common import (COMMON_BUCKETS, RAW, SIFMA_HOLIDAYS, TRACE_WINDOW, clean_num,
                    month_end, trading_days_between)

BASE_URL = "https://cdn.finra.org/trace/treasury-aggregates/monthly/ts-monthly-aggregates-"
FOLDER = RAW / "trace_us"
TYPES = ["Bills", "FRNs", "Nominal Coupons", "TIPS", "Total"]
BUCKET_ORDER = ["<= 2 years", "> 2 years and <= 3 years", "> 3 years and <= 5 years",
                "> 5 years and <= 7 years", "> 7 years and <= 10 years",
                "> 10 years and <= 20 years", "> 20 years"]
BUCKET_MAP = dict(zip(BUCKET_ORDER, ["0-3y", "0-3y", "3-5y", "5-7y", "7-10y", "10y+", "10y+"]))
VENUES = {"ats": "ATS & Interdealer", "d2c": "Dealer to Customer", "tot": "Total"}


def download(first_month="2023-01", refresh=False):
    """Download any missing monthly file from 2023-01 up to last month."""
    FOLDER.mkdir(parents=True, exist_ok=True)
    today = dt.date.today()
    y, m = map(int, first_month.split("-"))
    months = []
    while (y, m) < (today.year, today.month):
        months.append(f"{y}-{m:02d}")
        m += 1
        if m == 13:
            y, m = y + 1, 1
    got = 0
    for mm in months:
        f = FOLDER / f"ts-monthly-aggregates-{mm}.xlsx"
        if f.exists() and not refresh:
            continue
        r = requests.get(BASE_URL + mm + ".xlsx", timeout=60, headers={"User-Agent": "Mozilla/5.0"})
        if r.status_code == 200 and r.content[:2] == b"PK":
            f.write_bytes(r.content)
            got += 1
    print(f"TRACE: downloaded {got} new monthly files")


def parse_file(path: Path) -> pd.DataFrame:
    raw = pd.read_excel(path, sheet_name="Summary", header=None)
    title = str(raw.iat[0, 0])
    asof = dt.datetime.strptime(re.sub(r"^TRACE Volumes - ", "", title).strip(), "%B %d, %Y").date()
    col0 = raw[0].astype(str).str.strip()
    hdr = col0[col0 == "Category"].index[0]
    end = [i for i in col0[col0 == "Total"].index if i > hdr][0]
    body = raw.iloc[hdr + 2:end + 1].copy()
    body["label"] = body[0].astype(str).str.strip()
    rows = []
    sec_type = None
    bucket = "All"
    for _, r in body.iterrows():
        lab = r["label"]
        if lab in TYPES:
            sec_type = "All" if lab == "Total" else lab
            bucket = "All"
            run = "All"
        elif re.match(r"^(<=|>)", lab):
            bucket = lab
            run = "All"
        elif lab in ("On-the-run", "Off-the-run"):
            run = lab
        else:
            continue
        for key, venue in VENUES.items():
            c = {"ats": (1, 2), "d2c": (3, 4), "tot": (5, 6)}[key]
            rows.append(dict(month=asof.replace(day=1), asof=asof, security_type=sec_type,
                             maturity_bucket=bucket, run_status=run, venue=venue,
                             trades=float(r[c[0]]), par_value_bn=float(r[c[1]]),
                             source_file=path.name))
    return pd.DataFrame(rows)


def load() -> pd.DataFrame:
    files = sorted(FOLDER.glob("ts-monthly-aggregates-*.xlsx"))
    if not files:
        sys.exit("TRACE: no files in rawData/trace_us")
    df = pd.concat([parse_file(f) for f in files], ignore_index=True)
    td = {m: trading_days_between(m, month_end(m), SIFMA_HOLIDAYS) for m in df["month"].unique()}
    df["trading_days"] = df["month"].map(td)
    df["adv_mn"] = df["par_value_bn"] * 1000 / df["trading_days"]
    # consistency checks (on + off = all; buckets sum to type)
    nc = df[(df.maturity_bucket != "All")]
    chk = nc.groupby(["month", "security_type", "maturity_bucket", "venue"]).apply(
        lambda g: g.loc[g.run_status != "All", "par_value_bn"].sum() - g.loc[g.run_status == "All", "par_value_bn"].sum(),
        include_groups=False)
    bad = chk[chk.abs() > 0.15]
    if len(bad):
        print(f"TRACE: WARNING on/off-the-run rows do not add up in {len(bad)} cases (max {bad.abs().max():.2f} bn)")
    return df


def build(df: pd.DataFrame) -> dict:
    """Return the JSON block for the page."""
    nc = df[(df.security_type == "Nominal Coupons") & (df.maturity_bucket != "All")].copy()
    nc["bucket"] = nc["maturity_bucket"].map(BUCKET_MAP)
    nc["seg"] = nc["venue"].map({"ATS & Interdealer": "d2d", "Dealer to Customer": "d2c", "Total": "total"})
    nc["run"] = nc["run_status"].map({"All": "all", "On-the-run": "on", "Off-the-run": "off"})
    months = sorted(nc["month"].unique())
    recent = months[-TRACE_WINDOW:]

    # Monthly ADV by common bucket x segment x run (time series for charts)
    mb = nc.groupby(["month", "bucket", "seg", "run"], as_index=False)["adv_mn"].sum()
    monthly = {}
    for (seg, run), g in mb.groupby(["seg", "run"]):
        piv = g.pivot(index="month", columns="bucket", values="adv_mn").reindex(columns=COMMON_BUCKETS)
        monthly[f"{seg}_{run}"] = {b: [clean_num(v) for v in piv[b].reindex(months)] for b in COMMON_BUCKETS}

    # Monthly ADV by TRACE bucket (finer) for the detail table
    tb = nc.groupby(["month", "maturity_bucket", "seg", "run"], as_index=False)["adv_mn"].sum()
    trace_buckets = {}
    for (seg, run), g in tb.groupby(["seg", "run"]):
        piv = g.pivot(index="month", columns="maturity_bucket", values="adv_mn").reindex(columns=BUCKET_ORDER)
        trace_buckets[f"{seg}_{run}"] = {b: [clean_num(v) for v in piv[b].reindex(months)] for b in BUCKET_ORDER}

    # Window averages by common bucket (the liquidity-profile inputs)
    w = mb[mb.month.isin(recent)].groupby(["bucket", "seg", "run"], as_index=False)["adv_mn"].mean()
    window = {}
    for (seg, run), g in w.groupby(["seg", "run"]):
        window[f"{seg}_{run}"] = {b: clean_num(v) for b, v in zip(g.bucket, g.adv_mn)}
    # Totals by security type per month (context: bills, FRNs, TIPS, coupons)
    st = df[(df.maturity_bucket == "All") & (df.run_status == "All")]
    by_type = {}
    for (t, v), g in st.groupby(["security_type", "venue"]):
        s = g.set_index("month")["adv_mn"].reindex(months)
        by_type.setdefault(t, {})[{"ATS & Interdealer": "d2d", "Dealer to Customer": "d2c", "Total": "total"}[v]] = [clean_num(x) for x in s]
    trades = {}
    for (t, v), g in st[st.security_type == "Nominal Coupons"].groupby(["security_type", "venue"]):
        s = g.set_index("month")["trades"].reindex(months)
        trades[{"ATS & Interdealer": "d2d", "Dealer to Customer": "d2c", "Total": "total"}[v]] = [clean_num(x) for x in s]

    segments = {
        "d2c_base": {"key": "d2c_off", "label": "Dealer-to-customer, off-the-run",
                     "note": "TRACE nominal coupons, par value, dealer-to-customer venue, off-the-run issues only (strips included); single-counted per trade; remaining maturity"},
        "d2c_all": {"key": "d2c_all", "label": "Dealer-to-customer, all issues",
                    "note": "TRACE nominal coupons, par value, dealer-to-customer venue, on- and off-the-run; single-counted per trade; remaining maturity"},
        "d2d": {"key": "d2d_all", "label": "ATS and interdealer, all issues",
                "note": "TRACE nominal coupons, par value, ATS and interdealer venue (dealer-to-dealer), on- and off-the-run; single-counted per trade"},
        "total": {"key": "total_all", "label": "All venues, all issues",
                  "note": "TRACE nominal coupons, par value, all venues incl. ATS and interdealer, on- and off-the-run; single-counted per trade; remaining maturity"},
    }
    return {
        "code": "USD", "name": "US Treasuries", "currency": "USD", "unit": "USD mn per trading day",
        "source": "FINRA TRACE Treasury Monthly Aggregate Statistics",
        "source_url": "https://www.finra.org/finra-data/browse-catalog/about-monthly-treasury",
        "counting": "single-counted per trade (FINRA reports each trade once; ATS and interdealer trades are not doubled)",
        "maturity_basis": "remaining",
        "groups": COMMON_BUCKETS, "group_map": dict(zip(COMMON_BUCKETS, COMMON_BUCKETS)),
        "months": [m.isoformat() for m in months],
        "trading_days": [int(td) for td in nc.drop_duplicates("month").set_index("month")["trading_days"].reindex(months)],
        "window": {"from": recent[0].isoformat(), "to": recent[-1].isoformat(), "n": len(recent), "label": f"{recent[0]:%b %Y} to {recent[-1]:%b %Y}"},
        "segments": segments,
        "window_adv": {"d2c_base": window["d2c_off"], "d2c_all": window["d2c_all"], "d2d": window["d2d_all"], "total": window["total_all"]},
        "window_adv_detail": window,     # {seg_run: {bucket: adv_mn}} incl. on/off-the-run by venue
        "monthly_adv": monthly,          # {seg_run: {bucket: [by month]}}
        "trace_buckets": BUCKET_ORDER,
        "trace_bucket_map": BUCKET_MAP,
        "monthly_adv_trace_buckets": trace_buckets,
        "by_type_adv": by_type,          # {security_type: {d2d/d2c/total: [by month]}}
        "coupon_trades_per_month": trades,
        "files": len(months),
    }


if __name__ == "__main__":
    if "--refresh" in sys.argv:
        download()
    d = build(load())
    print(d["window"], {k: v for k, v in d["window_adv"].items() if k in ("d2c_off", "d2d_all", "total_all")})
