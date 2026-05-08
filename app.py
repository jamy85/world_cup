import streamlit as st
import pandas as pd
from datetime import datetime

# --- 1. STYLING & PREMIUM GRASS BACKGROUND ---
st.set_page_config(page_title="2026 Market Mover", layout="wide", page_icon="⚽")

st.markdown("""
    <style>
    .stApp {
        background-image: url("https://images.unsplash.com/photo-1556056504-517173f44056?q=80&w=2000");
        background-attachment: fixed;
        background-size: cover;
    }
    /* Main container styling */
    [data-testid="stVerticalBlock"] > div:has(div.stMarkdown) {
        background-color: rgba(255, 255, 255, 0.96);
        padding: 30px; border-radius: 20px; box-shadow: 0 8px 32px rgba(0,0,0,0.2);
    }
    /* Custom Tiers */
    .tier-card { border-left: 12px solid; padding: 15px; border-radius: 10px; margin-bottom: 15px; background: #fff; }
    .gold-border { border-color: #FFD700; }
    .silver-border { border-color: #C0C0C0; }
    .bronze-border { border-color: #CD7F32; }
    .neutral-border { border-color: #95A5A6; }
    
    /* Country List Flexbox */
    .country-item { display: flex; align-items: center; gap: 10px; font-weight: 500; margin-bottom: 4px; }
    .country-item img { border: 1px solid #eee; border-radius: 3px; }
    </style>
    """, unsafe_allow_html=True)

# --- 2. DATA & API UTILS ---
def get_flag(name_or_code):
    # Mapping for fixtures and rankings
    mapping = {
        "France": "fr", "Spain": "es", "Argentina": "ar", "England": "gb-eng", "Portugal": "pt", 
        "Brazil": "br", "Netherlands": "nl", "Morocco": "ma", "Belgium": "be", "Germany": "de",
        "Croatia": "hr", "Colombia": "co", "Senegal": "sn", "Mexico": "mx", "USA": "us", "Uruguay": "uy",
        "South Africa": "za", "South Korea": "kr", "Czechia": "cz", "Canada": "ca", "Bosnia": "ba",
        "Qatar": "qa", "Switzerland": "ch", "Haiti": "ht", "Scotland": "gb-sct", "Paraguay": "py",
        "Australia": "au", "Türkiye": "tr"
    }
    code = mapping.get(name_or_code, "un")
    return f"https://flagcdn.com/w40/{code.lower()}.png"

# Tiers based on May 2026 Rankings
TIERS = {
    "Gold": {"pts": 30, "style": "gold-border", "teams": ["France", "Spain", "Argentina", "England", "Portugal", "Brazil", "Netherlands", "Morocco"]},
    "Silver": {"pts": 20, "style": "silver-border", "teams": ["Belgium", "Germany", "Croatia", "Colombia", "Senegal", "Mexico", "USA", "Uruguay"]},
    "Bronze": {"pts": 10, "style": "bronze-border", "teams": ["Japan", "Switzerland", "Türkiye", "Ecuador", "Austria", "South Korea", "Australia", "Norway"]},
    "Neutral": {"pts": 0, "style": "neutral-border", "teams": ["Canada", "Ghana", "South Africa", "Czechia", "Bosnia", "Scotland", "Paraguay", "Qatar"]}
}

# SGT Schedule (GMT+8)
SGT_SCHEDULE = [
    {"Date": "12 Jun", "SGT Time": "05:00 AM", "Match": "Mexico vs South Africa", "Group": "A"},
    {"Date": "12 Jun", "SGT Time": "12:00 PM", "Match": "South Korea vs Czechia", "Group": "A"},
    {"Date": "13 Jun", "SGT Time": "05:00 AM", "Match": "Canada vs Bosnia", "Group": "B"},
    {"Date": "13 Jun", "SGT Time": "11:00 AM", "Match": "USA vs Paraguay", "Group": "D"},
    {"Date": "14 Jun", "SGT Time": "05:00 AM", "Match": "Qatar vs Switzerland", "Group": "B"},
    {"Date": "14 Jun", "SGT Time": "08:00 AM", "Match": "Brazil vs Morocco", "Group": "C"},
]

# --- 3. LEADERBOARD LOGIC ---
try:
    df_raw = pd.read_csv("participants.csv")
except:
    # Fallback dummy data for testing
    df_raw = pd.DataFrame({
        "Participant": ["Sarah", "David", "James"],
        "Team 1": ["France", "Brazil", "Germany"], "Strategy 1": ["LONG", "LONG", "SHORT"],
        "Team 2": ["USA", "England", "Japan"], "Strategy 2": ["LONG", "SHORT", "LONG"],
        "Team 3": ["Germany", "Ghana", "Morocco"], "Strategy 3": ["SHORT", "LONG", "LONG"]
    })

