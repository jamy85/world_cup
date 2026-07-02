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


def build_instruments(trades, provided, provider, defaults):
    """Return ``(instruments_df, info)`` covering every traded id.

    Ids present in ``provided`` (the instruments file) are used as-is. Ids not
    found there are auto-resolved from ``defaults`` — and, when the provider is
    a live Bloomberg session, enriched with real currency (``CRNCY``) and
    futures multiplier (``FUT_VAL_PT``). Non-numeric multipliers (Bloomberg
    returns ``'varies'`` for some contracts) or missing values fall back to the
    default multiplier instead of crashing.

    ``info`` is ``{"inferred": [...], "no_multiplier": [...]}``:
      * ``inferred`` — ids whose metadata came from defaults/Bloomberg, not the file.
      * ``no_multiplier`` — ids where a numeric multiplier couldn't be determined
        and the default was used (set ``point_value`` manually for accurate P&L).
    """
    ids = sorted(trades["id"].unique())
    suffix = defaults.get("bbg_suffix", "")
    default_ac = defaults.get("default_asset_class", "future")
    rows, inferred, no_multiplier = [], [], []

    for _id in ids:
        if provided is not None and _id in provided.index:
            m = provided.loc[_id]
            ac = str(m["asset_class"]).lower()
            ccy = str(m["currency"]).upper()
            pv = _num(m["point_value"])
            if pv is None:  # blank / 'varies' in the file
                pv = 0.01 if ac == "bond" else float(defaults.get("default_point_value", 1000.0))
                no_multiplier.append(_id)
            rows.append({"id": _id, "bbg_ticker": m["bbg_ticker"],
                         "asset_class": ac, "currency": ccy, "point_value": pv})
            continue

        ac = default_ac
        bbg = _id if (_has_yellow_key(_id) or not suffix) else f"{_id} {suffix}"
        ccy = defaults.get("default_currency", "USD")
        pv = 0.01 if ac == "bond" else float(defaults.get("default_point_value", 1000.0))
        pv_from_bbg = False

        if getattr(provider, "is_live", False):
            try:
                ref = provider.reference([bbg], ["CRNCY", "FUT_VAL_PT"]).get(bbg, {})
            except Exception:
                ref = {}
            if ref.get("CRNCY"):
                ccy = str(ref["CRNCY"]).upper()
            if ac != "bond":
                fv = _num(ref.get("FUT_VAL_PT"))
                if fv is not None:
                    pv, pv_from_bbg = fv, True

        rows.append({"id": _id, "bbg_ticker": bbg, "asset_class": ac,
                     "currency": ccy, "point_value": pv})
        inferred.append(_id)
        if ac != "bond" and not pv_from_bbg:
            no_multiplier.append(_id)

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
    for _id in ids:
        meta = instruments.loc[_id]
        bbg = meta["bbg_ticker"]
        pv = float(meta["point_value"])
        ccy = meta["currency"]
        is_bond = meta["asset_class"] == "bond"
        clean = px[bbg][CLEAN_FIELD]
        accrued = px[bbg].get(ACCRUED_FIELD, {}) if is_bond else {}
        fx_ser = fx.get(ccy, {})

        tr = trades[trades["id"] == _id]
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
                    "strategy": tr["strategy"].iloc[0] if not tr.empty else "",
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
    last_pos = attr.sort_values("date").groupby("id")["position"].last()
    g = attr.groupby(["strategy", "id", "bbg_ticker", "currency"])[
        [f"price_{suffix}", f"carry_{suffix}", f"total_{suffix}"]
    ].sum().rename(columns={
        f"price_{suffix}": "spread_price_pnl",
        f"carry_{suffix}": "carry_pnl",
        f"total_{suffix}": "total_pnl",
    }).reset_index()
    g["position"] = g["id"].map(last_pos)
    return g.sort_values(["strategy", "total_pnl"], ascending=[True, False])
