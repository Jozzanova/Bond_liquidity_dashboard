Government bond liquidity dashboard: data files
Pipeline run 2026-11-04 11:50

Each dataset is an Excel workbook with a Data sheet (one observation per row) and an About sheet (source, counting, column dictionary). Amounts in local currency millions unless the column name says otherwise. Empty cells = not available.

== bond_liquidity_all_datasets.xlsx ==
All datasets in one workbook
Every dataset below as its own sheet, with an Index sheet linking to them. The per-dataset workbooks carry the full About sheet with the column dictionary.
Source: pipeline output
Counting / notes: same content as the individual workbooks

== window_adv.xlsx ==
Window averages used in the liquidity profile
Average daily turnover per maturity group and segment for every market, over each source's latest window. This is the table the profile calculation starts from. The USD rows with issue on_the_run / off_the_run are the TRACE split used when the on-the-run share is set; d2c_base for USD is off-the-run only. EUR conversion uses the ECB reference rates listed on this tab.
Source: all pipeline sources (see the conventions table on the Notes tab)
Counting / notes: Segments and counting follow each source; the d2d and total columns are not comparable across markets. Maturity groups are the common buckets for USD and GBP, original-maturity classes for Bunds and JGBs, and a single group for OATs and CGBs.
Columns: market, market_name, currency, window, segment, segment_description, maturity_group, issue, adv_local_mn_per_day, adv_eur_mn_per_day

