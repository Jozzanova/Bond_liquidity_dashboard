# cny_bond_connect.R
# ---------------------------------------------------------------------------
# Executed from main_liquidity.R. Requires: raw.cny.path, cny.scrape,
# cny.window, cny.channel, cny.bondconnect.share, cny.market.cgb.adv.bn,
# common.buckets.
#
# Source: Bond Connect Company Limited, monthly Flash Reports
#   https://www.chinabondconnect.com/en/Resource/Flash-Report.html
# Each report states Northbound monthly trading volume (RMB bn), monthly
# average daily turnover (RMB bn) and the shares of the two most traded bond
# types (policy financial bonds, Chinese government bonds). Reports are HTML
# pages; the highlights sentence is parsed with regular expressions, and a
# dated snapshot is saved to rawData/cny_bond_connect/.
#
# Level choice (cny.channel):
#   "bond_connect": CGB turnover through Bond Connect only
#   "all_foreign":  Bond Connect CGB turnover / cny.bondconnect.share, i.e.
#                   an estimate of all foreign-investor CGB turnover across
#                   Bond Connect and CIBM Direct (HKMA, July 2026: Bond Connect
#                   carries over 64 % of foreign turnover in the CIBM)
# total = whole-market CGB cash turnover (CFETS), entered as cny.market.cgb.adv.bn.
# Maturity split: none published; CNY is a single liquidity group.
# ---------------------------------------------------------------------------

cny.index.url <- "https://www.chinabondconnect.com/en/Resource/Flash-Report.html"

# --- 0. Embedded fallback (read from the Flash Reports, 2026-08-26) --------
# CGB share is NA where the report page was not read; it is filled with the
# turnover-weighted mean of the months that were.
cny.fallback <- data.table(
  month      = as.Date(c("2025-08-01", "2025-09-01", "2025-10-01", "2025-11-01", "2025-12-01", "2026-01-01",
                         "2026-02-01", "2026-03-01", "2026-04-01", "2026-05-01", "2026-06-01", "2026-07-01")),
  volume_bn  = c(750.1, 581.0, 572.3, 667.8, 639.5, 942.5, 805.5, 1224.1, 984.8, 893.1, 864.9, 858.6),
  adt_bn     = c(35.7, 25.3, 31.8, 33.4, 27.8, 44.9, 50.3, 55.6, 46.9, 47.0, 41.2, 37.3),
  cgb_share  = c(0.38, NA, NA, NA, 0.39, 0.34, NA, 0.24, 0.22, NA, NA, 0.22),
  pfb_share  = c(0.41, NA, NA, NA, 0.49, 0.51, NA, 0.59, 0.58, NA, NA, 0.59))

# --- 1. Scraper -------------------------------------------------------------

cny_parse_report <- function(url) {
  txt <- rvest::html_text2(rvest::read_html(url))
  txt <- gsub("\\s+", " ", txt)
  num <- function(p) { m <- regmatches(txt, regexpr(p, txt, perl = TRUE))
                       if (length(m) == 0) return(NA_real_); as.numeric(gsub(",", "", sub(p, "\\1", m, perl = TRUE))) }
  vol <- num("monthly trading volume (?:of \\w+ |for \\w+ )?(?:was|stood at) RMB ([0-9,\\.]+) billion")
  adt <- num("average daily turnover stood at RMB ([0-9,\\.]+) billion")
  # Shares: order of bond types varies between reports
  sh  <- regmatches(txt, regexpr("(Policy financial bond|Chinese government bond) and (Policy financial bond|Chinese government bond) were the most popular bond types, accounting for ([0-9]+)% and ([0-9]+)%",
                                 txt, ignore.case = TRUE, perl = TRUE))
  cgb <- pfb <- NA_real_
  if (length(sh) == 1) {
    parts <- regmatches(sh, gregexpr("(Policy financial bond|Chinese government bond|[0-9]+(?=%))", sh, ignore.case = TRUE, perl = TRUE))[[1]]
    first_is_cgb <- grepl("government", parts[1], ignore.case = TRUE)
    p1 <- as.numeric(parts[3]) / 100; p2 <- as.numeric(parts[4]) / 100
    cgb <- if (first_is_cgb) p1 else p2
    pfb <- if (first_is_cgb) p2 else p1
  }
  mon <- regmatches(url, regexpr("(January|February|March|April|May|June|July|August|September|October|November|December)-[0-9]{4}", url))
  data.table(month = as.Date(paste0("01-", gsub("-", "-", mon)), format = "%d-%B-%Y"),
             volume_bn = vol, adt_bn = adt, cgb_share = cgb, pfb_share = pfb, url = url)
}

cny_scrape <- function(index_url, n_months) {
  page  <- rvest::read_html(index_url)
  links <- rvest::html_attr(rvest::html_elements(page, "a"), "href")
  links <- unique(links[grepl("Flash-Report/Bond-Connect-Flash-Report", links)])
  if (length(links) == 0) stop("No Flash Report links found on index page")
  # Index page lists the most recent ~12 reports; parse them all and keep n_months
  dt <- rbindlist(lapply(links, function(u) tryCatch(cny_parse_report(u), error = function(e) NULL)), fill = TRUE)
  dt <- dt[!is.na(month) & !is.na(adt_bn)]
  setorder(dt, -month)
  dt[seq_len(min(n_months, .N))][order(month)]
}

