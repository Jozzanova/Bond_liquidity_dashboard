"""Write the structured datasets behind the dashboard as CSV files into
site/data/, plus the full JSON and a plain-text data dictionary. Called by
build.py; returns the manifest that the Notes tab renders as a Downloads block.

Every dataset is an Excel workbook with a "Wide" sheet where the data are a
series table (one row per period or market, one column per series), a "Data"
sheet (tidy: one observation per row) and an "About" sheet (title,
description, source, counting convention, column dictionary). A combined workbook holds every
dataset with an index sheet. Amounts are in local currency millions unless
the column name says otherwise. Empty cells mean "not available".
"""
from __future__ import annotations

import json
from pathlib import Path

from openpyxl import Workbook
from openpyxl.styles import Alignment, Font
from openpyxl.utils import get_column_letter

COLDESC = {
    "market": "market code (USD, GBP, EUR-DE, EUR-FR, JPY, CNY)", "market_name": "market name", "currency": "currency of the amounts",
    "window": "averaging window of the source", "segment": "liquidity segment: d2c_base, d2c_all, d2d, total (or d2c / d2d / total / combined in source files)",
    "segment_description": "segment in words", "maturity_group": "maturity group used in the profile", "issue": "all, on_the_run or off_the_run (USD only)",
    "adv_local_mn_per_day": "average daily volume, local currency millions per trading day", "adv_eur_mn_per_day": "the same converted to EUR millions at the ECB rates",
    "month": "first day of the month", "quarter": "calendar quarter", "trading_days": "trading days in the period on the market's calendar",
    "trading_days_implied": "monthly volume divided by the reported average daily turnover", "adv_usd_mn_per_day": "average daily volume, USD millions",
    "adv_gbp_mn_per_day": "average daily turnover, GBP millions, market value", "adv_jpy_mn_per_day": "average daily volume, JPY millions, face value",
    "trace_bucket": "remaining-maturity bucket as published by FINRA", "common_group": "the common maturity group the bucket or band maps to",
    "security_type": "All, Bills, FRNs, Nominal Coupons or TIPS", "coupon_trades_per_month": "number of trades in nominal coupons in the month",
    "maturity_band": "DMO remaining-maturity band (Index-linked and Strips have no band)", "week_ending": "Friday ending the week",
    "customer_gbp_mn": "turnover with customer counterparties, GBP millions, whole week", "professional_gbp_mn": "turnover with professional counterparties (DMO, BoE, GEMMs, IDBs, agency brokers), whole week",
    "combined_gbp_mn": "customer plus professional, whole week", "financial_year": "UK financial year (April to March)",
    "year": "calendar year", "kind": "instrument, counterparty or summary row", "name": "instrument, counterparty type or summary item", "value_eur_bn": "gross trading volume, EUR billions (share for broker_share)",
    "item": "parameter name", "value": "value", "note": "what the parameter is", "jgb_class": "JSDA class by original maturity: super_long, long, medium, zero_coupon, tbills",
    "profile_group": "profile maturity group the class maps to (empty = not used)", "investor_category": "JSDA investor category",
    "volume_rmb_bn": "monthly Northbound trading volume, RMB billions, all bonds", "adt_rmb_bn": "average daily turnover, RMB billions, all bonds",
    "cgb_share_stated": "share of CGBs in volume where the report states it", "cgb_share_used": "share used (weighted mean of stated months where missing)",
    "cgb_adt_rmb_bn": "CGB part of the average daily turnover", "source_file": "Flash Report page the row comes from",
    "cgb_mn": "cash settlement of Chinese government bonds in the month, RMB millions, face value", "all_mn": "cash settlement of all CCDC-registered bonds",
    "pbb_mn": "policy bank bonds", "lgb_mn": "local government bonds", "foreign_mn": "foreign investors' own-side cash settlement, all CCDC bonds",
    "inv_total_mn": "total of the investor-type table (counts both sides)", "cgb_adv_mn": "CGB settlement per trading day", "all_adv_mn": "all CCDC bonds per trading day",
    "cgb_share": "CGBs as a share of all CCDC cash settlement", "foreign_adv_mn": "foreign investors per trading day", "foreign_share": "foreign investors' share of the market by side",
    "double_count_ok": "TRUE when the investor-type total equals twice the bond-type total",
    "as_of": "date the outstanding amounts refer to", "bucket": "remaining-maturity bucket", "share": "share of the market's nominal outstanding in the bucket", "amount_bn": "nominal outstanding in the bucket, billions of the unit column", "unit": "unit of amount_bn", "source": "source of the figures", "universe": "which securities are counted", "units_per_eur": "units of the currency per euro", "date": "rate date",
}


