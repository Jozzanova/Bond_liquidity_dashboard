"""Update status of every dataset: latest data point, when the raw files were
last written, how the dataset is refreshed (automatic download or a file
placed by hand) and when new data can be expected. Feeds the Update tab.
"""
from __future__ import annotations

import datetime as dt

from common import RAW


def _files(folder, patterns):
    out = []
    if folder.exists():
        for p in patterns:
            out += [f for f in folder.glob(p) if f.is_file() and not f.name.endswith(".meta.json")]
    return sorted(set(out))


def _stamp(files):
    if not files:
        return None
    return dt.datetime.fromtimestamp(max(f.stat().st_mtime for f in files)).strftime("%Y-%m-%d %H:%M")


def _month_plus(month_iso: str, months: int, day: int) -> dt.date:
    y, m = int(month_iso[:4]), int(month_iso[5:7])
    m += months
    y += (m - 1) // 12
    m = (m - 1) % 12 + 1
    return dt.date(y, m, min(day, 28))


def _quarter_next(q: str) -> dt.date:
    # "2026Q2" -> figures for the next quarter are published about six weeks after it ends
    y, n = int(q[:4]), int(q[-1])
    end_next = {1: dt.date(y, 6, 30), 2: dt.date(y, 9, 30), 3: dt.date(y, 12, 31), 4: dt.date(y + 1, 3, 31)}[n]
    return end_next + dt.timedelta(days=45)


