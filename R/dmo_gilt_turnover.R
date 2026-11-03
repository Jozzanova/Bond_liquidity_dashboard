# dmo_gilt_turnover.R
# ---------------------------------------------------------------------------
# Executed from main_liquidity.R. Requires: raw.dmo.path, clean.path,
# output.path, dmo.window, uk.holidays, trading_days_between(), common.buckets.
#
# Source: UK DMO gilt turnover data reported by GEMMs
#   https://www.dmo.gov.uk/data/gilt-market/turnover-data
# Turnover is market value; "customer" (own-account counterparties) is the
# dealer-to-customer analogue and single-counted; "professional" (DMO, BoE,
# GEMMs, IDBs, agency brokers) may double count via IDBs.
# ---------------------------------------------------------------------------

# --- 1. Locate raw files (latest by name if several) -----------------------

dmo_latest <- function(pattern) {
  f <- sort(list.files(raw.dmo.path, pattern = pattern, full.names = TRUE), decreasing = TRUE)
  if (length(f) == 0) stop("No file matching ", pattern, " in ", raw.dmo.path)
  f[1]
}
dmo.file.bands  <- dmo_latest("^gemm-turnover-by-maturity-band.*\\.xlsx$")
dmo.file.weekly <- dmo_latest("^all-gemms-turnover.*\\.xls$")
dmo.file.annual <- dmo_latest("^annual-turnover-report.*\\.xls$")

# --- 2. Turnover by maturity band (quarterly, one sheet per year) ----------

dmo.band.levels <- c("0-1y", "1-3y", "3-5y", "5-7y", "7-10y", "10-15y", "15y+", "Index-linked", "Strips")
dmo.band.map <- data.table(
  raw  = c("0-12 months", "1-3 years", "3-5 years", "5-7 years", "7-10 years",
           "10-15 years", "15+ years", "index-linked", "strips"),
  band = dmo.band.levels)

dmo.sheets <- grep("^\\d{4}$", excel_sheets(dmo.file.bands), value = TRUE)
dmo.list <- lapply(dmo.sheets, function(sheet) {
  raw <- as.data.table(read_excel(dmo.file.bands, sheet = sheet, col_names = FALSE, .name_repair = "minimal"))
  setnames(raw, paste0("V", seq_len(ncol(raw))))
  raw[, V1 := as.character(V1)]
  out <- list(); quarter <- NA_integer_; in_table <- FALSE
  for (i in seq_len(nrow(raw))) {
    lab <- raw$V1[i]
    if (is.na(lab)) next
    if (grepl("^Q[1-4]", lab)) { quarter <- as.integer(substr(lab, 2, 2)); in_table <- FALSE; next }
    if (lab == "BAND")  { in_table <- TRUE;  next }
    if (lab == "Total") { in_table <- FALSE; next }
    if (in_table) {
      out[[length(out) + 1]] <- data.table(
        year = as.integer(sheet), quarter = quarter, raw_band = lab,
        customer     = as.numeric(raw$V2[i]),
        professional = as.numeric(raw$V4[i]),
        combined     = as.numeric(raw$V6[i]))
    }
  }
  rbindlist(out)
})
dmo.bands <- rbindlist(dmo.list)
dmo.bands[, raw := tolower(trimws(raw_band))]
dmo.bands[, raw := sub("mths$", "months", raw)]
dmo.bands[, raw := sub("yrs$", "years", raw)]
dmo.bands <- dmo.band.map[dmo.bands, on = "raw"]
if (any(is.na(dmo.bands$band))) {
  warning("Unrecognised DMO band labels dropped: ",
          paste(unique(dmo.bands[is.na(band), raw_band]), collapse = ", "))
  dmo.bands <- dmo.bands[!is.na(band)]
}
dmo.bands[, band := factor(band, levels = dmo.band.levels)]
dmo.bands[, period_start := as.Date(sprintf("%d-%02d-01", year, (quarter - 1) * 3 + 1))]
dmo.bands[, period_end   := as.Date(sprintf("%d-%02d-01", year + (quarter == 4), (quarter %% 4) * 3 + 1)) - 1]

dmo.long <- data.table::melt(
  dmo.bands[, .(year, quarter, period_start, period_end, band, customer, professional, combined)],
  id.vars = c("year", "quarter", "period_start", "period_end", "band"),
  variable.name = "segment", value.name = "turnover_gbp_mn")
dmo.long[, trading_days := trading_days_between(period_start[1], period_end[1], uk.holidays),
         by = .(period_start, period_end)]
dmo.long[, adv_gbp_mn := turnover_gbp_mn / trading_days]
setkey(dmo.long, year, quarter, band, segment)

