"""Prints a compact numeric brief of what changed in the bond liquidity data, for the monthly letter agent.

    python -X utf8 pipeline/brief.py          # reads data/liquidity.json, prints text

For each market: the averaging window, average daily turnover in the window by segment (local currency bn), and, where the
source is monthly, the latest month against the previous month and the same month a year earlier (dealer-to-customer and
total). Then the status of every dataset (latest data point, next expected release, manual or automatic) so the letter can say
what is new and what is still due. Nothing is downloaded.
"""
from __future__ import annotations
import json
from datetime import date
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
D = json.loads((ROOT / "data" / "liquidity.json").read_text(encoding="utf-8"))
out = []; P = out.append
f = lambda x, d=1: "n/a" if x is None else f"{x:,.{d}f}"

P(f"BRIEF {date.today().isoformat()}; pipeline run {D.get('generated')}, last refresh {D.get('last_refresh')}; ECB rates of {D['fx']['date']}")
for code in D["order"]:
    m = D["markets"][code]
    P(f"\n== {m['name']} ({code}), {m['unit']}; source {m['source']} ==")
    P(f"window: {m['window']['label']} ({m['window']['n']} periods)")
    seen = set()
    for seg, groups in m["window_adv"].items():
        key = (m["segments"].get(seg) or {}).get("key", seg)
        if key in seen: continue   # d2c_base and d2c_all share one series outside the US
        seen.add(key)
        vals = [v for v in groups.values() if v is not None]
        lab = (m["segments"].get(seg) or {}).get("label", seg)
        P(f"- {lab}: {f(sum(vals) / 1000, 1) if vals else 'n/a'} bn per day" + (f" ({', '.join(f'{g} {f(v / 1000, 1)}' for g, v in groups.items() if v is not None)})" if len(groups) > 1 else ""))
    ma, months = m.get("monthly_adv"), m.get("months") or []
    if isinstance(ma, dict) and months:
        for seg in ("d2c_base", "total"):
            key = (m["segments"].get(seg) or {}).get("key")
            series = ma.get(key) if key else None
            if not series: continue
            n = len(months)
            tot = [sum((series[g][i] or 0) for g in series if series[g][i] is not None) if any(series[g][i] is not None for g in series) else None for i in range(n)]
            last = n - 1
            while last >= 0 and tot[last] is None: last -= 1
            if last < 0: continue
            prev, yago = tot[last - 1] if last >= 1 else None, tot[last - 12] if last >= 12 else None
            lab = (m["segments"].get(seg) or {}).get("label", seg)
            P(f"- latest month {months[last][:7]}, {lab}: {f(tot[last] / 1000, 1)} bn/day; vs previous month {f(100 * (tot[last] / prev - 1), 1) + ' %' if prev else 'n/a'}; vs a year earlier {f(100 * (tot[last] / yago - 1), 1) + ' %' if yago else 'n/a'}")
            hi = max(range(n), key=lambda i: tot[i] if tot[i] is not None else -1)
            P(f"  highest month in the series: {months[hi][:7]} at {f(tot[hi] / 1000, 1)} bn/day; series from {months[0][:7]}")
    if m.get("provisional"): P("- PROVISIONAL figures (source files missing); see the page's caveat")

P("\n== Dataset status ==")
today = date.today().isoformat()
for s in D.get("status", []):
    due = s.get("next_expected") and today >= s["next_expected"] and not s.get("available") is False
    P(f"- {s.get('title')}: latest {s.get('latest')}; mode {s.get('mode')}; next expected {s.get('next_expected')}{'; DUE' if due else ''}{'; FILE NEEDED' if s.get('available') is False else ''}")
print("\n".join(out))
