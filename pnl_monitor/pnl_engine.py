"""P&L computation over flexible windows.

The book is marked to market on the *current* set of positions and compared
against the price on each window's reference date. This is a price-only
"mark-over-window" P&L on today's holdings — it deliberately ignores
intra-period trades (buys/sells within the window), which is the standard
quick desk view for a static position snapshot. If you need trade-aware P&L,
that requires a position time series, not just a snapshot.

Formula per position, per window::

    pnl = quantity * point_value * (price_today - price_reference)

``point_value`` is the currency P&L per 1.0 move in the quoted price per unit
of ``quantity``. Set it per instrument in the positions CSV:

* Bond quoted per 100, quantity = face value  ->  point_value = 0.01
  (a 1-point price move on 1,000,000 face = 1,000,000 * 0.01 * 1 = 10,000)
* Future, quantity = # contracts             ->  point_value = contract multiplier
  (e.g. 10Y note future = 1000 -> 1 pt move * 1 contract = 1000)
"""

from __future__ import annotations

import datetime as dt
from dataclasses import dataclass
from typing import Dict, List, Mapping

import pandas as pd

# Default Bloomberg fields by asset class. Bonds use the dirty (full) price so
# daily P&L captures carry/accrued; everything else uses last price.
DEFAULT_FIELD = {
    "bond": "PX_DIRTY_MID",
    "future": "PX_LAST",
    "option": "PX_LAST",
    "swap": "PX_LAST",
}
FALLBACK_FIELD = "PX_LAST"

REQUIRED_COLUMNS = ["ticker", "asset_class", "quantity", "point_value"]


def load_positions(path: str) -> pd.DataFrame:
    """Read and validate the positions CSV."""
    df = pd.read_csv(path)
    df.columns = [c.strip().lower() for c in df.columns]
    missing = [c for c in REQUIRED_COLUMNS if c not in df.columns]
    if missing:
        raise ValueError(
            f"positions file is missing required columns: {missing}. "
            f"Required: {REQUIRED_COLUMNS}"
        )
    df["ticker"] = df["ticker"].astype(str).str.strip()
    df["asset_class"] = df["asset_class"].astype(str).str.strip().str.lower()
    df["quantity"] = pd.to_numeric(df["quantity"], errors="coerce")
    df["point_value"] = pd.to_numeric(df["point_value"], errors="coerce")
    if "name" not in df.columns:
        df["name"] = df["ticker"]
    if "currency" not in df.columns:
        df["currency"] = ""
    # Optional explicit price field per row; otherwise inferred by asset class.
    if "price_field" not in df.columns:
        df["price_field"] = ""
    df["price_field"] = df["price_field"].fillna("").astype(str).str.strip()
    bad = df[df["quantity"].isna() | df["point_value"].isna()]
    if not bad.empty:
        raise ValueError(
            "Non-numeric quantity/point_value in rows: "
            f"{bad['ticker'].tolist()}"
        )
    return df


def field_for(row) -> str:
    """Bloomberg field to use for a position row."""
    if row["price_field"]:
        return row["price_field"]
    return DEFAULT_FIELD.get(row["asset_class"], FALLBACK_FIELD)


def field_map(positions: pd.DataFrame) -> Dict[str, str]:
    """``{ticker: field}`` for the whole book (last field wins on dupes)."""
    return {row["ticker"]: field_for(row) for _, row in positions.iterrows()}


# ---------------------------------------------------------------------------
# Reference dates
# ---------------------------------------------------------------------------
@dataclass(frozen=True)
class Window:
    label: str
    reference: dt.date  # the close we compare *against*
    note: str = ""


def fy_start(today: dt.date, fy_start_month: int = 4, fy_start_day: int = 1) -> dt.date:
    """First day of the financial year containing ``today`` (default 1 April)."""
    this_year = dt.date(today.year, fy_start_month, fy_start_day)
    return this_year if today >= this_year else dt.date(
        today.year - 1, fy_start_month, fy_start_day
    )


def standard_windows(
    today: dt.date,
    fy_start_month: int = 4,
    fy_start_day: int = 1,
) -> List[Window]:
    """FYTD, CYTD and MTD windows for ``today``.

    Each reference is the close of the day *before* the period starts, so the
    P&L captures the move from that starting mark to today.
    """
    fys = fy_start(today, fy_start_month, fy_start_day)
    fy_ref = fys - dt.timedelta(days=1)                       # e.g. 31 Mar
    cy_ref = dt.date(today.year - 1, 12, 31)                  # prior year-end
    mtd_ref = today.replace(day=1) - dt.timedelta(days=1)     # prior month-end
    return [
        Window("FYTD", fy_ref, f"since FY start {fys:%d %b %Y}"),
        Window("CYTD", cy_ref, f"since {cy_ref:%d %b %Y} close"),
        Window("MTD", mtd_ref, f"since {mtd_ref:%d %b %Y} close"),
    ]


# ---------------------------------------------------------------------------
# P&L
# ---------------------------------------------------------------------------
def compute_pnl(
    positions: pd.DataFrame,
    provider,
    windows: List[Window],
    today: dt.date,
    history_pad_days: int = 10,
) -> pd.DataFrame:
    """Return a per-position frame with a P&L column for each window.

    Columns: ticker, name, asset_class, currency, quantity, point_value,
    price_today, plus ``pnl_<LABEL>`` and ``ref_px_<LABEL>`` per window.
    """
    fmap = field_map(positions)
    spot = provider.spot(fmap)

    # One historical pull covering the earliest reference date through today.
    earliest = min(w.reference for w in windows)
    hist = provider.historical(
        fmap,
        start=earliest - dt.timedelta(days=history_pad_days),
        end=today,
    )

    rows = []
    for _, pos in positions.iterrows():
        ticker = pos["ticker"]
        px_today = spot.get(ticker)
        row = {
            "ticker": ticker,
            "name": pos["name"],
            "asset_class": pos["asset_class"],
            "currency": pos["currency"],
            "quantity": pos["quantity"],
            "point_value": pos["point_value"],
            "price_today": px_today,
        }
        series = hist.get(ticker, {})
        for w in windows:
            ref_date, ref_px = provider.price_on_or_before(series, w.reference)
            if px_today is None or ref_px is None:
                pnl = None
            else:
                pnl = pos["quantity"] * pos["point_value"] * (px_today - ref_px)
            row[f"ref_px_{w.label}"] = ref_px
            row[f"ref_date_{w.label}"] = ref_date
            row[f"pnl_{w.label}"] = pnl
        rows.append(row)

    return pd.DataFrame(rows)


def totals(pnl_df: pd.DataFrame, windows: List[Window]) -> Dict[str, float]:
    """Sum each window's P&L across the book (ignoring missing marks)."""
    return {
        w.label: float(pnl_df[f"pnl_{w.label}"].dropna().sum()) for w in windows
    }
