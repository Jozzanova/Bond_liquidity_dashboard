# trace_treasury_aggregates.R
# ---------------------------------------------------------------------------
# Executed from main_liquidity.R. Requires: raw.trace.path, clean.path,
# output.path, trace.months, trace.download, trace.window, sifma.holidays,
# trading_days_between(), common.buckets.
#
# Source: FINRA TRACE Treasury Monthly Aggregate Statistics
#   https://cdn.finra.org/trace/treasury-aggregates/monthly/ts-monthly-aggregates-YYYY-MM.xlsx
# Par value in USD bn for the month; volume is single-counted per trade.
# ---------------------------------------------------------------------------

trace.base.url <- "https://cdn.finra.org/trace/treasury-aggregates/monthly/ts-monthly-aggregates-"

# --- 1. Locate or download raw files ---------------------------------------

trace.files <- character(0)
for (m in trace.months) {
  f1 <- paste0(raw.trace.path, "ts-monthly-aggregates-", m, ".xlsx")
  f2 <- paste0(raw.trace.path, m, ".xlsx")                # manually downloaded naming
  if (file.exists(f1))      f <- f1
  else if (file.exists(f2)) f <- f2
  else if (trace.download) {
    message("Downloading TRACE ", m)
    download.file(paste0(trace.base.url, m, ".xlsx"), f1, mode = "wb", quiet = TRUE)
    f <- f1
  } else {
    warning("TRACE file for ", m, " not found and trace.download = FALSE"); next
  }
  trace.files <- c(trace.files, f)
}

# --- 2. Parse each file into a long table ----------------------------------

trace.list <- lapply(trace.files, function(file) {
  raw <- as.data.table(read_excel(file, sheet = "Summary", col_names = FALSE, .name_repair = "minimal"))
  setnames(raw, paste0("V", seq_len(ncol(raw))))

  asof <- as.Date(sub("^TRACE Volumes - ", "", raw$V1[1]), format = "%B %d, %Y")
  if (is.na(asof)) stop("Could not read as-of date from title in ", file)

  hdr  <- which(raw$V1 == "Category")[1]
  end  <- which(raw$V1 == "Total"); end <- end[end > hdr][1]
  body <- raw[(hdr + 2):end]

  types <- c("Bills", "FRNs", "Nominal Coupons", "TIPS", "Total")
  body[, label     := trimws(V1)]
  body[, is_type   := label %in% types]
  body[, is_bucket := grepl("^(<=|>)", label)]
  body[, is_run    := label %in% c("On-the-run", "Off-the-run")]
  body[, security_type := label[is_type][1], by = .(grp = cumsum(is_type))]
  body[, maturity_bucket := if (any(is_bucket)) label[is_bucket][1] else "All",
       by = .(grp = cumsum(is_type | is_bucket))]
  body[, run_status := fifelse(is_run, label, "All")]
  body[security_type == "Total", security_type := "All"]

  vals <- body[, .(security_type, maturity_bucket, run_status,
                   ats_trades = as.numeric(V2), ats_par = as.numeric(V3),
                   d2c_trades = as.numeric(V4), d2c_par = as.numeric(V5),
                   tot_trades = as.numeric(V6), tot_par = as.numeric(V7))]

  long <- data.table::melt(
    vals,
    id.vars       = c("security_type", "maturity_bucket", "run_status"),
    measure.vars  = list(trades       = c("ats_trades", "d2c_trades", "tot_trades"),
                         par_value_bn = c("ats_par",    "d2c_par",    "tot_par")),
    variable.name = "venue")
  long[, venue := c("ATS & Interdealer", "Dealer to Customer", "Total")[as.integer(venue)]]
  long[, month := as.Date(format(asof, "%Y-%m-01"))]
  long[, asof  := asof]
  long[, source_file := basename(file)]
  long[]
})
trace <- rbindlist(trace.list)

# --- 3. Trading days and ADV -----------------------------------------------

trace[, month_end := as.Date(format(month + 31, "%Y-%m-01")) - 1]
trace[, trading_days := trading_days_between(month[1], month_end[1], sifma.holidays), by = month]
trace[, adv_bn := par_value_bn / trading_days]
trace[, adv_mn := adv_bn * 1000]
setcolorder(trace, c("month", "asof", "security_type", "maturity_bucket", "run_status", "venue",
                     "trades", "par_value_bn", "trading_days", "adv_bn", "adv_mn"))
setkey(trace, month, security_type, maturity_bucket, run_status, venue)

# --- 4. Consistency checks -------------------------------------------------

