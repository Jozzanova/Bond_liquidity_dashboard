"""UK DMO gilt turnover reported by GEMMs (GBP).

Source: https://www.dmo.gov.uk/data/gilt-market/turnover-data (the site sits
behind a bot check, so the three files are downloaded by hand into
rawData/dmo_gilts):
  gemm-turnover-by-maturity-band-*.xlsx   quarterly, one sheet per year
  all-gemms-turnover-*.xls                weekly customer / professional / combined
  annual-turnover-report-*.xls            financial-year ADV and turnover ratios
Turnover is market value. "Customer" (own-account counterparties) is the
dealer-to-customer analogue and single-counted; "professional" (DMO, BoE,
GEMMs, IDBs, agency brokers) is the dealer-to-dealer analogue and may double
count via IDBs.
"""
from __future__ import annotations

import datetime as dt
import re

import pandas as pd

from common import COMMON_BUCKETS, DMO_WINDOW, RAW, UK_HOLIDAYS, clean_num, latest_file, trading_days_between

FOLDER = RAW / "dmo_gilts"
BAND_LEVELS = ["0-1y", "1-3y", "3-5y", "5-7y", "7-10y", "10-15y", "15y+", "Index-linked", "Strips"]
BAND_RAW = {"0-12 months": "0-1y", "1-3 years": "1-3y", "3-5 years": "3-5y", "5-7 years": "5-7y",
            "7-10 years": "7-10y", "10-15 years": "10-15y", "15+ years": "15y+",
            "index-linked": "Index-linked", "strips": "Strips"}
BAND_MAP = {"0-1y": "0-3y", "1-3y": "0-3y", "3-5y": "3-5y", "5-7y": "5-7y", "7-10y": "7-10y", "10-15y": "10y+", "15y+": "10y+"}


def norm_band(lab: str):
    s = str(lab).strip().lower()
    s = re.sub(r"mths$", "months", s)
    s = re.sub(r"yrs$", "years", s)
    s = re.sub(r"\s+", " ", s)
    for k, v in BAND_RAW.items():
        if s.startswith(k) or s == k:
            return v
    return None


def read_any(path, sheet):
    return pd.read_excel(path, sheet_name=sheet, header=None)


def parse_bands(path) -> pd.DataFrame:
    x = pd.ExcelFile(path)
    sheets = [s for s in x.sheet_names if re.match(r"^\d{4}$", s)]
    rows = []
    for sh in sheets:
        raw = read_any(path, sh)
        quarter, in_table = None, False
        for i in range(len(raw)):
            lab = raw.iat[i, 0]
            if pd.isna(lab):
                continue
            lab = str(lab).strip()
            if re.match(r"^Q[1-4]", lab):
                quarter, in_table = int(lab[1]), False
                continue
            if lab.upper() == "BAND":
                in_table = True
                continue
            if lab.lower() == "total":
                in_table = False
                continue
            if in_table and quarter:
                band = norm_band(lab)
                if band is None:
                    print("DMO: unrecognised band label dropped:", lab)
                    continue
                rows.append(dict(year=int(sh), quarter=quarter, band=band,
                                 customer=pd.to_numeric(raw.iat[i, 1], errors="coerce"),
                                 professional=pd.to_numeric(raw.iat[i, 3], errors="coerce"),
                                 combined=pd.to_numeric(raw.iat[i, 5], errors="coerce")))
    df = pd.DataFrame(rows)
    df["period_start"] = [dt.date(y, (q - 1) * 3 + 1, 1) for y, q in zip(df.year, df.quarter)]
    df["period_end"] = [dt.date(y + (q == 4), (q % 4) * 3 + 1, 1) - dt.timedelta(days=1) for y, q in zip(df.year, df.quarter)]
    td = {p: trading_days_between(p[0], p[1], UK_HOLIDAYS) for p in set(zip(df.period_start, df.period_end))}
    df["trading_days"] = [td[(a, b)] for a, b in zip(df.period_start, df.period_end)]
    return df


