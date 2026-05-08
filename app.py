import streamlit as st
import pandas as pd
from datetime import datetime

# --- 1. STYLING & BACKGROUND ---
st.set_page_config(page_title="2026 Market Mover", layout="wide", page_icon="⚽")

st.markdown("""
    <style>
    .stApp {
        background-image: url("https://images.unsplash.com/photo-1556056504-517173f44056?q=80&w=2000");
        background-attachment: fixed;
        background-size: cover;
    }
    /* Semi-transparent containers for data visibility */
    [data-testid="stVerticalBlock"] > div:has(div.stMarkdown) {
        background-color: rgba(255, 255, 255, 0.95);
        padding: 25px;
        border-radius: 15px;
        box-shadow: 0 4px 15px rgba(0,0,0,0.1);
    }
    .tier-gold { border-left: 10px solid #FFD700; background: #FFFDF0; padding: 12px; border-radius: 8px; margin-bottom: 10px; font-weight: bold; }
    .tier-silver { border-left: 10px solid #C0C0C0; background: #F5F5F5; padding: 12px; border-radius: 8px; margin-bottom: 10px; font-weight: bold; }
    .tier-bronze { border-left: 10px solid #CD7F32; background: #FAF3EE; padding: 12px; border-radius: 8px; margin-bottom: 10px; font-weight: bold; }
    .tier-neutral { border-left: 10px solid #95A5A6; background: #FDFDFD; padding: 12px; border-radius: 8px; margin-bottom: 10px; font-weight: bold; }
    
    /* Flex container for Flag + Name */
    .country-row { display: flex; align-items: center; gap: 12px; margin: 8px 0; }
    .country-row img { width: 30px; height: auto; border-radius: 2px; }
    </style>
    """, unsafe_allow_html=True)

# --- 2. DATA DEFINITIONS ---
def get_flag(code):
    return f"https://flagcdn.com/w40/{code.lower()}.png"

# Updated Tiers with Codes
TIERS = {
    "Gold": {"pts": 30, "class": "tier-gold", "teams": [("FR", "France"), ("AR", "Argentina"), ("ES", "Spain"), ("GB-ENG", "England"), ("BR", "Brazil"), ("NL", "Netherlands"), ("PT", "Portugal"), ("MA", "Morocco")]},
    "Silver": {"pts": 20, "class": "tier-silver", "teams": [("BE", "Belgium"), ("DE", "Germany"), ("HR", "Croatia"), ("UY", "Uruguay"), ("CO", "Colombia"), ("SN", "Senegal"), ("US", "USA"), ("MX", "Mexico")]},
    "Bronze": {"pts": 10, "class": "tier-bronze", "teams": [("CH", "Switzerland"), ("JP", "Japan"), ("KR", "South Korea"), ("SE", "Sweden"), ("EC", "Ecuador"), ("CI", "Ivory Coast"), ("AT", "Austria"), ("EG", "Egypt"), ("NO", "Norway"), ("AU", "Australia"), ("GH", "Ghana"), ("CA", "Canada")]},
    "Neutral": {"pts": 0, "class": "tier-neutral", "teams": [("ZA", "South Africa"), ("CZ", "Czechia"), ("BA", "Bosnia"), ("QA", "Qatar"), ("HT", "Haiti"), ("GB-SCT", "Scotland"), ("PY", "Paraguay"), ("TR", "Türkiye")]}
}

# Official 2026 Opening Fixtures (Singapore Time - SGT)
FIXTURES = [
    {"Date": "12 Jun", "Time (SGT)": "03:00 AM", "Match": "🇲🇽 Mexico vs South Africa 🇿🇦", "Group": "A"},
    {"Date": "12 Jun", "Time (SGT)": "10:00 AM", "Match": "🇰🇷 South Korea vs Czechia 🇨🇿", "Group": "A"},
    {"Date": "13 Jun", "Time (SGT)": "03:00 AM", "Match": "🇨🇦 Canada vs Bosnia 🇧🇦", "Group": "B"},
    {"Date": "13 Jun", "Time (SGT)": "09:00 AM", "Match": "🇺🇸 USA vs Paraguay 🇵🇾", "Group": "D"},
    {"Date": "14 Jun", "Time (SGT)": "03:00 AM", "Match": "🇶🇦 Qatar vs Switzerland 🇨🇭", "Group": "B"},
    {"Date": "14 Jun", "Time (SGT)": "06:00 AM", "Match": "🇧🇷 Brazil vs Morocco 🇲🇦", "Group": "C"},
    {"Date": "14 Jun", "Time (SGT)": "09:00 AM", "Match": "🇭🇹 Haiti vs Scotland 🏴󠁧󠁢󠁳󠁣󠁴󠁿", "Group": "C"},
    {"Date": "14 Jun", "Time (SGT)": "12:00 PM", "Match": "🇦🇺 Australia vs Türkiye 🇹🇷", "Group": "D"},
    {"Date": "15 Jun", "Time (SGT)": "01:00 AM", "Match": "🇩🇪 Germany vs Curaçao 🇨🇼", "Group": "E"},
]

# Function to color the Long/Short cells
def color_positions(val):
    if val == "LONG":
        return 'background-color: #d4edda; color: #155724; font-weight: bold;'
    elif val == "SHORT":
        return 'background-color: #f8d7da; color: #721c24; font-weight: bold;'
    return ''

# --- 3. UI TABS ---
st.title("🏆 World Cup 2026: Market Mover")

tab1, tab2, tab3 = st.tabs(["🥇 Leaderboard", "📊 Market Groups", "📅 SGT Schedule"])

with tab1:
    st.header("Global Standings")
    try:
        df = pd.read_csv("participants.csv")
        # Apply the styling to the position columns
        styled_df = df.style.map(color_positions, subset=['Pos_1', 'Pos_2', 'Pos_3'])
        
        st.dataframe(
            styled_df,
            column_config={
                "Team_1": "Team 1", "Pos_1": "Pos",
                "Team_2": "Team 2", "Pos_2": "Pos",
                "Team_3": "Team 3", "Pos_3": "Pos"
            },
            hide_index=True, use_container_width=True
        )
    except FileNotFoundError:
        st.info("Upload participants.csv to see the rankings!")

with tab2:
    st.header("The Tiers & Rankings")
    t_cols = st.columns(4)
    for i, (tier, info) in enumerate(TIERS.items()):
        with t_cols[i]:
            st.markdown(f"<div class='{info['class']}'>{tier} Tier ({info['pts']} pts)</div>", unsafe_allow_html=True)
            for code, name in info["teams"]:
                # Custom HTML for single-line Flag + Name
                st.markdown(f"""
                    <div class="country-row">
                        <img src="{get_flag(code)}">
                        <span>{name}</span>
                    </div>
                    """, unsafe_allow_html=True)

with tab3:
    st.header("Tournament Schedule (Singapore Time)")
    st.dataframe(pd.DataFrame(FIXTURES), hide_index=True, use_container_width=True)
