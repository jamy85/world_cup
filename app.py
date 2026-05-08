import streamlit as st
import pandas as pd
from datetime import datetime

# --- 1. STYLING & BACKGROUND ---
st.set_page_config(page_title="2026 Market Mover", layout="wide", page_icon="⚽")

# Custom CSS for Grass Background and Tier Styling
st.markdown("""
    <style>
    .stApp {
        background-image: url("https://images.unsplash.com/photo-1551029104-3990886c5f7e?auto=format&fit=crop&q=80&w=2000");
        background-attachment: fixed;
        background-size: cover;
    }
    /* Semi-transparent containers for readability */
    [data-testid="stVerticalBlock"] > div:has(div.stMarkdown) {
        background-color: rgba(255, 255, 255, 0.9);
        padding: 20px;
        border-radius: 15px;
    }
    .tier-gold { border-left: 10px solid #FFD700; background: #FFFDF0; padding: 10px; border-radius: 5px; margin: 5px 0; }
    .tier-silver { border-left: 10px solid #C0C0C0; background: #F5F5F5; padding: 10px; border-radius: 5px; margin: 5px 0; }
    .tier-bronze { border-left: 10px solid #CD7F32; background: #FAF3EE; padding: 10px; border-radius: 5px; margin: 5px 0; }
    .tier-neutral { border-left: 10px solid #95A5A6; background: #FDFDFD; padding: 10px; border-radius: 5px; margin: 5px 0; }
    </style>
    """, unsafe_allow_html=True)

# --- 2. DATA DEFINITIONS ---
# Helper to get flag URLs (bypasses Windows emoji issues)
def get_flag(country_code):
    return f"https://flagcdn.com/w40/{country_code.lower()}.png"

TIERS = {
    "Gold": {"pts": 30, "class": "tier-gold", "teams": [("FR", "France"), ("AR", "Argentina"), ("ES", "Spain"), ("GB-ENG", "England"), ("BR", "Brazil"), ("NL", "Netherlands"), ("PT", "Portugal"), ("MA", "Morocco")]},
    "Silver": {"pts": 20, "class": "tier-silver", "teams": [("BE", "Belgium"), ("DE", "Germany"), ("HR", "Croatia"), ("UY", "Uruguay"), ("CO", "Colombia"), ("SN", "Senegal"), ("US", "USA"), ("MX", "Mexico")]},
    "Bronze": {"pts": 10, "class": "tier-bronze", "teams": [("CH", "Switzerland"), ("JP", "Japan"), ("KR", "South Korea"), ("SE", "Sweden"), ("EC", "Ecuador"), ("CI", "Ivory Coast"), ("AT", "Austria"), ("EG", "Egypt"), ("NO", "Norway"), ("AU", "Australia"), ("GH", "Ghana"), ("CA", "Canada")]},
    "Neutral": {"pts": 0, "class": "tier-neutral", "teams": [("ZA", "South Africa"), ("CZ", "Czechia"), ("BA", "Bosnia"), ("QA", "Qatar"), ("HT", "Haiti"), ("GB-SCT", "Scotland"), ("PY", "Paraguay"), ("TR", "Türkiye")]}
}

# 2026 Expansion: 12 Groups of 4 (Partial List for demo)
FIXTURES = [
    {"Match": 1, "Date": "June 11", "Group": "A", "Teams": "Mexico vs South Africa"},
    {"Match": 2, "Date": "June 11", "Group": "A", "Teams": "South Korea vs Czechia"},
    {"Match": 3, "Date": "June 12", "Group": "B", "Teams": "Canada vs Bosnia"},
    {"Match": 4, "Date": "June 12", "Group": "D", "Teams": "USA vs Paraguay"},
    {"Match": 5, "Date": "June 13", "Group": "B", "Teams": "Qatar vs Switzerland"},
    {"Match": 6, "Date": "June 13", "Group": "C", "Teams": "Brazil vs Morocco"},
    {"Match": 7, "Date": "June 13", "Group": "C", "Teams": "Haiti vs Scotland"},
    # ... You can add all 72 group stage matches here
]

# --- 3. UI TABS ---
st.title("🏆 World Cup 2026: Market Mover")

tab1, tab2, tab3 = st.tabs(["🥇 Leaderboard", "📊 Market Groups", "📅 Full Fixtures"])

with tab1:
    st.header("Global Standings")
    try:
        data = pd.read_csv("participants.csv")
        st.dataframe(
            data,
            column_config={
                "Participant": "Player",
                "Team_1": "1st Investment", "Pos_1": "Position",
                "Team_2": "2nd Investment", "Pos_2": "Position",
                "Team_3": "3rd Investment", "Pos_3": "Position"
            },
            hide_index=True, use_container_width=True
        )
    except:
        st.info("Upload participants.csv to activate.")

with tab2:
    st.header("The Tiers & Rankings")
    t_cols = st.columns(4)
    for i, (tier, info) in enumerate(TIERS.items()):
        with t_cols[i]:
            st.markdown(f"<div class='{info['class']}'>{tier} Tier ({info['pts']} pts)</div>", unsafe_allow_html=True)
            for code, name in info["teams"]:
                st.image(get_flag(code), width=25)
                st.caption(name)

with tab3:
    st.header("Tournament Schedule (Group Stage)")
    st.table(FIXTURES)
