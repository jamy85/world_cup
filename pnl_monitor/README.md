# Daily P&L Monitor

A locally-hosted **Shiny for Python** app (the Python equivalent of R Shiny —
reactive `ui` + `server`, fully customizable layout) that computes a
**trade-blotter-driven P&L time series** for two portfolios, with **carry vs.
spread (price) attribution**. Prices and FX come from a local **Bloomberg
Terminal** (Desktop API), with a deterministic **mock** fallback so the app runs
anywhere.

The UI (`app.py`) is fully separated from the compute engine (`pnl_engine.py`)
and data layer (`providers.py`), so you can restyle or extend it freely.

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

## Inputs — two CSVs per portfolio

### 1. Trade blotter (`trades_*.csv`) — drives the P&L time series

| column | meaning |
|---|---|
| `trade_date` | trade date (YYYY-MM-DD) |
| `id` | instrument key — Bloomberg ticker or ISIN; matches the reference file |
| `quantity` | face value (bonds) or # contracts (futures); **negative = short** |
| `trade_price` | execution price (bonds: clean price; futures: futures price) |
| `strategy` | groups legs into a strategy (e.g. `Bund-BTP 10Y`) |

Positions are rebuilt cumulatively from the blotter, so P&L is **trade-date
aware** — no static snapshot assumption.

### 2. Instrument reference (`instruments_*.csv`) — static data

| column | meaning |
|---|---|
| `id` | matches the blotter `id` |
| `bbg_ticker` | Bloomberg ticker incl. yellow key (e.g. `TYU6 Comdty`, `DE0001102606 Govt`) |
| `asset_class` | `bond` or `future` (bonds get carry attribution) |
| `currency` | quote currency (`USD`, `EUR`, `JPY`, …) — used for FX conversion |
| `point_value` | currency P&L per 1.0 price move per unit of quantity |

**`point_value`:** bonds quoted per 100 with `quantity` = face → `0.01`
(1 clean point on 1,000,000 face = 10,000). Futures → contract multiplier
(e.g. 10Y T-Note = `1000`).

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
- FX conversion of a daily P&L flow uses that day's rate (standard convention);
  it is not a full multi-currency return decomposition.
- Carry uses Bloomberg `INT_ACC`; if a bond doesn't serve accrued historically,
  that day's carry is treated as zero (price P&L is unaffected).

## Files

- `app.py` — Shiny for Python UI (reactive; portfolio selector, currency toggle, charts)
- `pnl_engine.py` — blotter → daily attribution + aggregations
- `providers.py` — `BloombergProvider` (live) and `MockProvider` (fallback)
- `trades_futures.csv` / `instruments_futures.csv` — sample futures book
- `trades_bonds.csv` / `instruments_bonds.csv` — sample EUR bond spread book
