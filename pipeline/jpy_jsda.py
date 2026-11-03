"""JSDA OTC bond trading volume (JPY, JGBs). Port of jpy_jsda_turnover.R.

Source: https://www.jsda.or.jp/shiryoshitsu/toukei/tentoubaibai/koushasai.xlsx (current FY)
        https://www.jsda.or.jp/shiryoshitsu/toukei/tentoubaibai/koushasaiYYYY.xlsx (FY YYYY)
Sheet "(B) 一般売買高" = outright transactions only, all JSDA members, sell +
purchase, face value, JPY 100 mn. JGB columns by ORIGINAL maturity: super-long
(>10y), long (6y, 10y), medium (2y, 4y, 5y), zero-coupon, T-bills.
Members report their own legs: customer trades appear once, member-to-member
("Bond Dealers") trades twice.
"""
from __future__ import annotations

import datetime as dt
import sys

import pandas as pd
import requests

from common import COMMON_BUCKETS, JP_HOLIDAYS, JPY_INCLUDE_OTHERS, JPY_WINDOW, RAW, clean_num, month_end, trading_days_between

FOLDER = RAW / "jpy_jsda"
BASE = "https://www.jsda.or.jp/shiryoshitsu/toukei/tentoubaibai/"
CLASSES = ["super_long", "long", "medium", "zero_coupon", "tbills"]
CLASS_MAP = {"medium": "0-5y", "long": "5-10y", "super_long": "10y+"}
GROUPS = ["0-5y", "5-10y", "10y+"]
GROUP_MAP = dict(zip(COMMON_BUCKETS, ["0-5y", "0-5y", "5-10y", "5-10y", "10y+"]))


def download(refresh=False):
    FOLDER.mkdir(parents=True, exist_ok=True)
    names = ["koushasai.xlsx"] + [f"koushasai{y}.xlsx" for y in range(dt.date.today().year - 1, 2022, -1)]
    for n in names:
        f = FOLDER / n
        if f.exists() and not (refresh and n == "koushasai.xlsx"):
            continue
        r = requests.get(BASE + n, timeout=120, headers={"User-Agent": "Mozilla/5.0"})
        if r.status_code == 200 and r.content[:2] == b"PK":
            f.write_bytes(r.content)
            print("JPY: downloaded", n)
        else:
            print("JPY:", n, "status", r.status_code)


def parse_file(path):
    x = pd.ExcelFile(path)
    sh = [s for s in x.sheet_names if "一般売買高" in s and "証券" not in s][0]
    raw = pd.read_excel(path, sheet_name=sh, header=None)
    hdr4 = " | ".join(str(v).lower() for v in raw.iloc[3, 4:9])
    if not all(k in hdr4 for k in ("over 10-year", "medium-term", "treasury discount")):
        raise ValueError(f"JGB column layout changed in {path.name}: {hdr4}")
    body = raw.iloc[4:, [0, 2, 3, 4, 5, 6, 7, 8]].copy()
    body.columns = ["month_lab", "category", "jgb_total"] + CLASSES
    body = body.dropna(subset=["month_lab", "category"])
    body["category"] = body["category"].astype(str).str.strip()
    body = body[~body["category"].str.contains("previous|comparison|change", case=False)]   # month-on-month rows
    body["month"] = pd.to_datetime(body["month_lab"].astype(str).str.replace("/", "-") + "-01", errors="coerce")
    body = body.dropna(subset=["month"])
    for c in ["jgb_total"] + CLASSES:
        body[c] = pd.to_numeric(body[c], errors="coerce")
    body["source_file"] = path.name
    return body


def load():
    files = sorted(FOLDER.glob("koushasai*.xlsx"))
    if not files:
        sys.exit("JPY: no koushasai*.xlsx in rawData/jpy_jsda")
    df = pd.concat([parse_file(f) for f in files], ignore_index=True)
    df = df.drop_duplicates(subset=["month", "category"], keep="last")
    chk = (df[CLASSES].sum(axis=1) - df["jgb_total"]).abs()
    if (chk > 5).any():
        print(f"JPY: WARNING JGB sub-columns do not sum to total for {(chk > 5).sum()} rows")
    return df


