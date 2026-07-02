"""Daily P&L monitor — Shiny for Python app entrypoint.

A reactive dashboard (the Python equivalent of an R Shiny app) over the
trade-blotter P&L engine. Two portfolios, carry vs. spread attribution, EUR/USD
reporting, and an interactive cumulative-P&L chart.

The app is split for modularity:

* ``ui.py``       — layout (inputs/outputs)
* ``server.py``   — reactive logic
* ``config.py``   — portfolios, colours, shared settings
* ``pnl_engine.py`` — blotter → daily attribution (UI-agnostic)
* ``providers.py``  — Bloomberg / mock data backends

Run locally on a Bloomberg-connected machine::

    shiny run --reload app.py       # then open http://localhost:8000

…or just press Run in your IDE (see the ``__main__`` block below).
"""

from __future__ import annotations

from shiny import App

from server import server
from ui import app_ui

app = App(app_ui, server)


if __name__ == "__main__":
    # Lets you launch straight from an IDE (e.g. PyCharm's green Run button)
    # instead of the `shiny run` command line. If you DON'T see the banner below
    # when you press Run, you're executing an older copy of this file.
    from shiny import run_app

    print("=" * 60)
    print(" Daily P&L Monitor starting…")
    print(" Open  http://127.0.0.1:8000  in your browser")
    print(" (Press Ctrl+C in this console to stop)")
    print("=" * 60, flush=True)

    run_app(app, host="127.0.0.1", port=8000)
