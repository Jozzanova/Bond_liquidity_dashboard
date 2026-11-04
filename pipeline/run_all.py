"""Run every source module and write data/liquidity.json for build.py.

    python -X utf8 pipeline/run_all.py            # parse the files in rawData/
    python -X utf8 pipeline/run_all.py --refresh  # download / scrape first (DMO files stay manual)
"""
from __future__ import annotations

import datetime as dt
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import cny_bond_connect, cny_ccdc, dmo_gilts, eur_bunds, fx_rates, jpy_jsda, maturity, status, trace_us  # noqa: E402
from common import (CNY_5_10_SPLIT, CNY_BONDCONNECT_SHARE, CNY_CHANNEL, CNY_D2C_ADV_BN_OVERRIDE, CNY_D2C_OVERRIDE_NOTE, CNY_MARKET_CGB_ADV_BN, CNY_MARKET_CGB_NOTE, CNY_WINDOW, COMMON_BUCKETS, FR_REFERENCE_NOTE, FR_REFERENCE_TOTAL_MN,  # noqa: E402
                    DATA, DMO_WINDOW, EUR_FR_SCALE, EUR_TRADING_DAYS, JPY_INCLUDE_OTHERS, JPY_WINDOW,
                    RAW, TRACE_WINDOW, dump_json)

refresh = "--refresh" in sys.argv
if refresh:
    trace_us.download()
    jpy_jsda.download()
    eur_bunds.fetch(refresh=True)
    cny_bond_connect.download()
    fx_rates.download()

markets = {}
markets["USD"] = trace_us.build(trace_us.load())
gbp = dmo_gilts.build()
if gbp:
    markets["GBP"] = gbp
de, fr = eur_bunds.build()
markets["EUR-DE"] = de
markets["EUR-FR"] = fr
markets["JPY"] = jpy_jsda.build(jpy_jsda.load())
rows, origin = cny_bond_connect.load()
ccdc = cny_ccdc.build(cny_ccdc.load())
print("CNY: CCDC files", "found, window " + ccdc["window"]["label"] if ccdc else "absent, using CNY_MARKET_CGB_ADV_BN")
markets["CNY"] = cny_bond_connect.build(rows, origin, ccdc)

out = {
    "generated": dt.datetime.now().strftime("%Y-%m-%d %H:%M"),
    "buckets": COMMON_BUCKETS,
    "order": ["USD", "GBP", "EUR-DE", "EUR-FR", "JPY", "CNY"],
    "settings": {
        "trace_window_months": TRACE_WINDOW, "dmo_window_quarters": DMO_WINDOW, "jpy_window_months": JPY_WINDOW,
        "cny_window_months": CNY_WINDOW, "eur_trading_days": EUR_TRADING_DAYS, "eur_fr_scale": EUR_FR_SCALE,
        "jpy_include_others": JPY_INCLUDE_OTHERS, "cny_channel": CNY_CHANNEL,
        "cny_bondconnect_share": CNY_BONDCONNECT_SHARE, "cny_market_cgb_adv_bn": CNY_MARKET_CGB_ADV_BN, "cny_market_cgb_note": CNY_MARKET_CGB_NOTE,
        "cny_d2c_adv_bn_override": CNY_D2C_ADV_BN_OVERRIDE, "cny_d2c_override_note": CNY_D2C_OVERRIDE_NOTE, "cny_5_10_split": CNY_5_10_SPLIT,
        "fr_reference_total_mn": FR_REFERENCE_TOTAL_MN, "fr_reference_note": FR_REFERENCE_NOTE,
    },
    "fx": fx_rates.load(),
    "maturity": maturity.build(refresh),
    "markets": markets,
}
STAMP = RAW / ".last_refresh"   # when the automatic sources were last checked (run with --refresh)
if refresh:
    STAMP.write_text(dt.datetime.now().strftime("%Y-%m-%d %H:%M"), encoding="utf-8")
out["last_refresh"] = STAMP.read_text(encoding="utf-8").strip() if STAMP.exists() else None
out["status"] = status.build(markets, out["fx"], out["maturity"], checked=out["last_refresh"])
dump_json(out, DATA / "liquidity.json")
for k, m in markets.items():
    print(f"{k:7s} {m['window']['label']:22s}", {g: round(v or 0) for g, v in m["window_adv"]["d2c_base"].items()})
