import datetime
import os
import re

import altair as alt
import pandas as pd
import streamlit as st

import scoring

CACHE_FILE = "results_cache.csv"     # auto-fetched results (GitHub Action)
RESULTS_FILE = "results.csv"         # manual results / overrides (hand-edited)
SCHEDULE_FILE = "schedule.csv"
REFRESH_FILE = "last_refresh.txt"    # UTC ISO timestamp of the last refresh run

# --- 1. STYLING & PREMIUM GRASS BACKGROUND ---
st.set_page_config(page_title="RMD World Cup 2026 Sweepstake", layout="wide", page_icon="⚽")

st.markdown("""
    <style>
    .stApp {
        background-image: url("https://images.unsplash.com/photo-1556056504-517173f44056?q=80&w=2000");
        background-attachment: fixed;
        background-size: cover;
    }
    /* One white card for the whole page (was: a box around every element,
       which trapped each table in its own narrow box). */
    .block-container {
        background-color: rgba(255, 255, 255, 0.96);
        padding: 2rem 2.5rem 3rem;
        border-radius: 20px;
        box-shadow: 0 8px 32px rgba(0,0,0,0.2);
        margin-top: 2rem;
        margin-bottom: 2rem;
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
    .wc-table td { padding: 6px 10px; border-bottom: 1px solid #eee; }      /* cells wrap so the table fits its card */
    .wc-table tr:last-child td { border-bottom: none; }
    .wc-table img { vertical-align: middle; border: 1px solid #eee; border-radius: 3px; }
    .wc-num { text-align: right; font-variant-numeric: tabular-nums; white-space: nowrap; }
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

# NOTE: the CSV loaders below are intentionally NOT cached with
# @st.cache_data. The files are tiny, and caching them means an edit (a new
# participant, a manual result) wouldn't show until the app process restarts —
# a confusing "I changed the file but nothing happened" trap. Reading them
# fresh each rerun costs microseconds and makes edits appear on a refresh.

# Full 104-match SGT (GMT+8) schedule lives in schedule.csv. The "No" column
# holds the official FIFA match number (M73–M104) for knockout fixtures so the
# bracket references (e.g. "W(M74) vs W(M77)") stay anchored to it.
def load_schedule():
    df = pd.read_csv(SCHEDULE_FILE, dtype=str).fillna("")
    return df.to_dict("records")

SGT_SCHEDULE = load_schedule()

# Group membership, derived from the schedule (Stage == "Group X"). Needed by
# the results pipeline (group qualification) and the standings display.
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

# --- 3. DATA LOADING ---
def load_expectations():
    df = pd.read_csv("team_expectations.csv")
    return df.set_index("Team")["Expectation"].to_dict()

def load_participants():
    return pd.read_csv("participants.csv")

# Results come from two committed, match-level CSVs (Home, Away, HomeScore,
# AwayScore, Stage, Date):
#   • results_cache.csv — written once a day by the GitHub Action (fetch_results.py)
#   • results.csv       — hand-edited manual entries / corrections
# Manual entries WIN on conflict, so anything the auto-fetch misses or gets
# wrong can always be fixed by editing results.csv. The app only reads these
# committed files — no per-visitor API calls. Date is optional: when present it
# fixes a match to its exact day on the score-over-time chart (used for
# knockouts, which the schedule can't date by team); blank falls back to the
# schedule. Group rows in results.csv are pre-filled with their schedule dates.
def _read_results(path):
    """Return {(Home, Away): row-dict} for rows that have both scores."""
    out = {}
    try:
        df = pd.read_csv(path, dtype=str).fillna("")
    except (OSError, pd.errors.EmptyDataError):
        return out
    for _, r in df.iterrows():
        hs, as_ = str(r.get("HomeScore", "")).strip(), str(r.get("AwayScore", "")).strip()
        if not (hs.isdigit() and as_.isdigit()):
            continue
        home, away = str(r["Home"]).strip(), str(r["Away"]).strip()
        out[(home, away)] = {
            "home": home, "away": away,
            "home_score": int(hs), "away_score": int(as_),
            "stage": str(r.get("Stage", "")).strip(),
            "date": str(r.get("Date", "")).strip(),  # optional; blank -> schedule fallback
        }
    return out

def _merged_results():
    """Auto-fetched results, with hand-edited results.csv overriding on conflict."""
    merged = _read_results(CACHE_FILE)          # auto first…
    merged.update(_read_results(RESULTS_FILE))  # …then manual overrides win
    return list(merged.values())

def get_team_states(all_teams, results):
    events = scoring.build_events(results)
    states = scoring.compute_team_states(events, list(all_teams), GROUP_TEAMS)
    source = "results" if events else "none"
    return states, source, _results_updated_at()

def _results_updated_at():
    """Most recent change to either results file (≈ last deploy on the Cloud)."""
    times = []
    for path in (CACHE_FILE, RESULTS_FILE):
        try:
            times.append(os.path.getmtime(path))
        except OSError:
            pass
    return datetime.datetime.fromtimestamp(max(times)) if times else None

def _last_refresh_at():
    """When the refresh job (daily cron or manual trigger) last ran, as written
    to last_refresh.txt by fetch_results.py. Falls back to the results files'
    mtime if the stamp file isn't there yet (e.g. before the first run)."""
    try:
        with open(REFRESH_FILE, encoding="utf-8") as f:
            return datetime.datetime.fromisoformat(f.read().strip())
    except (OSError, ValueError):
        return _results_updated_at()

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

merged_results = _merged_results()
states, source, _ = get_team_states(tuple(all_teams), merged_results)
scores = scoring.compute_scores(participants, expectations, states)

# Before any result is in, every score/standing is 0 so "natural" ranking order
# is meaningless — present ranking tables alphabetically until the tournament
# actually starts, then switch to performance order.
tournament_started = source == "results"

# Fill in knockout fixtures (Winner A, 3rd (…), W(M74)…) with the real teams as
# results decide them; {match No: "Home vs Away"} with placeholders kept where
# still undecided. Used by the schedule and knockout draw tabs.
resolved_bracket = scoring.resolve_bracket(SGT_SCHEDULE, states, GROUP_TEAMS, merged_results)

def resolved_match(row):
    """The fixture for a schedule row, with knockout placeholders resolved."""
    return resolved_bracket.get(str(row.get("No", "")).strip(), row["Match"])

# --- 4. UI TABS ---
st.title("🏆 RMD World Cup 2026 Sweepstake")

SGT = datetime.timezone(datetime.timedelta(hours=8))
REFRESH_HOURS_SGT = (7, 11, 14)   # mirrors the cron in .github/workflows/daily-results.yml

def _stamp_sgt(dt):
    if dt is None:
        return "unknown"
    if dt.tzinfo is None:                      # mtime fallback is naive UTC on the server
        dt = dt.replace(tzinfo=datetime.timezone.utc)
    return dt.astimezone(SGT).strftime("%d %b %Y, %H:%M SGT")

def _next_refresh_sgt():
    """The next scheduled refresh in SGT, given the thrice-daily cron."""
    now = datetime.datetime.now(SGT)
    candidates = [now.replace(hour=h, minute=0, second=0, microsecond=0) for h in REFRESH_HOURS_SGT]
    upcoming = [c for c in candidates if c > now]
    nxt = upcoming[0] if upcoming else candidates[0] + datetime.timedelta(days=1)
    label = "today" if nxt.date() == now.date() else "tomorrow"
    return f"{nxt.strftime('%H:%M')} SGT {label}"

stamp = _stamp_sgt(_last_refresh_at())
if source == "results":
    st.caption(f"🔄 Last refresh: {stamp} · next refresh ~{_next_refresh_sgt()}")
else:
    st.caption(f"🔄 Last refresh: {stamp} · no matches played yet — standings appear once results come in")

tabs = st.tabs(["🥇 Leaderboard", "📅 SGT Schedule", "📈 Group Rankings", "🌳 Knockout Draw", "📊 Market Tiers"])

with tabs[0]:
    st.header("Tournament Leaderboard")
    st.info("💡 Expand a player to see how each pick contributes to their score.")

    def _pick_label(pick):
        return f"{pick['team']} ({'L' if pick['position'] == 'Long' else 'S'})"

    # Performance order (by score) once the tournament's underway; alphabetical
    # by player name beforehand, when every score is still 0.
    players_ranked = scores["players"] if tournament_started else sorted(
        scores["players"], key=lambda p: p["name"].lower())

    board_rows = []
    for i, p in enumerate(players_ranked):
        row = {"Rank": i + 1, "Player": p["name"], "Score": p["total"]}
        # List each player's picks alphabetically by team name.
        picks = sorted(p["picks"], key=lambda pk: pk["team"].lower())
        for j in range(3):  # always 3 columns, even if a player has fewer picks
            pick = picks[j] if j < len(picks) else None
            row[f"Team {j + 1}"] = _pick_label(pick) if pick else "—"
            row[f"Pts {j + 1}"] = pick["total"] if pick else 0
        board_rows.append(row)
    board = pd.DataFrame(board_rows)
    render_table(board)

    st.divider()
    st.subheader("📈 Score over time")
    timeline = scoring.compute_score_timeline(
        merged_results, participants, expectations, all_teams, GROUP_TEAMS, SGT_SCHEDULE,
    )
    if not timeline:
        st.caption("No matches played yet — each player's running total will chart here as results come in.")
    else:
        # Long form: one row per (player, date).
        trend_long = (
            pd.DataFrame(timeline)
            .melt(id_vars="date", var_name="Player", value_name="Score")
            .rename(columns={"date": "Date"})
        )
        st.caption("Cumulative total score after each match day. Hover a line for that player's score; scroll or drag to zoom and pan (double-click to reset). Click a name in the legend to focus on a player (shift-click to add more, click blank space to reset).")

        focus = alt.selection_point(fields=["Player"], bind="legend")
        zoom = alt.selection_interval(bind="scales")   # scroll to zoom, drag to pan
        # Nearest single point under the cursor (by both axes), so the tooltip
        # describes one player at one date rather than all of them at once.
        hover = alt.selection_point(
            on="pointerover", nearest=True, empty=False, encodings=["x", "y"]
        )

        base = alt.Chart(trend_long).encode(
            x=alt.X("Date:T", title="Date"),
            y=alt.Y("Score:Q", title="Cumulative score"),
            color=alt.Color(
                "Player:N",
                legend=alt.Legend(
                    orient="bottom",
                    direction="horizontal",
                    # No fixed `columns`: a horizontal bottom legend wraps its
                    # entries to the available browser width on its own.
                    symbolLimit=0,    # show every player, no truncation
                    labelLimit=200,
                    title=None,
                ),
            ),
            opacity=alt.condition(focus, alt.value(1.0), alt.value(0.12)),
        )
        lines = base.mark_line()
        # Per-point markers: invisible until they're the nearest point, then they
        # pop in and carry the single-player tooltip.
        points = base.mark_point(size=70, filled=True).encode(
            opacity=alt.condition(hover, alt.value(1.0), alt.value(0.0)),
            tooltip=[
                alt.Tooltip("Player:N"),
                alt.Tooltip("Date:T", title="Date"),
                alt.Tooltip("Score:Q"),
            ],
        ).add_params(hover)

        # `height` is the plotting-area height only; the wrapped legend is laid
        # out below it (autosize "pad"), so the chart keeps this minimum no
        # matter how many rows the legend needs.
        chart = (
            (lines + points)
            .add_params(focus, zoom)
            .properties(
                height=400,
                # "pad" (the default) grows the chart to fit the legend below
                # the plot instead of shrinking the plot to share the space.
                autosize=alt.AutoSizeParams(type="pad", contains="padding"),
            )
        )
        st.altair_chart(chart, use_container_width=True)

    st.divider()
    st.subheader("🔍 Portfolio breakdowns")
    for p in players_ranked:
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

with tabs[4]:
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
            grp_df = pd.DataFrame(rows)
            grp_df = (grp_df.sort_values(["Pts", "GD", "W"], ascending=False)
                      if tournament_started else grp_df.sort_values("Team"))
            with col:
                st.subheader(f"Group {grp}")
                render_table(grp_df)

with tabs[1]:
    st.header("Singapore Time Schedule")

    sched_df = pd.DataFrame(SGT_SCHEDULE)
    sched_df["_kickoff"] = pd.to_datetime(
        sched_df["Date"] + " " + sched_df["SGT Time"], format="%d %b %Y %I:%M %p"
    )
    sgt = datetime.timezone(datetime.timedelta(hours=8))
    now_sgt = datetime.datetime.now(sgt).replace(tzinfo=None)

    view = st.radio("Show", ["Upcoming", "Past", "All"], horizontal=True, index=0)
    if view == "Upcoming":
        filtered = sched_df[sched_df["_kickoff"] >= now_sgt]
    elif view == "Past":
        filtered = sched_df[sched_df["_kickoff"] < now_sgt]
    else:
        filtered = sched_df

    def _flag_safe(match, idx):
        # Flag any side that's resolved to a real team (group or knockout);
        # placeholders like "Winner E" / "W(M74)" stay blank.
        parts = match.split(" vs ")
        team = parts[idx].strip() if len(parts) > idx else ""
        return get_flag(team) if team in FLAG_CODES else ""

    filtered = filtered.copy()
    filtered["Match"] = filtered.apply(resolved_match, axis=1)
    # Single vs double space → distinct column keys that both render as blank headers.
    filtered[" "] = filtered["Match"].apply(lambda m: _flag_safe(m, 0))
    filtered["  "] = filtered["Match"].apply(lambda m: _flag_safe(m, 1))

    render_table(
        filtered[["Date", "SGT Time", " ", "Match", "  ", "Stage"]],
        image_cols=(" ", "  "),
    )

with tabs[3]:
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

    def _label(m):
        """Resolved fixture for a knockout row, with placeholders prettified."""
        return _prettify(resolved_match(m))

    kcols = st.columns(5)

    with kcols[0]:
        st.caption("Round of 32")
        for m in _by_no("Round of 32"):
            st.info(f"**{m['No']}:** {_label(m)}")

    with kcols[1]:
        st.caption("Round of 16")
        for m in _by_no("Round of 16"):
            st.info(f"**{m['No']}:** {_label(m)}")

    with kcols[2]:
        st.caption("Quarter-Finals")
        for m in _by_no("Quarter-Final"):
            st.warning(f"**{m['No']}:** {_label(m)}")

    with kcols[3]:
        st.caption("Semi-Finals")
        for m in _by_no("Semi-Final"):
            st.error(f"**{m['No']}:** {_label(m)}")

    with kcols[4]:
        st.caption("Final & 3rd Place")
        for m in _by_no("Final"):
            st.success(f"🏆 **{m['No']}:** {_label(m)}")
        for m in _by_no("3rd Place"):
            st.info(f"🥉 **{m['No']}:** {_label(m)}")
