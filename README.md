# Government bond liquidity dashboard

Average daily turnover in six government bond markets, split where the sources allow it into
dealer-to-customer (D2C) and dealer-to-dealer (D2D) volume, and the liquidity profile of a
multi-currency holding: how many trading days it takes to sell a holding of a given size,
currency allocation and maturity mix at a chosen participation rate.

Segment definitions, counting conventions, liquidity groups and averaging windows follow each
source's own reporting; see the Methods & sources tab of the page.

## Layout

```
pipeline/common.py          settings (windows, scale factors, holiday calendars), helpers
pipeline/trace_us.py        FINRA TRACE Treasury monthly aggregates (USD)        rawData/trace_us/
pipeline/dmo_gilts.py       UK DMO GEMM turnover (GBP)                           rawData/dmo_gilts/
pipeline/eur_bunds.py       Deutsche Finanzagentur annual volumes (EUR-DE) + scaled OATs (EUR-FR)   rawData/eur_bunds/
pipeline/jpy_jsda.py        JSDA OTC bond trading volume (JPY)                   rawData/jpy_jsda/
pipeline/cny_bond_connect.py  Bond Connect Flash Reports (CNY)                   rawData/cny_bond_connect/
pipeline/cny_ccdc.py        CCDC monthly settlement statistics (CNY, whole market)  rawData/ccdc_cgb/
pipeline/fx_rates.py        ECB reference rates                                  rawData/fx/
pipeline/run_all.py         runs everything -> data/liquidity.json
build.py                    template.html + data/liquidity.json -> site/index.html
maturity.py                 outstanding stock by remaining maturity (US MSPD via Fiscal Data, Finanzagentur itemised list, AFT OAT page, MoF Japan by-issue file; gilts from the DMO 'Gilts in Issue' .xls placed in rawData/maturity by hand, present since 3 Nov 2026; CGBs from the ADB AsianBondsOnline quarterly maturity profile, shares only with the 5-10y bucket split by assumption, unless a ChinaBond per-issue export cny_cgb.xls is supplied) -> data['maturity'], the market-weighted default of the optional maturity distribution
status.py                   per-dataset update status (latest data point, raw-file timestamps, next expected publication, how to refresh) -> data['status'], shown on the Update tab
export_data.py              called by build.py: one xlsx per dataset (Wide + Data + About sheets; wide = one column per series), a combined workbook, README.txt and liquidity.json -> site/data/ (Downloads block on the Notes tab)
wrangler.jsonc              Cloudflare Worker "bond-liquidity": src/worker.js in front of the static site
src/worker.js               serves /api/fx (today's ECB reference rates, cached 30 min) and passes everything else to site/; the page applies the live rates on load and keeps the baked-in ones if the call fails
```

## Rebuild

```
python -X utf8 pipeline/run_all.py --refresh   # download new TRACE months, JSDA workbooks, Finanzagentur page, Flash Reports, ECB rates
python -X utf8 pipeline/run_all.py             # parse what is in rawData/ without touching the network
python -X utf8 build.py                        # write site/index.html
npx wrangler deploy                            # publish
```

### UK gilts need a manual download

dmo.gov.uk sits behind a bot check, so the pipeline cannot fetch the DMO spreadsheets. Download
these from https://www.dmo.gov.uk/data/gilt-market/turnover-data into `rawData/dmo_gilts/`:

- `gemm-turnover-by-maturity-band-*.xlsx` (quarterly, one sheet per year; customer / professional / combined by band)
- `all-gemms-turnover-*.xls` (weekly aggregate)
- `annual-turnover-report-*.xls`

The files dated 18 Sep 2026 (and the 2025-26 annual report) are in place as of 3 Nov 2026; the
parser takes the latest file matching each pattern, so newer downloads only need to be dropped in
and the pipeline rerun. If none are present, `dmo_gilts.py` uses a provisional fallback: FY 2025-26 turnover by
short/medium/long segment from the DMO Annual Review Table 1 and a customer share of 0.41 read
by eye from the Quarterly Review April-June 2026 chart. The page flags the GBP block as
provisional.

### Chinese whole-market CGB turnover needs a manual download

The CCDC (ChinaBond) Monthly Bulletin of Statistics serves its Excel tables through a POST endpoint
that the pipeline does not call. Download by hand from
https://www.chinabond.com.cn/zzsj/zzsj_tjsj/tjsj_tjyb/ (Data > Statistics > Monthly Bulletin): pick
year and month, click the table title, choose Excel. Save into `rawData/ccdc_cgb/` with the names the
site gives, one pair per month:

    CIBM Bond Settlement (By Bond Type)_YYYYMM.xls
    CIBM Bond Settlement (By Investor Type)_YYYYMM.xls

