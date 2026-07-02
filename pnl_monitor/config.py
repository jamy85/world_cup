"""Shared configuration for the P&L monitor UI and server.

Kept separate so new portfolios or theming can be added in one place without
touching the UI layout or the reactive server logic.
"""

from __future__ import annotations

import os

# Directory holding this project's CSVs (used for the bundled sample data).
HERE = os.path.dirname(os.path.abspath(__file__))

# Add a portfolio by adding an entry here — the UI and server pick it up
# automatically (radio choices, conditional currency toggle, value boxes).
PORTFOLIOS = {
    "Futures (multi-ccy → USD)": {
        "trades": "trades_futures.csv",
        "multi_ccy": False,   # reported in USD only
        "show_carry": False,  # futures carry is embedded in price
        # Defaults used to auto-resolve tickers not found in the instruments
        # file (currency & point_value come from Bloomberg when live):
        "default_asset_class": "future",
        "default_currency": "USD",
        "default_point_value": 1000.0,
        "bbg_suffix": "Comdty",   # appended to a bare id lacking a yellow key
    },
    "Cash bonds (EUR)": {
        "trades": "trades_bonds.csv",
        "multi_ccy": True,    # EUR or USD
        "show_carry": True,
        "default_asset_class": "bond",
        "default_currency": "EUR",
        "default_point_value": 0.01,
        "bbg_suffix": "Govt",
    },
}

# Portfolios flagged multi_ccy expose the EUR/USD toggle; the UI needs the key
# name to build the conditional panel.
MULTI_CCY_KEYS = [name for name, cfg in PORTFOLIOS.items() if cfg["multi_ccy"]]

# Colours.
POS = "#27ae60"
NEG = "#c0392b"
SERIES_COLORS = {
    "cum_total": "#2c3e50",
    "cum_price": "#2980b9",
    "cum_carry": "#e67e22",
}
