"""ECB euro foreign exchange reference rates, used to express holdings and ADV
in one base currency. Saved to rawData/fx/eurofxref-daily.xml."""
from __future__ import annotations

import re
import sys

import requests

from common import RAW

URL = "https://www.ecb.europa.eu/stats/eurofxref/eurofxref-daily.xml"
FOLDER = RAW / "fx"
WANT = ["USD", "GBP", "JPY", "CNY", "NOK", "SEK", "CHF", "DKK", "AUD", "CAD"]


def download():
    FOLDER.mkdir(parents=True, exist_ok=True)
    r = requests.get(URL, timeout=60, headers={"User-Agent": "Mozilla/5.0"})
    r.raise_for_status()
    (FOLDER / "eurofxref-daily.xml").write_text(r.text, encoding="utf-8")
    print("FX: ECB reference rates saved")


def load() -> dict:
    f = FOLDER / "eurofxref-daily.xml"
    if not f.exists():
        download()
    txt = f.read_text(encoding="utf-8")
    date = re.search(r"Cube time='(\d{4}-\d{2}-\d{2})'", txt).group(1)
    rates = {"EUR": 1.0}
    for cur, rate in re.findall(r"currency='(\w{3})' rate='([\d.]+)'", txt):
        if cur in WANT:
            rates[cur] = float(rate)
    return {"date": date, "base": "EUR", "per_eur": rates, "source": "ECB euro foreign exchange reference rates", "source_url": URL}


if __name__ == "__main__":
    if "--refresh" in sys.argv:
        download()
    print(load())