def _sheet_name(s: str) -> str:
    s = s.replace(".xlsx", "")
    return s[:31]


def _data_sheet(ws, header, rows):
    ws.append(header)
    for c in ws[1]:
        c.font = Font(bold=True)
        c.alignment = Alignment(vertical="top", wrap_text=True)
    for r in rows:
        ws.append(list(r))
    ws.freeze_panes = "A2"
    for i, h in enumerate(header, 1):
        lens = [len(str(r[i - 1])) for r in rows[:200] if r[i - 1] is not None]
        width = max([len(str(h))] + lens)
        ws.column_dimensions[get_column_letter(i)].width = min(max(10, width + 2), 48)


def _about_sheet(ws, meta, header, generated):
    ws.column_dimensions["A"].width = 22
    ws.column_dimensions["B"].width = 110

    def row(k, v, bold=False):
        ws.append([k, v])
        ws.cell(ws.max_row, 1).font = Font(bold=True)
        ws.cell(ws.max_row, 2).alignment = Alignment(wrap_text=True, vertical="top")
        if bold:
            ws.cell(ws.max_row, 2).font = Font(bold=True)
    row("Dataset", meta["title"], True)
    row("Description", meta["description"])
    row("Source", meta["source"])
    if meta.get("source_url"):
        row("Source URL", meta["source_url"])
        ws.cell(ws.max_row, 2).hyperlink = meta["source_url"]
        ws.cell(ws.max_row, 2).font = Font(color="0563C1", underline="single")
    row("Counting / notes", meta["notes"])
    if meta.get("wide"):
        row("Sheets", meta["wide"])
    row("Units", "local currency millions unless the column name says otherwise; empty cells = not available")
    row("Pipeline run", generated)
    row("Page", "https://bond-liquidity.jskjeltorp.workers.dev (Notes & sources tab)")
    if header:
        ws.append([])
        ws.append(["Column", "Meaning"])
        ws.cell(ws.max_row, 1).font = Font(bold=True)
        ws.cell(ws.max_row, 2).font = Font(bold=True)
        for h in header:
            d = COLDESC.get(h)
            if d is None and h.endswith("_bn_per_month"):
                d = f"average monthly volume, JPY billions, {h[:-13].replace('_', ' ')}"
            ws.append([h, d or h])
            ws.cell(ws.max_row, 2).alignment = Alignment(wrap_text=True, vertical="top")

SEG_LONG = {"d2c_base": "dealer-to-customer, conservative definition", "d2c_all": "dealer-to-customer, all issues",
            "d2d": "dealer-to-dealer (as reported by the source)", "total": "total (as reported by the source)",
            "d2c": "dealer-to-customer", "combined": "customer + professional"}


_GENERATED = ""

# wide layouts: index columns stay as rows, the "columns" keys are spread across the sheet, one block per value column
WIDE = {
    "window_adv": dict(index=["market", "market_name", "currency", "window", "issue", "maturity_group"], columns=["segment"], values=["adv_local_mn_per_day", "adv_eur_mn_per_day"]),
    "usd_trace_monthly": dict(index=["month", "trading_days"], columns=["segment", "issue", "maturity_group"], values=["adv_usd_mn_per_day"]),
    "usd_trace_monthly_trace_buckets": dict(index=["month", "trading_days"], columns=["segment", "issue", "trace_bucket"], values=["adv_usd_mn_per_day"]),
    "usd_trace_monthly_by_type": dict(index=["month", "trading_days"], columns=["security_type", "segment"], values=["adv_usd_mn_per_day", "coupon_trades_per_month"]),
    "gbp_dmo_quarterly_bands": dict(index=["quarter", "trading_days"], columns=["segment", "maturity_band"], values=["adv_gbp_mn_per_day"]),
    "eur_de_finanzagentur_annual": dict(index=["year"], columns=["kind", "name"], values=["value_eur_bn"]),
    "jpy_jsda_monthly": dict(index=["month", "trading_days"], columns=["segment", "jgb_class"], values=["adv_jpy_mn_per_day"]),
    "maturity_profile": dict(index=["market", "market_name", "as_of", "unit"], columns=["bucket"], values=["share", "amount_bn"]),
}


