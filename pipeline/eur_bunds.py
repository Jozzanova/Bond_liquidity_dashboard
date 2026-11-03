"""Deutsche Finanzagentur annual trading volumes (EUR, Bunds) and the scaled
French OAT level. Port of eur_bund_turnover.R.

Source: https://www.deutsche-finanzagentur.de/en/federal-securities/trading/secondary-market/trading-volumes/year
Gross = sales plus purchases reported by a representative subset of Bund Issues
Auction Group banks; instruments classified by ORIGINAL maturity; "Broker" =
interdealer-like counterparties. Customer-facing legs are reported once and
used as reported; broker legs are reported by both banks and halved.
"""
from __future__ import annotations

import datetime as dt
import io
import re
import sys

import lxml.html
import requests

from common import COMMON_BUCKETS, EUR_FR_SCALE, EUR_TRADING_DAYS, FR_REFERENCE_NOTE, FR_REFERENCE_TOTAL_MN, RAW, clean_num

URL = "https://www.deutsche-finanzagentur.de/en/federal-securities/trading/secondary-market/trading-volumes/year"
FOLDER = RAW / "eur_bunds"
INSTR_MAP = {"Schatz": "0-5y", "Bobl": "0-5y", "Bund7": "5-10y", "Bund10": "5-10y", "Bund15": "10y+", "Bund30": "10y+"}
GROUPS = ["0-5y", "5-10y", "10y+"]
GROUP_MAP = dict(zip(COMMON_BUCKETS, ["0-5y", "0-5y", "5-10y", "5-10y", "10y+"]))

# Embedded fallback (typed from the page, retrieved 2026-08-25)
FALLBACK = {
    "instruments": {2024: dict(Bobl=1402, Bubill=628, Bund7=260, Bund10=2474, Bund15=196, Bund30=641, Green=117, ILB=58, Schatz=962),
                    2025: dict(Bobl=1389, Bubill=501, Bund7=224, Bund10=2714, Bund15=220, Bund30=785, Green=112, ILB=41, Schatz=1100)},
    "counterparties": {2024: {"Asset Manager": 1635, "Banks": 1283, "Broker": 1754, "Hedge funds": 1214, "Pension funds": 93, "Others": 69, "Insurances": 46, "Central Banks": 644},
                       2025: {"Asset Manager": 1595, "Banks": 1261, "Broker": 2137, "Hedge funds": 1159, "Pension funds": 120, "Others": 66, "Insurances": 49, "Central Banks": 725}},
    "totals": {2024: 6738, 2025: 7113},
}


def parse_number(s: str):
    """Integers with inconsistent separators ('1,067', '1.188', '1;159', '-0')."""
    s = re.sub(r"[^0-9.,;-]", "", str(s).strip())
    s = re.sub(r"[;,]", "", s)
    if re.match(r"^-?\d{1,3}\.\d{3}$", s):
        s = s.replace(".", "")
    try:
        return float(s)
    except ValueError:
        return None


def table_rows(tab):
    rows = []
    for tr in tab.iter("tr"):
        cells = [c.text_content().strip() for c in tr if c.tag in ("td", "th")]
        if cells:
            rows.append(cells)
    return rows


def parse_html(html: str) -> dict:
    doc = lxml.html.fromstring(html)
    out = {"instruments": {}, "counterparties": {}, "totals": {}}
    found = {"instruments": 0, "counterparties": 0, "totals": 0}
    for tab in doc.iter("table"):
        rows = table_rows(tab)
        if len(rows) < 2:
            continue
        head = [h.lower() for h in rows[0]]
        years = [int(y) for y in rows[0][1:] if re.match(r"^\d{4}$", y.strip())]
        if not years:
            continue
        first_col = " ".join(r[0].lower() for r in rows[1:])
        body = rows[1:]
        if "gross" in head[0] and "schatz" in first_col:
            key = "instruments"
        elif "gross" in head[0] and "broker" in first_col:
            key = "counterparties"
        elif "trading volume" in first_col and "net trading" in first_col:
            key = "totals"
        else:
            continue
        found[key] += 1
        for r in body:
            for y, v in zip(years, r[1:]):
                val = parse_number(v)
                if key == "totals":
                    if "gross" in r[0].lower():
                        out["totals"][y] = val
                else:
                    out[key].setdefault(y, {})[r[0].strip()] = val
    if any(n != 1 for n in found.values()):
        raise ValueError(f"Finanzagentur page layout not recognised: {found}")
    # sanity: instrument sums within 5 % of reported totals
    for y, tot in out["totals"].items():
        s = sum(v for v in out["instruments"].get(y, {}).values() if v is not None)
        if tot and abs(s / tot - 1) > 0.05:
            print(f"EUR: WARNING instrument sum {s} differs from total {tot} in {y}")
    return out


