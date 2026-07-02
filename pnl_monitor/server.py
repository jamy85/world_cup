"""Reactive server logic for the P&L monitor.

Reads inputs (defined in ``ui.py``), runs the attribution engine
(``pnl_engine.py``) against the chosen data provider (``providers.py``), and
renders the outputs. All heavy lifting funnels through the single ``bundle()``
reactive so every output stays consistent and the engine runs once per change.
"""

from __future__ import annotations

import os

import pandas as pd
import plotly.graph_objects as go
from shiny import reactive, render, ui

import config
import pnl_engine as eng
import providers


def server(input, output, session):

    def _read_csv_input(file_input, default_name, loader):
        f = file_input()
        if f:
            return loader(f[0]["datapath"])
        return loader(os.path.join(config.HERE, default_name))

    @reactive.calc
    def bundle():
        """Compute everything reactively. Returns a dict; never raises to the UI."""
        cfg = config.PORTFOLIOS[input.portfolio()]
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
            color = config.POS if val >= 0 else config.NEG
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
        series = [("cum_total", "Total")]
        if b["cfg"]["show_carry"]:
            series += [("cum_price", "Spread / price"), ("cum_carry", "Carry")]
        fig = go.Figure()
        for col, name in series:
            fig.add_scatter(x=daily["date"], y=daily[col], mode="lines", name=name,
                            line=dict(color=config.SERIES_COLORS[col], width=2))
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
