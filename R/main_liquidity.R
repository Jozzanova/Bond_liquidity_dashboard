# main_liquidity.R
# ---------------------------------------------------------------------------
# Master script for market volume (ADV) inputs to the FX reserve liquidity
# profile. Sets libraries, paths and input variables, then executes the
# source-specific scripts, which read raw files from rawData/<source>/,
# write cleaned long tables to cleanData/liquidity_clean.xlsx and aggregated
# ADV tables to output/liquidity_adv.xlsx (plus .rds copies of the clean tables).
#
# Folder layout (relative to this file):
#   rawData/trace_us/     FINRA TRACE monthly aggregate files (downloaded if missing)
#   rawData/dmo_gilts/    DMO turnover files (gemm-turnover-by-maturity-band-*.xlsx,
#                         all-gemms-turnover-*.xls, annual-turnover-report-*.xls)
#   rawData/eur_bunds/    dated snapshots of the Finanzagentur HTML tables (written by the scraper)
#   rawData/jpy_jsda/     JSDA OTC bond trading volume files (koushasai.xlsx, koushasai2025.xlsx, ...)
#   rawData/cny_bond_connect/ dated snapshots of Bond Connect Flash Report figures (written by the scraper)
#   cleanData/            tidy long tables, one row per period x bucket x segment
#   output/               ADV tables for the liquidity profile workbook
# ---------------------------------------------------------------------------

rm(list = ls())
.libPaths("C:\\Users\\wm1640\\R4_libraries")

# Set paths and source functions
code.path      <- paste0(dirname(rstudioapi::getActiveDocumentContext()$path), "\\")
raw.path       <- paste0(code.path, "\\rawData\\")
clean.path     <- paste0(code.path, "\\cleanData\\")
output.path    <- paste0(code.path, "\\output\\")
raw.trace.path <- paste0(raw.path, "trace_us\\")
raw.dmo.path   <- paste0(raw.path, "dmo_gilts\\")
raw.eur.path   <- paste0(raw.path, "eur_bunds\\")
raw.jpy.path   <- paste0(raw.path, "jpy_jsda\\")
raw.cny.path   <- paste0(raw.path, "cny_bond_connect\\")

for (p in c(raw.trace.path, raw.dmo.path, raw.eur.path, raw.jpy.path, raw.cny.path, clean.path, output.path)) {
  dir.create(p, recursive = TRUE, showWarnings = FALSE)
}

# Libraries (data.table loaded last so its melt/dcast are not masked)
library(readxl)
library(rvest)        # Finanzagentur HTML tables
library(openxlsx)
library(data.table)

# --- Input variables -------------------------------------------------------

# Common maturity grid for entering exposures. ADV is reported per LIQUIDITY
# GROUP: a set of buckets sharing one ADV pool, defined per currency by what
# the source measures (USD, GBP: remaining maturity, 5 groups; EUR-DE, JPY:
# original maturity, 3 groups 0-5y/5-10y/10y+; EUR-FR, CNY: level only, 1 group).
common.buckets <- c("0-3y", "3-5y", "5-7y", "7-10y", "10y+")

# TRACE (USD): months to load and whether to download missing files
trace.months   <- format(seq(as.Date("2025-08-01"), as.Date("2026-07-01"), by = "month"), "%Y-%m")
trace.download <- TRUE
trace.window   <- 12          # months averaged for the ADV table written to output/

# DMO (GBP): number of quarters averaged for the ADV table written to output/
dmo.window     <- 4

# Finanzagentur (EUR): trading days per year (TARGET) and OAT/Bund scaling for
# France.
# eur.fr.scale: ratio of OAT to Bund daily turnover. Provisional value from the
# AFT monthly bulletin chart (SVT-reported average daily volume, roughly
# EUR 20 bn) against Finanzagentur MLT gross per day (about EUR 26 bn); verify
# from the AFT statistical report before relying on it.
eur.scrape              <- TRUE       # FALSE: use latest snapshot in rawData/eur_bunds/ or embedded fallback
eur.trading.days        <- 255
eur.fr.scale            <- 0.75

# JSDA (JPY): months averaged; whether the "Others" investor category (which
# includes members' auction allotments) counts as customer flow.
jpy.window          <- 12
jpy.include.others  <- FALSE

# Bond Connect (CNY): scrape switch, months averaged, level definition and
# maturity spread. cny.channel: "bond_connect" (CGB turnover through Bond
# Connect only) or "all_foreign" (Bond Connect divided by its share of total
# foreign turnover, cny.bondconnect.share; HKMA July 2026: over 64 %).
# cny.market.cgb.adv.bn: whole-market CGB cash turnover, CNY bn per day, from
# CFETS, for the "total" segment (NA until entered).
cny.scrape             <- TRUE
cny.window             <- 12
cny.channel            <- "all_foreign"
cny.bondconnect.share  <- 0.64
cny.market.cgb.adv.bn  <- NA_real_

