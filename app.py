import datetime
import os
import re

import pandas as pd
import streamlit as st

import scoring

CACHE_FILE = "results_cache.csv"
SCHEDULE_FILE = "schedule.csv"

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

    /* Static HTML tables — avoid Streamlit's interactive grid (ResizeObserver
       loop / React #185) that flickers scrollbars on resize. The wrapper gives
       a plain CSS horizontal scrollbar for wide tables without that bug. */
    .wc-table-wrap { overflow-x: auto; width: 100%; }
    .wc-table { width: 100%; border-collapse: collapse; font-size: 0.9rem; }
    .wc-table th { text-align: left; padding: 8px 10px; border-bottom: 2px solid #e0e0e0; font-weight: 600; background: #f7f7f7; white-space: nowrap; }
    .wc-table td { padding: 6px 10px; border-bottom: 1px solid #eee; white-space: nowrap; }
    .wc-table tr:last-child td { border-bottom: none; }
    .wc-table img { vertical-align: middle; border: 1px solid #eee; border-radius: 3px; }
    .wc-num { text-align: right; font-variant-numeric: tabular-nums; }
    </style>
    """, unsafe_allow_html=True)

def render_table(df, image_cols=(), num_cols=None):
    """Render a DataFrame as a static HTML table inside a scrollable wrapper.

    Static markup sidesteps st.dataframe's interactive grid, whose
    ResizeObserver loop flickers scrollbars and can throw React error #185
    when a table is wider than its container.
    """
    if num_cols is None:
        num_cols = [c for c in df.columns
                    if c not in image_cols and pd.api.types.is_numeric_dtype(df[c])]
    num_cols = set(num_cols)
    image_cols = set(image_cols)

    head = "".join(f"<th class='{'wc-num' if c in num_cols else ''}'>{c}</th>" for c in df.columns)
    body = []
    for _, row in df.iterrows():
        cells = []
        for c in df.columns:
            v = row[c]
            if c in image_cols:
                inner = f"<img src='{v}' width='28'>" if v else ""
            else:
                inner = "" if pd.isna(v) else str(v)
            cells.append(f"<td class='{'wc-num' if c in num_cols else ''}'>{inner}</td>")
        body.append("<tr>" + "".join(cells) + "</tr>")

    html = (
        "<div class='wc-table-wrap'><table class='wc-table'>"
        f"<thead><tr>{head}</tr></thead><tbody>{''.join(body)}</tbody></table></div>"
    )
    st.markdown(html, unsafe_allow_html=True)

# --- 2. FLAGS & TIERS ---
# ISO flag codes (flagcdn) for every World Cup nation.
FLAG_CODES = {
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

def get_flag(name_or_code):
    code = FLAG_CODES.get(name_or_code, "un")
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

# Full 104-match SGT (GMT+8) schedule lives in schedule.csv. The "No" column
# holds the official FIFA match number (M73–M104) for knockout fixtures so the
# bracket references (e.g. "W(M74) vs W(M77)") stay anchored to it.
@st.cache_data
def load_schedule():
    df = pd.read_csv(SCHEDULE_FILE, dtype=str).fillna("")
    return df.to_dict("records")

SGT_SCHEDULE = load_schedule()

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
    except Exception:  # noqa: BLE001 — any failure -> use cached results
        states = _states_from_cache()
        return states, "cache", _cache_mtime()

def _cache_mtime():
    try:
        return datetime.datetime.fromtimestamp(os.path.getmtime(CACHE_FILE))
    except OSError:
        return None

# Group membership, derived once from the schedule (Stage == "Group X").
def _derive_group_teams(schedule):
    groups: dict[str, set] = {}
    for m in schedule:
        stage = m["Stage"]
        if not stage.startswith("Group "):
            continue
        group = stage.split(" ", 1)[1]  # "A", "B", …
        parts = m["Match"].split(" vs ")
        if len(parts) == 2:
            groups.setdefault(group, set()).update(p.strip() for p in parts)
    return groups

GROUP_TEAMS = _derive_group_teams(SGT_SCHEDULE)

# Single source of truth = the teams that actually appear in the schedule.
# Warn (don't crash) if the flag/ranking/tier tables drift out of sync with it.
def _validate_team_coverage():
    scheduled = {t for teams in GROUP_TEAMS.values() for t in teams}
    tiered = {t for d in TIERS.values() for t in d["teams"]}
    problems = []
    for label, known in (("flag", set(FLAG_CODES)), ("FIFA ranking", set(FIFA_RANKINGS)), ("tier", tiered)):
        missing = scheduled - known
        if missing:
            problems.append(f"{label}: {', '.join(sorted(missing))}")
    if problems:
        st.warning("⚠️ Some scheduled teams are missing data — " + " · ".join(problems))

# Load everything
expectations = load_expectations()
participants = load_participants()
all_teams = list(expectations.keys())

_validate_team_coverage()

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

    def _pick_label(pick):
        return f"{pick['team']} ({'L' if pick['position'] == 'Long' else 'S'})"

    board_rows = []
    for i, p in enumerate(scores["players"]):
        row = {"Rank": i + 1, "Player": p["name"], "Score": p["total"]}
        for j in range(3):  # always 3 columns, even if a player has fewer picks
            pick = p["picks"][j] if j < len(p["picks"]) else None
            row[f"Team {j + 1}"] = _pick_label(pick) if pick else "—"
            row[f"Pts {j + 1}"] = pick["total"] if pick else 0
        board_rows.append(row)
    board = pd.DataFrame(board_rows)
    render_table(board)

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
                        f"Progression {pick['progression']:+d} · Group {pick['league']:+d}"
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
    render_table(stage_df)

with tabs[2]:
    st.header("Group Stage Standings")
    st.caption("Live W/D/L and points (3 for a win, 1 for a draw) from the group stage.")

    groups_sorted = sorted(GROUP_TEAMS.keys())
    cols_per_row = 4
    for row_start in range(0, len(groups_sorted), cols_per_row):
        row_groups = groups_sorted[row_start:row_start + cols_per_row]
        cols = st.columns(len(row_groups))
        for col, grp in zip(cols, row_groups):
            rows = []
            for team in GROUP_TEAMS[grp]:
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
                render_table(grp_df)

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
    # Single vs double space → distinct column keys that both render as blank headers.
    filtered[" "] = filtered.apply(lambda r: _flag_safe(r["Match"], r["Stage"], 0), axis=1)
    filtered["  "] = filtered.apply(lambda r: _flag_safe(r["Match"], r["Stage"], 1), axis=1)

    render_table(
        filtered[["Date", "SGT Time", " ", "Match", "  ", "Stage"]],
        image_cols=(" ", "  "),
    )

with tabs[4]:
    st.header("Knockout Draw")

    def _prettify(match: str) -> str:
        """Expand short placeholders to readable descriptions."""
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

    def _by_no(stage):
        """Schedule rows for a stage, sorted by FIFA match number (the 'No' field)."""
        rows = [m for m in SGT_SCHEDULE if m["Stage"] == stage]
        return sorted(rows, key=lambda m: int(m["No"][1:]) if m["No"] else 0)

    kcols = st.columns(5)

    with kcols[0]:
        st.caption("Round of 32")
        for m in _by_no("Round of 32"):
            st.info(f"**{m['No']}:** {_prettify(m['Match'])}")

    with kcols[1]:
        st.caption("Round of 16")
        for m in _by_no("Round of 16"):
            st.info(f"**{m['No']}:** {m['Match']}")

    with kcols[2]:
        st.caption("Quarter-Finals")
        for m in _by_no("Quarter-Final"):
            st.warning(f"**{m['No']}:** {m['Match']}")

    with kcols[3]:
        st.caption("Semi-Finals")
        for m in _by_no("Semi-Final"):
            st.error(f"**{m['No']}:** {m['Match']}")

    with kcols[4]:
        st.caption("Final & 3rd Place")
        for m in _by_no("Final"):
            st.success(f"🏆 **{m['No']}:** {m['Match']}")
        for m in _by_no("3rd Place"):
            st.info(f"🥉 **{m['No']}:** {m['Match']}")
