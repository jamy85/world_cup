"""Trade-blotter-driven P&L time series with carry / price attribution.

Given a trade blotter and an instrument reference, this rebuilds daily
positions and computes, for every trading day, each instrument's:

* **price P&L** — mark-to-market on the clean price (for a bond spread trade,
  the net of the long/short legs' clean moves is the *spread compression*), and
* **carry P&L** — accrual earned by holding the bond overnight (bonds only;
  futures carry is embedded in the price and is not separated here).

Daily price P&L per instrument on day *t* (previous trading day *p*)::

    pos_before * pv * (mark_t - mark_p)                      # holding the prior book
      + Σ_trades_today  qty * pv * (mark_t - trade_price)    # trades done today

Daily carry P&L (bonds)::

    pos_after * pv * carry_per_100_t

where ``carry_per_100_t`` is the day's accrual (Δ accrued interest), with a
coupon-payment reset so it stays ≈ one day's accrual across coupon dates.

Conventions
-----------
* Bond: ``quantity`` = face value, ``point_value`` = 0.01 (1 clean point on
  1,000,000 face = 10,000). ``mark`` = clean price; accrued from ``INT_ACC``.
* Future: ``quantity`` = # contracts, ``point_value`` = contract multiplier.
  ``mark`` = ``PX_LAST``. No separate carry.

Each day's local P&L is converted to USD at that day's FX rate and summed.
"""

from __future__ import annotations

import datetime as dt
import re
from typing import Dict, List

import pandas as pd

TRADE_COLUMNS = ["trade_date", "id", "quantity", "trade_price", "strategy"]
INSTRUMENT_COLUMNS = ["id", "bbg_ticker", "asset_class", "currency", "point_value"]

CLEAN_FIELD = "PX_LAST"
ACCRUED_FIELD = "INT_ACC"


# ---------------------------------------------------------------------------
# Loading / validation
# ---------------------------------------------------------------------------
def _norm_cols(df: pd.DataFrame) -> pd.DataFrame:
    df.columns = [c.strip().lower() for c in df.columns]
    return df


_ISO_DATE = re.compile(r"^\d{4}[-/]\d{1,2}[-/]\d{1,2}$")


def _parse_trade_dates(s: pd.Series) -> pd.Series:
    """Parse trade dates tolerantly.

    * Year-first values (``2026-01-05``, ``2026/1/5``) are read as ISO.
    * Everything else is read **day-first** (``20/1/2026`` → 20 Jan;
      ``5/1/2026`` → 5 Jan), matching UK/Asia conventions rather than US
      month-first. This is decided per value, so a file may mix both.
    """
    def parse_one(v):
        v = str(v).strip()
        if _ISO_DATE.match(v):
            return pd.to_datetime(v).date()            # year-first
        return pd.to_datetime(v, dayfirst=True).date()  # day-first for D/M/Y

    raw = s.astype(str).str.strip()
    try:
        return raw.map(parse_one)
    except Exception as exc:
        raise ValueError(
            "Could not parse 'trade_date'. Use ISO (YYYY-MM-DD) or day-first "
            f"(DD/MM/YYYY) dates. Values look like: {raw.head(3).tolist()}. ({exc})"
        )


def load_trades(path_or_buffer) -> pd.DataFrame:
    df = _norm_cols(pd.read_csv(path_or_buffer))
    missing = [c for c in TRADE_COLUMNS if c not in df.columns]
    if missing:
        raise ValueError(f"trade blotter missing columns: {missing}")
    df["trade_date"] = _parse_trade_dates(df["trade_date"])
    df["id"] = df["id"].astype(str).str.strip()
    df["strategy"] = df["strategy"].astype(str).str.strip()
    df["quantity"] = pd.to_numeric(df["quantity"], errors="coerce")
    df["trade_price"] = pd.to_numeric(df["trade_price"], errors="coerce")
    bad = df[df["quantity"].isna() | df["trade_price"].isna()]
    if not bad.empty:
        raise ValueError(f"non-numeric quantity/trade_price in rows: {bad.index.tolist()}")
    return df


def load_instruments(path_or_buffer) -> pd.DataFrame:
    df = _norm_cols(pd.read_csv(path_or_buffer))
    missing = [c for c in INSTRUMENT_COLUMNS if c not in df.columns]
    if missing:
        raise ValueError(f"instruments reference missing columns: {missing}")
    for c in ["id", "bbg_ticker", "asset_class", "currency"]:
        df[c] = df[c].astype(str).str.strip()
    df["asset_class"] = df["asset_class"].str.lower()
    df["currency"] = df["currency"].str.upper()
    df["point_value"] = pd.to_numeric(df["point_value"], errors="coerce")
    return df.set_index("id")


