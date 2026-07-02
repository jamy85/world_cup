"""UI layout for the P&L monitor (Shiny for Python).

Pure layout — no compute logic. Inputs/outputs are wired to the reactive
functions in ``server.py`` by matching ids.
"""

from __future__ import annotations

import datetime as dt
import json

from shiny import ui

import config

# Show the EUR/USD toggle only when a multi-currency portfolio is selected.
# Built from config so adding a multi-ccy portfolio needs no edit here.
_ccy_condition = f"{json.dumps(config.MULTI_CCY_KEYS)}.indexOf(input.portfolio) >= 0"

app_ui = ui.page_sidebar(
    ui.sidebar(
        ui.input_radio_buttons("portfolio", "Portfolio", choices=list(config.PORTFOLIOS)),
        ui.input_switch("use_bbg", "Use Bloomberg if available", value=True),
        ui.input_date("end", "As-of date", value=dt.date.today()),
        ui.input_checkbox("from_first_trade", "Start from first trade", value=True),
        ui.panel_conditional(
            "!input.from_first_trade",
            ui.input_date("start", "Series start", value=dt.date(dt.date.today().year, 1, 1)),
        ),
        ui.panel_conditional(
            _ccy_condition,
            ui.input_radio_buttons(
                "ccy", "Reporting currency",
                choices={"local": "EUR", "usd": "USD"}, selected="local",
            ),
        ),
        ui.hr(),
        ui.input_file("trades_file", "Trade blotter CSV", accept=[".csv"]),
        ui.input_file("instruments_file", "Instrument overrides CSV (optional)", accept=[".csv"]),
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
