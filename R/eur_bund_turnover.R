# eur_bund_turnover.R
# ---------------------------------------------------------------------------
# Executed from main_liquidity.R. Requires: raw.eur.path, eur.scrape,
# eur.trading.days, eur.fr.scale, common.buckets.
#
# Source: Deutsche Finanzagentur, Trading Volumes (annual), HTML tables at
#   https://www.deutsche-finanzagentur.de/en/federal-securities/trading/secondary-market/trading-volumes/year
# The page has no downloadable file, so the tables are scraped with rvest and
# saved as a dated snapshot in rawData/eur_bunds/. If scraping is switched off
# or fails, the latest snapshot is used; if none exists, the embedded copy of
# the 2024 and 2025 tables (retrieved 2026-08-25) is used.
#
# Definitions (Finanzagentur): gross = sales plus purchases reported by a
# representative subset of Bund Issues Auction Group banks; instruments are
# classified by ORIGINAL maturity; broker = interdealer-like counterparties.
#
# Adjustments, all kept as columns in eur.audit:
#   customer-facing legs (gross x (1 - broker share)) are reported once by the
#     bank and are used as they are (dealer-to-customer analogue);
#   broker legs (gross x broker share) are reported by both banks and are halved;
#   total = customer + 0.5 x broker;
#   per trading day: / eur.trading.days
# ---------------------------------------------------------------------------

eur.url <- "https://www.deutsche-finanzagentur.de/en/federal-securities/trading/secondary-market/trading-volumes/year"

# --- 0. Embedded fallback (typed from the page, retrieved 2026-08-25) ------

eur.fallback <- list(
  instruments = data.table(
    year         = rep(c(2024, 2025), each = 9),
    instrument   = rep(c("Bobl", "Bubill", "Bund7", "Bund10", "Bund15", "Bund30", "Green", "ILB", "Schatz"), 2),
    gross_eur_bn = c(1402, 628, 260, 2474, 196, 641, 117, 58, 962,
                     1389, 501, 224, 2714, 220, 785, 112, 41, 1100)),
  counterparties = data.table(
    year         = rep(c(2024, 2025), each = 8),
    counterparty = rep(c("Asset Manager", "Banks", "Broker", "Hedge funds", "Pension funds",
                         "Others", "Insurances", "Central Banks"), 2),
    gross_eur_bn = c(1635, 1283, 1754, 1214, 93, 69, 46, 644,
                     1595, 1261, 2137, 1159, 120, 66, 49, 725)),
  totals = data.table(year = c(2024, 2025), gross_total_eur_bn = c(6738, 7113), net_total_eur_bn = c(337, 272)))

# --- 1. Scraper -------------------------------------------------------------
# Numbers on the page are integers with inconsistent separators ("1,067",
# "1.188", "1;159", "-0"), so parsing strips everything but digits and sign.

eur_parse_number <- function(x) {
  x <- trimws(as.character(x))
  x <- gsub("[^0-9.,;-]", "", x)
  x <- gsub("[;,]", "", x)
  # a dot followed by exactly three digits is a thousands separator on this page
  x <- ifelse(grepl("^-?\\d{1,3}\\.\\d{3}$", x), gsub("\\.", "", x), x)
  suppressWarnings(as.numeric(x))
}

eur_table_to_long <- function(tab, label_col, value_name) {
  tab <- as.data.table(tab)
  yrs <- names(tab)[-1]
  setnames(tab, c(label_col, yrs))
  long <- data.table::melt(tab, id.vars = label_col, variable.name = "year", value.name = value_name)
  long[, year := as.integer(as.character(year))]
  long[, (value_name) := eur_parse_number(get(value_name))]
  long[!is.na(year)]
}