def parse_weekly(path) -> pd.DataFrame:
    raw = read_any(path, 0)
    col0 = raw[0].astype(str).str.strip()
    hdr = col0[col0 == "Date"].index[0]
    body = raw.iloc[hdr + 1:, :4].copy()
    body.columns = ["week_ending", "customer", "professional", "combined"]
    body["week_ending"] = pd.to_datetime(body["week_ending"], errors="coerce")
    body = body.dropna(subset=["week_ending"])
    for c in ["customer", "professional", "combined"]:
        body[c] = pd.to_numeric(body[c], errors="coerce")
    return body.sort_values("week_ending")


def parse_annual(path) -> pd.DataFrame:
    raw = read_any(path, 0)
    col0 = raw[0].astype(str).str.strip()
    hdr = col0[col0 == "Financial Year"].index[0]
    body = raw.iloc[hdr + 1:, :7].copy()
    body.columns = ["financial_year", "adv_gbp_bn", "annual_turnover_gbp_bn", "gross_portfolio_mv_gbp_bn",
                    "net_portfolio_mv_gbp_bn", "turnover_ratio_gross", "turnover_ratio_net"]
    for c in body.columns[1:]:
        body[c] = pd.to_numeric(body[c], errors="coerce")
    return body.dropna(subset=["adv_gbp_bn"])


# Fallback: DMO Annual Review 2025-26, Table 1 "Aggregate gilt market turnover
# (cash terms) by GEMMs" (GBP bn per financial year; short = 0-7y, medium =
# 7-15y, long = 15y+ conventional gilts; index-linked = total less the three).
# Customer share read off the "Total GEMM market turnover (weekly total)" chart
# of the Quarterly Review April-June 2026 (professional about 1.83 trn against
# customer about 1.26 trn over the 13 weeks): provisional.
ANNUAL_FALLBACK = [  # (financial year, short, medium, long, total)
    ("2000-01", 608, 446, 412, 1531), ("2001-02", 733, 692, 396, 1907), ("2002-03", 784, 822, 460, 2168),
    ("2003-04", 1016, 1071, 599, 2858), ("2004-05", 1120, 1161, 738, 3195), ("2005-06", 1186, 1252, 825, 3500),
    ("2006-07", 1139, 1548, 893, 3856), ("2007-08", 1262, 1399, 877, 3808), ("2008-09", 1389, 1358, 894, 3988),
    ("2009-10", 1754, 1702, 976, 4769), ("2010-11", 1691, 2073, 991, 5240), ("2011-12", 2280, 2753, 1541, 7263),
    ("2012-13", 2308, 2659, 1488, 7213), ("2013-14", 2391, 2555, 1356, 6992), ("2014-15", 1828, 2256, 1485, 6387),
    ("2015-16", 1569, 2084, 1474, 5949), ("2016-17", 1571, 2485, 1745, 6826), ("2017-18", 2048, 2629, 1660, 7777),
    ("2018-19", 2232, 3295, 1923, 9136), ("2019-20", 2231, 3375, 2114, 9491), ("2020-21", 2417, 4275, 2476, 10457),
    ("2021-22", 2409, 3885, 1920, 9600), ("2022-23", 2223, 3365, 1715, 8683), ("2023-24", 3010, 3394, 1969, 9791),
    ("2024-25", 3338, 4422, 1979, 11187), ("2025-26", 3867, 4816, 1822, 12052)]
FALLBACK_CUSTOMER_SHARE = 0.41
FALLBACK_GROUPS = ["0-7y", "7-15y", "15y+"]
FALLBACK_GROUP_MAP = {"0-3y": "0-7y", "3-5y": "0-7y", "5-7y": "0-7y", "7-10y": "7-15y", "10y+": "15y+"}