# Bloomberg "yellow key" market sectors — if an id already ends in one, we use
# it as the Bloomberg ticker verbatim; otherwise we append the portfolio suffix.
YELLOW_KEYS = {"COMDTY", "INDEX", "CURNCY", "GOVT", "CORP", "MTGE", "EQUITY", "PFD", "MUNI"}


def _has_yellow_key(id_str: str) -> bool:
    parts = id_str.strip().split()
    return len(parts) >= 2 and parts[-1].upper() in YELLOW_KEYS


def _num(x):
    """Coerce to float, returning None for non-numeric or NaN (e.g. 'varies')."""
    try:
        v = float(x)
    except (TypeError, ValueError):
        return None
    return v if v == v else None  # reject NaN


# Bloomberg static fields fetched per contract to resolve currency & multiplier.
REF_FIELDS = ["CRNCY", "FUT_VAL_PT", "FUT_TICK_VAL", "FUT_TICK_SIZE"]


def _multiplier_from_ref(ref) -> float | None:
    """P&L per 1.0 price move for a futures contract, from Bloomberg static data.

    Preference order:
      1. ``FUT_TICK_VAL / FUT_TICK_SIZE`` — money per tick ÷ price per tick, i.e.
         money per 1.0 price move. This is the **universal** quantity: it is
         defined for every futures contract, including yield-quoted ones like
         Australian 3y/10y bond futures (YM/XM), where the "value of a price
         point" is not constant and Bloomberg reports ``FUT_VAL_PT = 'varies'``.
      2. ``FUT_VAL_PT`` — Bloomberg's value of a price point, used only as a
         fallback when the tick fields are unavailable.
    Returns None if neither can be derived.

    Note: for yield-quoted contracts the true tick value drifts with the price
    level; using the current tick value is the standard static approximation for
    daily P&L (exact repricing would require the underlying yield model).
    """
    tv, ts = _num(ref.get("FUT_TICK_VAL")), _num(ref.get("FUT_TICK_SIZE"))
    if tv is not None and ts:
        return tv / ts
    return _num(ref.get("FUT_VAL_PT"))


def build_instruments(trades, provided, provider, defaults):
    """Return ``(instruments_df, info)`` covering every traded id.

    Currency and futures multiplier are retrieved from Bloomberg on the fly for
    each contract (batched into one request). The instruments file is an
    optional override; any field it supplies takes precedence, and any it omits
    (e.g. a blank ``point_value``) is filled from Bloomberg. A hardcoded default
    is used only as a last resort when Bloomberg can't supply a numeric value
    (offline/mock, or a contract with no derivable multiplier).

    ``info`` is ``{"inferred": [...], "no_multiplier": [...]}``.
    """
    ids = sorted(trades["id"].unique())
    suffix = defaults.get("bbg_suffix", "")
    default_ac = defaults.get("default_asset_class", "future")
    default_pv = float(defaults.get("default_point_value", 1000.0))
    live = bool(getattr(provider, "is_live", False))

    # Pass 1 — decide each id's Bloomberg ticker, asset class, and what the file
    # (if any) already pins down.
    plan = []
    for _id in ids:
        if provided is not None and _id in provided.index:
            m = provided.loc[_id]
            bbg = str(m["bbg_ticker"]).strip()
            ac = str(m["asset_class"]).lower()
            ccy = str(m["currency"]).upper()
            pv = _num(m["point_value"])
            plan.append({"id": _id, "bbg": bbg, "ac": ac, "ccy": ccy,
                         "pv": pv, "from_file": True})
        else:
            bbg = _id if (_has_yellow_key(_id) or not suffix) else f"{_id} {suffix}"
            plan.append({"id": _id, "bbg": bbg, "ac": default_ac, "ccy": None,
                         "pv": None, "from_file": False})

    # Batch-fetch Bloomberg reference for every contract that still needs
    # currency or a multiplier.
    ref_map = {}
    if live:
        need = sorted({p["bbg"] for p in plan
                       if p["ccy"] is None or (p["ac"] != "bond" and p["pv"] is None)})
        if need:
            try:
                ref_map = provider.reference(need, REF_FIELDS)
            except Exception:
                ref_map = {}

    # Pass 2 — assemble final rows.
    rows, inferred, no_multiplier = [], [], []
    for p in plan:
        ref = ref_map.get(p["bbg"], {})
        ac = p["ac"]
        ccy = p["ccy"] or (str(ref["CRNCY"]).upper() if ref.get("CRNCY")
                           else defaults.get("default_currency", "USD"))

        pv = p["pv"]
        if pv is None:
            if ac == "bond":
                pv = 0.01
            else:
                pv = _multiplier_from_ref(ref)
                if pv is None:
                    pv, missing_mult = default_pv, True
                else:
                    missing_mult = False
                if missing_mult:
                    no_multiplier.append(p["id"])

        rows.append({"id": p["id"], "bbg_ticker": p["bbg"], "asset_class": ac,
                     "currency": ccy, "point_value": pv})
        if not p["from_file"]:
            inferred.append(p["id"])

    info = {"inferred": inferred, "no_multiplier": no_multiplier}
    return pd.DataFrame(rows).set_index("id"), info