eur_scrape <- function(url) {
  page <- rvest::read_html(url)
  tabs <- rvest::html_table(page, fill = TRUE)
  first_col <- function(t) tolower(paste(t[[1]], collapse = " "))
  head_col  <- function(t) tolower(names(t)[1])
  is_gross  <- vapply(tabs, function(t) grepl("gross", head_col(t)), logical(1))
  inst <- tabs[is_gross & vapply(tabs, function(t) grepl("schatz", first_col(t)), logical(1))]
  cpty <- tabs[is_gross & vapply(tabs, function(t) grepl("broker", first_col(t)), logical(1))]
  tot  <- tabs[vapply(tabs, function(t) grepl("trading volume", first_col(t)) &&
                                         grepl("net trading", first_col(t)), logical(1))]
  if (length(inst) != 1 || length(cpty) != 1 || length(tot) != 1) {
    stop("Finanzagentur page layout not recognised (found ", length(inst), " instrument, ",
         length(cpty), " counterparty, ", length(tot), " totals tables)")
  }
  inst <- eur_table_to_long(inst[[1]], "instrument", "gross_eur_bn")
  cpty <- eur_table_to_long(cpty[[1]], "counterparty", "gross_eur_bn")
  totl <- as.data.table(tot[[1]]); setnames(totl, c("item", names(totl)[-1]))
  totl <- data.table::melt(totl, id.vars = "item", variable.name = "year", value.name = "value")
  totl[, year := as.integer(as.character(year))]
  totl[, value := eur_parse_number(value)]
  totl <- data.table::dcast(totl, year ~ item, value.var = "value")
  setnames(totl, names(totl), c("year", "gross_total_eur_bn", "net_total_eur_bn")[seq_len(ncol(totl))])
  # basic sanity: instrument sum within a few per cent of the reported total
  chk <- inst[, .(s = sum(gross_eur_bn)), by = year][totl, on = "year"]
  if (any(abs(chk$s / chk$gross_total_eur_bn - 1) > 0.05, na.rm = TRUE)) {
    warning("Scraped instrument sums differ from reported totals by more than 5 %; check the tables")
  }
  list(instruments = inst, counterparties = cpty, totals = totl)
}

# --- 2. Get data: scrape -> snapshot -> fallback ----------------------------

eur.data <- NULL
if (isTRUE(eur.scrape)) {
  eur.data <- tryCatch(eur_scrape(eur.url), error = function(e) {
    warning("Finanzagentur scrape failed: ", conditionMessage(e), ". Using snapshot or fallback.")
    NULL
  })
  if (!is.null(eur.data)) {
    snap <- paste0(raw.eur.path, "finanzagentur_turnover_", format(Sys.Date(), "%Y%m%d"), ".xlsx")
    openxlsx::write.xlsx(c(eur.data, list(source = data.frame(
      note = c(paste("Scraped from", eur.url), paste("Retrieved", Sys.time()))))), snap, overwrite = TRUE)
    message("EUR: scraped Finanzagentur page, snapshot saved to ", basename(snap))
  }
}
if (is.null(eur.data)) {
  snaps <- sort(list.files(raw.eur.path, pattern = "^finanzagentur_turnover.*\\.xlsx$", full.names = TRUE),
                decreasing = TRUE)
  if (length(snaps) > 0) {
    eur.data <- list(
      instruments    = as.data.table(read_excel(snaps[1], sheet = "instruments")),
      counterparties = as.data.table(read_excel(snaps[1], sheet = "counterparties")),
      totals         = as.data.table(read_excel(snaps[1], sheet = "totals")))
    message("EUR: using snapshot ", basename(snaps[1]))
  } else {
    eur.data <- eur.fallback
    message("EUR: using embedded fallback tables (2024, 2025)")
  }
}
eur.inst <- eur.data$instruments
eur.cpty <- eur.data$counterparties
eur.tot  <- eur.data$totals
eur.year <- max(eur.inst$year)

# --- 3. Customer-like share from the counterparty table ---------------------

eur.broker.share <- eur.cpty[year == eur.year, sum(gross_eur_bn[counterparty == "Broker"]) / sum(gross_eur_bn)]
eur.cust.share   <- 1 - eur.broker.share

# --- 4. Liquidity groups -----------------------------------------------------
# The Finanzagentur classifies by ORIGINAL maturity, which supports three
# groups on remaining maturity and nothing finer: 0-5y (Schatz, Bobl),
# 5-10y (Bund 7, Bund 10), 10y+ (Bund 15, Bund 30). No within-group split.

eur.map <- data.table(
  instrument = c("Schatz", "Bobl", "Bund7", "Bund10", "Bund15", "Bund30"),
  group      = c("0-5y",   "0-5y", "5-10y", "5-10y",  "10y+",   "10y+"))
eur.group.levels <- c("0-5y", "5-10y", "10y+")
eur.de.group.map <- data.table(currency = "EUR-DE", bucket = common.buckets,
                               group = c("0-5y", "0-5y", "5-10y", "5-10y", "10y+"))

eur.de <- eur.inst[year == eur.year][eur.map, on = "instrument"]
if (any(is.na(eur.de$gross_eur_bn))) stop("Missing instrument rows for ", eur.year, ": ",
                                          paste(eur.de[is.na(gross_eur_bn), instrument], collapse = ", "))