trace.chk.run <- trace[maturity_bucket != "All",
  .(diff = sum(par_value_bn[run_status != "All"]) - par_value_bn[run_status == "All"]),
  by = .(month, security_type, maturity_bucket, venue)][abs(diff) > 0.15]
trace.chk.bkt <- trace[security_type %in% c("Nominal Coupons", "TIPS") & run_status == "All",
  .(diff = sum(par_value_bn[maturity_bucket != "All"]) - par_value_bn[maturity_bucket == "All"]),
  by = .(month, security_type, venue)][abs(diff) > 0.15]
if (nrow(trace.chk.run) + nrow(trace.chk.bkt) > 0) {
  warning("TRACE consistency check failed; see trace.chk.run / trace.chk.bkt")
}

# --- 5. Clean data ---------------------------------------------------------

saveRDS(trace, paste0(clean.path, "trace_us_monthly_long.rds"))

# --- 6. ADV by TRACE bucket, per month --------------------------------------
# Nominal coupons only; columns for D2C and Total, each with all / on / off.

trace.bucket.order <- c("<= 2 years", "> 2 years and <= 3 years", "> 3 years and <= 5 years",
                        "> 5 years and <= 7 years", "> 7 years and <= 10 years",
                        "> 10 years and <= 20 years", "> 20 years")

trace.nc <- trace[security_type == "Nominal Coupons" & maturity_bucket != "All" &
                  venue %in% c("Dealer to Customer", "Total")]
trace.nc[, segment := fifelse(venue == "Dealer to Customer", "d2c", "total")]
trace.nc[, run := fcase(run_status == "All", "all", run_status == "On-the-run", "on",
                        run_status == "Off-the-run", "off")]
trace.adv.month <- data.table::dcast(trace.nc, month + trading_days + maturity_bucket ~ segment + run,
                                     value.var = "adv_mn")
trace.adv.month[, maturity_bucket := factor(maturity_bucket, levels = trace.bucket.order)]
setorder(trace.adv.month, month, maturity_bucket)

# --- 7. Trailing average mapped to the common bucket grid -------------------

trace.map <- data.table(
  maturity_bucket = trace.bucket.order,
  bucket = c("0-3y", "0-3y", "3-5y", "5-7y", "7-10y", "10y+", "10y+"))

trace.recent <- sort(unique(trace.nc$month), decreasing = TRUE)[seq_len(min(trace.window, uniqueN(trace.nc$month)))]
trace.adv.common <- trace.nc[month %in% trace.recent][trace.map, on = "maturity_bucket"]
trace.adv.common <- trace.adv.common[, .(adv_mn = sum(adv_mn)), by = .(month, bucket, segment, run)]
trace.adv.common <- trace.adv.common[, .(adv_local_mn = mean(adv_mn)), by = .(bucket, segment, run)]
trace.adv.common[, segment := fcase(segment == "d2c" & run == "off", "d2c_base",
                                    segment == "d2c" & run == "all", "d2c_all",
                                    segment == "total" & run == "all", "total",
                                    default = NA_character_)]
trace.adv.common <- trace.adv.common[!is.na(segment), .(bucket, segment, adv_local_mn)]
trace.adv.common[, `:=`(currency = "USD", unit = "USD mn per day",
                        window = paste0(format(min(trace.recent), "%Y-%m"), " to ",
                                        format(max(trace.recent), "%Y-%m")))]
trace.adv.common[, bucket := factor(bucket, levels = common.buckets)]
setorder(trace.adv.common, segment, bucket)

# Liquidity groups: TRACE reports remaining maturity, so each bucket is its own group
trace.adv.groups <- trace.adv.common[, .(currency, segment, unit, window, group = as.character(bucket), adv_local_mn)]
trace.adv.groups[segment == "d2c_base", unit := "USD mn per day (TRACE nominal coupons, par value; off-the-run, dealer-to-customer; single-counted per trade; remaining maturity)"]
trace.adv.groups[segment == "d2c_all",  unit := "USD mn per day (TRACE nominal coupons, par value; on- and off-the-run, dealer-to-customer; single-counted per trade; remaining maturity)"]
trace.adv.groups[segment == "total",    unit := "USD mn per day (TRACE nominal coupons, par value; all venues incl. ATS/interdealer, all issues; single-counted per trade; remaining maturity)"]
trace.group.map  <- data.table(currency = "USD", bucket = common.buckets, group = common.buckets)

message("TRACE: ", uniqueN(trace$month), " months loaded, ", nrow(trace), " rows")
