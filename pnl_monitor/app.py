"""Daily P&L monitor — Shiny for Python app.

A reactive dashboard (the Python equivalent of an R Shiny app) over the
trade-blotter P&L engine. Two portfolios, carry vs. spread attribution, EUR/USD
reporting, and an interactive cumulative-P&L chart.

Run locally on a Bloomberg-connected machine::

    shiny run --reload app.py
    # then open http://localhost:8000

The UI (this file) is fully separated from the compute engine (`pnl_engine.py`)
and the data layer (`providers.py`), so you can restyle or extend it freely.
"""

from __future__ import annotations

import datetime as dt
import os

import pandas as pd
import plotly.graph_objects as go
from shiny import App, reactive, render, ui

import pnl_engine as eng
import providers

HERE = os.path.dirname(os.path.abspath(__file__))

PORTFOLIOS = {
    "Futures (multi-ccy → USD)": {
        "trades": "trades_futures.csv",
        "instruments": "instruments_futures.csv",
        "multi_ccy": False,   # reported in USD only
        "show_carry": False,  # futures carry is embedded in price
    },
    "Cash bonds (EUR)": {
        "trades": "trades_bonds.csv",
        "instruments": "instruments_bonds.csv",
        "multi_ccy": True,    # EUR or USD
        "show_carry": True,
    },
}
BONDS_KEY = "Cash bonds (EUR)"

POS = "#27ae60"
NEG = "#c0392b"


# ---------------------------------------------------------------------------
# UI
# ---------------------------------------------------------------------------
app_ui = ui.page_sidebar(
    ui.sidebar(
        ui.input_radio_buttons("portfolio", "Portfolio", choices=list(PORTFOLIOS)),
        ui.input_switch("use_bbg", "Use Bloomberg if available", value=True),
        ui.input_date("end", "As-of date", value=dt.date.today()),
        ui.input_checkbox("from_first_trade", "Start from first trade", value=True),
        ui.panel_conditional(
            "!input.from_first_trade",
            ui.input_date("start", "Series start", value=dt.date(dt.date.today().year, 1, 1)),
        ),
        ui.panel_conditional(
            f"input.portfolio === '{BONDS_KEY}'",
            ui.input_radio_buttons(
                "ccy", "Reporting currency",
                choices={"local": "EUR", "usd": "USD"}, selected="local",
            ),
        ),
        ui.hr(),
        ui.input_file("trades_file", "Trade blotter CSV (optional)", accept=[".csv"]),
        ui.input_file("instruments_file", "Instrument reference CSV (optional)", accept=[".csv"]),
        width=330,
        title="Controls",
    ),
    ui.output_ui("status"),
    ui.output_ui("headline"),
    ui.card(
        ui.card_header("Cumulative P&L"),
        ui.output_ui("cum_chart"),
        full_screen=True,
    ),
    ui.layout_columns(
        ui.card(ui.card_header("By strategy"), ui.output_data_frame("strategy_tbl")),
        ui.card(ui.card_header("By instrument (legs)"), ui.output_data_frame("instrument_tbl")),
        col_widths=[5, 7],
    ),
    title="📈 Daily P&L Monitor",
    fillable=False,
)