def _widen(header: list[str], rows: list[list], spec: dict):
    """Pivot the long rows: one row per distinct index tuple (first-appearance order), one column per value x column-key
    combination (first-appearance order). Returns (header, rows)."""
    pos = {h: i for i, h in enumerate(header)}
    idx_i = [pos[k] for k in spec["index"]]
    col_i = [pos[k] for k in spec["columns"]]
    val_i = [pos[k] for k in spec["values"]]
    keys, cols, table = [], [], {}
    for r in rows:
        k = tuple(r[i] for i in idx_i)
        c = tuple(r[i] for i in col_i)
        if k not in table:
            table[k] = {}
            keys.append(k)
        if c not in cols:
            cols.append(c)
        for v in val_i:
            table[k][(header[v], c)] = r[v]
    multi = len(spec["values"]) > 1
    out_header = list(spec["index"])
    series = []
    for v in spec["values"]:
        for c in cols:
            label = " | ".join(str(x) for x in c)
            out_header.append(f"{v}: {label}" if multi else label)
            series.append((v, c))
    out_rows = [list(k) + [table[k].get(sc) for sc in series] for k in keys]
    return out_header, out_rows


def _write(path: Path, header: list[str], rows: list[list], manifest: list, meta: dict):
    path = path.with_suffix(".xlsx")
    wb = Workbook()
    ws = wb.active
    spec = WIDE.get(path.stem)
    if spec:
        ws.title = "Wide"
        wh, wr = _widen(header, rows, spec)
        _data_sheet(ws, wh, wr)
        ws.freeze_panes = get_column_letter(len(spec["index"]) + 1) + "2"
        _data_sheet(wb.create_sheet("Data"), header, rows)
        meta = dict(meta, wide=f"Wide sheet: one row per {' / '.join(spec['index'][:1])}, one column per {' | '.join(spec['columns'])}"
                              + (f", in blocks for {', '.join(spec['values'])}" if len(spec["values"]) > 1 else f" ({spec['values'][0]})") + ". Data sheet: the same in long form, one observation per row.")
    else:
        ws.title = "Data"
        _data_sheet(ws, header, rows)
    _about_sheet(wb.create_sheet("About"), meta, header, _GENERATED)
    wb.save(path)
    manifest.append(dict(file=path.name, rows=len(rows), bytes=path.stat().st_size, columns=header, _header=header, _rows=rows, **meta))


