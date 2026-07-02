# Daily P&L Monitor

A locally-hosted Streamlit app that marks a bond/derivatives book to market and
shows P&L over flexible windows — **financial YTD (from 1 April), calendar YTD,
month-to-date, and a user-selected reference date**. Prices come from your local
**Bloomberg Terminal** via the Desktop API, with a synthetic **mock** fallback
so the app runs even without a Terminal.

## Why it must run locally (and can't fetch Bloomberg from the cloud)

Bloomberg market data isn't a public REST API. The `blpapi` Desktop API library
connects to a **Bloomberg Terminal running on the same machine** (`localhost:8194`)
and requires a live, logged-in Terminal session with a valid entitlement. So the
app has to run on your Bloomberg-connected desktop. A cloud/CI box has no Terminal
and will always fall back to mock prices — that's expected.

## Setup (on your Bloomberg machine)

```bash
cd pnl_monitor
python -m venv .venv && . .venv/Scripts/activate      # or source .venv/bin/activate
pip install -r requirements.txt

# Bloomberg Desktop API (only works with a running Terminal):
pip install --index-url=https://blpapi.bloomberg.com/repository/releases/python/simple/ blpapi
```

Then, with the Terminal open and logged in:

```bash
streamlit run pnl_app.py
```

Open http://localhost:8501. The header shows **🟢 LIVE** when connected to
Bloomberg or **🟡 MOCK** when using synthetic prices.

## Positions file (`positions.csv`)

| column | required | meaning |
|---|---|---|
| `ticker` | yes | Bloomberg ticker incl. yellow key, e.g. `TYU6 Comdty`, `US91282CJL57 Govt` |
| `asset_class` | yes | `bond`, `future`, `option`, or `swap` — picks the default price field |
| `quantity` | yes | face value for bonds; number of contracts for futures/options (negative = short) |
| `point_value` | yes | currency P&L per **1.0** move in the quoted price, per unit of quantity |
| `name` | no | display label |
| `currency` | no | shown only (no FX conversion — see limitations) |
| `price_field` | no | override the Bloomberg field for this row |

### Setting `point_value`

The P&L formula is one line:

```
pnl = quantity × point_value × (price_today − price_reference)
```

- **Bond** quoted per 100, `quantity` = face value → `point_value = 0.01`
  (1-pt move on 1,000,000 face = `1,000,000 × 0.01 × 1 = 10,000`).
- **Future/option**, `quantity` = # contracts → `point_value` = contract multiplier
  (e.g. 10Y T-Note future = `1000`).

## How the windows work

Each window compares today's price to the **close on the day before the period
starts**, resolved to the nearest business day on or before that date:

| Window | Reference (today = 2 Jul 2026) |
|---|---|
| FYTD | 31 Mar 2026 (day before 1 Apr FY start; FY start is configurable) |
| CYTD | 31 Dec 2025 |
| MTD | 30 Jun 2026 (prior month-end) |
| Custom | close on the date you pick in the sidebar |

## Price fields

- Bonds default to `PX_DIRTY_MID` so daily P&L includes accrued/carry.
- Futures/options/swaps default to `PX_LAST`.
- Override per row via the `price_field` column.

## Limitations (by design)

- **Snapshot, not trade-aware.** P&L marks *today's* positions over the window
  and ignores buys/sells made within the window. Trade-aware P&L needs a
  position time series, not just a snapshot.
- **No FX conversion.** P&L is reported in each instrument's own quote currency;
  the total sums raw numbers. Add an FX step if your book is multi-currency.
- **Historical dirty prices.** Some venues/tickers don't serve `PX_DIRTY`
  historically; if a reference mark is missing, that window shows blank for the
  row. Override `price_field` to `PX_LAST` if needed.

## Files

- `pnl_app.py` — Streamlit UI
- `pnl_engine.py` — windows + P&L math
- `providers.py` — `BloombergProvider` (live) and `MockProvider` (fallback)
- `positions.csv` — sample book (edit with your own positions)
