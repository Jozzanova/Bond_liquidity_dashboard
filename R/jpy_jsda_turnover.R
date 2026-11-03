# jpy_jsda_turnover.R
# ---------------------------------------------------------------------------
# Executed from main_liquidity.R. Requires: raw.jpy.path, jpy.window,
# jp.holidays, jpy.include.others, trading_days_between(), common.buckets.
#
# Source: JSDA, Trading Volume of Over-the-Counter (OTC) Bonds, monthly
#   current FY: https://www.jsda.or.jp/shiryoshitsu/toukei/tentoubaibai/koushasai.xlsx
#   FY2025:     https://www.jsda.or.jp/shiryoshitsu/toukei/tentoubaibai/koushasai2025.xlsx
# Sheet "(B) 一般売買高" = outright transactions only (repos are on sheet C),
# all JSDA members, sell + purchase, face value, units of JPY 100 mn.
# JGB columns are by ORIGINAL maturity: super-long (>10y), long (6y, 10y),
# medium (2y, 4y, 5y), zero-coupon (discount, STRIPS), T-bills.
#
# Counting: members report their own legs, so trades with a customer appear
# once and member-to-member trades ("Bond Dealers" category) appear twice.
#   customer = Total - Bond Dealers (- Others, see jpy.include.others)
#   total    = customer + 0.5 x Bond Dealers (+ Others if included)
# "Others" includes members' auction allotments (primary market) and is
# excluded by default.
# ---------------------------------------------------------------------------

jpy.files <- sort(list.files(raw.jpy.path, pattern = "^koushasai.*\\.xlsx$", full.names = TRUE))
if (length(jpy.files) == 0) stop("No koushasai*.xlsx files in ", raw.jpy.path)
jpy.sheet <- "(Ｂ)一般売買高"     # full-width B; matched by pattern below for safety

jpy.list <- lapply(jpy.files, function(f) {
  sheets <- excel_sheets(f)
  sh <- sheets[grepl("一般売買高", sheets) & !grepl("証券", sheets)][1]   # all members, outright
  if (is.na(sh)) stop("Outright sheet not found in ", basename(f))
  raw <- as.data.table(read_excel(f, sheet = sh, col_names = FALSE, .name_repair = "minimal"))
  setnames(raw, paste0("V", seq_len(ncol(raw))))
  # Verify the JGB sub-columns are where expected (row 4, columns E:I)
  hdr4 <- tolower(paste(unlist(raw[4, 5:9]), collapse = " | "))
  if (!grepl("over 10-year", hdr4) || !grepl("medium-term", hdr4) || !grepl("treasury discount", hdr4)) {
    stop("JGB column layout changed in ", basename(f), ": ", hdr4)
  }
  dt <- raw[5:.N, .(month_lab = V1, category = V3,
                    jgb_total  = as.numeric(V4),
                    super_long = as.numeric(V5),
                    long       = as.numeric(V6),
                    medium     = as.numeric(V7),
                    zero_coupon = as.numeric(V8),
                    tbills     = as.numeric(V9))]
  dt <- dt[!is.na(month_lab) & !is.na(category)]
  dt[, month := as.Date(paste0(gsub("/", "-", month_lab), "-01"))]
  dt[, source_file := basename(f)]
  dt[]
})
jpy.raw <- rbindlist(jpy.list)
jpy.raw <- unique(jpy.raw, by = c("month", "category"))
jpy.raw[, category := trimws(category)]

# Sanity: sum of JGB classes equals the JGB total (rounding tolerance)
jpy.chk <- jpy.raw[, .(diff = super_long + long + medium + zero_coupon + tbills - jgb_total),
                   by = .(month, category)][abs(diff) > 5]
if (nrow(jpy.chk) > 0) warning("JSDA: JGB sub-columns do not sum to total for ", nrow(jpy.chk), " rows")

# --- Long table: month x category x class, JPY mn face value ----------------

