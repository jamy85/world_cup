import streamlit as st
import pandas as pd
from datetime import datetime

# --- 1. CONFIGURATION & STYLING ---
st.set_page_config(page_title="2026 World Cup Market Mover", layout="wide", page_icon="⚽")

# Custom CSS for the "Tier" boxes
st.markdown("""
    <style>
    .tier-gold { background-color: #FFD700; color: black; padding: 10px; border-radius: 5px; font-weight: bold; }
    .tier-silver { background-color: #C0C0C0; color: black; padding: 10px; border-radius: 5px; font-weight: bold; }
    .tier-bronze { background-color: #CD7F32; color: white; padding: 10px; border-radius: 5px; font-weight: bold; }
    .tier-neutral { background-color: #F0F2F6; color: #31333F; padding: 10px; border-radius: 5px; font-weight: bold; }
    .group-box { border: 1px solid #ddd; padding: 15px; border-radius: 10px; margin-bottom: 20px; background-color: #ffffff; }
    </style>
    """, unsafe_allow_html=True)

# Tier Definitions with Flags
TIERS = {
    "Gold": {"pts": 30, "color": "tier-gold", "teams": ["🇫🇷 France", "🇦🇷 Argentina", "🇪🇸 Spain", "🏴󠁧󠁢󠁥󠁮󠁧󠁿 England", "🇧🇷 Brazil", "🇳🇱 Netherlands", "🇵🇹 Portugal", "🇲🇦 Morocco"]},
    "Silver": {"pts": 20, "color": "tier-silver", "teams": ["🇧🇪 Belgium", "🇩🇪 Germany", "🇭🇷 Croatia", "🇺🇾 Uruguay", "🇨🇴 Colombia", "🇸🇳 Senegal", "🇺🇸 USA", "🇲🇽 Mexico"]},
    "Bronze": {"pts": 10, "color": "tier-bronze", "teams": ["🇨🇭 Switzerland", "🇯🇵 Japan", "🇰🇷 South Korea", "🇸🇪 Sweden", "🇪🇨 Ecuador", "🇨🇮 Ivory Coast", "🇦🇹 Austria", "🇪🇬 Egypt", "🇳🇴 Norway", "🇦🇺 Australia", "🇬🇭 Ghana", "🇨🇦 Canada"]},
    "Neutral": {"pts": 0, "color": "tier-neutral", "teams": ["🇿🇦 South Africa", "🇨🇿 Czechia", "🇧🇦 Bosnia", "🇶🇦 Qatar", "🇭🇹 Haiti", "🏴󠁧󠁢󠁳󠁣󠁴󠁿 Scotland", "🇵🇾 Paraguay", "🇹🇷 Türkiye", "🇨🇼 Curaçao", "🇹🇳 Tunisia", "🇮🇷 Iran", "🇳🇿 New Zealand", "🇨🇻 Cape Verde", "🇸🇦 Saudi Arabia", "🇮🇶 Iraq", "🇩🇿 Algeria", "🇯🇴 Jordan", "🇨🇩 DR Congo", "🇺🇿 Uzbekistan", "🇵🇦 Panama"]}
}

GROUPS = {
    "Group A": ["🇲🇽 Mexico", "🇿🇦 South Africa", "🇰🇷 South Korea", "🇨🇿 Czechia"],
    "Group B": ["🇨🇦 Canada", "🇧🇦 Bosnia", "🇶🇦 Qatar", "🇨🇭 Switzerland"],
    "Group C": ["🇧🇷 Brazil", "🇲🇦 Morocco", "🇭🇹 Haiti", "🏴󠁧󠁢󠁳󠁣󠁴󠁿 Scotland"],
    "Group D": ["🇺🇸 USA", "🇵🇾 Paraguay", "🇦🇺 Australia", "🇹🇷 Türkiye"]
}

# --- 2. HEADER & COUNTDOWN ---
st.title("🏆 World Cup 2026: Market Mover")
start_date = datetime(2026, 6, 11, 15, 0)
now = datetime.now()

if now < start_date:
    diff = start_date - now
    st.metric("Tournament Countdown", f"{diff.days} Days to Kickoff", delta=f"{diff.seconds//3600}h left")
else:
    st.success("⚽ THE BALL IS ROLLING!")

# --- 3. MAIN APP TABS ---
tab1, tab2, tab3, tab4 = st.tabs(["🥇 Leaderboard", "📊 Market Groups", "📅 Fixtures", "📖 Rules"])

with tab1:
    st.header("Participant Standings")
    try:
        df = pd.read_csv("participants.csv")
        # Beautify columns
        st.dataframe(
            df,
            column_config={
                "Participant": "Name",
                "Team_1": "1st Team", "Pos_1": "Pos",
                "Team_2": "2nd Team", "Pos_2": "Pos",
                "Team_3": "3rd Team", "Pos_3": "Pos"
            },
            hide_index=True,
            use_container_width=True
        )
    except FileNotFoundError:
        st.info("Upload participants.csv to see the rankings!")

with tab2:
    st.header("The Market Tiers")
    # Display Tiers in color-coded boxes
    cols = st.columns(4)
    for i, (tier_name, info) in enumerate(TIERS.items()):
        with cols[i]:
            st.markdown(f"<div class='{info['color']}'>{tier_name} Tier (Exp: {info['pts']} pts)</div>", unsafe_allow_html=True)
            for team in info["teams"]:
                st.caption(team)

    st.divider()
    st.header("Tournament Groups")
    g_cols = st.columns(2)
    for i, (group_name, teams) in enumerate(GROUPS.items()):
        with g_cols[i % 2]:
            st.markdown(f"<div class='group-box'><h3>{group_name}</h3>{'<br>'.join(teams)}</div>", unsafe_allow_html=True)

with tab3:
    st.header("Match Schedule")
    # Mock data for demonstration - in production, fetch from API using st.secrets
    fixtures = [
        {"Date": "June 11", "Match": "🇲🇽 Mexico vs 🇿🇦 South Africa", "Status": "Upcoming"},
        {"Date": "June 11", "Match": "🇰🇷 South Korea vs 🇨🇿 Czechia", "Status": "Upcoming"},
        {"Date": "June 12", "Match": "🇨🇦 Canada vs 🇧🇦 Bosnia", "Status": "Upcoming"},
    ]
    st.table(fixtures)

with tab4:
    st.markdown("""
    ### 📖 How it Works
    - **Long 📈:** Earn points for team wins + bonus for exceeding tier expectation.
    - **Short 📉:** Earn points for team losses + bonus for failing tier expectation.
    """)