def export(data: dict, out_dir: Path) -> list[dict]:
    global _GENERATED
    _GENERATED = data["generated"]
    out_dir.mkdir(parents=True, exist_ok=True)
    for old in list(out_dir.glob("*.csv")) + list(out_dir.glob("*.xlsx")):
        old.unlink()
    M = data["markets"]
    fx = data["fx"]["per_eur"]
    man: list[dict] = []

    # ---- 1. window averages used in the profile ----
    rows = []
    for code, m in M.items():
        eur_per_unit = 1 / fx[m["currency"]]
        for seg, groups in m["window_adv"].items():
            for g, v in groups.items():
                rows.append([code, m["name"], m["currency"], m["window"]["label"], seg, SEG_LONG[seg], g, "all", v, None if v is None else round(v * eur_per_unit, 3)])
        for seg, groups in (m.get("window_adv_detail") or {}).items():
            base_seg, issue = seg.rsplit("_", 1)
            if issue == "all":
                continue
            for g, v in groups.items():
                rows.append([code, m["name"], m["currency"], m["window"]["label"], base_seg, SEG_LONG.get(base_seg, base_seg), g, issue + "_the_run", v, None if v is None else round(v * eur_per_unit, 3)])
    _write(out_dir / "window_adv.csv",
           ["market", "market_name", "currency", "window", "segment", "segment_description", "maturity_group", "issue", "adv_local_mn_per_day", "adv_eur_mn_per_day"],
           rows, man, dict(
               title="Window averages used in the liquidity profile",
               description="Average daily turnover per maturity group and segment for every market, over each source's latest window. This is the table the profile calculation starts from. The USD rows with issue on_the_run / off_the_run are the TRACE split used when the on-the-run share is set; d2c_base for USD is off-the-run only. EUR conversion uses the ECB reference rates listed on this tab.",
               source="all pipeline sources (see the conventions table on the Notes tab)",
               notes="Segments and counting follow each source; the d2d and total columns are not comparable across markets. Maturity groups are the common buckets for USD and GBP, original-maturity classes for Bunds and JGBs, and a single group for OATs and CGBs."))

    # ---- 2. USD TRACE monthly ----
    u = M["USD"]
    rows, rows_b, rows_t = [], [], []
    for key, groups in u["monthly_adv"].items():
        seg, issue = key.rsplit("_", 1)
        for g, series in groups.items():
            for i, mo in enumerate(u["months"]):
                rows.append([mo, u["trading_days"][i], seg, issue, g, series[i]])
    for key, groups in u["monthly_adv_trace_buckets"].items():
        seg, issue = key.rsplit("_", 1)
        for b, series in groups.items():
            for i, mo in enumerate(u["months"]):
                rows_b.append([mo, u["trading_days"][i], seg, issue, b, u["trace_bucket_map"].get(b), series[i]])
    for typ, segs in u["by_type_adv"].items():
        for seg, series in segs.items():
            for i, mo in enumerate(u["months"]):
                rows_t.append([mo, u["trading_days"][i], typ, seg, series[i], u["coupon_trades_per_month"][seg][i] if typ == "Nominal Coupons" else None])
    _write(out_dir / "usd_trace_monthly.csv", ["month", "trading_days", "segment", "issue", "maturity_group", "adv_usd_mn_per_day"], rows, man, dict(
        title="US Treasuries: TRACE monthly average daily volume by common maturity bucket",
        description="Nominal coupon Treasuries, remaining maturity mapped from the TRACE buckets to the five common groups. segment d2c = dealer-to-customer, d2d = dealer-to-dealer (incl. ATS), total = both; issue = all, on (on-the-run) or off (off-the-run).",
        source=u["source"], source_url=u["source_url"], notes=u["counting"]))
    _write(out_dir / "usd_trace_monthly_trace_buckets.csv", ["month", "trading_days", "segment", "issue", "trace_bucket", "common_group", "adv_usd_mn_per_day"], rows_b, man, dict(
        title="US Treasuries: TRACE monthly average daily volume by original TRACE bucket",
        description="Same as the previous file but on the seven remaining-maturity buckets as published by FINRA, before mapping to the common groups.",
        source=u["source"], source_url=u["source_url"], notes=u["counting"]))
    _write(out_dir / "usd_trace_monthly_by_type.csv", ["month", "trading_days", "security_type", "segment", "adv_usd_mn_per_day", "coupon_trades_per_month"], rows_t, man, dict(
        title="US Treasuries: TRACE monthly average daily volume by security type",
        description="All Treasuries, Bills, FRNs, Nominal Coupons and TIPS, all maturities; the number of trades is given for nominal coupons.",
        source=u["source"], source_url=u["source_url"], notes=u["counting"]))

    # ---- 3. GBP DMO ----
    g = M["GBP"]
    rows = []
    for seg, bands in g["quarterly_adv_bands"].items():
        for b, series in bands.items():
            for i, q in enumerate(g["quarters"]):
                rows.append([q, g["trading_days"][i], seg, b, g["band_map"].get(b), series[i]])
    for b, series in g["quarterly_combined_adv_all_bands"].items():
        if b in g["bands"]:
            continue
        for i, q in enumerate(g["quarters"]):
            rows.append([q, g["trading_days"][i], "combined", b, None, series[i]])
    _write(out_dir / "gbp_dmo_quarterly_bands.csv", ["quarter", "trading_days", "segment", "maturity_band", "common_group", "adv_gbp_mn_per_day"], rows, man, dict(
        title="UK gilts: DMO quarterly GEMM turnover by maturity band",
        description="Average daily turnover per DMO maturity band and quarter. segment d2c = customer counterparties, d2d = professional counterparties (as reported, see counting), total = both. Index-linked gilts and strips are reported without a maturity split and appear with segment combined.",
        source=g["source"], source_url=g["source_url"], notes=g["counting"]))
    wk = g["weekly"]
    rows = [[wk["week_ending"][i], wk["customer"][i], wk["professional"][i], wk["combined"][i]] for i in range(len(wk["week_ending"]))]
    _write(out_dir / "gbp_dmo_weekly.csv", ["week_ending", "customer_gbp_mn", "professional_gbp_mn", "combined_gbp_mn"], rows, man, dict(
        title="UK gilts: DMO weekly aggregate GEMM turnover",
        description="Total turnover per week (not per day) by counterparty type, market values, as reported by GEMMs. Weeks with bank holidays have fewer trading days, which shows as the dips around Christmas and Easter.",
        source=g["source"], source_url=g["source_url"], notes="whole-week totals; professional counterparties are the DMO, the Bank of England, other GEMMs, IDBs and agency brokers"))
    an = g["annual"]
    _write(out_dir / "gbp_dmo_annual.csv", list(an[0].keys()), [list(r.values()) for r in an], man, dict(
        title="UK gilts: DMO annual turnover report",
        description="Financial-year turnover, average daily turnover and turnover ratios against the gilt portfolio, GBP bn.",
        source=g["source"], source_url=g["source_url"], notes="as published in the DMO annual turnover report"))

    # ---- 4. EUR Finanzagentur ----
    d = M["EUR-DE"]
    rows = []
    for y in d["annual"]:
        for name, v in y["instruments"].items():
            rows.append([y["year"], "instrument", name, v])
        for name, v in y["counterparties"].items():
            rows.append([y["year"], "counterparty", name, v])
        rows.append([y["year"], "summary", "gross_total_bn", y["gross_total_bn"]])
        rows.append([y["year"], "summary", "gross_mlt_bn", y["gross_mlt_bn"]])
        rows.append([y["year"], "summary", "broker_share", y["broker_share"]])
    _write(out_dir / "eur_de_finanzagentur_annual.csv", ["year", "kind", "name", "value_eur_bn"], rows, man, dict(
        title="German Bunds: Finanzagentur annual trading volumes",
        description="Gross annual trading volume by instrument and by counterparty type as published, EUR bn, plus the summary rows used by the pipeline (gross total, gross medium/long term, broker share).",
        source=d["source"], source_url=d["source_url"], notes=d["counting"]))
    ins = d["instruments"]
    _write(out_dir / "eur_de_instruments_latest.csv", list(ins[0].keys()), [list(r.values()) for r in ins], man, dict(
        title=f"German Bunds: derived per-instrument figures, {d['year']}",
        description="The nominal instruments used in the profile with the customer / broker split and the resulting average daily volumes (EUR mn per day, 255 trading days). Bubills, inflation-linked and green Bunds are excluded, see the Bunds tab.",
        source=d["source"], source_url=d["source_url"], notes=f"customer share {d['customer_share']}, broker share {d['broker_share']} applied uniformly"))
    f = M["EUR-FR"]
    ref = f["reference"]
    _write(out_dir / "eur_fr_derivation.csv", ["item", "value", "note"], [
        ["scale_oat_over_bund", f["scale"], "EUR_FR_SCALE in pipeline/common.py"],
        ["de_0_10y_d2c_eur_mn_per_day", f["de_010_d2c_mn"], "German 0-10y customer-facing level"],
        ["de_0_10y_total_eur_mn_per_day", f["de_010_total_mn"], "German 0-10y total level"],
        ["fr_d2c_eur_mn_per_day", f["window_adv"]["d2c_base"]["all"], "figure used in the profile"],
        ["fr_total_eur_mn_per_day", f["window_adv"]["total"]["all"], "total segment"],
        ["reference_total_eur_mn_per_day", ref["total_mn"], ref["note"]],
        ["de_like_for_like_eur_mn_per_day", ref["de_like_for_like_mn"], "German gross excluding Bubills, including linkers and green Bunds"],
        ["implied_scale", ref["implied_scale"], "reference / like-for-like German figure"],
        ["fr_d2c_at_implied_scale_eur_mn_per_day", ref["d2c_at_implied_scale_mn"], "what the profile would use at the implied scale"],
    ], man, dict(
        title="French OATs: how the proxy is derived",
        description="There is no French turnover dataset in the pipeline. This file lists the German inputs, the scale factor and the reference figure so the derivation can be reproduced or replaced.",
        source=f["source"], source_url=f["source_url"], notes="provisional proxy; see the OAT tab"))

    # ---- 5. JPY JSDA ----
    j = M["JPY"]
    rows = []
    for seg, classes in j["monthly_adv"].items():
        for c, series in classes.items():
            for i, mo in enumerate(j["months"]):
                rows.append([mo, j["trading_days"][i], seg, c, j["class_map"].get(c), series[i]])
    _write(out_dir / "jpy_jsda_monthly.csv", ["month", "trading_days", "segment", "jgb_class", "profile_group", "adv_jpy_mn_per_day"], rows, man, dict(
        title="Japanese government bonds: JSDA monthly OTC outright volume by JGB class",
        description="Average daily volume by original-maturity class (super_long > 10y, long 6-10y, medium 2-5y, zero_coupon, tbills). segment d2c = Total less Bond Dealers less Others, d2d = Bond Dealers halved, total = d2c + d2d. T-bills and zero-coupon JGBs are not used in the profile.",
        source=j["source"], source_url=j["source_url"], notes=j["counting"]))
    inv = j["investors_window_bn_per_month"]
    rows = [[cat] + [vals.get(k) for k in ["jgb_total"] + j["classes"]] for cat, vals in inv.items()]
    _write(out_dir / "jpy_jsda_investors_window.csv", ["investor_category", "jgb_total_bn_per_month"] + [c + "_bn_per_month" for c in j["classes"]], rows, man, dict(
        title=f"Japanese government bonds: JSDA outright volume by investor category, {j['window']['label']}",
        description="Average monthly outright JGB volume (purchases plus sales, face value, JPY bn per month) per investor category over the window.",
        source=j["source"], source_url=j["source_url"], notes="monthly totals, not daily; Bond Dealers are member-to-member trades counted by both members"))

    # ---- 6. CNY ----
    c = M["CNY"]
    rows = [[r["month"], r["trading_days"], r["volume_bn"], r["adt_bn"], r["cgb_share"], r["cgb_share_used"], r["cgb_adt_bn"], r["file"]] for r in c["monthly"]]
    _write(out_dir / "cny_bond_connect_monthly.csv", ["month", "trading_days_implied", "volume_rmb_bn", "adt_rmb_bn", "cgb_share_stated", "cgb_share_used", "cgb_adt_rmb_bn", "source_file"], rows, man, dict(
        title="Chinese government bonds: Bond Connect Northbound monthly turnover",
        description="Monthly volume and average daily turnover of all bonds through Bond Connect, the stated CGB share where the report gives one, the share used (weighted mean where missing) and the CGB part of daily turnover. trading_days_implied = volume / ADT.",
        source=c["source"], source_url=c["source_url"], notes=c["counting"]))
    if c.get("ccdc"):
        cc = c["ccdc"]
        cols = ["month", "trading_days", "cgb_mn", "all_mn", "pbb_mn", "lgb_mn", "foreign_mn", "inv_total_mn", "cgb_adv_mn", "all_adv_mn", "cgb_share", "foreign_adv_mn", "foreign_share", "double_count_ok"]
        _write(out_dir / "cny_ccdc_monthly.csv", cols, [[r.get(k) for k in cols] for r in cc["monthly"]], man, dict(
            title="Chinese government bonds: CCDC interbank cash-bond settlement by month",
            description="Cash-bond settlement in the interbank market, RMB mn: CGBs (cgb), all CCDC-registered bonds (all), policy bank bonds (pbb), local government bonds (lgb), and foreign investors' own-side settlement of all CCDC bonds (foreign). *_adv_mn are per trading day on the Chinese interbank calendar. double_count_ok confirms that the investor-type table sums to twice the bond-type table.",
            source=cc["source"], source_url=cc["source_url"], notes=cc["counting"] + ". " + cc["coverage"]))

    # ---- 7. FX ----
    _write(out_dir / "fx_rates.csv", ["currency", "units_per_eur", "date"], [[k, v, data["fx"]["date"]] for k, v in fx.items()], man, dict(
        title="Exchange rates",
        description="ECB euro reference rates used for the base-currency conversion on the profile tab.",
        source=data["fx"]["source"], source_url=data["fx"]["source_url"], notes="units of currency per euro"))

    # ---- 7b. outstanding stock by remaining maturity ----
    mat = data.get("maturity", {}).get("markets", {})
    rows = []
    for code, m in mat.items():
        if not m.get("available"):
            rows.append([code, M[code]["name"], None, None, None, None, None, m.get("source"), m.get("how_to") or m.get("error")])
            continue
        for b, sh, a in zip(data["buckets"], m["shares"], m["amounts_bn"]):
            rows.append([code, M[code]["name"], m["as_of"], b, round(sh, 5), None if a is None else round(a, 3), m["unit"], m["source"], m["universe"]])
    _write(out_dir / "maturity_profile.csv", ["market", "market_name", "as_of", "bucket", "share", "amount_bn", "unit", "source", "universe"], rows, man, dict(
        title="Outstanding stock by remaining maturity (market-weighted maturity profile)",
        description="Nominal amount outstanding of each market's nominal coupon government bonds in the five common remaining-maturity buckets, and its share of the total. These shares are the default holding distribution when the maturity option on the Profile tab is switched on.",
        source="US Treasury MSPD (Fiscal Data API), Deutsche Finanzagentur itemised list, Agence France Tresor OAT outstanding page, Ministry of Finance Japan outstanding by issue, ADB AsianBondsOnline for China (shares only, unless a ChinaBond per-issue file is supplied); DMO file by hand",
        notes="universe per market in the universe column; remaining maturity measured on the as-of date; markets without a source have empty rows and a note in the last column"))

    # ---- 8. full JSON ----
    jp = out_dir / "liquidity.json"
    jp.write_text(json.dumps({k: v for k, v in data.items() if k != "downloads"}, ensure_ascii=False, indent=1), encoding="utf-8")
    man.append(dict(file=jp.name, rows=None, bytes=jp.stat().st_size, columns=[],
                    title="Everything: the JSON the page is built from",
                    description="All series, window averages, segment definitions, settings and notes in one file, exactly as produced by pipeline/run_all.py. The workbooks above are flattened views of it.",
                    source="pipeline output", notes="keys are documented in the project README"))

    # ---- 9. combined workbook with an index sheet ----
    wb = Workbook()
    ix = wb.active
    ix.title = "Index"
    for col, wd in zip("ABCD", (34, 60, 90, 50)):
        ix.column_dimensions[col].width = wd
    ix.append(["Government bond liquidity dashboard: all datasets"])
    ix.cell(1, 1).font = Font(bold=True, size=13)
    ix.append([f"Pipeline run {data['generated']}. One sheet per dataset, in wide form where the dataset is a set of series (one row per period, one column per series). The per-dataset workbooks on the page carry the long form and an About sheet with the column dictionary. Amounts in local currency millions unless the column name says otherwise; empty cells = not available."])
    ix.cell(2, 1).alignment = Alignment(wrap_text=True)
    ix.merge_cells("A2:D2")
    ix.row_dimensions[2].height = 32
    ix.append([])
    ix.append(["Sheet", "Dataset", "Description", "Source"])
    for c in ix[4]:
        c.font = Font(bold=True)
    for e in [e for e in man if e.get("_rows") is not None]:
        name = _sheet_name(e["file"])
        ix.append([name, e["title"], e["description"], e["source"]])
        r = ix.max_row
        ix.cell(r, 1).hyperlink = f"#'{name}'!A1"
        ix.cell(r, 1).font = Font(color="0563C1", underline="single")
        for c in ix[r]:
            c.alignment = Alignment(wrap_text=True, vertical="top")
        spec = WIDE.get(name)
        if spec:
            wh, wr = _widen(e["_header"], e["_rows"], spec)
            _data_sheet(wb.create_sheet(name), wh, wr)
        else:
            _data_sheet(wb.create_sheet(name), e["_header"], e["_rows"])
    allp = out_dir / "bond_liquidity_all_datasets.xlsx"
    wb.save(allp)
    man.insert(0, dict(file=allp.name, rows=None, bytes=allp.stat().st_size, columns=[],
                       title="All datasets in one workbook",
                       description="Every dataset below as its own sheet, with an Index sheet linking to them. The per-dataset workbooks carry the full About sheet with the column dictionary.",
                       source="pipeline output", notes="same content as the individual workbooks"))
    for e in man:
        e.pop("_header", None)
        e.pop("_rows", None)

    # ---- 10. data dictionary ----
    lines = ["Government bond liquidity dashboard: data files", f"Pipeline run {data['generated']}", "",
             "Each dataset is an Excel workbook with a Wide sheet where the data form series (one row per period, one column per series), a Data sheet (one observation per row) and an About sheet (source, counting, column dictionary). Amounts in local currency millions unless the column name says otherwise. Empty cells = not available.", ""]
    for e in man:
        lines += [f"== {e['file']} ==", e["title"], e["description"], f"Source: {e['source']}" + (f" ({e['source_url']})" if e.get("source_url") else ""), f"Counting / notes: {e['notes']}"]
        if e["columns"]:
            lines.append("Columns: " + ", ".join(e["columns"]))
        lines.append("")
    (out_dir / "README.txt").write_text("\n".join(lines), encoding="utf-8")
    return man