def build(df) -> dict:
    cats = {"Total": "total_reported", "Bond Dealers": "dealers", "Others": "others"}
    sub = df[df.category.isin(cats)].copy()
    sub["cat"] = sub["category"].map(cats)
    months = sorted(sub["month"].dt.date.unique())
    td = {m: trading_days_between(m, month_end(m), JP_HOLIDAYS) for m in months}
    seg = {}   # (month, class) -> dict
    for cls in CLASSES:
        piv = sub.pivot(index="month", columns="cat", values=cls) * 100   # JPY mn
        for m, r in piv.iterrows():
            md = m.date()
            customer = r["total_reported"] - r["dealers"] - r["others"]
            if JPY_INCLUDE_OTHERS:
                customer += r["others"]
            d2d = 0.5 * r["dealers"]
            seg[(md, cls)] = dict(customer=customer, dealers=r["dealers"], others=r["others"],
                                  d2c_adv=customer / td[md], d2d_adv=d2d / td[md],
                                  total_adv=(customer + d2d) / td[md])
    recent = months[-JPY_WINDOW:]
    monthly = {k: {cls: [clean_num(seg[(m, cls)][f"{k}_adv"]) for m in months] for cls in CLASSES}
               for k in ("d2c", "d2d", "total")}
    window = {}
    for k in ("d2c", "d2d", "total"):
        window[k] = {}
        for cls, grp in CLASS_MAP.items():
            vals = [seg[(m, cls)][f"{k}_adv"] for m in recent]
            window[k][grp] = clean_num(sum(vals) / len(vals))
    # Investor-category breakdown of JGB outright volume, latest window (face value, JPY bn per month avg)
    inv = df[df.month.dt.date.isin(recent)].groupby("category")[["jgb_total"] + CLASSES].mean() * 100 / 1000
    inv = inv.drop(index=[c for c in ["Total"] if c in inv.index])
    investors = {c: {k: clean_num(v) for k, v in row.items()} for c, row in inv.iterrows()}
    return {
        "code": "JPY", "name": "Japanese government bonds", "currency": "JPY", "unit": "JPY mn per trading day",
        "source": "JSDA, Trading Volume of OTC Bonds (sheet B, outright transactions, all members)",
        "source_url": "https://www.jsda.or.jp/en/statistics/bonds/index.html",
        "counting": "members report their own legs: customer trades appear once, member-to-member (Bond Dealers) trades twice and are halved",
        "maturity_basis": "original",
        "groups": GROUPS, "group_map": GROUP_MAP,
        "months": [m.isoformat() for m in months],
        "trading_days": [td[m] for m in months],
        "window": {"from": recent[0].isoformat(), "to": recent[-1].isoformat(), "n": len(recent), "label": f"{recent[0]:%b %Y} to {recent[-1]:%b %Y}"},
        "include_others": JPY_INCLUDE_OTHERS,
        "classes": CLASSES, "class_map": CLASS_MAP,
        "segments": {
            "d2c_base": {"key": "d2c", "label": "Customer (Total less Bond Dealers less Others)", "note": "JSDA OTC outright JGBs, face value, all members; single-counted as reported; no on/off-the-run split so d2c_base = d2c_all; groups by original maturity class"},
            "d2c_all": {"key": "d2c", "label": "Customer", "note": "same as d2c_base"},
            "d2d": {"key": "d2d", "label": "Bond Dealers, halved", "note": "member-to-member trades are reported by both members"},
            "total": {"key": "total", "label": "Customer + 0.5 x Bond Dealers", "note": "Others (incl. members' auction allotments) excluded"},
        },
        "window_adv": {"d2c_base": window["d2c"], "d2c_all": window["d2c"], "d2d": window["d2d"], "total": window["total"]},
        "monthly_adv": monthly,          # {d2c/d2d/total: {class: [by month]}}
        "investors_window_bn_per_month": investors,
    }


if __name__ == "__main__":
    if "--refresh" in sys.argv:
        download(True)
    d = build(load())
    print(d["window"], d["window_adv"])
