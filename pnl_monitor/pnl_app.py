"""Daily P&L monitor — locally hosted Streamlit app.

Run locally on a Bloomberg-connected machine::

    streamlit run pnl_monitor/pnl_app.py

With a Terminal running it pulls live prices; otherwise it falls back to
deterministic mock prices so you can see the app work end-to-end.
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

DEFAULT_POSITIONS = os.path.join(os.path.dirname(__file__), "positions.csv")


def fmt_ccy(x) -> str:
    if x is None or pd.isna(x):
        return "—"
    return f"{x:,.0f}"


def main() -> None:
    st.title("📈 Daily P&L Monitor")

    # -- Sidebar controls -------------------------------------------------
    with st.sidebar:
        st.header("Settings")
        use_bbg = st.toggle("Use Bloomberg (if available)", value=True)
        today = st.date_input("Valuation ('today') date", value=dt.date.today())
        st.caption("Live spot ignores this; it drives the mock provider and history window.")

        st.subheader("Financial year start")
        fy_month = st.number_input("Month", 1, 12, 4)
        fy_day = st.number_input("Day", 1, 31, 1)

        st.subheader("Custom reference date")
        use_custom = st.checkbox("Add a custom window", value=True)
        default_custom = (today - dt.timedelta(days=7))
        custom_ref = st.date_input("Reference close", value=default_custom)

        uploaded = st.file_uploader("Positions CSV", type="csv")

    # -- Positions --------------------------------------------------------
    try:
        if uploaded is not None:
            positions = eng.load_positions(uploaded)
            src = "uploaded file"
        else:
            positions = eng.load_positions(DEFAULT_POSITIONS)
            src = "positions.csv"
    except Exception as exc:
        st.error(f"Could not load positions: {exc}")
        st.stop()

    # -- Provider ---------------------------------------------------------
    provider, warning = providers.get_provider(prefer_bloomberg=use_bbg)
    if warning:
        st.warning(warning)
    banner = "🟢 LIVE" if provider.is_live else "🟡 MOCK"
    st.caption(f"Data source: **{banner} — {provider.name}**  ·  positions from *{src}*")

    # -- Windows ----------------------------------------------------------
    windows = eng.standard_windows(today, int(fy_month), int(fy_day))
    if use_custom:
        windows.append(
            eng.Window("Custom", custom_ref, f"since {custom_ref:%d %b %Y} close")
        )

    # -- Compute ----------------------------------------------------------
    try:
        pnl = eng.compute_pnl(positions, provider, windows, today)
    except Exception as exc:
        st.error(f"P&L computation failed: {exc}")
        st.stop()

    tot = eng.totals(pnl, windows)

    # -- Headline metrics -------------------------------------------------
    st.subheader("Portfolio P&L")
    cols = st.columns(len(windows))
    for col, w in zip(cols, windows):
        col.metric(w.label, fmt_ccy(tot[w.label]), help=w.note)

    # -- Per-position table ----------------------------------------------
    st.subheader("By position")
    display = pnl[["ticker", "name", "asset_class", "quantity", "price_today"]].copy()
    for w in windows:
        display[f"P&L {w.label}"] = pnl[f"pnl_{w.label}"]
    st.dataframe(
        display.style.format(
            {
                "quantity": "{:,.0f}",
                "price_today": "{:,.4f}",
                **{f"P&L {w.label}": "{:,.0f}" for w in windows},
            }
        ).map(
            lambda v: "color: #c0392b" if isinstance(v, (int, float)) and v < 0 else "",
            subset=[f"P&L {w.label}" for w in windows],
        ),
        use_container_width=True,
        hide_index=True,
    )

    # -- Contribution chart ----------------------------------------------
    st.subheader("Contribution to P&L")
    sel = st.selectbox("Window", [w.label for w in windows], index=0)
    chart_df = pnl[["name"]].copy()
    chart_df["pnl"] = pnl[f"pnl_{sel}"]
    chart_df = chart_df.dropna(subset=["pnl"])
    if not chart_df.empty:
        chart = (
            alt.Chart(chart_df)
            .mark_bar()
            .encode(
                x=alt.X("pnl:Q", title=f"P&L ({sel})"),
                y=alt.Y("name:N", sort="-x", title=None),
                color=alt.condition(
                    alt.datum.pnl < 0, alt.value("#c0392b"), alt.value("#27ae60")
                ),
                tooltip=["name", alt.Tooltip("pnl:Q", format=",.0f")],
            )
            .properties(height=max(120, 40 * len(chart_df)))
        )
        st.altair_chart(chart, use_container_width=True)

    # -- Reference detail -------------------------------------------------
    with st.expander("Reference prices & dates used"):
        detail = pnl[["ticker", "price_today"]].copy()
        for w in windows:
            detail[f"{w.label} ref date"] = pnl[f"ref_date_{w.label}"]
            detail[f"{w.label} ref px"] = pnl[f"ref_px_{w.label}"]
        st.dataframe(detail, use_container_width=True, hide_index=True)
        st.caption(
            "P&L = quantity × point_value × (price_today − reference price). "
            "Bonds default to PX_DIRTY_MID (captures accrued/carry); futures & "
            "options to PX_LAST. Marks are on today's positions only — "
            "intra-period trades are not reflected."
        )


if __name__ == "__main__":
    main()