# --- 2. Get data: scrape -> snapshot -> fallback ----------------------------

cny.data <- NULL
if (isTRUE(cny.scrape)) {
  cny.data <- tryCatch(cny_scrape(cny.index.url, cny.window), error = function(e) {
    warning("Bond Connect scrape failed: ", conditionMessage(e), ". Using snapshot or fallback."); NULL })
  if (!is.null(cny.data) && nrow(cny.data) > 0) {
    snap <- paste0(raw.cny.path, "bond_connect_flash_", format(Sys.Date(), "%Y%m%d"), ".xlsx")
    openxlsx::write.xlsx(cny.data, snap, overwrite = TRUE)
    message("CNY: scraped ", nrow(cny.data), " Flash Reports, snapshot saved to ", basename(snap))
  } else cny.data <- NULL
}
if (is.null(cny.data)) {
  snaps <- sort(list.files(raw.cny.path, pattern = "^bond_connect_flash.*\\.xlsx$", full.names = TRUE), decreasing = TRUE)
  if (length(snaps) > 0) {
    cny.data <- as.data.table(read_excel(snaps[1])); cny.data[, month := as.Date(month)]
    message("CNY: using snapshot ", basename(snaps[1]))
  } else { cny.data <- copy(cny.fallback); message("CNY: using embedded fallback (Aug 2025 to Jul 2026)") }
}

# --- 3. Monthly CGB turnover through Bond Connect ---------------------------

cny.month <- copy(cny.data)
cny.fill.share <- cny.month[!is.na(cgb_share), sum(cgb_share * adt_bn) / sum(adt_bn)]
cny.month[, cgb_share_used := fifelse(is.na(cgb_share), cny.fill.share, cgb_share)]
cny.month[, cgb_adt_bn := adt_bn * cgb_share_used]
cny.month[, trading_days := round(volume_bn / adt_bn)]         # implied by the report itself
setorder(cny.month, month)

cny.recent <- tail(cny.month$month, cny.window)
cny.avg <- cny.month[month %in% cny.recent, .(adt_bn = mean(adt_bn), cgb_adt_bn = mean(cgb_adt_bn),
                                              cgb_share = sum(cgb_adt_bn) / sum(adt_bn))]

# --- 4. Level by channel and whole-market total ----------------------------

cny.bc.cgb.mn      <- cny.avg$cgb_adt_bn * 1000
cny.foreign.cgb.mn <- cny.bc.cgb.mn / cny.bondconnect.share
cny.d2c.mn <- switch(cny.channel, bond_connect = cny.bc.cgb.mn, all_foreign = cny.foreign.cgb.mn,
                     stop("cny.channel must be 'bond_connect' or 'all_foreign'"))
cny.total.mn <- if (is.na(cny.market.cgb.adv.bn)) NA_real_ else cny.market.cgb.adv.bn * 1000

# --- 5. Single liquidity group (no maturity data) ---------------------------

cny.adv.groups <- data.table(currency = "CNY",
                             segment  = c("d2c_base", "d2c_all", "total"),
                             group    = "all",
                             adv_local_mn = c(cny.d2c.mn, cny.d2c.mn, cny.total.mn))
cny.adv.groups[segment %in% c("d2c_base", "d2c_all"),
               unit := if (cny.channel == "bond_connect")
                 "CNY mn per day (Bond Connect Northbound ADT x CGB share, Flash Reports; foreign-investor turnover through Bond Connect only; no on/off-the-run split so d2c_base = d2c_all; single group, no maturity data)"
               else sprintf("CNY mn per day (Bond Connect Northbound ADT x CGB share / %.2f = all-foreign CGB turnover estimate incl. CIBM Direct, Flash Reports and HKMA share; no on/off-the-run split so d2c_base = d2c_all; single group, no maturity data)", cny.bondconnect.share)]
cny.adv.groups[segment == "total",
               unit := "CNY mn per day (whole interbank market CGB cash turnover, CFETS, entered manually as cny.market.cgb.adv.bn; single group, no maturity data)"]
cny.adv.groups[, window := paste0(format(min(cny.recent), "%Y-%m"), " to ", format(max(cny.recent), "%Y-%m"))]
setcolorder(cny.adv.groups, c("currency", "segment", "unit", "window", "group", "adv_local_mn"))
cny.group.map <- data.table(currency = "CNY", bucket = common.buckets, group = "all")

cny.audit <- cny.month[, .(month, trading_days, volume_bn, adt_bn, cgb_share, cgb_share_used, cgb_adt_bn)]

message("CNY: Bond Connect ADT ", round(cny.avg$adt_bn, 1), " bn, CGB share ", round(cny.avg$cgb_share, 3),
        ", CGB ADT ", round(cny.avg$cgb_adt_bn, 1), " bn (", cny.channel, " -> d2c ",
        round(cny.d2c.mn / 1000, 1), " bn per day)")