def fetch(refresh=False):
    FOLDER.mkdir(parents=True, exist_ok=True)
    if refresh:
        r = requests.get(URL, timeout=60, headers={"User-Agent": "Mozilla/5.0"})
        r.raise_for_status()
        f = FOLDER / f"finanzagentur_{dt.date.today():%Y%m%d}.html"
        f.write_text(r.text, encoding="utf-8")
        print("EUR: page saved to", f.name)
    snaps = sorted(FOLDER.glob("finanzagentur_*.html"))
    if snaps:
        try:
            return parse_html(snaps[-1].read_text(encoding="utf-8")), f"snapshot {snaps[-1].name}"
        except Exception as e:  # noqa: BLE001
            print("EUR: snapshot parse failed:", e)
    return FALLBACK, "embedded fallback (2024, 2025)"


def build(refresh=False) -> dict:
    data, origin = fetch(refresh)
    years = sorted(data["instruments"])
    year = years[-1]
    inst = data["instruments"][year]
    cp = data["counterparties"][year]
    broker_share = cp["Broker"] / sum(v for v in cp.values() if v is not None)
    cust_share = 1 - broker_share
    rows = []
    for name, grp in INSTR_MAP.items():
        g = inst[name]
        customer = g * cust_share
        broker = g * broker_share
        rows.append(dict(instrument=name, group=grp, gross_eur_bn=g,
                         customer_bn=customer, broker_bn=broker, d2d_single_bn=0.5 * broker,
                         total_single_bn=customer + 0.5 * broker,
                         d2c_adv_mn=customer * 1000 / EUR_TRADING_DAYS,
                         d2d_adv_mn=0.5 * broker * 1000 / EUR_TRADING_DAYS,
                         total_adv_mn=(customer + 0.5 * broker) * 1000 / EUR_TRADING_DAYS))
    by_group = {g: {"d2c": 0.0, "d2d": 0.0, "total": 0.0} for g in GROUPS}
    for r in rows:
        by_group[r["group"]]["d2c"] += r["d2c_adv_mn"]
        by_group[r["group"]]["d2d"] += r["d2d_adv_mn"]
        by_group[r["group"]]["total"] += r["total_adv_mn"]
    window_adv = {
        "d2c_base": {g: clean_num(v["d2c"]) for g, v in by_group.items()},
        "d2c_all": {g: clean_num(v["d2c"]) for g, v in by_group.items()},
        "d2d": {g: clean_num(v["d2d"]) for g, v in by_group.items()},
        "total": {g: clean_num(v["total"]) for g, v in by_group.items()},
    }
    # Annual series (all years on the page) for the chart
    annual = []
    for y in years:
        cpy = data["counterparties"].get(y, {})
        bs = cpy.get("Broker", 0) / sum(v for v in cpy.values() if v is not None) if cpy else None
        iy = data["instruments"][y]
        mlt = sum(iy[k] for k in INSTR_MAP)
        annual.append(dict(year=y, gross_total_bn=data["totals"].get(y), gross_mlt_bn=mlt,
                           broker_share=clean_num(bs),
                           instruments={k: iy.get(k) for k in iy},
                           counterparties=cpy,
                           d2c_adv_mn=clean_num(mlt * (1 - bs) * 1000 / EUR_TRADING_DAYS) if bs is not None else None,
                           d2d_adv_mn=clean_num(mlt * bs * 0.5 * 1000 / EUR_TRADING_DAYS) if bs is not None else None,
                           total_adv_mn=clean_num(mlt * (1 - 0.5 * bs) * 1000 / EUR_TRADING_DAYS) if bs is not None else None))
    de = {
        "code": "EUR-DE", "name": "German Bunds", "currency": "EUR", "unit": "EUR mn per trading day",
        "source": "Deutsche Finanzagentur, trading volumes (annual, by instrument and counterparty)",
        "source_url": URL, "origin": origin,
        "counting": "customer-facing legs reported once by the bank (used as reported); broker legs reported by both banks (halved)",
        "maturity_basis": "original",
        "groups": GROUPS, "group_map": GROUP_MAP,
        "year": year, "trading_days": EUR_TRADING_DAYS,
        "broker_share": clean_num(broker_share), "customer_share": clean_num(cust_share),
        "window": {"label": str(year), "n": 1},
        "segments": {
            "d2c_base": {"key": "d2c_base", "label": "Customer-facing (non-broker) legs", "note": "gross x (1 - broker share), single-counted as reported; no on/off-the-run split so d2c_base = d2c_all; subset of auction-group banks; uniform counterparty mix across instruments assumed"},
            "d2c_all": {"key": "d2c_all", "label": "Customer-facing (non-broker) legs", "note": "same as d2c_base"},
            "d2d": {"key": "d2d", "label": "Broker legs, halved", "note": "gross x broker share x 0.5 (both banks report the same interdealer trade)"},
            "total": {"key": "total", "label": "Customer + 0.5 x broker legs", "note": "single-counted total of the reporting banks' turnover"},
        },
        "window_adv": window_adv,
        "instruments": rows,
        "annual": annual,
        "counterparties_latest": cp,
        "instruments_latest": inst,
    }
    # Instruments outside the maturity groups (gross, latest year): amounts shown on the page
    gross_all = sum(inst.values())
    de["excluded_latest"] = {k: {"gross_bn": inst[k], "per_day_mn": clean_num(inst[k] * 1000 / EUR_TRADING_DAYS), "share_of_gross": clean_num(inst[k] / gross_all)}
                             for k in ("Bubill", "ILB", "Green") if k in inst}
    de["gross_all_bn"] = gross_all
    de["gross_ex_bubill_per_day_mn"] = clean_num((gross_all - inst.get("Bubill", 0)) * 1000 / EUR_TRADING_DAYS)
    # France: scaled Bund level, one group covering 0-10y (benchmark universe)
    d2c_010 = sum(v["d2c"] for g, v in by_group.items() if g != "10y+") * EUR_FR_SCALE
    d2d_010 = sum(v["d2d"] for g, v in by_group.items() if g != "10y+") * EUR_FR_SCALE
    tot_010 = sum(v["total"] for g, v in by_group.items() if g != "10y+") * EUR_FR_SCALE
    fr = {
        "code": "EUR-FR", "name": "French OATs", "currency": "EUR", "unit": "EUR mn per trading day",
        "source": "Derived: German Bund level (Finanzagentur, 0-10y) x OAT/Bund scale",
        "source_url": "https://www.aft.gouv.fr/en/bulletins-mensuels", "origin": "scaled from EUR-DE",
        "counting": "as for EUR-DE", "maturity_basis": "none (one group)",
        "groups": ["all"], "group_map": {b: "all" for b in COMMON_BUCKETS},
        "scale": EUR_FR_SCALE, "year": year,
        "de_010_d2c_mn": clean_num(d2c_010 / EUR_FR_SCALE), "de_010_total_mn": clean_num(tot_010 / EUR_FR_SCALE),
        "reference": {"total_mn": FR_REFERENCE_TOTAL_MN, "note": FR_REFERENCE_NOTE,
                      "de_like_for_like_mn": de["gross_ex_bubill_per_day_mn"],
                      "implied_scale": clean_num(FR_REFERENCE_TOTAL_MN / de["gross_ex_bubill_per_day_mn"]),
                      "d2c_at_implied_scale_mn": clean_num(d2c_010 / EUR_FR_SCALE * FR_REFERENCE_TOTAL_MN / de["gross_ex_bubill_per_day_mn"])},
        "window": {"label": str(year), "n": 1},
        "segments": {
            "d2c_base": {"key": "d2c_base", "label": "Customer-facing level, scaled", "note": f"EUR-DE customer-facing 0-10y level x {EUR_FR_SCALE}; no French turnover data by maturity or counterparty"},
            "d2c_all": {"key": "d2c_all", "label": "Customer-facing level, scaled", "note": "same as d2c_base"},
            "d2d": {"key": "d2d", "label": "Broker legs, halved, scaled", "note": f"EUR-DE broker legs x 0.5 x {EUR_FR_SCALE}"},
            "total": {"key": "total", "label": "Total, scaled", "note": f"EUR-DE total 0-10y level x {EUR_FR_SCALE}"},
        },
        "window_adv": {"d2c_base": {"all": clean_num(d2c_010)}, "d2c_all": {"all": clean_num(d2c_010)},
                       "d2d": {"all": clean_num(d2d_010)}, "total": {"all": clean_num(tot_010)}},
    }
    return de, fr


if __name__ == "__main__":
    de, fr = build("--refresh" in sys.argv)
    print(de["origin"], de["year"], de["window_adv"])
    print(fr["window_adv"])