jpy.long <- data.table::melt(jpy.raw, id.vars = c("month", "category", "source_file"),
                             measure.vars = c("super_long", "long", "medium", "zero_coupon", "tbills"),
                             variable.name = "jgb_class", value.name = "volume_100mn")
jpy.long[, volume_jpy_mn := volume_100mn * 100]
jpy.long[, month_end := as.Date(format(month + 31, "%Y-%m-01")) - 1]
jpy.long[, trading_days := trading_days_between(month[1], month_end[1], jp.holidays), by = month]
setkey(jpy.long, month, jgb_class, category)

# --- Segments per month and class ------------------------------------------

jpy.seg <- data.table::dcast(jpy.long[category %in% c("Total", "Bond Dealers", "Others")],
                             month + trading_days + jgb_class ~ category, value.var = "volume_jpy_mn")
setnames(jpy.seg, c("Total", "Bond Dealers", "Others"), c("total_reported", "dealers", "others"))
jpy.seg[, customer := total_reported - dealers - others]
if (isTRUE(jpy.include.others)) jpy.seg[, customer := customer + others]
jpy.seg[, total_single := customer + 0.5 * dealers]
jpy.seg[, `:=`(d2c_adv_mn = customer / trading_days, total_adv_mn = total_single / trading_days)]
setorder(jpy.seg, month, jgb_class)

# --- Trailing window, liquidity groups ------------------------------------
# JSDA classes are by ORIGINAL maturity, which supports three groups on
# remaining maturity: medium (2/4/5y) -> 0-5y, long (6/10y) -> 5-10y,
# super-long -> 10y+. No within-group split.

jpy.recent <- sort(unique(jpy.seg$month), decreasing = TRUE)[seq_len(min(jpy.window, uniqueN(jpy.seg$month)))]
jpy.avg <- jpy.seg[month %in% jpy.recent, .(d2c_adv_mn = mean(d2c_adv_mn), total_adv_mn = mean(total_adv_mn)),
                   by = jgb_class]
jpy.map <- data.table(jgb_class = c("medium", "long", "super_long"), group = c("0-5y", "5-10y", "10y+"))
jpy.group <- jpy.avg[jpy.map, on = "jgb_class"]

jpy.adv.groups <- rbindlist(list(
  jpy.group[, .(currency = "JPY", segment = "d2c_base", group, adv_local_mn = d2c_adv_mn)],
  jpy.group[, .(currency = "JPY", segment = "d2c_all",  group, adv_local_mn = d2c_adv_mn)],
  jpy.group[, .(currency = "JPY", segment = "total",    group, adv_local_mn = total_adv_mn)]))
jpy.adv.groups[segment %in% c("d2c_base", "d2c_all"),
               unit := "JPY mn per day (JSDA OTC outright JGBs, face value, all members; Total less Bond Dealers less Others, single-counted as reported; no on/off-the-run split so d2c_base = d2c_all; groups by original maturity class)"]
jpy.adv.groups[segment == "total",
               unit := "JPY mn per day (JSDA OTC outright JGBs, face value, all members; customer + 0.5 x Bond Dealers, Others excluded; groups by original maturity class)"]
jpy.adv.groups[, window := paste0(format(min(jpy.recent), "%Y-%m"), " to ", format(max(jpy.recent), "%Y-%m"))]
setcolorder(jpy.adv.groups, c("currency", "segment", "unit", "window", "group", "adv_local_mn"))
jpy.group.map <- data.table(currency = "JPY", bucket = common.buckets, group = c("0-5y", "0-5y", "5-10y", "5-10y", "10y+"))

# Monthly ADV by JSDA class for the workbook (excluded classes shown for reference)
jpy.adv.month <- jpy.seg[, .(month, trading_days, jgb_class, customer_jpy_mn = customer,
                             dealers_jpy_mn = dealers, others_jpy_mn = others,
                             d2c_adv_mn, total_adv_mn)]

message("JPY: ", uniqueN(jpy.seg$month), " months loaded (", format(min(jpy.seg$month), "%Y-%m"), " to ",
        format(max(jpy.seg$month), "%Y-%m"), "), window ", jpy.window, " months")
