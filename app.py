import datetime
import os

import pandas as pd
import streamlit as st

import scoring

CACHE_FILE = "results_cache.csv"

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
    }
    code = mapping.get(name_or_code, "un")
    return f"https://flagcdn.com/w40/{code.lower()}.png"

# Tiers (visual grouping by expectation score). Points here == starting expectation.
TIERS = {
    "Gold": {"pts": 30, "style": "gold-border", "teams": ["France", "Spain", "Argentina", "England", "Portugal", "Brazil", "Netherlands", "Morocco"]},
    "Silver": {"pts": 20, "style": "silver-border", "teams": ["Belgium", "Germany", "Croatia", "Colombia", "Senegal", "Mexico", "USA", "Uruguay"]},
    "Bronze": {"pts": 10, "style": "bronze-border", "teams": ["Japan", "Switzerland", "Türkiye", "Ecuador", "Austria", "South Korea", "Australia", "Norway"]},
    "Neutral": {"pts": 0, "style": "neutral-border", "teams": ["Canada", "Ghana", "South Africa", "Czechia", "Bosnia", "Scotland", "Paraguay", "Qatar"]},
}

ROUND_LABELS = {
    "Group": "Group Stage", "R32": "Round of 32", "R16": "Round of 16",
    "QF": "Quarter-Final", "SF": "Semi-Final", "Final": "Runner-up", "Winner": "🏆 Champion",
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
        }
    return states

def _save_states_to_cache(states):
    rows = [
        {"Team": t, "wins": s["wins"], "draws": s["draws"],
         "losses": s["losses"], "round_reached": s["round_reached"]}
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

if st.sidebar.button("🔄 Refresh results now"):
    get_team_states.clear()

states, source, updated_at = get_team_states(tuple(all_teams))
scores = scoring.compute_scores(participants, expectations, states)

# --- 4. UI TABS ---
st.title("🏆 World Cup 2026: Market Mover")

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
        {"Rank": i + 1, "Player": p["name"], "Score": p["total"]}
        for i, p in enumerate(scores["players"])
    ])
    st.dataframe(board, hide_index=True, use_container_width=True)

    st.divider()
    st.subheader("🔍 Portfolio breakdowns")
    for p in scores["players"]:
        with st.expander(f"**{p['name']}** — {p['total']:+d} pts"):
            cols = st.columns(3)
            for col, pick in zip(cols, p["picks"]):
                with col:
                    st.image(get_flag(pick["team"]), width=50)
                    pos_emoji = "📈" if pick["position"] == "Long" else "📉"
                    st.metric(
                        f"{pos_emoji} {pick['team']} ({pick['position']})",
                        f"{pick['total']:+d} pts",
                    )
                    st.caption(
                        f"Reached: {ROUND_LABELS.get(pick['round_reached'], pick['round_reached'])}  \n"
                        f"Expectation: {pick['expectation']}  ·  Record: {pick['record']}  \n"
                        f"Progression {pick['progression']:+d} · League {pick['league']:+d}"
                    )

with tabs[1]:
    st.header("The Market Tiers")
    st.caption("A team's starting **expectation** is its tier value. Beat it to score; fall short to lose points (reversed for Short picks).")
    t_cols = st.columns(4)
    for i, (tier, data) in enumerate(TIERS.items()):
        with t_cols[i]:
            st.markdown(f"<div class='tier-card {data['style']}'>{tier} Tier ({data['pts']} pts)</div>", unsafe_allow_html=True)
            for team in data["teams"]:
                st.markdown(f"<div class='country-item'><img src='{get_flag(team)}' width='25'> {team}</div>", unsafe_allow_html=True)

with tabs[2]:
    st.header("Group Stage Standings")
    st.caption("Live W/D/L and points (3 for a win, 1 for a draw) from the group stage.")
    rows = []
    for team, s in states.items():
        played = s["wins"] + s["draws"] + s["losses"]
        rows.append({
            "Flag": get_flag(team), "Team": team, "P": played,
            "W": s["wins"], "D": s["draws"], "L": s["losses"],
            "Pts": 3 * s["wins"] + s["draws"], "Round": ROUND_LABELS.get(s["round_reached"], s["round_reached"]),
        })
    standings = pd.DataFrame(rows).sort_values(["Pts", "W"], ascending=False)
    st.dataframe(
        standings,
        column_config={"Flag": st.column_config.ImageColumn(" ")},
        hide_index=True, use_container_width=True,
    )

with tabs[3]:
    st.header("Singapore Time Schedule")
    sched_df = pd.DataFrame(SGT_SCHEDULE)
    sched_df["Flag 1"] = sched_df["Match"].apply(lambda x: get_flag(x.split(" vs ")[0]))
    sched_df["Flag 2"] = sched_df["Match"].apply(lambda x: get_flag(x.split(" vs ")[1]))
    st.dataframe(
        sched_df[["Date", "SGT Time", "Flag 1", "Match", "Flag 2", "Group"]],
        column_config={
            "Flag 1": st.column_config.ImageColumn(" "),
            "Flag 2": st.column_config.ImageColumn(" "),
        },
        hide_index=True, use_container_width=True,
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