# ---------------------------------------------------------------------------
# Core computation
# ---------------------------------------------------------------------------
def _fields_by_ticker(instruments: pd.DataFrame, ids: List[str]) -> Dict[str, List[str]]:
    out: Dict[str, List[str]] = {}
    for _id in ids:
        meta = instruments.loc[_id]
        bbg = meta["bbg_ticker"]
        if meta["asset_class"] == "bond":
            out[bbg] = [CLEAN_FIELD, ACCRUED_FIELD]
        else:
            out[bbg] = [CLEAN_FIELD]
    return out


def _carry_per_100(acc_today, acc_prev) -> float:
    """One day's accrual per 100, robust to coupon-payment resets.

    On a normal day this is the accrual increment. On a coupon date accrued
    drops sharply; we treat that drop as the coupon paid and report ``acc_today``
    (the fresh period's accrual) so daily carry stays ≈ one day's accrual.
    """
    if acc_today is None or acc_prev is None:
        return 0.0
    if acc_today >= acc_prev:
        return acc_today - acc_prev
    return acc_today  # coupon reset day


def compute_attribution(
    trades: pd.DataFrame,
    instruments: pd.DataFrame,
    provider,
    end: dt.date,
    start: dt.date | None = None,
    pad_days: int = 7,
) -> pd.DataFrame:
    """Return a long-form daily attribution frame.

    Columns: date, id, bbg_ticker, strategy, currency, asset_class,
    position, price_local, carry_local, total_local, fx,
    price_usd, carry_usd, total_usd.
    """
    ids = sorted(trades["id"].unique())
    unknown = [i for i in ids if i not in instruments.index]
    if unknown:
        raise ValueError(f"trades reference unknown instrument ids: {unknown}")

    first_trade = min(trades["trade_date"])
    if start is None:
        start = first_trade
    start = min(start, first_trade)

    fbt = _fields_by_ticker(instruments, ids)
    px = provider.price_series(fbt, start - dt.timedelta(days=pad_days), end)
    currencies = sorted(instruments.loc[ids, "currency"].unique())
    fx = provider.fx_to_usd_series(currencies, start - dt.timedelta(days=pad_days), end)

    # Calendar = sorted union of all clean-price dates within [start, end].
    all_dates = set()
    for bbg, fields in px.items():
        all_dates.update(d for d in fields.get(CLEAN_FIELD, {}) if start <= d <= end)
    calendar = sorted(all_dates)
    if not calendar:
        return pd.DataFrame()

    val = provider.value_on_or_before
    rows = []
    # Position and P&L are tracked per (instrument, strategy) so the same ticker
    # traded under different strategies keeps separate books and is attributed
    # correctly. Summing over strategies still reconciles to the portfolio total.
    combos = list(trades[["id", "strategy"]].drop_duplicates().itertuples(index=False))
    for _id, strat in combos:
        meta = instruments.loc[_id]
        bbg = meta["bbg_ticker"]
        pv = float(meta["point_value"])
        ccy = meta["currency"]
        is_bond = meta["asset_class"] == "bond"
        clean = px[bbg][CLEAN_FIELD]
        accrued = px[bbg].get(ACCRUED_FIELD, {}) if is_bond else {}
        fx_ser = fx.get(ccy, {})

        tr = trades[(trades["id"] == _id) & (trades["strategy"] == strat)]
        prev_day = None
        for day in calendar:
            pos_before = float(tr.loc[tr["trade_date"] < day, "quantity"].sum())
            today_tr = tr[tr["trade_date"] == day]
            pos_after = pos_before + float(today_tr["quantity"].sum())

            mark_t = val(clean, day)
            mark_p = val(clean, prev_day) if prev_day else None

            price_local = 0.0
            if mark_t is not None:
                if mark_p is not None:
                    price_local += pos_before * pv * (mark_t - mark_p)
                for _, t in today_tr.iterrows():
                    price_local += t["quantity"] * pv * (mark_t - t["trade_price"])

            carry_local = 0.0
            if is_bond:
                acc_prev = val(accrued, prev_day) if prev_day else None
                cpp = _carry_per_100(val(accrued, day), acc_prev)
                carry_local = pos_after * pv * cpp

            fx_rate = val(fx_ser, day)
            fx_rate = 1.0 if ccy == "USD" else (fx_rate if fx_rate is not None else None)

            total_local = price_local + carry_local
            rows.append(
                {
                    "date": day,
                    "id": _id,
                    "bbg_ticker": bbg,
                    "strategy": strat,
                    "currency": ccy,
                    "asset_class": meta["asset_class"],
                    "position": pos_after,
                    "price_local": price_local,
                    "carry_local": carry_local,
                    "total_local": total_local,
                    "fx": fx_rate,
                    "price_usd": price_local * fx_rate if fx_rate is not None else None,
                    "carry_usd": carry_local * fx_rate if fx_rate is not None else None,
                    "total_usd": total_local * fx_rate if fx_rate is not None else None,
                }
            )
            prev_day = day

    return pd.DataFrame(rows)