# Customer-facing legs are reported once (single-counted); broker legs are
# reported by both banks and are halved. Uniform counterparty mix across
# instruments is assumed (no instrument x counterparty table is published).
eur.de[, customer_bn     := gross_eur_bn * eur.cust.share]
eur.de[, broker_bn       := gross_eur_bn * eur.broker.share]
eur.de[, total_single_bn := customer_bn + 0.5 * broker_bn]
eur.de[, d2c_adv_mn      := customer_bn     * 1000 / eur.trading.days]
eur.de[, total_adv_mn    := total_single_bn * 1000 / eur.trading.days]

eur.de.group <- eur.de[, .(total_adv_mn = sum(total_adv_mn), d2c_adv_mn = sum(d2c_adv_mn)), by = group]
eur.de.group[, group := factor(group, levels = eur.group.levels)]
setorder(eur.de.group, group)

# --- 5. Group tables for DE (three groups) and FR (one group, scaled level) ----

eur.window <- as.character(eur.year)
eur.de.groups <- rbindlist(list(
  eur.de.group[, .(currency = "EUR-DE", segment = "d2c_base", group = as.character(group), adv_local_mn = d2c_adv_mn)],
  eur.de.group[, .(currency = "EUR-DE", segment = "d2c_all",  group = as.character(group), adv_local_mn = d2c_adv_mn)],
  eur.de.group[, .(currency = "EUR-DE", segment = "total",    group = as.character(group), adv_local_mn = total_adv_mn)]))
eur.de.groups[segment %in% c("d2c_base", "d2c_all"),
              unit := "EUR mn per day (Finanzagentur; customer-facing legs = gross x non-broker share, single-counted as reported; no on/off-the-run split so d2c_base = d2c_all; subset of auction group banks; groups by original maturity)"]
eur.de.groups[segment == "total",
              unit := "EUR mn per day (Finanzagentur; customer-facing legs + 0.5 x broker legs; subset of auction group banks; groups by original maturity)"]

# France: no turnover by maturity is published, so a single group holding the
# scaled Bund level. The group covers the benchmark universe (0-10y), so the
# 10y+ Bund group is excluded from the level. Replace eur.fr.scale with an
# AFT-based level when available.
eur.fr.level <- eur.de.group[group != "10y+", .(d2c = sum(d2c_adv_mn), total = sum(total_adv_mn))] * eur.fr.scale
eur.fr.groups <- data.table(currency = "EUR-FR",
                            segment  = c("d2c_base", "d2c_all", "total"),
                            group    = "all",
                            adv_local_mn = c(eur.fr.level$d2c, eur.fr.level$d2c, eur.fr.level$total))
eur.fr.groups[segment %in% c("d2c_base", "d2c_all"),
              unit := sprintf("EUR mn per day (EUR-DE customer-facing 0-10y level x %.2f, see eur.fr.scale; single group covering 0-10y; no French turnover data by maturity or counterparty)", eur.fr.scale)]
eur.fr.groups[segment == "total",
              unit := sprintf("EUR mn per day (EUR-DE total 0-10y level x %.2f, see eur.fr.scale; single group covering 0-10y; no French turnover data by maturity or counterparty)", eur.fr.scale)]
eur.fr.group.map <- data.table(currency = "EUR-FR", bucket = common.buckets, group = "all")

eur.adv.groups <- rbindlist(list(eur.de.groups, eur.fr.groups), use.names = TRUE)
eur.adv.groups[, window := eur.window]
setcolorder(eur.adv.groups, c("currency", "segment", "unit", "window", "group", "adv_local_mn"))
eur.group.map <- rbindlist(list(eur.de.group.map, eur.fr.group.map))

# Audit table kept for the workbook
eur.audit <- eur.de[, .(year, instrument, group, gross_eur_bn, customer_share = eur.cust.share,
                        customer_bn, broker_bn, total_single_bn,
                        trading_days = eur.trading.days, total_adv_mn, d2c_adv_mn)]
eur.raw.tables <- rbindlist(list(
  eur.inst[, .(year, table = "instruments", item = instrument, gross_eur_bn)],
  eur.cpty[, .(year, table = "counterparties", item = counterparty, gross_eur_bn)],
  eur.tot[,  .(year, table = "totals", item = "gross_total", gross_eur_bn = gross_total_eur_bn)]))

message("EUR: Finanzagentur ", eur.year, ", customer-like share ", round(eur.cust.share, 3),
        ", FR scale ", eur.fr.scale)