def build_fallback() -> dict:
    fy, short, medium, long_, total = ANNUAL_FALLBACK[-1]
    y0 = int(fy[:4])
    td = trading_days_between(dt.date(y0, 4, 1), dt.date(y0 + 1, 3, 31), UK_HOLIDAYS)
    cs = FALLBACK_CUSTOMER_SHARE
    comb = {"0-7y": short * 1000 / td, "7-15y": medium * 1000 / td, "15y+": long_ * 1000 / td}
    annual = [dict(financial_year=f, short=s, medium=m, long=l, index_linked=t - s - m - l, total=t)
              for f, s, m, l, t in ANNUAL_FALLBACK]
    return {
        "code": "GBP", "name": "UK gilts", "currency": "GBP", "unit": "GBP mn per trading day",
        "provisional": True,
        "source": "UK DMO Annual Review 2025-26, Table 1 (annual GEMM turnover by maturity segment) and Quarterly Review April-June 2026 (weekly customer/professional chart, read by eye)",
        "source_url": "https://www.dmo.gov.uk/data/gilt-market/turnover-data",
        "origin": "fallback: annual review table; the DMO turnover spreadsheets are not in rawData/dmo_gilts",
        "counting": "customer turnover single-counted; professional turnover (DMO, BoE, GEMMs, IDBs, agency brokers) as reported and may double count via IDBs",
        "maturity_basis": "remaining (DMO segments: short 0-7y, medium 7-15y, long 15y+)",
        "groups": FALLBACK_GROUPS, "group_map": FALLBACK_GROUP_MAP,
        "financial_year": fy, "trading_days_fy": td, "customer_share": cs,
        "window": {"label": f"FY {fy}", "n": 1},
        "segments": {
            "d2c_base": {"key": "d2c", "label": "Customer counterparties (assumed share)", "note": f"combined turnover x assumed customer share {cs:.2f} (read from the Q2 2026 weekly chart); conventional gilts, market value; no on/off-the-run split so d2c_base = d2c_all; DMO maturity segments on remaining maturity"},
            "d2c_all": {"key": "d2c", "label": "Customer counterparties (assumed share)", "note": "same as d2c_base"},
            "d2d": {"key": "d2d", "label": "Professional counterparties (assumed share)", "note": f"combined turnover x (1 - {cs:.2f}); may double count via IDBs"},
            "total": {"key": "total", "label": "Customer + professional", "note": "annual turnover / UK trading days in the financial year"},
        },
        "window_adv": {
            "d2c_base": {g: clean_num(v * cs) for g, v in comb.items()},
            "d2c_all": {g: clean_num(v * cs) for g, v in comb.items()},
            "d2d": {g: clean_num(v * (1 - cs)) for g, v in comb.items()},
            "total": {g: clean_num(v) for g, v in comb.items()},
        },
        "annual": annual,
    }