# --- 3. Weekly aggregate turnover and annual report ------------------------

raw <- as.data.table(read_excel(dmo.file.weekly, sheet = 1, col_names = FALSE, .name_repair = "minimal"))
setnames(raw, paste0("V", seq_len(ncol(raw))))
hdr <- which(raw$V1 == "Date")[1]
dmo.weekly <- raw[(hdr + 1):.N, .(week_ending = as.Date(as.numeric(V1), origin = "1899-12-30"),
                                   customer = as.numeric(V2), professional = as.numeric(V3),
                                   combined = as.numeric(V4))][!is.na(week_ending)]
setorder(dmo.weekly, week_ending)
dmo.weekly[, customer_share := customer / combined]

raw <- as.data.table(read_excel(dmo.file.annual, sheet = 1, col_names = FALSE, .name_repair = "minimal"))
setnames(raw, paste0("V", seq_len(ncol(raw))))
hdr <- which(raw$V1 == "Financial Year")[1]
dmo.annual <- raw[(hdr + 1):.N, .(financial_year = V1,
                                   adv_gbp_bn = as.numeric(V2), annual_turnover_gbp_bn = as.numeric(V3),
                                   gross_portfolio_mv_gbp_bn = as.numeric(V4),
                                   net_portfolio_mv_gbp_bn = as.numeric(V5),
                                   turnover_ratio_gross = as.numeric(V6),
                                   turnover_ratio_net = as.numeric(V7))][!is.na(adv_gbp_bn)]
rm(raw, hdr)

# --- 4. Clean data ---------------------------------------------------------

saveRDS(dmo.long,  paste0(clean.path, "dmo_gilts_turnover_by_band_long.rds"))

# --- 5. ADV by DMO band, per quarter --------------------------------------

dmo.adv.quarter <- data.table::dcast(dmo.long, year + quarter + trading_days + band ~ segment,
                                     value.var = "adv_gbp_mn")
setorder(dmo.adv.quarter, year, quarter, band)

# --- 6. Trailing average mapped to the common bucket grid -------------------

dmo.map <- data.table(
  band   = c("0-1y", "1-3y", "3-5y", "5-7y", "7-10y", "10-15y", "15y+"),
  bucket = c("0-3y", "0-3y", "3-5y", "5-7y", "7-10y", "10y+", "10y+"))

dmo.recent <- unique(dmo.long[, .(year, quarter)])[order(-year, -quarter)][seq_len(min(dmo.window, .N))]
dmo.adv.common <- dmo.long[dmo.recent, on = .(year, quarter)][dmo.map, on = "band"]
dmo.adv.common <- dmo.adv.common[, .(adv_gbp_mn = sum(adv_gbp_mn)), by = .(year, quarter, bucket, segment)]
dmo.adv.common <- dmo.adv.common[, .(adv_local_mn = mean(adv_gbp_mn)), by = .(bucket, segment)]
dmo.adv.common <- rbindlist(list(
  dmo.adv.common[segment == "customer", .(bucket, segment = "d2c_base", adv_local_mn)],
  dmo.adv.common[segment == "customer", .(bucket, segment = "d2c_all",  adv_local_mn)],
  dmo.adv.common[segment == "combined", .(bucket, segment = "total",    adv_local_mn)]))
dmo.adv.common[, `:=`(currency = "GBP", unit = "GBP mn per day (market value)",
                      window = paste0(dmo.recent[.N, sprintf("%dQ%d", year, quarter)], " to ",
                                      dmo.recent[1,  sprintf("%dQ%d", year, quarter)]))]
dmo.adv.common[, bucket := factor(bucket, levels = common.buckets)]
setorder(dmo.adv.common, segment, bucket)

# Liquidity groups: DMO reports remaining maturity, so each bucket is its own group
dmo.adv.groups <- dmo.adv.common[, .(currency, segment, unit, window, group = as.character(bucket), adv_local_mn)]
dmo.adv.groups[segment %in% c("d2c_base", "d2c_all"),
               unit := "GBP mn per day (DMO GEMM-reported conventional gilts, market value; customer counterparties only, single-counted; no on/off-the-run split so d2c_base = d2c_all; remaining maturity)"]
dmo.adv.groups[segment == "total",
               unit := "GBP mn per day (DMO GEMM-reported conventional gilts, market value; customer + professional as reported, professional may double count via IDBs; remaining maturity)"]
dmo.group.map  <- data.table(currency = "GBP", bucket = common.buckets, group = common.buckets)

message("DMO: ", uniqueN(dmo.long[, .(year, quarter)]), " quarters loaded, latest ",
        dmo.recent[1, sprintf("%dQ%d", year, quarter)])
