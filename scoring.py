"""
World Cup Sweepstake — results fetching and scoring engine.

The app fetches live World Cup 2026 results from a public, key-free web
source (TheSportsDB) once a day, derives each team's group-stage record and
the furthest knockout round it reached, and turns that into player scores.

Scoring rules (per pick):
  LONG:
    progression = ROUND_POINTS[round_reached] - team_expectation
    league      = 3*wins + 1*draws + 0*losses        (group stage only)
  SHORT (mirror image — profits when the team underperforms):
    progression = team_expectation - ROUND_POINTS[round_reached]
    league      = 3*losses + 1*draws + 0*wins        (group stage only)
  contribution = progression + league
A player's total is the sum of their three picks.
"""

from __future__ import annotations

import datetime as _dt

import requests

# --- Tournament constants ---------------------------------------------------

# Points awarded for reaching each round. 2026 uses a 48-team format, so the
# first knockout round is the Round of 32. "Winner" is the team that wins the
# final; "Final" is awarded to the beaten finalist.
ROUND_POINTS = {
    "Group": 0,
    "R32": 8,
    "R16": 18,
    "QF": 32,
    "SF": 48,
    "Final": 65,
    "Winner": 85,
}

# Order used to decide which round is "furthest reached".
ROUND_ORDER = ["Group", "R32", "R16", "QF", "SF", "Final", "Winner"]

LEAGUE_POINTS = {"win": 3, "draw": 1, "loss": 0}

# TheSportsDB free/test key. No signup required.
_TSDB_KEY = "3"
_TSDB_BASE = f"https://www.thesportsdb.com/api/v1/json/{_TSDB_KEY}"
_SEASON = "2026"
_HTTP_TIMEOUT = 20

# Map the many ways data sources spell a country onto our canonical names
# (the names used in team_expectations.csv and participants.csv).
_NAME_ALIASES = {
    "united states": "USA",
    "usa": "USA",
    "united states of america": "USA",
    "korea republic": "South Korea",
    "south korea": "South Korea",
    "republic of korea": "South Korea",
    "turkey": "Türkiye",
    "türkiye": "Türkiye",
    "turkiye": "Türkiye",
    "czech republic": "Czechia",
    "czechia": "Czechia",
    "bosnia and herzegovina": "Bosnia",
    "bosnia": "Bosnia",
    "bosnia & herzegovina": "Bosnia",
    "bosnia-herzegovina": "Bosnia",
    "ivory coast": "Ivory Coast",
    "côte d'ivoire": "Ivory Coast",
    "cote d'ivoire": "Ivory Coast",
    "dr congo": "DR Congo",
    "democratic republic of congo": "DR Congo",
    "congo dr": "DR Congo",
    "cape verde": "Cape Verde",
    "cabo verde": "Cape Verde",
}


def canonical_team(name: str) -> str:
    """Normalise an externally-sourced team name to our canonical spelling."""
    if not name:
        return ""
    key = name.strip().lower()
    return _NAME_ALIASES.get(key, name.strip())


# --- Stage detection --------------------------------------------------------

def _classify_stage(stage_text: str, group_text: str, round_num: str):
    """Return one of ROUND_ORDER for an event, or None if unknown.

    Group games return "Group". Knockout games return their round key.
    """
    stage = (stage_text or "").strip().lower()
    group = (group_text or "").strip()

    # A populated group label, or "group" in the stage, means group stage.
    if group or "group" in stage:
        return "Group"

    if "round of 32" in stage or stage in {"r32", "1/16"}:
        return "R32"
    if "round of 16" in stage or stage in {"r16", "1/8"}:
        return "R16"
    if "quarter" in stage or stage in {"qf", "1/4"}:
        return "QF"
    if "semi" in stage or stage in {"sf", "1/2"}:
        return "SF"
    if "final" in stage:  # plain "final" (3rd-place is filtered out below)
        return "Final"

    return None


def _is_third_place(stage_text: str) -> bool:
    s = (stage_text or "").lower()
    return "third" in s or "3rd" in s


# --- Fetching ---------------------------------------------------------------

def _find_world_cup_league_id(session: requests.Session) -> str:
    """Look up the FIFA World Cup league id by name so we never depend on a
    hard-coded id that could drift."""
    resp = session.get(f"{_TSDB_BASE}/all_leagues.php", timeout=_HTTP_TIMEOUT)
    resp.raise_for_status()
    leagues = resp.json().get("leagues") or []
    for lg in leagues:
        name = (lg.get("strLeague") or "").lower()
        sport = (lg.get("strSport") or "").lower()
        if sport != "soccer":
            continue
        bad = ("women", "u-", "u2", "u1", "qualif", "club", "beach", "futsal")
        if any(b in name for b in bad):
            continue
        if "world cup" in name and "fifa" in name:
            return lg["idLeague"]
    # Fallback to the well-known id if the name search comes up empty.
    return "4429"