# Trading-day calendars. VERIFY against SIFMA and gov.uk before relying on them.
sifma.holidays <- as.Date(c(
  "2025-01-01", "2025-01-20", "2025-02-17", "2025-04-18", "2025-05-26", "2025-06-19",
  "2025-07-04", "2025-09-01", "2025-10-13", "2025-11-11", "2025-11-27", "2025-12-25",
  "2026-01-01", "2026-01-19", "2026-02-16", "2026-04-03", "2026-05-25", "2026-06-19",
  "2026-07-03", "2026-09-07", "2026-10-12", "2026-11-11", "2026-11-26", "2026-12-25"))
uk.holidays <- as.Date(c(
  "2024-01-01", "2024-03-29", "2024-04-01", "2024-05-06", "2024-05-27", "2024-08-26", "2024-12-25", "2024-12-26",
  "2025-01-01", "2025-04-18", "2025-04-21", "2025-05-05", "2025-05-26", "2025-08-25", "2025-12-25", "2025-12-26",
  "2026-01-01", "2026-04-03", "2026-04-06", "2026-05-04", "2026-05-25", "2026-08-31", "2026-12-25", "2026-12-28"))
jp.holidays <- as.Date(c(   # JGB market closures incl. 2-3 Jan and 31 Dec; VERIFY against JSDA/JPX calendar
  "2025-01-01", "2025-01-02", "2025-01-03", "2025-01-13", "2025-02-11", "2025-02-24", "2025-03-20",
  "2025-04-29", "2025-05-05", "2025-05-06", "2025-07-21", "2025-08-11", "2025-09-15", "2025-09-23",
  "2025-10-13", "2025-11-03", "2025-11-24", "2025-12-31",
  "2026-01-01", "2026-01-02", "2026-01-12", "2026-02-11", "2026-02-23", "2026-03-20", "2026-04-29",
  "2026-05-04", "2026-05-05", "2026-05-06", "2026-07-20", "2026-08-11", "2026-09-21", "2026-09-22",
  "2026-09-23", "2026-10-12", "2026-11-03", "2026-11-23", "2026-12-31"))

# Shared helper: business days between two dates given a holiday vector
trading_days_between <- function(from, to, holidays) {
  d <- seq(from, to, by = "day")
  sum(!as.POSIXlt(d)$wday %in% c(0, 6) & !d %in% holidays)
}

# --- Execute source scripts ------------------------------------------------

source(paste0(code.path, "trace_treasury_aggregates.R"))
source(paste0(code.path, "dmo_gilt_turnover.R"))
source(paste0(code.path, "eur_bund_turnover.R"))
source(paste0(code.path, "jpy_jsda_turnover.R"))
source(paste0(code.path, "cny_bond_connect.R"))

# --- Combine into the group tables for the workbook -------------------------
# Segments: d2c_base = the conservative dealer-to-customer measure
#           (USD: off-the-run D2C; GBP: customer; EUR: non-broker; JPY: ex
#           dealers and Others; CNY: foreign-investor turnover),
#           d2c_all  = all dealer-to-customer (USD: on + off; others as d2c_base),
#           total    = all reported turnover converted to single counting.

adv.groups <- rbindlist(list(trace.adv.groups, dmo.adv.groups, eur.adv.groups, jpy.adv.groups, cny.adv.groups),
                        use.names = TRUE)
setorder(adv.groups, currency, segment, group)
group.map <- rbindlist(list(trace.group.map, dmo.group.map, eur.group.map, jpy.group.map, cny.group.map))
group.map[, bucket := factor(bucket, levels = common.buckets)]
setorder(group.map, currency, bucket)
print(adv.groups[, .(currency, segment, group, adv_local_mn = round(adv_local_mn))])

# --- Write Excel workbooks -------------------------------------------------
# output/liquidity_adv.xlsx     aggregated ADV tables (paste sheet "adv_groups" into the workbook's ADV sheet)
# cleanData/liquidity_clean.xlsx tidy long tables behind them

write_sheets <- function(file, sheets, notes = NULL) {
  wb <- createWorkbook()
  hdr <- createStyle(textDecoration = "bold", border = "bottom", fontName = "Arial", fontSize = 10)
  body <- createStyle(fontName = "Arial", fontSize = 10)
  for (nm in names(sheets)) {
    dt <- copy(sheets[[nm]])
    for (col in names(dt)) if (is.factor(dt[[col]])) dt[, (col) := as.character(get(col))]
    addWorksheet(wb, nm)
    writeData(wb, nm, dt, headerStyle = hdr, withFilter = FALSE)
    addStyle(wb, nm, body, rows = 2:(nrow(dt) + 1), cols = seq_len(ncol(dt)), gridExpand = TRUE)
    num_cols <- which(vapply(dt, is.numeric, logical(1)))
    if (length(num_cols)) addStyle(wb, nm, createStyle(numFmt = "#,##0", fontName = "Arial", fontSize = 10),
                                   rows = 2:(nrow(dt) + 1), cols = num_cols, gridExpand = TRUE, stack = TRUE)
    date_cols <- which(vapply(dt, function(x) inherits(x, "Date"), logical(1)))
    if (length(date_cols)) addStyle(wb, nm, createStyle(numFmt = "yyyy-mm-dd", fontName = "Arial", fontSize = 10),
                                    rows = 2:(nrow(dt) + 1), cols = date_cols, gridExpand = TRUE)
    freezePane(wb, nm, firstRow = TRUE)
    setColWidths(wb, nm, cols = seq_len(ncol(dt)), widths = "auto")
  }
  if (!is.null(notes)) {
    addWorksheet(wb, "notes")
    writeData(wb, "notes", data.frame(Note = notes), colNames = FALSE)
    addStyle(wb, "notes", body, rows = seq_along(notes), cols = 1)
    setColWidths(wb, "notes", cols = 1, widths = 120)
  }
  saveWorkbook(wb, file, overwrite = TRUE)
  invisible(file)
}

