# Monthly update and letter routine

You keep the government bond liquidity dashboard current and write its dated letter. You start with a fresh clone of this
repository, which includes the raw data files (`rawData/`), the hand-downloaded ones among them. Do the steps in order.

## 1. Refresh the automatic sources

    git pull --rebase origin main
    python -X utf8 pipeline/run_all.py --refresh      # several minutes: give the command a 15-minute timeout

This downloads new FINRA TRACE Treasury monthly aggregates, JSDA workbooks, the Finanzagentur page, Bond Connect flash
reports, ECB reference rates and the maturity sources, parses everything in `rawData/` and writes `data/liquidity.json`. Two
sources cannot be fetched by a script and stay hand-downloaded: the UK DMO gilt files (`rawData/dmo_gilts/`) and the Chinese
CCDC monthly bulletin tables (`rawData/ccdc_cgb/`). Do not try to fetch them; the pipeline uses the files that are there.

If a download fails, the pipeline keeps the previous data and prints a message; carry on and report it.

## 2. See what changed

    python -X utf8 pipeline/brief.py

Compare the brief with the previous letter in `data/letters/` (the newest file) and with the window labels there. A market is
"new" when its window end has moved on since the previous letter. The brief's dataset status lists what is due; a hand-
downloaded source marked DUE needs the owner to download a file, which you cannot do: say so in the report (and, if the owner
set up notifications, send one).

## 3. Write the letter, when there is something to say

If at least one market's data moved on since the previous letter, create `data/letters/YYYY-MM-DD.md` (today, UTC):

    # Liquidity letter, 6 November 2026

    Lead paragraph: what changed and the one number that matters most.

    ## Turnover by market
    ## Dealer-to-customer against interdealer
    ## Along the curve
    ## Data status

Length 300 to 500 words. Figures only from the brief or `data/liquidity.json`, with the period they refer to; local-currency
billions per trading day unless you say otherwise. Say which markets have new data and which do not. Note anything that looks
like a break (a month far above or below its neighbours, a window that shrank, provisional figures). No investment advice.

If nothing moved on, do not write a letter; just report that.

## 4. Publish

    python -X utf8 build.py
    npx --yes wrangler@4 deploy                       # needs CLOUDFLARE_API_TOKEN and CLOUDFLARE_ACCOUNT_ID; skip and say so if missing
    git add data rawData site/data
    git commit -m "Monthly update YYYY-MM-DD: <markets with new data>; letter <written / not written>"
    git pull --rebase origin main && git push origin main

Commit the refreshed raw files too: they are versioned so the next run starts from them. Finish with a short report: which
sources delivered new data, which are due or need a hand-downloaded file, what the letter says, and anything that failed.
