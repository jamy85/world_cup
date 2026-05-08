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
    [data-testid="stVerticalBlock"] > div:has(div.stMarkdown) {
        background-color: rgba(255, 255, 255, 0.95);
        padding: 25px; border-radius: 15px; box-shadow: 0 4px 15px rgba(0,0,0,0.1);
    }
    .country-row { display: flex; align-items: center; gap: 12px; margin: 8px 0; }
    .country-row img { width: 30px; height: auto; border-radius: 2px; }
    .bracket-round { border: 1px solid #ddd; padding: 10px; border-radius: 8px; background: #f9f9f9; margin-bottom: 5px; text-align: center;}
    </style>
    """, unsafe_allow_html=True)

# --- 2. DATA UTILITIES ---
def get_flag_url(name_or_code):
    # Mapping for fixtures and tiers
    mapping = {
        "Mexico": "mx", "South Africa": "za", "South Korea": "kr", "Czechia": "cz",
        "Canada": "ca", "Bosnia": "ba", "Qatar": "qa", "Switzerland": "ch",
        "Brazil": "br", "Morocco": "ma", "Haiti": "ht", "Scotland": "gb-sct",
        "USA": "us", "Paraguay": "py", "Australia": "au", "Türkiye": "tr",
        "France": "fr", "Argentina": "ar", "Spain": "es", "England": "gb-eng",
        "Netherlands": "nl", "Portugal": "pt", "Germany": "de"
    }
    code = mapping.get(name_or_code, "un")
    return f"https://flagcdn.com/w80/{code.lower()}.png"

# --- 3. THE LEADERBOARD DATA ---
# (Simulated data - replace with your collated CSV)
try:
    df_participants = pd.read_csv("participants.csv")
except:
    df_participants = pd.DataFrame({
        "Participant": ["Sarah", "David", "James"],
        "Team_1": ["France", "Brazil", "Germany"], "Pos_1": ["LONG", "LONG", "SHORT"],
        "Team_2": ["USA", "England", "Japan"], "Pos_2": ["LONG", "SHORT", "LONG"],
        "Team_3": ["Germany", "Ghana", "Morocco"], "Pos_3": ["SHORT", "LONG", "LONG"]
    })

# --- 4. UI TABS ---
st.title("🏆 World Cup 2026: Market Mover")

tab1, tab2, tab3, tab4, tab5 = st.tabs(["🥇 Leaderboard", "📊 Market Tiers", "📈 Group Rankings", "📅 SGT Schedule", "🌳 Knockout Draw"])

with tab1:
    st.header("Global Standings")
    st.write("💡 *Select a row to see a deep dive of that player's picks.*")
    
    # Using data_editor for selection capability
    event = st.dataframe(
        df_participants,
        column_config={
            "Pos_1": st.column_config.TextColumn("Pos", help="Long or Short"),
            "Pos_2": st.column_config.TextColumn("Pos"),
            "Pos_3": st.column_config.TextColumn("Pos"),
        },
        hide_index=True,
        use_container_width=True,
        on_select="rerun",
        selection_mode="single-row"
    )

    # --- THE "PERSONALIZED" RESULTS SECTION ---
    if len(event.selection.rows) > 0:
        idx = event.selection.rows[0]
        p_name = df_participants.iloc[idx]["Participant"]
        st.divider()
        st.subheader(f"🔍 Deep Dive: {p_name}")
        
        # Show results for their 3 teams
        p_cols = st.columns(3)
        for i in range(1, 4):
            team = df_participants.iloc[idx][f"Team_{i}"]
            pos = df_participants.iloc[idx][f"Pos_{i}"]
            with p_cols[i-1]:
                st.image(get_flag_url(team), width=50)
                st.metric(label=f"Team {i}: {team}", value=pos, delta="Live Points: +12") # Placeholder logic
                st.caption(f"Status: In Group Stage")

with tab3:
    st.header("Current Group Standings")
    # Sample Table
    group_data = pd.DataFrame([
        {"Group": "A", "Team": "Mexico", "GP": 0, "GD": 0, "Pts": 0},
        {"Group": "A", "Team": "South Africa", "GP": 0, "GD": 0, "Pts": 0},
    ])
    group_data["Flag"] = group_data["Team"].apply(get_flag_url)
    
    st.dataframe(
        group_data,
        column_config={"Flag": st.column_config.ImageColumn(" ", width="small")},
        hide_index=True, use_container_width=True
    )

with tab4:
    st.header("Schedule (Singapore Time)")
    
    # Mock Schedule with Flags
    fixtures_df = pd.DataFrame([
        {"Date": "12 Jun", "Time": "03:00 AM", "T1": "Mexico", "T2": "South Africa", "Grp": "A"},
        {"Date": "12 Jun", "Time": "10:00 AM", "T1": "South Korea", "T2": "Czechia", "Grp": "A"},
    ])
    
    fixtures_df["Flag 1"] = fixtures_df["T1"].apply(get_flag_url)
    fixtures_df["Flag 2"] = fixtures_df["T2"].apply(get_flag_url)

    st.dataframe(
        fixtures_df[["Date", "Time", "Flag 1", "T1", "Flag 2", "T2", "Grp"]],
        column_config={
            "Flag 1": st.column_config.ImageColumn(" "),
            "Flag 2": st.column_config.ImageColumn(" "),
            "T1": "Home", "T2": "Away"
        },
        hide_index=True, use_container_width=True
    )

with tab5:
    st.header("Knockout Stage Bracket")
    st.write("The bracket will populate as teams qualify from the group stage.")
    
    c1, c2, c3, c4 = st.columns(4)
    with c1:
        st.write("**Round of 32**")
        st.markdown("<div class='bracket-round'>Winner A vs Runner-up B</div>", unsafe_allow_html=True)
        st.markdown("<div class='bracket-round'>Winner C vs Runner-up D</div>", unsafe_allow_html=True)
    with c2:
        st.write("**Round of 16**")
        st.markdown("<div class='bracket-round' style='margin-top:20px'>TBD</div>", unsafe_allow_html=True)
    with c3:
        st.write("**Quarter-Finals**")
        st.markdown("<div class='bracket-round' style='margin-top:40px'>TBD</div>", unsafe_allow_html=True)
    with c4:
        st.write("**Final**")
        st.markdown("<div class='bracket-round' style='background: gold; margin-top:60px'>🏆 CHAMPION 🏆</div>", unsafe_allow_html=True)
