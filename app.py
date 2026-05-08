import streamlit as st
import pandas as pd
from datetime import datetime
import time

# --- 1. DATA SETUP ---
START_DATE = datetime(2026, 6, 11, 15, 0)  # June 11, 2026, 3:00 PM

GROUPS = {
    "Group A": ["Mexico", "South Africa", "South Korea", "Czechia"],
    "Group B": ["Canada", "Bosnia and Herz.", "Qatar", "Switzerland"],
    "Group C": ["Brazil", "Morocco", "Haiti", "Scotland"],
    "Group D": ["USA", "Paraguay", "Australia", "Türkiye"],
    "Group E": ["Germany", "Curaçao", "Ivory Coast", "Ecuador"],
    "Group F": ["Netherlands", "Japan", "Sweden", "Tunisia"],
    "Group G": ["Belgium", "Egypt", "Iran", "New Zealand"],
    "Group H": ["Spain", "Cape Verde", "Saudi Arabia", "Uruguay"],
    "Group I": ["France", "Senegal", "Iraq", "Norway"],
    "Group J": ["Argentina", "Algeria", "Austria", "Jordan"],
    "Group K": ["Portugal", "DR Congo", "Uzbekistan", "Colombia"],
    "Group L": ["England", "Croatia", "Ghana", "Panama"]
}

# Mapping all 48 teams to Tiers
TIERS = {
    # Tier 1 (30)
    "France": 30, "Argentina": 30, "Spain": 30, "England": 30, "Brazil": 30, "Netherlands": 30, "Portugal": 30, "Morocco": 30,
    # Tier 2 (20)
    "Belgium": 20, "Germany": 20, "Croatia": 20, "Uruguay": 20, "Colombia": 20, "Senegal": 20, "USA": 20, "Mexico": 20,
    # Tier 3 (10)
    "Switzerland": 10, "Japan": 10, "South Korea": 10, "Sweden": 10, "Ecuador": 10, "Ivory Coast": 10, "Austria": 10, "Egypt": 10, "Norway": 10, "Australia": 10, "Ghana": 10, "Canada": 10
    # All others default to Tier 4 (0)
}

# --- 2. APP UI ---
st.set_page_config(page_title="2026 World Cup Market Mover", layout="wide")

# Header & Countdown
st.title("📈 World Cup Market Mover")
now = datetime.now()
if now < START_DATE:
    diff = START_DATE - now
    st.info(f"⏳ **Tournament Countdown:** {diff.days}d {diff.seconds//3600}h {(diff.seconds//60)%60}m until kickoff!")
else:
    st.success("⚽ THE TOURNAMENT IS LIVE!")

# Main Tabs
tab1, tab2, tab3 = st.tabs(["🏆 Leaderboard", "📋 Groups & Tiers", "⚙️ Rules"])

with tab1:
    st.header("Global Standings")
    try:
        # Assuming you have your collated 'participants.csv'
        data = pd.read_csv("participants.csv")
        st.dataframe(data, use_container_width=True)
    except:
        st.warning("Upload 'participants.csv' to see the leaderboard. For now, here is the group layout:")

with tab2:
    st.header("Official 2026 Groups")
    cols = st.columns(3)
    for i, (group, teams) in enumerate(GROUPS.items()):
        with cols[i % 3]:
            st.subheader(group)
            for t in teams:
                tier_val = TIERS.get(t, 0)
                st.write(f"- {t} (Exp: {tier_val})")

with tab3:
    st.header("Sweepstake Rules")
    st.markdown("""
    1. **Pick 3 Teams:** Choose your squad and go **Long** (Expect Overperformance) or **Short** (Expect Flop).
    2. **Group Stage:** Longs get team points (3/1/0). Shorts get 'dropped' points (e.g. 3 if team loses).
    3. **Knockout Bonus:** You earn/lose the difference between their **Actual Final Score** and their **Tier Expectation**.
    """)