== usd_trace_monthly.xlsx ==
US Treasuries: TRACE monthly average daily volume by common maturity bucket
Nominal coupon Treasuries, remaining maturity mapped from the TRACE buckets to the five common groups. segment d2c = dealer-to-customer, d2d = dealer-to-dealer (incl. ATS), total = both; issue = all, on (on-the-run) or off (off-the-run).
Source: FINRA TRACE Treasury Monthly Aggregate Statistics (https://www.finra.org/finra-data/browse-catalog/about-monthly-treasury)
Counting / notes: single-counted per trade (FINRA reports each trade once; ATS and interdealer trades are not doubled)
Columns: month, trading_days, segment, issue, maturity_group, adv_usd_mn_per_day

== usd_trace_monthly_trace_buckets.xlsx ==
US Treasuries: TRACE monthly average daily volume by original TRACE bucket
Same as the previous file but on the seven remaining-maturity buckets as published by FINRA, before mapping to the common groups.
Source: FINRA TRACE Treasury Monthly Aggregate Statistics (https://www.finra.org/finra-data/browse-catalog/about-monthly-treasury)
Counting / notes: single-counted per trade (FINRA reports each trade once; ATS and interdealer trades are not doubled)
Columns: month, trading_days, segment, issue, trace_bucket, common_group, adv_usd_mn_per_day

== usd_trace_monthly_by_type.xlsx ==
US Treasuries: TRACE monthly average daily volume by security type
All Treasuries, Bills, FRNs, Nominal Coupons and TIPS, all maturities; the number of trades is given for nominal coupons.
Source: FINRA TRACE Treasury Monthly Aggregate Statistics (https://www.finra.org/finra-data/browse-catalog/about-monthly-treasury)
Counting / notes: single-counted per trade (FINRA reports each trade once; ATS and interdealer trades are not doubled)
Columns: month, trading_days, security_type, segment, adv_usd_mn_per_day, coupon_trades_per_month

== gbp_dmo_quarterly_bands.xlsx ==
UK gilts: DMO quarterly GEMM turnover by maturity band
Average daily turnover per DMO maturity band and quarter. segment d2c = customer counterparties, d2d = professional counterparties (as reported, see counting), total = both. Index-linked gilts and strips are reported without a maturity split and appear with segment combined.
Source: UK DMO, gilt turnover data reported by GEMMs (quarterly by maturity band; weekly aggregate; annual report) (https://www.dmo.gov.uk/data/gilt-market/turnover-data)
Counting / notes: customer turnover single-counted; professional turnover (DMO, BoE, GEMMs, IDBs, agency brokers) as reported and may double count via IDBs
Columns: quarter, trading_days, segment, maturity_band, common_group, adv_gbp_mn_per_day

== gbp_dmo_weekly.xlsx ==
UK gilts: DMO weekly aggregate GEMM turnover
Total turnover per week (not per day) by counterparty type, market values, as reported by GEMMs. Weeks with bank holidays have fewer trading days, which shows as the dips around Christmas and Easter.
Source: UK DMO, gilt turnover data reported by GEMMs (quarterly by maturity band; weekly aggregate; annual report) (https://www.dmo.gov.uk/data/gilt-market/turnover-data)
Counting / notes: whole-week totals; professional counterparties are the DMO, the Bank of England, other GEMMs, IDBs and agency brokers
Columns: week_ending, customer_gbp_mn, professional_gbp_mn, combined_gbp_mn

== gbp_dmo_annual.xlsx ==
UK gilts: DMO annual turnover report
Financial-year turnover, average daily turnover and turnover ratios against the gilt portfolio, GBP bn.
Source: UK DMO, gilt turnover data reported by GEMMs (quarterly by maturity band; weekly aggregate; annual report) (https://www.dmo.gov.uk/data/gilt-market/turnover-data)
Counting / notes: as published in the DMO annual turnover report
Columns: financial_year, adv_gbp_bn, annual_turnover_gbp_bn, gross_portfolio_mv_gbp_bn, net_portfolio_mv_gbp_bn, turnover_ratio_gross, turnover_ratio_net

== eur_de_finanzagentur_annual.xlsx ==
German Bunds: Finanzagentur annual trading volumes
Gross annual trading volume by instrument and by counterparty type as published, EUR bn, plus the summary rows used by the pipeline (gross total, gross medium/long term, broker share).
Source: Deutsche Finanzagentur, trading volumes (annual, by instrument and counterparty) (https://www.deutsche-finanzagentur.de/en/federal-securities/trading/secondary-market/trading-volumes/year)
Counting / notes: customer-facing legs reported once by the bank (used as reported); broker legs reported by both banks (halved)
Columns: year, kind, name, value_eur_bn

== eur_de_instruments_latest.xlsx ==
German Bunds: derived per-instrument figures, 2025
The nominal instruments used in the profile with the customer / broker split and the resulting average daily volumes (EUR mn per day, 255 trading days). Bubills, inflation-linked and green Bunds are excluded, see the Bunds tab.
Source: Deutsche Finanzagentur, trading volumes (annual, by instrument and counterparty) (https://www.deutsche-finanzagentur.de/en/federal-securities/trading/secondary-market/trading-volumes/year)
Counting / notes: customer share 0.6995, broker share 0.3005 applied uniformly
Columns: instrument, group, gross_eur_bn, customer_bn, broker_bn, d2d_single_bn, total_single_bn, d2c_adv_mn, d2d_adv_mn, total_adv_mn

== eur_fr_derivation.xlsx ==
French OATs: how the proxy is derived
There is no French turnover dataset in the pipeline. This file lists the German inputs, the scale factor and the reference figure so the derivation can be reproduced or replaced.
Source: Derived: German Bund level (Finanzagentur, 0-10y) x OAT/Bund scale (https://www.aft.gouv.fr/en/bulletins-mensuels)
Counting / notes: provisional proxy; see the OAT tab
Columns: item, value, note

== jpy_jsda_monthly.xlsx ==
Japanese government bonds: JSDA monthly OTC outright volume by JGB class
Average daily volume by original-maturity class (super_long > 10y, long 6-10y, medium 2-5y, zero_coupon, tbills). segment d2c = Total less Bond Dealers less Others, d2d = Bond Dealers halved, total = d2c + d2d. T-bills and zero-coupon JGBs are not used in the profile.
Source: JSDA, Trading Volume of OTC Bonds (sheet B, outright transactions, all members) (https://www.jsda.or.jp/en/statistics/bonds/index.html)
Counting / notes: members report their own legs: customer trades appear once, member-to-member (Bond Dealers) trades twice and are halved
Columns: month, trading_days, segment, jgb_class, profile_group, adv_jpy_mn_per_day

== jpy_jsda_investors_window.xlsx ==
Japanese government bonds: JSDA outright volume by investor category, Oct 2025 to Sep 2026
Average monthly outright JGB volume (purchases plus sales, face value, JPY bn per month) per investor category over the window.
Source: JSDA, Trading Volume of OTC Bonds (sheet B, outright transactions, all members) (https://www.jsda.or.jp/en/statistics/bonds/index.html)
Counting / notes: monthly totals, not daily; Bond Dealers are member-to-member trades counted by both members
Columns: investor_category, jgb_total_bn_per_month, super_long_bn_per_month, long_bn_per_month, medium_bn_per_month, zero_coupon_bn_per_month, tbills_bn_per_month

== cny_bond_connect_monthly.xlsx ==
Chinese government bonds: Bond Connect Northbound monthly turnover
Monthly volume and average daily turnover of all bonds through Bond Connect, the stated CGB share where the report gives one, the share used (weighted mean where missing) and the CGB part of daily turnover. trading_days_implied = volume / ADT.
Source: Bond Connect Company Limited, monthly Flash Reports (Northbound) (https://www.chinabondconnect.com/en/Resource/Flash-Report.html)
Counting / notes: Northbound average daily turnover as reported (foreign investors' trades with onshore market makers), times the CGB share of volume
Columns: month, trading_days_implied, volume_rmb_bn, adt_rmb_bn, cgb_share_stated, cgb_share_used, cgb_adt_rmb_bn, source_file

== cny_ccdc_monthly.xlsx ==
Chinese government bonds: CCDC interbank cash-bond settlement by month
Cash-bond settlement in the interbank market, RMB mn: CGBs (cgb), all CCDC-registered bonds (all), policy bank bonds (pbb), local government bonds (lgb), and foreign investors' own-side settlement of all CCDC bonds (foreign). *_adv_mn are per trading day on the Chinese interbank calendar. double_count_ok confirms that the investor-type table sums to twice the bond-type table.
Source: CCDC (China Central Depository & Clearing), Monthly Bulletin of Statistics, tables 7 and 8 (CIBM bond settlement by bond type / by investor type) (https://www.chinabond.com.cn/zzsj/zzsj_tjsj/tjsj_tjyb/)
Counting / notes: cash-bond settlement in the interbank market by settlement date, face value, RMB; by bond type each trade counts once; by investor type each side counts, so an investor type's figure is its own gross purchases plus sales. bonds registered at CCDC (CGBs, local government, policy bank, government-backed agency, commercial bank, enterprise bonds, ABS); interbank market only, no exchange or counter trading; the Bond Connect and CIBM Direct trades of foreign investors are included
Columns: month, trading_days, cgb_mn, all_mn, pbb_mn, lgb_mn, foreign_mn, inv_total_mn, cgb_adv_mn, all_adv_mn, cgb_share, foreign_adv_mn, foreign_share, double_count_ok

== fx_rates.xlsx ==
Exchange rates
ECB euro reference rates used for the base-currency conversion on the profile tab.
Source: ECB euro foreign exchange reference rates (https://www.ecb.europa.eu/stats/eurofxref/eurofxref-daily.xml)
Counting / notes: units of currency per euro
Columns: currency, units_per_eur, date

== maturity_profile.xlsx ==
Outstanding stock by remaining maturity (market-weighted maturity profile)
Nominal amount outstanding of each market's nominal coupon government bonds in the five common remaining-maturity buckets, and its share of the total. These shares are the default holding distribution when the maturity option on the Profile tab is switched on.
Source: US Treasury MSPD (Fiscal Data API), Deutsche Finanzagentur itemised list, Agence France Tresor OAT outstanding page, Ministry of Finance Japan outstanding by issue, ADB AsianBondsOnline for China (shares only, unless a ChinaBond per-issue file is supplied); DMO file by hand
Counting / notes: universe per market in the universe column; remaining maturity measured on the as-of date; markets without a source have empty rows and a note in the last column
Columns: market, market_name, as_of, bucket, share, amount_bn, unit, source, universe

== liquidity.json ==
Everything: the JSON the page is built from
All series, window averages, segment definitions, settings and notes in one file, exactly as produced by pipeline/run_all.py. The workbooks above are flattened views of it.
Source: pipeline output
Counting / notes: keys are documented in the project README