def fetch_events() -> list[dict]:
    """Fetch raw World Cup 2026 fixtures from TheSportsDB.

    Returns normalised dicts with the score and matchday round; the *stage* is
    deliberately NOT inferred here — TheSportsDB leaves strStage/strGroup empty
    for this tournament, so the caller maps each event onto our own schedule
    (which already knows the stage) instead:
        {home, away, home_score, away_score, round, finished}
    Raises on any network/parse failure so the caller can fall back to cache.
    """
    session = requests.Session()
    league_id = _find_world_cup_league_id(session)
    resp = session.get(
        f"{_TSDB_BASE}/eventsseason.php",
        params={"id": league_id, "s": _SEASON},
        timeout=_HTTP_TIMEOUT,
    )
    resp.raise_for_status()
    raw_events = resp.json().get("events") or []

    events: list[dict] = []
    for ev in raw_events:
        if _is_third_place(ev.get("strStage", "")):
            continue
        hs, as_ = ev.get("intHomeScore"), ev.get("intAwayScore")
        rnd = ev.get("intRound")
        finished = (
            str(ev.get("strStatus", "")).lower() in {"match finished", "ft", "finished", "aet", "pen"}
            or (hs not in (None, "") and as_ not in (None, ""))
        )
        events.append(
            {
                "home": canonical_team(ev.get("strHomeTeam", "")),
                "away": canonical_team(ev.get("strAwayTeam", "")),
                "home_score": int(hs) if str(hs).strip().isdigit() else None,
                "away_score": int(as_) if str(as_).strip().isdigit() else None,
                "round": int(rnd) if str(rnd).strip().isdigit() else None,
                "finished": bool(finished),
            }
        )
    return events


def build_events(results: list[dict]) -> list[dict]:
    """Turn match-result rows into events for compute_team_states().

    Each row needs: home, away, home_score, away_score, stage (a ROUND_ORDER
    key). Rows with an unknown stage or missing scores are skipped.
    """
    events = []
    for r in results:
        stage = r.get("stage")
        if stage not in ROUND_ORDER:
            continue
        hs, as_ = r.get("home_score"), r.get("away_score")
        if hs is None or as_ is None:
            continue
        events.append({
            "home": canonical_team(r.get("home", "")),
            "away": canonical_team(r.get("away", "")),
            "home_score": int(hs),
            "away_score": int(as_),
            "stage": stage,
            "finished": True,
        })
    return events


# --- Deriving team states ---------------------------------------------------

def compute_team_states(events: list[dict], all_teams: list[str], group_teams: dict | None = None) -> dict:
    """From completed match results, derive per-team state.

    Returns {team: {"wins", "draws", "losses", "gf", "ga", "round_reached",
    "done"}}. "done" is True once a team's run is decided (eliminated or
    champion), which is what lets scoring lock in a progression result instead
    of assuming an outcome. `group_teams` ({letter: {teams}}) enables group
    qualification — without it, group placings can't be resolved.
    """
    def _blank():
        return {"wins": 0, "draws": 0, "losses": 0, "gf": 0, "ga": 0,
                "round_reached": "Group", "done": False}

    states = {t: _blank() for t in all_teams}

    def _ensure(team):
        if team and team not in states:
            states[team] = _blank()

    def _promote(team, stage):
        if team and ROUND_ORDER.index(stage) > ROUND_ORDER.index(states[team]["round_reached"]):
            states[team]["round_reached"] = stage

    # Winning a knockout match means you've reached the next round.
    next_round = {"R32": "R16", "R16": "QF", "QF": "SF", "SF": "Final", "Final": "Winner"}

    for ev in events:
        home, away, stage = ev["home"], ev["away"], ev["stage"]
        if stage not in ROUND_ORDER:
            continue
        _ensure(home)
        _ensure(away)

        # Furthest round reached: appearing in a fixture of that round counts.
        _promote(home, stage)
        _promote(away, stage)

        if not ev["finished"] or ev["home_score"] is None or ev["away_score"] is None:
            continue

        hs, as_ = ev["home_score"], ev["away_score"]

        if stage == "Group":
            states[home]["gf"] += hs
            states[home]["ga"] += as_
            states[away]["gf"] += as_
            states[away]["ga"] += hs
            if hs > as_:
                states[home]["wins"] += 1
                states[away]["losses"] += 1
            elif hs < as_:
                states[away]["wins"] += 1
                states[home]["losses"] += 1
            else:
                states[home]["draws"] += 1
                states[away]["draws"] += 1
        elif stage in next_round:
            # The winner advances; the loser is out. The Final winner is champion.
            winner = home if hs > as_ else away if as_ > hs else None
            loser = (away if winner == home else home) if winner else None
            _promote(winner, next_round[stage])
            if loser:
                states[loser]["done"] = True          # knocked out
            if stage == "Final" and winner:
                states[winner]["done"] = True          # champion

    if group_teams:
        _resolve_group_qualification(states, group_teams, _promote)

    return states