def style_strategies(val):
    if val == "LONG": return 'background-color: #d1e7dd; color: #0f5132; font-weight: bold; border: 1px solid #badbcc'
    if val == "SHORT": return 'background-color: #f8d7da; color: #842029; font-weight: bold; border: 1px solid #f5c2c7'
    return ''

# --- 4. UI TABS ---
st.title("🏆 World Cup 2026: Market Mover")

tabs = st.tabs(["🥇 Leaderboard", "📊 Market Tiers", "📈 Group Rankings", "📅 SGT Schedule", "🌳 Knockout Draw"])

with tabs[0]:
    st.header("Tournament Leaderboard")
    st.info("💡 **Click a player's row** to see a deep dive of their portfolio.")
    
    # Styling and Renaming
    styled_df = df_raw.style.applymap(style_strategies, subset=["Strategy 1", "Strategy 2", "Strategy 3"])
    
    selection = st.dataframe(
        styled_df,
        hide_index=True,
        use_container_width=True,
        on_select="rerun",
        selection_mode="single-row"
    )

    if len(selection.selection.rows) > 0:
        idx = selection.selection.rows[0]
        row = df_raw.iloc[idx]
        st.divider()
        st.subheader(f"🔍 Portfolio Insight: {row['Participant']}")
        cols = st.columns(3)
        for i in range(1, 4):
            with cols[i-1]:
                team = row[f"Team {i}"]
                strat = row[f"Strategy {i}"]
                st.image(get_flag(team), width=60)
                st.metric(team, strat, delta="Live Tier Bonus: +15")
                st.caption("Expected Progress: " + str(next((v['pts'] for k,v in TIERS.items() if team in v['teams']), 0)) + " pts")

with tabs[1]:
    st.header("The Market Tiers")
    t_cols = st.columns(4)
    for i, (tier, data) in enumerate(TIERS.items()):
        with t_cols[i]:
            st.markdown(f"<div class='tier-card {data['style']}'>{tier} Tier ({data['pts']} pts)</div>", unsafe_allow_html=True)
            for team in data["teams"]:
                st.markdown(f"<div class='country-item'><img src='{get_flag(team)}' width='25'> {team}</div>", unsafe_allow_html=True)

with tabs[2]:
    st.header("Group Standings")
    # Generating mock rankings for Group A & B
    standings = pd.DataFrame([
        {"Group": "A", "Team": "Mexico", "GP": 0, "GD": 0, "Pts": 0},
        {"Group": "A", "Team": "South Africa", "GP": 0, "GD": 0, "Pts": 0},
        {"Group": "B", "Team": "Canada", "GP": 0, "GD": 0, "Pts": 0},
        {"Group": "B", "Team": "Switzerland", "GP": 0, "GD": 0, "Pts": 0},
    ])
    standings["Flag"] = standings["Team"].apply(get_flag)
    st.dataframe(
        standings[["Group", "Flag", "Team", "GP", "GD", "Pts"]],
        column_config={"Flag": st.column_config.ImageColumn(" ")},
        hide_index=True, use_container_width=True
    )

with tabs[3]:
    st.header("Singapore Time Schedule")
    sched_df = pd.DataFrame(SGT_SCHEDULE)
    # Extracting team names to get flags
    sched_df["Flag 1"] = sched_df["Match"].apply(lambda x: get_flag(x.split(" vs ")[0]))
    sched_df["Flag 2"] = sched_df["Match"].apply(lambda x: get_flag(x.split(" vs ")[1]))
    
    st.dataframe(
        sched_df[["Date", "SGT Time", "Flag 1", "Match", "Flag 2", "Group"]],
        column_config={
            "Flag 1": st.column_config.ImageColumn(" "),
            "Flag 2": st.column_config.ImageColumn(" ")
        },
        hide_index=True, use_container_width=True
    )

with tabs[4]:
    st.header("Official Knockout Draw")
    st.write("The path to the final at New York/New Jersey Stadium.")
    kcols = st.columns(4)
    with kcols[0]:
        st.caption("Round of 32")
        st.info("Winner A vs Runner-up B")
        st.info("Winner C vs Runner-up D")
    with kcols[1]:
        st.caption("Round of 16")
        st.warning("TBD")
    with kcols[2]:
        st.caption("Quarter-Finals")
        st.error("TBD")
    with kcols[3]:
        st.caption("Final")
        st.success("🏆 World Champion")