# ---------------------------------------------------------------------------
# Server
# ---------------------------------------------------------------------------
def server(input, output, session):

    def _read_csv_input(file_input, default_name, loader):
        f = file_input()
        if f:
            return loader(f[0]["datapath"])
        return loader(os.path.join(HERE, default_name))

    @reactive.calc
    def bundle():
        """Compute everything reactively. Returns a dict; never raises to the UI."""
        cfg = PORTFOLIOS[input.portfolio()]
        try:
            trades = _read_csv_input(input.trades_file, cfg["trades"], eng.load_trades)
            instruments = _read_csv_input(
                input.instruments_file, cfg["instruments"], eng.load_instruments)
        except Exception as exc:
            return {"error": f"Could not load inputs: {exc}", "cfg": cfg}

        provider, warning = providers.get_provider(prefer_bloomberg=input.use_bbg())
        start = None if input.from_first_trade() else input.start()
        try:
            attr = eng.compute_attribution(trades, instruments, provider, input.end(), start)
        except Exception as exc:
            return {"error": f"P&L computation failed: {exc}", "cfg": cfg,
                    "provider": provider, "warning": warning}

        ccy = input.ccy() if cfg["multi_ccy"] else "usd"
        return {
            "cfg": cfg, "provider": provider, "warning": warning,
            "attr": attr, "ccy": ccy,
            "ccy_label": "USD" if ccy == "usd" else "EUR",
        }

    # -- status / data-source banner --------------------------------------
    @render.ui
    def status():
        b = bundle()
        items = []
        if "provider" in b:
            p = b["provider"]
            tag = "🟢 LIVE" if p.is_live else "🟡 MOCK"
            items.append(ui.markdown(f"**Data source:** {tag} — {p.name}"))
        if b.get("warning"):
            items.append(ui.tags.div(b["warning"], class_="text-warning small"))
        if b.get("error"):
            items.append(ui.tags.div("⚠️ " + b["error"], class_="text-danger fw-bold"))
        return ui.TagList(*items)

    # -- headline value boxes (dynamic per portfolio) ---------------------
    @render.ui
    def headline():
        b = bundle()
        if "attr" not in b or b["attr"].empty:
            return ui.TagList()
        daily = eng.daily_totals(b["attr"], b["ccy"])
        lbl = b["ccy_label"]

        def box(title, val):
            color = POS if val >= 0 else NEG
            return ui.value_box(title, ui.span(f"{val:,.0f} {lbl}", style=f"color:{color}"))

        boxes = [box("Total P&L", daily["cum_total"].iloc[-1])]
        if b["cfg"]["show_carry"]:
            boxes.append(box("Spread / price", daily["cum_price"].iloc[-1]))
            boxes.append(box("Carry", daily["cum_carry"].iloc[-1]))
        return ui.layout_columns(*boxes)

    # -- interactive cumulative chart -------------------------------------
    # Embedded as self-contained plotly HTML (plotly.js inlined) so it needs no
    # CDN or widget bridge — it just works offline on a locally-hosted app.
    @render.ui
    def cum_chart():
        b = bundle()
        if "attr" not in b or b["attr"].empty:
            return ui.p("No data to plot.", class_="text-muted")
        daily = eng.daily_totals(b["attr"], b["ccy"])
        series = [("cum_total", "Total", "#2c3e50")]
        if b["cfg"]["show_carry"]:
            series += [("cum_price", "Spread / price", "#2980b9"),
                       ("cum_carry", "Carry", "#e67e22")]
        fig = go.Figure()
        for col, name, color in series:
            fig.add_scatter(x=daily["date"], y=daily[col], mode="lines",
                            name=name, line=dict(color=color, width=2))
        fig.update_layout(
            margin=dict(l=10, r=10, t=10, b=10),
            yaxis_title=f"Cumulative P&L ({b['ccy_label']})",
            legend=dict(orientation="h", y=1.12),
            hovermode="x unified", template="plotly_white", height=360,
        )
        html = fig.to_html(full_html=False, include_plotlyjs=True,
                           config={"displayModeBar": True, "responsive": True})
        return ui.HTML(html)

    # -- strategy table ---------------------------------------------------
    @render.data_frame
    def strategy_tbl():
        b = bundle()
        if "attr" not in b or b["attr"].empty:
            return pd.DataFrame()
        s = eng.strategy_breakdown(b["attr"], b["ccy"])
        cols = {"strategy": "Strategy", "total_pnl": f"Total ({b['ccy_label']})"}
        if b["cfg"]["show_carry"]:
            cols["spread_price_pnl"] = "Spread / price"
            cols["carry_pnl"] = "Carry"
        out = s[list(cols)].rename(columns=cols)
        for c in out.columns:
            if c != "Strategy":
                out[c] = out[c].map(lambda v: f"{v:,.0f}")
        return render.DataGrid(out, width="100%")

    # -- instrument table -------------------------------------------------
    @render.data_frame
    def instrument_tbl():
        b = bundle()
        if "attr" not in b or b["attr"].empty:
            return pd.DataFrame()
        inst = eng.instrument_breakdown(b["attr"], b["ccy"])
        cols = {"strategy": "Strategy", "id": "ID", "currency": "Ccy",
                "position": "Position", "spread_price_pnl": "Spread / price",
                "carry_pnl": "Carry", "total_pnl": f"Total ({b['ccy_label']})"}
        if not b["cfg"]["show_carry"]:
            cols.pop("carry_pnl")
        out = inst[list(cols)].rename(columns=cols)
        for c in ["Position", "Spread / price", "Carry", f"Total ({b['ccy_label']})"]:
            if c in out.columns:
                out[c] = out[c].map(lambda v: f"{v:,.0f}")
        return render.DataGrid(out, width="100%")


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