def build(markets: dict, fx: dict, maturity: dict, today: dt.date | None = None) -> list[dict]:
    today = today or dt.date.today()
    S = []

    def add(key, title, mode, source, source_url, latest, files, cadence, next_expected, folder, how, available=True, note=""):
        st = _stamp(files)
        if not available:
            status = "file needed"
        elif next_expected and today >= next_expected:
            status = "new data likely"
        else:
            status = "up to date"
        S.append(dict(key=key, title=title, mode=mode, source=source, source_url=source_url, latest=latest, files_updated=st,
                      n_files=len(files), folder=str(folder.relative_to(RAW.parent)).replace("\\", "/"), cadence=cadence,
                      next_expected=next_expected.isoformat() if next_expected else None, status=status, how=how, available=available, note=note))

    usd = markets.get("USD")
    if usd:
        to = usd["window"]["to"]
        add("trace_us", "US Treasuries: TRACE monthly aggregates", "automatic", usd["source"], usd["source_url"], usd["window"]["label"],
            _files(RAW / "trace_us", ["ts-monthly-aggregates-*.xlsx"]), "monthly, on the second business day after month end",
            _month_plus(to, 2, 4), RAW / "trace_us", "run the pipeline with --refresh; the module downloads any missing month from cdn.finra.org")
    gbp = markets.get("GBP")
    if gbp:
        prov = bool(gbp.get("provisional"))
        add("dmo_gilts", "UK gilts: DMO turnover", "manual", gbp["source"], gbp["source_url"], gbp["window"]["label"],
            _files(RAW / "dmo_gilts", ["gemm-turnover-by-maturity-band*.xlsx", "all-gemms-turnover*.xls*", "annual-turnover-report*.xls*"]),
            "quarterly, about six weeks after quarter end (weekly file updated more often)", _quarter_next(gbp["window"]["to"]) if not prov else None, RAW / "dmo_gilts",
            "dmo.gov.uk > Data > Gilt market > Turnover data. Download 'GEMM turnover by maturity band' (xlsx), 'All GEMMs turnover' (xls) and the latest 'Annual turnover report' (xls), keep the DMO file names and put them in rawData/dmo_gilts; the pipeline picks the newest file of each kind.",
            available=not prov, note="the DMO site sits behind a bot check, so the pipeline cannot download these")
    de = markets.get("EUR-DE")
    if de:
        yr = int(de["window"]["label"])
        add("eur_bunds", "German Bunds: Finanzagentur trading volumes", "automatic", de["source"], de["source_url"], de["window"]["label"],
            _files(RAW / "eur_bunds", ["finanzagentur_*.html"]), "annual, the full year appears early in the following year",
            dt.date(yr + 2, 2, 1), RAW / "eur_bunds", "run the pipeline with --refresh; the page is scraped and a dated snapshot kept")
    fr = markets.get("EUR-FR")
    if fr:
        add("eur_fr", "French OATs: derived from the Bund figures", "derived", fr["source"], fr["source_url"], fr["window"]["label"], [],
            "follows the German data", None, RAW / "eur_bunds", "nothing to download: the OAT level is the German 0-10y customer-facing level times EUR_FR_SCALE (pipeline/common.py)")
    jpy = markets.get("JPY")
    if jpy:
        add("jpy_jsda", "JGBs: JSDA trading volume by investor type", "automatic", jpy["source"], jpy["source_url"], jpy["window"]["label"],
            _files(RAW / "jpy_jsda", ["koushasai*.xlsx"]), "monthly, around the 20th of the following month",
            _month_plus(jpy["window"]["to"], 2, 22), RAW / "jpy_jsda", "run the pipeline with --refresh; the current and previous fiscal-year workbooks are downloaded")
    cny = markets.get("CNY")
    if cny:
        add("cny_bond_connect", "CGBs: Bond Connect flash reports", "automatic", cny["source"], cny["source_url"], cny["window"]["label"],
            _files(RAW / "cny_bond_connect", ["Bond-Connect-Flash-Report*.html"]), "monthly, in the first days of the following month",
            _month_plus(cny["window"]["to"], 2, 8), RAW / "cny_bond_connect", "run the pipeline with --refresh; new flash-report pages are fetched from chinabondconnect.com")
        cc = cny.get("ccdc")
        add("ccdc", "CGBs: CCDC monthly settlement statistics (whole market)", "manual",
            cc["source"] if cc else "CCDC Monthly Bulletin of Statistics", cc["source_url"] if cc else "https://www.chinabond.com.cn/zzsj/zzsj_tjsj/tjsj_tjyb/",
            cc["window"]["label"] if cc else None, _files(RAW / "ccdc_cgb", ["*.xls*"]), "monthly, around the 10th of the following month",
            _month_plus(cc["months"][-1], 2, 12) if cc else None, RAW / "ccdc_cgb",
            "chinabond.com.cn > Data > Statistics > Monthly Bulletin of Statistics. For each new month click table 7 'CIBM Bond Settlement (By Bond Type)' and table 8 '(By Investor Type)', choose Excel and save them as 'CIBM Bond Settlement (By Bond Type)_YYYYMM.xls' and 'CIBM Bond Settlement (By Investor Type)_YYYYMM.xls' in rawData/ccdc_cgb.",
            available=bool(cc), note="the download endpoint rejects scripted requests")
    add("fx", "Exchange rates: ECB reference rates", "automatic", fx["source"], fx["source_url"], fx["date"], _files(RAW / "fx", ["eurofxref-daily.xml"]),
        "daily, about 16:00 CET on ECB working days", dt.date.fromisoformat(fx["date"]) + dt.timedelta(days=1), RAW / "fx", "run the pipeline with --refresh")

    mm = (maturity or {}).get("markets", {})
    MAT = [("USD", "us_mspd_table3.json", "monthly, a few business days after month end", "automatic", 1, 6),
           ("GBP", "gilts*.xls*", "after every gilt operation; refresh when the holding profile matters", "manual", 3, 1),
           ("EUR-DE", "de_einzelaufstellung_en.xlsx", "monthly", "automatic", 1, 8),
           ("EUR-FR", "fr_encours_oat.html", "updated by AFT after each auction; the page carries no date", "automatic", 1, 1),
           ("JPY", "jp_maturity.xlsx", "annual, end-March figures published around June", "automatic", 12, 1),
           ("CNY", "cny_*.*", "when the holding profile matters", "manual", 3, 1)]
    for code, pat, cad, mode, months, day in MAT:
        x = mm.get(code, {})
        avail = bool(x.get("available"))
        nxt = _month_plus(x["as_of"][:7], months + 1, day) if avail and x.get("as_of") else None
        how = {"USD": "run the pipeline with --refresh (Fiscal Data API)", "EUR-DE": "run the pipeline with --refresh (itemised list xlsx)",
               "EUR-FR": "run the pipeline with --refresh (AFT page)", "JPY": "run the pipeline with --refresh (MoF maturity.xlsx)",
               "GBP": "dmo.gov.uk > Data > Gilt market > Gilts in issue: export to Excel and save it as rawData/maturity/gilts-in-issue.xls",
               "CNY": x.get("how_to") or "see the Notes tab"}[code]
        add("maturity_" + code, f"{markets[code]['name'] if code in markets else code}: outstanding stock by maturity", mode, x.get("source", ""), x.get("source_url", ""),
            x.get("as_of"), _files(RAW / "maturity", [pat]), cad, nxt, RAW / "maturity", how, available=avail or mode == "automatic",
            note="" if avail else (x.get("error") or "no file yet"))
    return S