`cny_ccdc.py` reads the cash-bond "current month" column (RMB 100 million, face value, interbank
market, settlement date). By bond type each trade counts once; by investor type each side counts, so
the foreign-investor figure is that group's own gross purchases plus sales. Daily averages use the
Chinese interbank calendar in `common.py` (State Council holidays, adjusted weekend working days
included), which matches the trading days implied by the Bond Connect reports month for month. The
12-month window average of CGB settlement per day feeds the CNY "total" segment; the
dealer-to-customer segments stay on foreign-investor turnover from Bond Connect. Without the files the
total segment falls back to CNY_MARKET_CGB_ADV_BN. Files present as of 3 Nov 2026: Sep 2025 to Sep 2026.

## Tabs

| Tab | Hash | Content |
|---|---|---|
| Liquidity profile | `#main` | Inputs (base currency, size, on/off switch and allocation per market, participation rate, haircut, illustrative stress presets, segment: dealer-to-customer or total, US on-the-run share of the holding (default 0.5 %), optional maturity distribution: off by default, when on the weights default to the market's outstanding stock by remaining maturity, with a maturity limit), cumulative-sale curves, days to sell, turnover comparison in the base currency, holdings vs turnover by liquidity group; each market tab has an optional panel with its own selling assumptions (participation, haircut, segment, on-the-run share, maturity limit and weights) for that market alone, holding still linked to the Profile tab |
| US Treasuries | `#usd` | TRACE by venue over time, by security type, by remaining maturity with on/off-the-run split |
| UK gilts | `#gbp` | DMO customer vs professional by quarter and band (annual fallback if the files are missing) |
| German Bunds | `#de` | Finanzagentur volumes by instrument and counterparty, implied daily turnover |
| French OATs | `#fr` | Scaled Bund level (EUR_FR_SCALE), shown against an independent 2025 reference of about EUR 24 bn/day gross (FR_REFERENCE_TOTAL_MN) and the ratio it implies |
| JGBs | `#jpy` | JSDA customer vs Bond Dealers by month, by original-maturity class, investor categories |
| CGBs | `#cny` | Bond Connect average daily turnover and CGB share by month; whole-market interbank CGB cash settlement from the CCDC monthly statistics (`rawData/ccdc_cgb`, 12-month window average, 409 bn/day for Oct 2025 to Sep 2026) fills the total segment only; the user's earlier estimate (CNY_MARKET_CGB_ADV_BN = 415) is shown as a reference and used only if the files are missing |
| Market comparison | `#cmp` | The six markets side by side, independent of the holding: scorecard (outstanding stock, D2C and total turnover per day, turnover ratio, days to turn the stock over, annual turnover, change vs a year earlier), stock-vs-turnover scatter, turnover ratio by market and by maturity bucket, D2C turnover over time indexed to 2024, and daily capacity at 1/3/5/10 % participation |
| Methods & sources | `#notes` | How the profile is computed, turnover segments, sources and counting conventions, outstanding stock by maturity, what is not in the data, exchange rates, Excel downloads |
| Update data | `#update` | Status of every dataset (latest data point, when the raw files were written, next expected publication), the step guide for the four hand-downloaded files, the commands that run an update, and (collapsed) the pipeline settings. The page is static, so it cannot run the pipeline or accept uploads itself; a runner (e.g. GitHub Actions behind a Worker endpoint) would be needed for that |

Every market tab shows that market's share of the liquidity profile (holding by group, days to
sell) driven by the Liquidity profile tab's inputs, optionally with its own selling assumptions,
and ends with its sources and caveats. The Liquidity profile tab can download the current
results as CSV. Inputs persist in the browser (localStorage).

## Method

Holding in market m = portfolio size x allocation share, converted at ECB rates, spread over
the five remaining-maturity buckets (0-3y, 3-5y, 5-7y, 7-10y, 10y+) with the weights entered,
then pooled into the market's liquidity groups (the finest split the source supports: five
groups for USD and full GBP data; 0-5y / 5-10y / 10y+ by original maturity for Bunds and
JGBs; one group for OATs and CGBs). Each group is sold at participation rate x average daily
turnover of the chosen segment (after the haircut), all groups in parallel; the cumulative
curve is the sum of min(holding, pace x days). "Days to sell" is where the curve reaches the
holding. This is a capacity measure, not a price-impact model.