def build() -> dict | None:
    f_bands = latest_file(FOLDER, r"^gemm-turnover-by-maturity-band.*\.xlsx$")
    if f_bands is None:
        print("DMO: no gemm-turnover-by-maturity-band-*.xlsx in rawData/dmo_gilts; using the annual-review fallback")
        return build_fallback()
    bands = parse_bands(f_bands)
    f_weekly = latest_file(FOLDER, r"^all-gemms-turnover.*\.xlsx?$")
    f_annual = latest_file(FOLDER, r"^annual-turnover-report.*\.xlsx?$")
    weekly = parse_weekly(f_weekly) if f_weekly else None
    annual = parse_annual(f_annual) if f_annual else None

    conv = bands[bands.band.isin(BAND_MAP)].copy()
    conv["bucket"] = conv["band"].map(BAND_MAP)
    for c in ["customer", "professional", "combined"]:
        conv[c + "_adv"] = conv[c] / conv["trading_days"]
    quarters = sorted(set(zip(conv.year, conv.quarter)))
    recent = quarters[-DMO_WINDOW:]
    qlab = [f"{y}Q{q}" for y, q in quarters]
    # quarterly ADV by common bucket
    qb = conv.groupby(["year", "quarter", "bucket"], as_index=False)[["customer_adv", "professional_adv", "combined_adv"]].sum()
    quarterly = {}
    for seg, col in (("d2c", "customer_adv"), ("d2d", "professional_adv"), ("total", "combined_adv")):
        piv = qb.pivot(index=["year", "quarter"], columns="bucket", values=col).reindex(quarters).reindex(columns=COMMON_BUCKETS)
        quarterly[seg] = {b: [clean_num(v) for v in piv[b]] for b in COMMON_BUCKETS}
    # by DMO band (finer) for the detail table
    qd = conv.copy()
    bands_q = {}
    for seg, col in (("d2c", "customer_adv"), ("d2d", "professional_adv"), ("total", "combined_adv")):
        piv = qd.pivot(index=["year", "quarter"], columns="band", values=col).reindex(quarters).reindex(columns=list(BAND_MAP))
        bands_q[seg] = {b: [clean_num(v) for v in piv[b]] for b in BAND_MAP}
    # all bands incl. index-linked and strips, combined ADV
    allb = bands.copy()
    allb["combined_adv"] = allb["combined"] / allb["trading_days"]
    piv = allb.pivot(index=["year", "quarter"], columns="band", values="combined_adv").reindex(quarters).reindex(columns=BAND_LEVELS)
    by_type = {b: [clean_num(v) for v in piv[b]] for b in BAND_LEVELS}
    w = qb[[(y, q) in recent for y, q in zip(qb.year, qb.quarter)]].groupby("bucket")[["customer_adv", "professional_adv", "combined_adv"]].mean()
    window_adv = {
        "d2c_base": {b: clean_num(w.loc[b, "customer_adv"]) for b in COMMON_BUCKETS},
        "d2c_all": {b: clean_num(w.loc[b, "customer_adv"]) for b in COMMON_BUCKETS},
        "d2d": {b: clean_num(w.loc[b, "professional_adv"]) for b in COMMON_BUCKETS},
        "total": {b: clean_num(w.loc[b, "combined_adv"]) for b in COMMON_BUCKETS},
    }
    out = {
        "code": "GBP", "name": "UK gilts", "currency": "GBP", "unit": "GBP mn per trading day",
        "source": "UK DMO, gilt turnover data reported by GEMMs (quarterly by maturity band; weekly aggregate; annual report)",
        "source_url": "https://www.dmo.gov.uk/data/gilt-market/turnover-data",
        "origin": f"{f_bands.name}" + (f", {f_weekly.name}" if f_weekly else "") + (f", {f_annual.name}" if f_annual else ""),
        "counting": "customer turnover single-counted; professional turnover (DMO, BoE, GEMMs, IDBs, agency brokers) as reported and may double count via IDBs",
        "maturity_basis": "remaining",
        "groups": COMMON_BUCKETS, "group_map": dict(zip(COMMON_BUCKETS, COMMON_BUCKETS)),
        "quarters": qlab,
        "trading_days": [int(conv[(conv.year == y) & (conv.quarter == q)].trading_days.iloc[0]) for y, q in quarters],
        "window": {"from": f"{recent[0][0]}Q{recent[0][1]}", "to": f"{recent[-1][0]}Q{recent[-1][1]}", "n": len(recent),
                   "label": f"{recent[0][0]}Q{recent[0][1]} to {recent[-1][0]}Q{recent[-1][1]}"},
        "segments": {
            "d2c_base": {"key": "d2c", "label": "Customer counterparties", "note": "DMO GEMM-reported conventional gilts, market value; customer counterparties only, single-counted; no on/off-the-run split so d2c_base = d2c_all; remaining maturity"},
            "d2c_all": {"key": "d2c", "label": "Customer counterparties", "note": "same as d2c_base"},
            "d2d": {"key": "d2d", "label": "Professional counterparties", "note": "DMO, Bank of England, other GEMMs, IDBs and agency brokers; may double count via IDBs"},
            "total": {"key": "total", "label": "Customer + professional", "note": "as reported; professional leg may double count via IDBs"},
        },
        "window_adv": window_adv,
        "quarterly_adv": quarterly,
        "bands": list(BAND_MAP), "band_map": BAND_MAP, "quarterly_adv_bands": bands_q,
        "all_bands": BAND_LEVELS, "quarterly_combined_adv_all_bands": by_type,
    }
    if weekly is not None:
        out["weekly"] = {"week_ending": [d.date().isoformat() for d in weekly.week_ending],
                         "customer": [clean_num(v) for v in weekly.customer],
                         "professional": [clean_num(v) for v in weekly.professional],
                         "combined": [clean_num(v) for v in weekly.combined]}
    if annual is not None:
        out["annual"] = annual.to_dict(orient="records")
    return out


if __name__ == "__main__":
    d = build()
    if d:
        print(d["window"], d["window_adv"])
