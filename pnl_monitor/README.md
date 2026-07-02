# Daily P&L Monitor

A locally-hosted **Shiny for Python** app (the Python equivalent of R Shiny —
reactive `ui` + `server`, fully customizable layout) that computes a
**trade-blotter-driven P&L time series** for two portfolios, with **carry vs.
spread (price) attribution**. Prices and FX come from a local **Bloomberg
Terminal** (Desktop API), with a deterministic **mock** fallback so the app runs
anywhere.

The layout (`ui.py`), reactive logic (`server.py`) and shared settings
(`config.py`) are separated from the compute engine (`pnl_engine.py`) and data
layer (`providers.py`), so you can restyle, extend, or add portfolios freely.

* **Futures portfolio** — futures in various currencies, reported in **USD**.
* **Cash-bond portfolio** — EUR government bonds, typically **spread trades**
  (long one bond / short another), reported in **EUR or USD**, with **carry**
  and **spread compression** shown separately per strategy.

## Why it must run locally (and can't fetch Bloomberg from the cloud)

Bloomberg market data isn't a public REST API. The `blpapi` Desktop API connects
to a **Bloomberg Terminal running on the same machine** (`localhost:8194`) and
needs a live, logged-in session with a valid entitlement. So the app runs on
your Bloomberg desktop; a cloud/CI box has no Terminal and falls back to mock
prices — that's expected.

## Setup (on your Bloomberg machine)

```bash
python -m venv .venv && . .venv/Scripts/activate      # or source .venv/bin/activate
pip install -r requirements.txt
# Bloomberg Desktop API (only works with a running Terminal):
pip install --index-url=https://blpapi.bloomberg.com/repository/releases/python/simple/ blpapi

shiny run --reload app.py       # with the Terminal open + logged in
```

Open http://localhost:8000. The status line shows **🟢 LIVE** (Bloomberg) or
**🟡 MOCK** (synthetic prices).

### Running in PyCharm

`app.py` has an `if __name__ == "__main__"` block, so you can just open it and
press the green **Run** button — it starts the server and opens a browser.

1. **Set the interpreter:** *Settings → Project → Python Interpreter →* add the
   `.venv` you created above (or let PyCharm create one and `pip install -r
   requirements.txt`).
2. Right-click `app.py` → **Run 'app'**. (Live reload isn't active this way; to
   get auto-reload use a terminal run configuration with `shiny run --reload
   app.py`, or edit the `run_app(..., reload=True)` call.)

PyCharm Professional also has native Shiny support, but the Run button above
works in both Community and Professional.

## Inputs — two CSVs per portfolio

### 1. Trade blotter (`trades_*.csv`) — drives the P&L time series

| column | meaning |
|---|---|
| `id` | instrument key — Bloomberg ticker or ISIN; matches the reference file |
| `trade_date` | trade date — ISO `YYYY-MM-DD` **or** day-first `DD/MM/YYYY` (e.g. `20/1/2026` = 20 Jan) |
| `quantity` | face value (bonds) or # contracts (futures); **negative = short** |
| `trade_price` | execution price (bonds: clean price; futures: futures price) |
| `strategy` | groups legs into a strategy (e.g. `Bund-BTP 10Y`) |

Positions are rebuilt cumulatively from the blotter, so P&L is **trade-date
aware** — no static snapshot assumption.

### 2. Instrument metadata — resolved from Bloomberg (no file needed)

**You only provide the blotter.** Currency and contract multiplier are retrieved
from Bloomberg per contract:

* **Bloomberg ticker** — a bare id (e.g. `DUH6`) gets the portfolio's yellow key
  appended (`DUH6 Comdty`); ids that already include a yellow key are used as-is.
* **Currency** — from `CRNCY`.
* **Futures multiplier** (P&L per 1.0 price move) — from
  `FUT_TICK_VAL / FUT_TICK_SIZE`, the universal quantity defined for every
  contract. `FUT_VAL_PT` is used only as a fallback if the tick fields are
  missing. This handles yield-quoted contracts such as Australian 3y/10y bond
  futures (YM/XM), where `FUT_VAL_PT` is reported as `'varies'`.

Only when Bloomberg can't resolve a value — or you're offline / in mock — is a
per-portfolio default used (see `config.py`), and the app warns which tickers
need attention.

**Optional override:** if you ever need to pin a value (exact multiplier,
currency, ISIN→ticker mapping, or to work precisely in mock mode), upload an
overrides CSV via the sidebar with columns
`id, bbg_ticker, asset_class, currency, point_value`. Any field you supply wins;
blanks are still filled from Bloomberg.

## P&L attribution

Daily price P&L per instrument (previous trading day *p*):

```
pos_before × pv × (mark_t − mark_p)  +  Σ_trades_today qty × pv × (mark_t − trade_price)
```

- **Spread / price P&L** — from the **clean price** move. For a long/short spread
  trade, the net of the two legs *is* the spread compression.
- **Carry P&L** (bonds only) — `pos × pv × Δ accrued interest` (`INT_ACC`), with a
  coupon-payment reset so daily carry stays ≈ one day's accrual across coupons.
- **Futures carry** is embedded in the price (roll) and is **not** separated —
  that portfolio shows price P&L only.

**FX:** each day's local P&L is converted to USD at that day's rate
(`<CCY>USD Curncy`) and summed. The futures portfolio reports USD; the bond
portfolio toggles EUR/USD.

## Limitations

- Futures carry/roll is not separately attributed (shown within price).
- Yield-quoted futures (e.g. Australian 3y/10y bond futures) have a tick value
  that drifts with the price level; the app uses the current `FUT_TICK_VAL`
  as a static multiplier — the standard daily-P&L approximation, not an exact
  yield reprice.
- FX conversion of a daily P&L flow uses that day's rate (standard convention);
  it is not a full multi-currency return decomposition.
- Carry uses Bloomberg `INT_ACC`; if a bond doesn't serve accrued historically,
  that day's carry is treated as zero (price P&L is unaffected).

## Files

- `app.py` — thin entrypoint: wires UI + server, IDE Run block
- `ui.py` — Shiny layout (inputs/outputs)
- `server.py` — reactive logic (loads data, runs engine, renders outputs)
- `config.py` — portfolios, colours, shared settings (add a portfolio here)
- `pnl_engine.py` — blotter → daily attribution + aggregations
- `providers.py` — `BloombergProvider` (live) and `MockProvider` (fallback)
- `trades_futures.csv` — sample futures blotter
- `trades_bonds.csv` — sample EUR bond spread blotter