output.notes <- c(
  paste0("Generated ", format(Sys.time(), "%Y-%m-%d %H:%M"), " by main_liquidity.R"),
  "adv_groups: average daily volume in local currency mn per trading day, one row per currency x segment x liquidity group. group_map: which exposure bucket belongs to which group.",
  "Liquidity groups follow what each source measures: USD, GBP on remaining maturity (5 groups = buckets); EUR-DE, JPY on original maturity (3 groups: 0-5y, 5-10y, 10y+); EUR-FR, CNY level only (1 group 'all'). Buckets in a group share one ADV pool.",
  "Segments: d2c_base = conservative dealer-to-customer (USD off-the-run D2C; GBP customer);",
  "          d2c_all = all dealer-to-customer (USD on+off D2C; GBP customer); total = all reported turnover.",
  "USD: FINRA TRACE Treasury monthly aggregates, nominal coupons, par value, single-counted per trade. Trading days: SIFMA calendar.",
  "GBP: UK DMO GEMM-reported turnover, conventional gilts only (index-linked and strips excluded), market value. Trading days: UK bank holidays.",
  "USD groups = buckets: <=2y and 2-3y -> 0-3y; 3-5y; 5-7y; 7-10y; 10-20y and >20y -> 10y+.",
  "GBP groups = buckets: 0-12m and 1-3y -> 0-3y; 3-5y; 5-7y; 7-10y; 10-15y and 15y+ -> 10y+.",
  "EUR-DE: Finanzagentur annual gross turnover by instrument (ORIGINAL maturity). d2c = gross x (1 - broker share), single-counted as reported; total = d2c + 0.5 x broker legs; / TARGET trading days.",
  "EUR-DE groups: Schatz + Bobl -> 0-5y; Bund7 + Bund10 -> 5-10y; Bund15 + Bund30 -> 10y+. Reporting is a subset of auction group banks: level is a lower bound.",
  "EUR-FR: single group, Bund level scaled by eur.fr.scale (provisional; replace with AFT bulletin level). d2c_base = d2c_all for EUR (no on/off-the-run split).",
  "JPY: JSDA OTC outright volume (sheet B, repos excluded), all members, face value. customer = Total - Bond Dealers - Others; total = customer + 0.5 x Bond Dealers. Zero-coupon and T-bills excluded.",
  "JPY groups: medium (2/4/5y) -> 0-5y; long (6/10y) -> 5-10y; super-long -> 10y+.",
  "CNY: Bond Connect Flash Reports, Northbound average daily turnover x CGB share; d2c = Bond Connect CGB turnover or all-foreign estimate (/ cny.bondconnect.share) per cny.channel; total = CFETS whole-market CGB turnover entered manually (NA if not).",
  "CNY: single group; no maturity data published.",
  "trace_us_adv_monthly: per month by TRACE bucket; columns <segment>_<run>, e.g. d2c_off = dealer-to-customer, off-the-run.",
  "dmo_gilts_adv_quarterly: per quarter by DMO band, GBP mn per trading day.",
  "Holiday calendars are typed into main_liquidity.R and should be verified against SIFMA and gov.uk.")

write_sheets(
  paste0(output.path, "liquidity_adv.xlsx"),
  list(adv_groups              = adv.groups,
       group_map               = group.map,
       trace_us_adv_monthly    = trace.adv.month,
       dmo_gilts_adv_quarterly = dmo.adv.quarter,
       dmo_gilts_annual        = dmo.annual,
       eur_bunds_audit         = eur.audit,
       eur_bunds_raw           = eur.raw.tables,
       jpy_jsda_adv_monthly    = jpy.adv.month,
       cny_bond_connect_audit  = cny.audit),
  notes = output.notes)

write_sheets(
  paste0(clean.path, "liquidity_clean.xlsx"),
  list(trace_us_monthly_long   = trace,
       dmo_gilts_band_long     = dmo.long,
       dmo_gilts_weekly        = dmo.weekly,
       dmo_gilts_annual        = dmo.annual,
       jpy_jsda_long           = jpy.long))

message("Written: ", output.path, "liquidity_adv.xlsx and ", clean.path, "liquidity_clean.xlsx")