# ---------------------------------------------------------------------------
# Aggregations for the UI
# ---------------------------------------------------------------------------
def daily_totals(attr: pd.DataFrame, ccy: str = "usd") -> pd.DataFrame:
    """Portfolio daily & cumulative P&L (price/carry/total) in the chosen ccy."""
    suffix = "usd" if ccy == "usd" else "local"
    g = attr.groupby("date")[[f"price_{suffix}", f"carry_{suffix}", f"total_{suffix}"]].sum()
    g = g.rename(columns={f"price_{suffix}": "price", f"carry_{suffix}": "carry", f"total_{suffix}": "total"})
    g[["cum_price", "cum_carry", "cum_total"]] = g[["price", "carry", "total"]].cumsum()
    return g.reset_index()


def daily_by_strategy(attr: pd.DataFrame, ccy: str = "usd") -> pd.DataFrame:
    """Long-form daily & cumulative total P&L per strategy.

    Columns: date, strategy, total, cum_total — one row per (day, strategy),
    ready to plot as one cumulative line per strategy.
    """
    suffix = "usd" if ccy == "usd" else "local"
    g = (attr.groupby(["date", "strategy"])[f"total_{suffix}"].sum()
         .reset_index().rename(columns={f"total_{suffix}": "total"}))
    g = g.sort_values(["strategy", "date"])
    g["cum_total"] = g.groupby("strategy")["total"].cumsum()
    return g


def strategy_breakdown(attr: pd.DataFrame, ccy: str = "usd") -> pd.DataFrame:
    """Per-strategy carry vs price (spread compression) totals over the window."""
    suffix = "usd" if ccy == "usd" else "local"
    g = attr.groupby("strategy")[[f"price_{suffix}", f"carry_{suffix}", f"total_{suffix}"]].sum()
    g = g.rename(columns={
        f"price_{suffix}": "spread_price_pnl",
        f"carry_{suffix}": "carry_pnl",
        f"total_{suffix}": "total_pnl",
    })
    return g.reset_index().sort_values("total_pnl", ascending=False)


def instrument_breakdown(attr: pd.DataFrame, ccy: str = "usd") -> pd.DataFrame:
    suffix = "usd" if ccy == "usd" else "local"
    # Latest position per (strategy, id) — an id can appear in several strategies.
    last_pos = (attr.sort_values("date").groupby(["strategy", "id"])["position"]
                .last().rename("position").reset_index())
    g = attr.groupby(["strategy", "id", "bbg_ticker", "currency"])[
        [f"price_{suffix}", f"carry_{suffix}", f"total_{suffix}"]
    ].sum().rename(columns={
        f"price_{suffix}": "spread_price_pnl",
        f"carry_{suffix}": "carry_pnl",
        f"total_{suffix}": "total_pnl",
    }).reset_index()
    g = g.merge(last_pos, on=["strategy", "id"], how="left")
    return g.sort_values(["strategy", "total_pnl"], ascending=[True, False])