def _group_rank_key(s):
    """Group ranking: points, then goal difference, then goals for."""
    return (3 * s["wins"] + s["draws"], s["gf"] - s["ga"], s["gf"])


def _resolve_group_qualification(states, group_teams, promote):
    """Once groups finish, mark non-qualifiers done and advance qualifiers.

    Top two of each completed group go through; the eight best third-placed
    teams (decided only once every group is complete) join them. Anyone else
    whose group is complete is out. Tie-breaks use points/GD/GF (the head-to-
    head and fair-play tie-breaks beyond that are rare and not modelled).
    """
    def played(t):
        s = states[t]
        return s["wins"] + s["draws"] + s["losses"]

    complete = {g: all(played(t) == 3 for t in teams) for g, teams in group_teams.items()}
    all_complete = all(complete.values())
    thirds = []

    for g, teams in group_teams.items():
        if not complete[g]:
            continue
        ordered = sorted(teams, key=lambda t: _group_rank_key(states[t]), reverse=True)
        for t in ordered[:2]:               # top two qualify
            promote(t, "R32")
        for t in ordered[3:]:               # 4th (and beyond) are out
            states[t]["done"] = True
        if len(ordered) >= 3:
            thirds.append(ordered[2])       # third place — fate pending

    if all_complete and thirds:
        ranked_thirds = sorted(thirds, key=lambda t: _group_rank_key(states[t]), reverse=True)
        for t in ranked_thirds[:8]:         # eight best thirds qualify
            promote(t, "R32")
        for t in ranked_thirds[8:]:
            states[t]["done"] = True


# --- Scoring ----------------------------------------------------------------

def score_pick(team: str, position: str, expectations: dict, state: dict) -> dict:
    """Score a single pick. Returns the component breakdown and total."""
    exp = expectations.get(team, 0)
    round_reached = state["round_reached"]
    is_short = str(position).strip().lower() == "short"
    done = state.get("done", False)

    # Progression only reflects what's actually decided, never an assumed
    # group-stage exit. `achieved` is the furthest round confirmed by completed
    # results. While a team is still alive we credit confirmed *over*-
    # performance but don't yet apply the shortfall (the outcome is unknown);
    # once the team is eliminated or wins, the full gap locks in.
    achieved = ROUND_POINTS.get(round_reached, 0)
    if is_short:
        progression = (exp - achieved) if done else min(exp - achieved, 0)
    else:
        progression = (achieved - exp) if done else max(achieved - exp, 0)

    # Group points: Long rewards wins (3/1/0); Short mirrors it, rewarding
    # losses instead (loss 3, draw 1, win 0) so shorting a team that loses is
    # rewarded rather than merely neutral.
    if is_short:
        league = (
            LEAGUE_POINTS["win"] * state["losses"]   # 3 per loss
            + LEAGUE_POINTS["draw"] * state["draws"]  # 1 per draw
            + LEAGUE_POINTS["loss"] * state["wins"]   # 0 per win
        )
    else:
        league = (
            LEAGUE_POINTS["win"] * state["wins"]
            + LEAGUE_POINTS["draw"] * state["draws"]
            + LEAGUE_POINTS["loss"] * state["losses"]
        )

    return {
        "team": team,
        "position": "Short" if is_short else "Long",
        "round_reached": round_reached,
        "expectation": exp,
        "record": f"{state['wins']}W-{state['draws']}D-{state['losses']}L",
        "progression": progression,
        "league": league,
        "total": progression + league,
    }


def compute_scores(participants_df, expectations: dict, states: dict) -> dict:
    """Score every participant.

    Returns {"players": [{name, total, picks:[breakdown,...]}], ...} sorted by
    total descending.
    """
    players = []
    default_state = {"wins": 0, "draws": 0, "losses": 0, "gf": 0, "ga": 0,
                     "round_reached": "Group", "done": False}

    for _, row in participants_df.iterrows():
        picks = []
        for i in (1, 2, 3):
            team = canonical_team(str(row.get(f"Team_{i}", "")))
            pos = str(row.get(f"Pos_{i}", "Long"))
            if not team:
                continue
            state = states.get(team, default_state)
            picks.append(score_pick(team, pos, expectations, state))
        players.append(
            {
                "name": row.get("Participant", "Unknown"),
                "total": sum(p["total"] for p in picks),
                "picks": picks,
            }
        )

    players.sort(key=lambda p: p["total"], reverse=True)
    return {"players": players, "computed_at": _dt.datetime.now(_dt.timezone.utc).isoformat()}
