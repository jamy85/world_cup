import datetime
import os

import pandas as pd
import streamlit as st

import scoring

CACHE_FILE = "results_cache.csv"

# --- 1. STYLING & PREMIUM GRASS BACKGROUND ---
st.set_page_config(page_title="RMD World Cup 2026 Sweepstake", layout="wide", page_icon="⚽")

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
    .tier-card { border-left: 12px solid; padding: 15px; border-radius: 10px; margin-bottom: 15px; background: #fff; overflow-wrap: break-word; word-break: break-word; box-sizing: border-box; width: 100%; }
    .sc-border { border-color: #E8B400; }
    .dh-border { border-color: #4A90D9; }
    .h-border  { border-color: #95A5A6; }

    /* Country List Flexbox */
    .country-item { display: flex; align-items: center; gap: 8px; font-weight: 500; margin-bottom: 4px; overflow: hidden; min-width: 0; }
    .country-item img { border: 1px solid #eee; border-radius: 3px; flex-shrink: 0; }
    .country-item span { white-space: nowrap; }
    .country-item-name { overflow: hidden; text-overflow: ellipsis; white-space: nowrap; min-width: 0; }
    </style>
    """, unsafe_allow_html=True)

# --- 2. FLAGS & TIERS ---
def get_flag(name_or_code):
    mapping = {
        "France": "fr", "Spain": "es", "Argentina": "ar", "England": "gb-eng", "Portugal": "pt",
        "Brazil": "br", "Netherlands": "nl", "Morocco": "ma", "Belgium": "be", "Germany": "de",
        "Croatia": "hr", "Colombia": "co", "Senegal": "sn", "Mexico": "mx", "USA": "us", "Uruguay": "uy",
        "South Africa": "za", "South Korea": "kr", "Czechia": "cz", "Canada": "ca", "Bosnia": "ba",
        "Qatar": "qa", "Switzerland": "ch", "Haiti": "ht", "Scotland": "gb-sct", "Paraguay": "py",
        "Australia": "au", "Türkiye": "tr", "Japan": "jp", "Ecuador": "ec", "Austria": "at",
        "Norway": "no", "Ghana": "gh",
        "Cape Verde": "cv", "Curaçao": "cw", "DR Congo": "cd",
        "Ivory Coast": "ci", "New Zealand": "nz", "Uzbekistan": "uz",
        "Sweden": "se", "Tunisia": "tn", "Saudi Arabia": "sa", "Iran": "ir",
        "Egypt": "eg", "Iraq": "iq", "Algeria": "dz", "Jordan": "jo", "Panama": "pa",
    }
    code = mapping.get(name_or_code, "un")
    return f"https://flagcdn.com/w40/{code.lower()}.png"

# Tiers (visual grouping by expectation score). Points here == starting expectation.
TIERS = {
    "Serious Contenders": {"pts": 35, "style": "sc-border", "teams": [
        "France", "Spain", "Argentina", "Brazil", "England", "Germany", "Portugal", "Netherlands",
    ]},
    "Dark Horses": {"pts": 15, "style": "dh-border", "teams": [
        "Belgium", "Morocco", "Colombia", "Uruguay", "Croatia", "Senegal",
        "Japan", "USA", "Mexico", "Türkiye", "South Korea", "Switzerland", "Norway",
    ]},
    "Hopefuls": {"pts": 0, "style": "h-border", "teams": [
        "Ecuador", "Austria", "Australia", "Ghana", "South Africa", "Czechia",
        "Bosnia", "Scotland", "Paraguay", "Qatar", "Canada", "Haiti", "Curaçao",
        "Ivory Coast", "Sweden", "Tunisia", "Cape Verde", "Saudi Arabia", "Iran",
        "New Zealand", "Egypt", "Iraq", "Algeria", "Jordan", "DR Congo", "Uzbekistan", "Panama",
    ]},
}

# FIFA Men's World Rankings — April 2026 (official update; next due 11 Jun 2026)
FIFA_RANKINGS = {
    "France": 1, "Spain": 2, "Argentina": 3, "England": 4, "Portugal": 5,
    "Brazil": 6, "Netherlands": 7, "Morocco": 8, "Belgium": 9, "Germany": 10,
    "Croatia": 11, "Colombia": 13, "Senegal": 14, "Mexico": 15, "USA": 16,
    "Uruguay": 17, "Japan": 18, "Switzerland": 19, "Iran": 21, "Türkiye": 22,
    "Austria": 23, "Ecuador": 24, "South Korea": 25, "Australia": 27,
    "Egypt": 28, "Algeria": 29, "Canada": 30, "Norway": 31, "Panama": 33,
    "Ivory Coast": 34, "Sweden": 38, "Paraguay": 40, "Czechia": 41,
    "Scotland": 43, "Tunisia": 45, "DR Congo": 46, "Uzbekistan": 50,
    "Qatar": 55, "Iraq": 57, "South Africa": 60, "Saudi Arabia": 61,
    "Jordan": 63, "Bosnia": 65, "Cape Verde": 69, "Ghana": 74,
    "Curaçao": 82, "Haiti": 83, "New Zealand": 85,
}

ROUND_LABELS = {
    "Group": "Group Stage", "R32": "Round of 32", "R16": "Round of 16",
    "QF": "Quarter-Final", "SF": "Semi-Final", "Final": "Runner-up", "Winner": "🏆 Champion",
}

# SGT Schedule (GMT+8) — full 104-match schedule
SGT_SCHEDULE = [
    # Group Stage
    {"Date": "12 Jun 2026", "SGT Time": "03:00 AM", "Match": "Mexico vs South Africa", "Stage": "Group A"},
    {"Date": "12 Jun 2026", "SGT Time": "10:00 AM", "Match": "South Korea vs Czechia", "Stage": "Group A"},
    {"Date": "13 Jun 2026", "SGT Time": "03:00 AM", "Match": "Canada vs Bosnia", "Stage": "Group B"},
    {"Date": "13 Jun 2026", "SGT Time": "09:00 AM", "Match": "USA vs Paraguay", "Stage": "Group D"},
    {"Date": "14 Jun 2026", "SGT Time": "03:00 AM", "Match": "Qatar vs Switzerland", "Stage": "Group B"},
    {"Date": "14 Jun 2026", "SGT Time": "06:00 AM", "Match": "Brazil vs Morocco", "Stage": "Group C"},
    {"Date": "14 Jun 2026", "SGT Time": "09:00 AM", "Match": "Haiti vs Scotland", "Stage": "Group C"},
    {"Date": "14 Jun 2026", "SGT Time": "12:00 PM", "Match": "Australia vs Türkiye", "Stage": "Group D"},
    {"Date": "15 Jun 2026", "SGT Time": "01:00 AM", "Match": "Germany vs Curaçao", "Stage": "Group E"},
    {"Date": "15 Jun 2026", "SGT Time": "04:00 AM", "Match": "Netherlands vs Japan", "Stage": "Group F"},
    {"Date": "15 Jun 2026", "SGT Time": "07:00 AM", "Match": "Ivory Coast vs Ecuador", "Stage": "Group E"},
    {"Date": "15 Jun 2026", "SGT Time": "10:00 AM", "Match": "Sweden vs Tunisia", "Stage": "Group F"},
    {"Date": "16 Jun 2026", "SGT Time": "12:00 AM", "Match": "Spain vs Cape Verde", "Stage": "Group H"},
    {"Date": "16 Jun 2026", "SGT Time": "03:00 AM", "Match": "Belgium vs Egypt", "Stage": "Group G"},
    {"Date": "16 Jun 2026", "SGT Time": "06:00 AM", "Match": "Saudi Arabia vs Uruguay", "Stage": "Group H"},
    {"Date": "16 Jun 2026", "SGT Time": "09:00 AM", "Match": "Iran vs New Zealand", "Stage": "Group G"},
    {"Date": "17 Jun 2026", "SGT Time": "03:00 AM", "Match": "France vs Senegal", "Stage": "Group I"},
    {"Date": "17 Jun 2026", "SGT Time": "06:00 AM", "Match": "Iraq vs Norway", "Stage": "Group I"},
    {"Date": "17 Jun 2026", "SGT Time": "09:00 AM", "Match": "Argentina vs Algeria", "Stage": "Group J"},
    {"Date": "17 Jun 2026", "SGT Time": "12:00 PM", "Match": "Austria vs Jordan", "Stage": "Group J"},
    {"Date": "18 Jun 2026", "SGT Time": "01:00 AM", "Match": "Portugal vs DR Congo", "Stage": "Group K"},
    {"Date": "18 Jun 2026", "SGT Time": "04:00 AM", "Match": "England vs Croatia", "Stage": "Group L"},
    {"Date": "18 Jun 2026", "SGT Time": "07:00 AM", "Match": "Ghana vs Panama", "Stage": "Group L"},
    {"Date": "18 Jun 2026", "SGT Time": "10:00 AM", "Match": "Uzbekistan vs Colombia", "Stage": "Group K"},
    {"Date": "19 Jun 2026", "SGT Time": "12:00 AM", "Match": "Czechia vs South Africa", "Stage": "Group A"},
    {"Date": "19 Jun 2026", "SGT Time": "03:00 AM", "Match": "Switzerland vs Bosnia", "Stage": "Group B"},
    {"Date": "19 Jun 2026", "SGT Time": "06:00 AM", "Match": "Canada vs Qatar", "Stage": "Group B"},
    {"Date": "19 Jun 2026", "SGT Time": "09:00 AM", "Match": "Mexico vs South Korea", "Stage": "Group A"},
    {"Date": "20 Jun 2026", "SGT Time": "03:00 AM", "Match": "USA vs Australia", "Stage": "Group D"},
    {"Date": "20 Jun 2026", "SGT Time": "06:00 AM", "Match": "Scotland vs Morocco", "Stage": "Group C"},
    {"Date": "20 Jun 2026", "SGT Time": "08:30 AM", "Match": "Brazil vs Haiti", "Stage": "Group C"},
    {"Date": "20 Jun 2026", "SGT Time": "11:00 AM", "Match": "Türkiye vs Paraguay", "Stage": "Group D"},
    {"Date": "21 Jun 2026", "SGT Time": "01:00 AM", "Match": "Netherlands vs Sweden", "Stage": "Group F"},
    {"Date": "21 Jun 2026", "SGT Time": "04:00 AM", "Match": "Germany vs Ivory Coast", "Stage": "Group E"},
    {"Date": "21 Jun 2026", "SGT Time": "08:00 AM", "Match": "Ecuador vs Curaçao", "Stage": "Group E"},
    {"Date": "21 Jun 2026", "SGT Time": "12:00 PM", "Match": "Tunisia vs Japan", "Stage": "Group F"},
    {"Date": "22 Jun 2026", "SGT Time": "12:00 AM", "Match": "Spain vs Saudi Arabia", "Stage": "Group H"},
    {"Date": "22 Jun 2026", "SGT Time": "03:00 AM", "Match": "Belgium vs Iran", "Stage": "Group G"},
    {"Date": "22 Jun 2026", "SGT Time": "06:00 AM", "Match": "Uruguay vs Cape Verde", "Stage": "Group H"},
    {"Date": "22 Jun 2026", "SGT Time": "09:00 AM", "Match": "New Zealand vs Egypt", "Stage": "Group G"},
    {"Date": "23 Jun 2026", "SGT Time": "01:00 AM", "Match": "Argentina vs Austria", "Stage": "Group J"},
    {"Date": "23 Jun 2026", "SGT Time": "05:00 AM", "Match": "France vs Iraq", "Stage": "Group I"},
    {"Date": "23 Jun 2026", "SGT Time": "08:00 AM", "Match": "Norway vs Senegal", "Stage": "Group I"},
    {"Date": "23 Jun 2026", "SGT Time": "11:00 AM", "Match": "Jordan vs Algeria", "Stage": "Group J"},
    {"Date": "24 Jun 2026", "SGT Time": "01:00 AM", "Match": "Portugal vs Uzbekistan", "Stage": "Group K"},
    {"Date": "24 Jun 2026", "SGT Time": "04:00 AM", "Match": "England vs Ghana", "Stage": "Group L"},
    {"Date": "24 Jun 2026", "SGT Time": "07:00 AM", "Match": "Panama vs Croatia", "Stage": "Group L"},
    {"Date": "24 Jun 2026", "SGT Time": "10:00 AM", "Match": "Colombia vs DR Congo", "Stage": "Group K"},
    {"Date": "25 Jun 2026", "SGT Time": "03:00 AM", "Match": "Switzerland vs Canada", "Stage": "Group B"},
    {"Date": "25 Jun 2026", "SGT Time": "03:00 AM", "Match": "Bosnia vs Qatar", "Stage": "Group B"},
    {"Date": "25 Jun 2026", "SGT Time": "06:00 AM", "Match": "Scotland vs Brazil", "Stage": "Group C"},
    {"Date": "25 Jun 2026", "SGT Time": "06:00 AM", "Match": "Morocco vs Haiti", "Stage": "Group C"},
    {"Date": "25 Jun 2026", "SGT Time": "09:00 AM", "Match": "Czechia vs Mexico", "Stage": "Group A"},
    {"Date": "25 Jun 2026", "SGT Time": "09:00 AM", "Match": "South Africa vs South Korea", "Stage": "Group A"},
    {"Date": "26 Jun 2026", "SGT Time": "04:00 AM", "Match": "Curaçao vs Ivory Coast", "Stage": "Group E"},
    {"Date": "26 Jun 2026", "SGT Time": "04:00 AM", "Match": "Ecuador vs Germany", "Stage": "Group E"},
    {"Date": "26 Jun 2026", "SGT Time": "07:00 AM", "Match": "Japan vs Sweden", "Stage": "Group F"},
    {"Date": "26 Jun 2026", "SGT Time": "07:00 AM", "Match": "Tunisia vs Netherlands", "Stage": "Group F"},
    {"Date": "26 Jun 2026", "SGT Time": "10:00 AM", "Match": "Türkiye vs USA", "Stage": "Group D"},
    {"Date": "26 Jun 2026", "SGT Time": "10:00 AM", "Match": "Paraguay vs Australia", "Stage": "Group D"},
    {"Date": "27 Jun 2026", "SGT Time": "03:00 AM", "Match": "Norway vs France", "Stage": "Group I"},
    {"Date": "27 Jun 2026", "SGT Time": "03:00 AM", "Match": "Senegal vs Iraq", "Stage": "Group I"},
    {"Date": "27 Jun 2026", "SGT Time": "08:00 AM", "Match": "Cape Verde vs Saudi Arabia", "Stage": "Group H"},
    {"Date": "27 Jun 2026", "SGT Time": "08:00 AM", "Match": "Uruguay vs Spain", "Stage": "Group H"},
    {"Date": "27 Jun 2026", "SGT Time": "11:00 AM", "Match": "Egypt vs Iran", "Stage": "Group G"},
    {"Date": "27 Jun 2026", "SGT Time": "11:00 AM", "Match": "New Zealand vs Belgium", "Stage": "Group G"},
    {"Date": "28 Jun 2026", "SGT Time": "05:00 AM", "Match": "Panama vs England", "Stage": "Group L"},
    {"Date": "28 Jun 2026", "SGT Time": "05:00 AM", "Match": "Croatia vs Ghana", "Stage": "Group L"},
    {"Date": "28 Jun 2026", "SGT Time": "07:30 AM", "Match": "Colombia vs Portugal", "Stage": "Group K"},
    {"Date": "28 Jun 2026", "SGT Time": "07:30 AM", "Match": "DR Congo vs Uzbekistan", "Stage": "Group K"},
    {"Date": "28 Jun 2026", "SGT Time": "10:00 AM", "Match": "Algeria vs Austria", "Stage": "Group J"},
    {"Date": "28 Jun 2026", "SGT Time": "10:00 AM", "Match": "Jordan vs Argentina", "Stage": "Group J"},
    # Round of 32  (match numbers = FIFA M73–M88)
    {"Date": "29 Jun 2026", "SGT Time": "03:00 AM", "Match": "Runner-up A vs Runner-up B", "Stage": "Round of 32"},           # M73
    {"Date": "30 Jun 2026", "SGT Time": "01:00 AM", "Match": "Winner C vs Runner-up F", "Stage": "Round of 32"},              # M76
    {"Date": "30 Jun 2026", "SGT Time": "04:30 AM", "Match": "Winner E vs 3rd (A/B/C/D/F)", "Stage": "Round of 32"},         # M74
    {"Date": "30 Jun 2026", "SGT Time": "09:00 AM", "Match": "Winner F vs Runner-up C", "Stage": "Round of 32"},              # M75
    {"Date": "01 Jul 2026", "SGT Time": "01:00 AM", "Match": "Runner-up E vs Runner-up I", "Stage": "Round of 32"},           # M78
    {"Date": "01 Jul 2026", "SGT Time": "05:00 AM", "Match": "Winner I vs 3rd (C/D/F/G/H)", "Stage": "Round of 32"},         # M77
    {"Date": "01 Jul 2026", "SGT Time": "09:00 AM", "Match": "Winner A vs 3rd (C/E/F/H/I)", "Stage": "Round of 32"},         # M79
    {"Date": "02 Jul 2026", "SGT Time": "12:00 AM", "Match": "Winner L vs 3rd (E/H/I/J/K)", "Stage": "Round of 32"},         # M80
    {"Date": "02 Jul 2026", "SGT Time": "04:00 AM", "Match": "Winner G vs 3rd (A/E/H/I/J)", "Stage": "Round of 32"},         # M82
    {"Date": "02 Jul 2026", "SGT Time": "08:00 AM", "Match": "Winner D vs 3rd (B/E/F/I/J)", "Stage": "Round of 32"},         # M81
    {"Date": "03 Jul 2026", "SGT Time": "03:00 AM", "Match": "Winner H vs Runner-up J", "Stage": "Round of 32"},              # M84
    {"Date": "03 Jul 2026", "SGT Time": "07:00 AM", "Match": "Runner-up K vs Runner-up L", "Stage": "Round of 32"},           # M83
    {"Date": "03 Jul 2026", "SGT Time": "11:00 AM", "Match": "Winner B vs 3rd (E/F/G/I/J)", "Stage": "Round of 32"},         # M85
    {"Date": "04 Jul 2026", "SGT Time": "02:00 AM", "Match": "Runner-up D vs Runner-up G", "Stage": "Round of 32"},           # M88
    {"Date": "04 Jul 2026", "SGT Time": "06:00 AM", "Match": "Winner J vs Runner-up H", "Stage": "Round of 32"},              # M86
    {"Date": "04 Jul 2026", "SGT Time": "09:30 AM", "Match": "Winner K vs 3rd (D/E/I/J/L)", "Stage": "Round of 32"},         # M87
    # Round of 16  (winners of M74+M77, M73+M75, M76+M78, M79+M80, M83+M84, M81+M82, M86+M88, M85+M87)
    {"Date": "05 Jul 2026", "SGT Time": "01:00 AM", "Match": "W(M74) vs W(M77)", "Stage": "Round of 16"},
    {"Date": "05 Jul 2026", "SGT Time": "05:00 AM", "Match": "W(M73) vs W(M75)", "Stage": "Round of 16"},
    {"Date": "06 Jul 2026", "SGT Time": "04:00 AM", "Match": "W(M76) vs W(M78)", "Stage": "Round of 16"},
    {"Date": "06 Jul 2026", "SGT Time": "08:00 AM", "Match": "W(M79) vs W(M80)", "Stage": "Round of 16"},
    {"Date": "07 Jul 2026", "SGT Time": "03:00 AM", "Match": "W(M83) vs W(M84)", "Stage": "Round of 16"},
    {"Date": "07 Jul 2026", "SGT Time": "08:00 AM", "Match": "W(M81) vs W(M82)", "Stage": "Round of 16"},
    {"Date": "08 Jul 2026", "SGT Time": "12:00 AM", "Match": "W(M86) vs W(M88)", "Stage": "Round of 16"},
    {"Date": "08 Jul 2026", "SGT Time": "04:00 AM", "Match": "W(M85) vs W(M87)", "Stage": "Round of 16"},
    # Quarter-Finals  (M89=W(M74/77) vs W(M77/74), etc.)
    {"Date": "10 Jul 2026", "SGT Time": "04:00 AM", "Match": "W(M89) vs W(M90)", "Stage": "Quarter-Final"},
    {"Date": "11 Jul 2026", "SGT Time": "03:00 AM", "Match": "W(M93) vs W(M94)", "Stage": "Quarter-Final"},
    {"Date": "12 Jul 2026", "SGT Time": "05:00 AM", "Match": "W(M91) vs W(M92)", "Stage": "Quarter-Final"},
    {"Date": "12 Jul 2026", "SGT Time": "09:00 AM", "Match": "W(M95) vs W(M96)", "Stage": "Quarter-Final"},
    # Semi-Finals
    {"Date": "15 Jul 2026", "SGT Time": "03:00 AM", "Match": "W(M97) vs W(M98)", "Stage": "Semi-Final"},
    {"Date": "16 Jul 2026", "SGT Time": "03:00 AM", "Match": "W(M99) vs W(M100)", "Stage": "Semi-Final"},
    # 3rd Place & Final
    {"Date": "19 Jul 2026", "SGT Time": "05:00 AM", "Match": "3rd Place Play-off", "Stage": "3rd Place"},
    {"Date": "20 Jul 2026", "SGT Time": "03:00 AM", "Match": "🏆 Final", "Stage": "Final"},
]

# --- 3. DATA LOADING ---
@st.cache_data
def load_expectations():
    df = pd.read_csv("team_expectations.csv")
    return df.set_index("Team")["Expectation"].to_dict()

@st.cache_data
def load_participants():
    return pd.read_csv("participants.csv")

def _states_from_cache():
    """Read the last-known team states from disk (fallback / pre-fetch)."""
    df = pd.read_csv(CACHE_FILE)
    states = {}
    for _, r in df.iterrows():
        states[r["Team"]] = {
            "wins": int(r["wins"]), "draws": int(r["draws"]),
            "losses": int(r["losses"]), "round_reached": r["round_reached"],
            "gf": int(r["gf"]) if "gf" in r else 0,
            "ga": int(r["ga"]) if "ga" in r else 0,
        }
    return states

def _save_states_to_cache(states):
    rows = [
        {"Team": t, "wins": s["wins"], "draws": s["draws"],
         "losses": s["losses"], "round_reached": s["round_reached"],
         "gf": s.get("gf", 0), "ga": s.get("ga", 0)}
        for t, s in states.items()
    ]
    pd.DataFrame(rows).to_csv(CACHE_FILE, index=False)

# Fetch live results at most once per day (24h cache). Live failures fall back
# to the on-disk cache so the leaderboard always renders.
@st.cache_data(ttl=60 * 60 * 24, show_spinner="Fetching latest results…")
def get_team_states(all_teams):
    try:
        events = scoring.fetch_events()
        if not events:
            raise ValueError("no events returned")
        states = scoring.compute_team_states(events, all_teams)
        _save_states_to_cache(states)
        return states, "live", datetime.datetime.now()
    except Exception as exc:  # noqa: BLE001 — any failure -> use cached results
        states = _states_from_cache()
        return states, f"cache ({exc})", _cache_mtime()

def _cache_mtime():
    try:
        return datetime.datetime.fromtimestamp(os.path.getmtime(CACHE_FILE))
    except OSError:
        return None

# Load everything
expectations = load_expectations()
participants = load_participants()
all_teams = list(expectations.keys())

states, source, updated_at = get_team_states(tuple(all_teams))
scores = scoring.compute_scores(participants, expectations, states)

# --- 4. UI TABS ---
st.title("🏆 RMD World Cup 2026 Sweepstake")

stamp = updated_at.strftime("%d %b %Y, %H:%M") if updated_at else "unknown"
if source == "live":
    st.caption(f"📡 Results updated live · {stamp} · refreshes once a day")
else:
    st.caption(f"💾 Showing last saved results · {stamp} · live fetch unavailable, will retry")

tabs = st.tabs(["🥇 Leaderboard", "📊 Market Tiers", "📈 Group Rankings", "📅 SGT Schedule", "🌳 Knockout Draw"])

with tabs[0]:
    st.header("Tournament Leaderboard")
    st.info("💡 Expand a player to see how each pick contributes to their score.")

    board = pd.DataFrame([
        {
            "Rank": i + 1, "Player": p["name"], "Score": p["total"],
            "Team 1": f"{p['picks'][0]['team']} ({'L' if p['picks'][0]['position'] == 'Long' else 'S'})", "Pts 1": p["picks"][0]["total"],
            "Team 2": f"{p['picks'][1]['team']} ({'L' if p['picks'][1]['position'] == 'Long' else 'S'})", "Pts 2": p["picks"][1]["total"],
            "Team 3": f"{p['picks'][2]['team']} ({'L' if p['picks'][2]['position'] == 'Long' else 'S'})", "Pts 3": p["picks"][2]["total"],
        }
        for i, p in enumerate(scores["players"])
    ])
    st.dataframe(board, hide_index=True, use_container_width=True, height=38 + len(board) * 35)

    st.divider()
    st.subheader("🔍 Portfolio breakdowns")
    for p in scores["players"]:
        with st.expander(f"**{p['name']}** — {p['total']:+d} pts"):
            cols = st.columns(3)
            for col, pick in zip(cols, p["picks"]):
                with col:
                    _team = pick["team"]
                    st.markdown(f"<div class='country-item'><img src='{get_flag(_team)}' width='25'><span class='country-item-name'>{_team}</span></div>", unsafe_allow_html=True)
                    pos_emoji = "📈" if pick["position"] == "Long" else "📉"
                    st.metric(
                        f"{pos_emoji} {pick['position']}",
                        f"{pick['total']:+d} pts",
                    )
                    st.caption(
                        f"Reached: {ROUND_LABELS.get(pick['round_reached'], pick['round_reached'])}  \n"
                        f"Expectation: {pick['expectation']}  ·  Record: {pick['record']}  \n"
                        f"Progression {pick['progression']:+d} · League {pick['league']:+d}"
                    )

with tabs[1]:
    st.header("The Market Tiers")
    st.caption("A team's starting **expectation** is its tier value. Beat it to score; fall short to lose points (reversed for Short picks). The number next to each team is their FIFA world ranking — teams are sorted by this within each tier.")
    t_cols = st.columns(3)
    for i, (tier, data) in enumerate(TIERS.items()):
        with t_cols[i]:
            st.markdown(f"<div class='tier-card {data['style']}'>{tier} ({data['pts']} pts expectation)</div>", unsafe_allow_html=True)
            sorted_teams = sorted(data["teams"], key=lambda t: FIFA_RANKINGS.get(t, 999))
            for team in sorted_teams:
                rank = FIFA_RANKINGS.get(team, "—")
                st.markdown(f"<div class='country-item'><img src='{get_flag(team)}' width='25'><span style='color:#888;font-size:0.8em;min-width:26px;display:inline-block'>#{rank}</span><span class='country-item-name'>{team}</span></div>", unsafe_allow_html=True)

    st.divider()
    st.subheader("Progression points by stage")
    st.caption("Points earned from reaching each round (Long position). Short picks are the inverse. Group stage points (W/D/L) are added separately.")

    stage_rows = []
    for round_key, round_label in ROUND_LABELS.items():
        row = {"Stage": round_label}
        for tier, data in TIERS.items():
            row[f"{tier} ({data['pts']} pts)"] = scoring.ROUND_POINTS[round_key] - data["pts"]
        stage_rows.append(row)

    stage_df = pd.DataFrame(stage_rows)
    st.dataframe(stage_df, hide_index=True, use_container_width=True, height=38 + len(stage_df) * 35)

with tabs[2]:
    st.header("Group Stage Standings")
    st.caption("Live W/D/L and points (3 for a win, 1 for a draw) from the group stage.")

    # Derive group membership from schedule
    group_teams: dict[str, set] = {}
    for m in SGT_SCHEDULE:
        stage = m["Stage"]
        if not stage.startswith("Group "):
            continue
        group = stage.split(" ", 1)[1]  # "A", "B", …
        parts = m["Match"].split(" vs ")
        if len(parts) == 2:
            group_teams.setdefault(group, set()).update(p.strip() for p in parts)

    groups_sorted = sorted(group_teams.keys())
    cols_per_row = 4
    for row_start in range(0, len(groups_sorted), cols_per_row):
        row_groups = groups_sorted[row_start:row_start + cols_per_row]
        cols = st.columns(len(row_groups))
        for col, grp in zip(cols, row_groups):
            rows = []
            for team in group_teams[grp]:
                s = states.get(team, {"wins": 0, "draws": 0, "losses": 0, "round_reached": "Group"})
                pts = 3 * s["wins"] + s["draws"]
                gd = s.get("gf", 0) - s.get("ga", 0)
                rows.append({
                    "Team": team,
                    "Pts": pts, "W": s["wins"], "D": s["draws"], "L": s["losses"],
                    "GD": gd,
                })
            grp_df = pd.DataFrame(rows).sort_values(["Pts", "GD", "W"], ascending=False)
            with col:
                st.subheader(f"Group {grp}")
                st.dataframe(
                    grp_df,
                    hide_index=True, use_container_width=True,
                    height=38 + len(grp_df) * 35,
                )

with tabs[3]:
    st.header("Singapore Time Schedule")

    sched_df = pd.DataFrame(SGT_SCHEDULE)
    sched_df["_date"] = pd.to_datetime(sched_df["Date"], format="%d %b %Y").dt.date
    today = datetime.date.today()

    view = st.radio("Show", ["Upcoming", "Past", "All"], horizontal=True, index=0)
    if view == "Upcoming":
        filtered = sched_df[sched_df["_date"] >= today]
    elif view == "Past":
        filtered = sched_df[sched_df["_date"] < today]
    else:
        filtered = sched_df

    def _flag_safe(match, stage, idx):
        if not stage.startswith("Group "):
            return ""
        parts = match.split(" vs ")
        return get_flag(parts[idx].strip()) if len(parts) > idx else ""

    filtered = filtered.copy()
    filtered["Flag 1"] = filtered.apply(lambda r: _flag_safe(r["Match"], r["Stage"], 0), axis=1)
    filtered["Flag 2"] = filtered.apply(lambda r: _flag_safe(r["Match"], r["Stage"], 1), axis=1)

    st.dataframe(
        filtered[["Date", "SGT Time", "Flag 1", "Match", "Flag 2", "Stage"]],
        column_config={
            "Flag 1": st.column_config.ImageColumn(" "),
            "Flag 2": st.column_config.ImageColumn(" "),
        },
        hide_index=True, use_container_width=True, height=38 + len(filtered) * 35,
    )

with tabs[4]:
    st.header("Knockout Draw")

    def _prettify(match: str) -> str:
        """Expand short placeholders to readable descriptions."""
        import re
        def _expand(name):
            name = name.strip()
            m = re.match(r"^Winner ([A-L])$", name)
            if m:
                return f"Winner Group {m.group(1)}"
            m = re.match(r"^Runner-up ([A-L])$", name)
            if m:
                return f"Runner-up Group {m.group(1)}"
            m = re.match(r"^3rd \((.+)\)$", name)
            if m:
                return f"Best 3rd ({m.group(1)})"
            return name
        parts = match.split(" vs ")
        return " vs ".join(_expand(p) for p in parts) if len(parts) == 2 else match

    _r32  = [m for m in SGT_SCHEDULE if m["Stage"] == "Round of 32"]
    _r16  = [m for m in SGT_SCHEDULE if m["Stage"] == "Round of 16"]
    _qf   = [m for m in SGT_SCHEDULE if m["Stage"] == "Quarter-Final"]
    _sf   = [m for m in SGT_SCHEDULE if m["Stage"] == "Semi-Final"]
    _fin  = [m for m in SGT_SCHEDULE if m["Stage"] == "Final"]

    # Official FIFA match numbers (M73–M104)
    _R32_NOS = ["M73","M76","M74","M75","M78","M77","M79","M80","M82","M81","M84","M83","M85","M88","M86","M87"]
    _R16_NOS = ["M89","M90","M91","M92","M93","M94","M95","M96"]
    _QF_NOS  = ["M97","M98","M99","M100"]
    _SF_NOS  = ["M101","M102"]

    kcols = st.columns(5)

    def _sorted(nos, matches):
        return sorted(zip(nos, matches), key=lambda x: int(x[0][1:]))

    with kcols[0]:
        st.caption("Round of 32")
        for no, m in _sorted(_R32_NOS, _r32):
            st.info(f"**{no}:** {_prettify(m['Match'])}")

    with kcols[1]:
        st.caption("Round of 16")
        for no, m in _sorted(_R16_NOS, _r16):
            st.info(f"**{no}:** {m['Match']}")

    with kcols[2]:
        st.caption("Quarter-Finals")
        for no, m in _sorted(_QF_NOS, _qf):
            st.warning(f"**{no}:** {m['Match']}")

    with kcols[3]:
        st.caption("Semi-Finals")
        for no, m in _sorted(_SF_NOS, _sf):
            st.error(f"**{no}:** {m['Match']}")

    with kcols[4]:
        st.caption("Final")
        for m in _fin:
            st.success(m["Match"])
