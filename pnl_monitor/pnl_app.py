"""Daily P&L monitor — two portfolios, trade-blotter driven, with attribution.

Run locally on a Bloomberg-connected machine::

    streamlit run pnl_monitor/pnl_app.py

* Futures portfolio — mixed currencies, reported in USD.
* Cash-bond portfolio — EUR, reported in EUR or USD, with carry vs. spread
  (price) compression shown separately per strategy.

With a Terminal running it pulls live prices/FX; otherwise it falls back to
deterministic mock data so the app works end-to-end.
"""

from __future__ import annotations

import datetime as dt
import os

import altair as alt
import pandas as pd
import streamlit as st

import pnl_engine as eng
import providers

st.set_page_config(page_title="Daily P&L Monitor", layout="wide", page_icon="📈")
HERE = os.path.dirname(__file__)

PORTFOLIOS = {
    "Futures (multi-ccy → USD)": {
        "trades": "trades_futures.csv",
        "instruments": "instruments_futures.csv",
        "currencies": ["usd"],           # reported in USD only
        "show_carry": False,             # futures carry is embedded in price
    },
    "Cash bonds (EUR)": {
        "trades": "trades_bonds.csv",
        "instruments": "instruments_bonds.csv",
        "currencies": ["local", "usd"],  # EUR or USD
        "show_carry": True,
    },
}


def fmt(x) -> str:
    return "—" if x is None or pd.isna(x) else f"{x:,.0f}"


def main() -> None:
    st.title("📈 Daily P&L Monitor")

    with st.sidebar:
        st.header("Portfolio")
        pf_name = st.radio("Select portfolio", list(PORTFOLIOS))
        cfg = PORTFOLIOS[pf_name]

        use_bbg = st.toggle("Use Bloomberg (if available)", value=True)
        end = st.date_input("As-of date", value=dt.date.today())
        start = st.date_input("Series start (blank = first trade)", value=None)

        if len(cfg["currencies"]) > 1:
            ccy = st.radio("Reporting currency", ["local", "usd"],
                           format_func=lambda c: "EUR" if c == "local" else "USD")
        else:
            ccy = cfg["currencies"][0]

        st.divider()
        up_tr = st.file_uploader("Trade blotter CSV", type="csv")
        up_in = st.file_uploader("Instrument reference CSV", type="csv")

    # -- Load inputs ------------------------------------------------------
    try:
        trades = eng.load_trades(up_tr) if up_tr else eng.load_trades(
            os.path.join(HERE, cfg["trades"]))
        instruments = eng.load_instruments(up_in) if up_in else eng.load_instruments(
            os.path.join(HERE, cfg["instruments"]))
    except Exception as exc:
        st.error(f"Could not load inputs: {exc}")
        st.stop()

    provider, warning = providers.get_provider(prefer_bloomberg=use_bbg)
    if warning:
        st.warning(warning)
    banner = "🟢 LIVE" if provider.is_live else "🟡 MOCK"
    st.caption(f"Data source: **{banner} — {provider.name}**")

    try:
        attr = eng.compute_attribution(trades, instruments, provider, end, start)
    except Exception as exc:
        st.error(f"P&L computation failed: {exc}")
        st.stop()
    if attr.empty:
        st.info("No price observations in the selected window.")
        st.stop()

    ccy_label = "USD" if ccy == "usd" else "EUR"
    daily = eng.daily_totals(attr, ccy)
    strat = eng.strategy_breakdown(attr, ccy)

    # -- Headline metrics -------------------------------------------------
    st.subheader(f"{pf_name} — cumulative P&L ({ccy_label})")
    if cfg["show_carry"]:
        c1, c2, c3 = st.columns(3)
        c1.metric("Total", fmt(daily["cum_total"].iloc[-1]))
        c2.metric("Spread / price", fmt(daily["cum_price"].iloc[-1]))
        c3.metric("Carry", fmt(daily["cum_carry"].iloc[-1]))
    else:
        st.metric("Total (price)", fmt(daily["cum_total"].iloc[-1]))

    # -- Cumulative time series ------------------------------------------
    series_cols = (["cum_total", "cum_price", "cum_carry"] if cfg["show_carry"]
                   else ["cum_total"])
    names = {"cum_total": "Total", "cum_price": "Spread / price", "cum_carry": "Carry"}
    long = daily.melt(id_vars="date", value_vars=series_cols,
                      var_name="component", value_name="pnl")
    long["component"] = long["component"].map(names)
    line = (
        alt.Chart(long).mark_line().encode(
            x=alt.X("date:T", title=None),
            y=alt.Y("pnl:Q", title=f"Cumulative P&L ({ccy_label})"),
            color=alt.Color("component:N", title=None),
            tooltip=["date:T", "component:N", alt.Tooltip("pnl:Q", format=",.0f")],
        ).properties(height=320)
    )
    st.altair_chart(line, use_container_width=True)

    # -- Strategy breakdown ----------------------------------------------
    st.subheader("By strategy")
    show = strat.copy()
    cols = {"strategy": "Strategy", "total_pnl": f"Total ({ccy_label})"}
    if cfg["show_carry"]:
        cols["spread_price_pnl"] = "Spread / price"
        cols["carry_pnl"] = "Carry"
    show = show[list(cols)].rename(columns=cols)
    num_cols = [c for c in show.columns if c != "Strategy"]
    st.dataframe(
        show.style.format({c: "{:,.0f}" for c in num_cols}).map(
            lambda v: "color:#c0392b" if isinstance(v, (int, float)) and v < 0 else "",
            subset=num_cols),
        use_container_width=True, hide_index=True)

    # -- Instrument detail -----------------------------------------------
    with st.expander("By instrument (legs of each strategy)"):
        inst = eng.instrument_breakdown(attr, ccy)
        icols = {"strategy": "Strategy", "id": "ID", "bbg_ticker": "Ticker",
                 "currency": "Ccy", "position": "Position",
                 "spread_price_pnl": "Spread / price", "carry_pnl": "Carry",
                 "total_pnl": f"Total ({ccy_label})"}
        if not cfg["show_carry"]:
            icols.pop("carry_pnl")
        inst = inst[list(icols)].rename(columns=icols)
        fmtd = {c: "{:,.0f}" for c in inst.columns if c not in ("Strategy", "ID", "Ticker", "Ccy")}
        st.dataframe(inst.style.format(fmtd), use_container_width=True, hide_index=True)
        st.caption(
            "Price P&L = position × point_value × Δ clean price (long−short legs "
            "net to spread compression). Carry = accrual earned overnight (bonds "
            "only). Each day's local P&L is converted to USD at that day's FX rate. "
            "Positions are rebuilt from the blotter, so this is trade-date-aware."
        )


if __name__ == "__main__":
    main()
