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
import os
import re

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

# TheSportsDB API key. Defaults to the free/test key "3" (no signup, but it
# serves a stale, capped snapshot for in-progress seasons). Set TSDB_KEY to a
# premium/Patreon key for full, current season data — that's what the daily
# job uses via a repo secret.
_TSDB_KEY = os.environ.get("TSDB_KEY", "").strip() or "3"
_TSDB_BASE = f"https://www.thesportsdb.com/api/v1/json/{_TSDB_KEY}"
_SEASON = "2026"
_HTTP_TIMEOUT = 20

# football-data.org — preferred source when a key is configured. Its free tier
# covers the FIFA World Cup and (unlike TheSportsDB's free key) stays current
# for an in-progress tournament. Auth is an X-Auth-Token header.
_FD_KEY = os.environ.get("FOOTBALL_DATA_API_KEY", "").strip()
_FD_BASE = "https://api.football-data.org/v4"
_FD_COMPETITION = "WC"  # FIFA World Cup competition code

# football-data's knockout `stage` -> the matchday "round" number our
# schedule-matcher expects (fetch_results.ROUND_TO_STAGE maps 4..8 back to
# R32..Final). Group games carry their real matchday (1-3) instead.
_FD_STAGE_ROUND = {
    "LAST_32": 4,
    "LAST_16": 5,
    "QUARTER_FINALS": 6,
    "SEMI_FINALS": 7,
    "FINAL": 8,
}

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
    # football-data.org lists this national team under its long-form name.
    "cape verde islands": "Cape Verde",
    "cabo verde islands": "Cape Verde",
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


def _fetch_events_football_data() -> list[dict]:
    """Fetch World Cup fixtures from football-data.org (when a key is set).

    Returns the same normalised dicts as fetch_events(). football-data gives a
    real `stage`/`matchday`, which we translate into the matchday "round"
    number the schedule-matcher already understands, so the caller is unchanged.
    """
    resp = requests.get(
        f"{_FD_BASE}/competitions/{_FD_COMPETITION}/matches",
        headers={"X-Auth-Token": _FD_KEY},
        timeout=_HTTP_TIMEOUT,
    )
    resp.raise_for_status()
    matches = resp.json().get("matches") or []

    events: list[dict] = []
    for m in matches:
        stage = str(m.get("stage", ""))
        if stage == "THIRD_PLACE":          # mirrors the TSDB path: not scored
            continue
        if stage == "GROUP_STAGE":
            md = m.get("matchday")
            rnd = int(md) if str(md).strip().isdigit() else None
        else:
            rnd = _FD_STAGE_ROUND.get(stage)

        ft = (m.get("score") or {}).get("fullTime") or {}
        hs, as_ = ft.get("home"), ft.get("away")
        finished = str(m.get("status", "")).upper() == "FINISHED"
        events.append(
            {
                "home": canonical_team((m.get("homeTeam") or {}).get("name", "")),
                "away": canonical_team((m.get("awayTeam") or {}).get("name", "")),
                "home_score": hs if isinstance(hs, int) else None,
                "away_score": as_ if isinstance(as_, int) else None,
                "round": rnd,
                "date": str(m.get("utcDate", ""))[:10],  # ISO date, e.g. 2026-07-06
                "finished": bool(finished),
            }
        )
    return events


def fetch_events() -> list[dict]:
    """Fetch raw World Cup 2026 fixtures from the configured source.

    Uses football-data.org when FOOTBALL_DATA_API_KEY is set, else falls back
    to TheSportsDB's free key. Either way returns normalised dicts with the
    score and matchday round; the *stage* is deliberately NOT inferred here, so
    the caller maps each event onto our own schedule (which knows the stage):
        {home, away, home_score, away_score, round, date, finished}
    Raises on any network/parse failure so the caller can fall back to cache.
    """
    if _FD_KEY:
        return _fetch_events_football_data()

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
                "date": str(ev.get("dateEvent", "")).strip(),  # ISO, e.g. 2026-07-06
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


# --- Bracket resolution -----------------------------------------------------
# Turn the schedule's placeholder knockout fixtures ("Winner E", "Runner-up B",
# "3rd (A/B/C/D/F)", "W(M74)") into real teams once results decide them. Each
# side resolves independently and only when *provably* determined, so a fixture
# can show one real team next to a still-pending placeholder, and nothing shown
# is ever a guess.

_RE_WINNER = re.compile(r"^Winner ([A-L])$")
_RE_RUNNER = re.compile(r"^Runner-up ([A-L])$")
_RE_THIRD = re.compile(r"^3rd \(([A-L/]+)\)$")
_RE_WMATCH = re.compile(r"^W\(M(\d+)\)$")

# Schedule "Stage" text for each knockout round, in the order they're played so
# a round's winners are known before the next round is resolved.
_KO_STAGES = ["Round of 32", "Round of 16", "Quarter-Final", "Semi-Final", "Final"]

# FIFA's predetermined allocation of the eight qualifying third-placed teams to
# R32 fixtures. This is a fixed lookup keyed by *which* eight groups' thirds
# qualify — it is NOT derivable from the schedule's "3rd (A/B/C/D/F)" candidate
# lists alone, because several distinct one-to-one matchings satisfy those
# lists; FIFA breaks that tie with this table. Each entry maps a group letter to
# the match "No" that group's third is assigned to. Rows are added as real
# combinations occur; _assign_third_slots validates every mapping against the
# schedule's own candidate lists before trusting it, and falls back to the
# combinatorial "invariant across all matchings" resolution otherwise.
#   • BDEFIJKL — verified against the official 2026 Round of 32 bracket
#     (France v 3F, Mexico v 3E, England v 3K, USA v 3B, Belgium v 3I,
#     Switzerland v 3J; Germany v 3D and Colombia v 3L by elimination).
_FIFA_THIRD_ALLOCATION = {
    frozenset("BDEFIJKL"): {
        "D": "M74", "F": "M77", "E": "M79", "K": "M80",
        "B": "M81", "I": "M82", "J": "M85", "L": "M87",
    },
}


def _group_complete_order(states, teams):
    """Teams of a group ranked best-first, or None until all have played 3."""
    def played(t):
        s = states.get(t)
        return (s["wins"] + s["draws"] + s["losses"]) if s else 0
    if not all(played(t) == 3 for t in teams):
        return None
    return sorted(teams, key=lambda t: _group_rank_key(states[t]), reverse=True)


def _best_thirds(states, group_teams):
    """{group_letter: third_placed_team} for the 8 best thirds, or None until
    every group is complete (their relative ranking isn't final before then)."""
    thirds = {}
    for g, teams in group_teams.items():
        order = _group_complete_order(states, teams)
        if order is None or len(order) < 3:
            return None
        thirds[g] = order[2]
    ranked = sorted(thirds, key=lambda g: _group_rank_key(states[thirds[g]]), reverse=True)
    return {g: thirds[g] for g in ranked[:8]}


def _assign_third_slots(schedule, states, group_teams):
    """Map each R32 'No' hosting a best-third slot to the team that fills it.

    Each slot allows thirds from a fixed set of groups (the "3rd (A/B/C/D/F)"
    text); the 8 qualifying thirds must fill the 8 slots one-to-one. FIFA's
    predetermined allocation (_FIFA_THIRD_ALLOCATION) settles this exactly when
    the realized combination is tabulated. Failing that we fall back to a
    provable subset: assign a slot only when it holds the *same* group in every
    valid perfect matching of groups to slots (FIFA's allocation is one such
    matching, so an invariant slot must equal it). Slots that vary between
    equally-valid matchings stay unresolved (placeholder kept).
    """
    thirds = _best_thirds(states, group_teams)
    if not thirds:
        return {}
    qualifying = set(thirds)

    slots = {}  # match No -> set of qualifying groups it may host
    for m in schedule:
        no = str(m.get("No", "")).strip()
        for tok in str(m.get("Match", "")).split(" vs "):
            mm = _RE_THIRD.match(tok.strip())
            if mm and no:
                slots[no] = set(mm.group(1).split("/")) & qualifying

    # Authoritative FIFA table first — but only trust it if every mapping lands
    # in a slot the schedule actually allows for that group, so the table can't
    # silently drift from the bracket. Otherwise fall through to combinatorics.
    alloc = _FIFA_THIRD_ALLOCATION.get(frozenset(qualifying))
    if alloc and all(g in slots.get(no, set()) for g, no in alloc.items()):
        return {no: thirds[g] for g, no in alloc.items()}

    slot_nos = list(slots)
    matchings = []  # every one-to-one group→slot assignment respecting `allowed`

    def backtrack(i, used, current):
        if i == len(slot_nos):
            matchings.append(dict(current))
            return
        no = slot_nos[i]
        for g in slots[no]:
            if g not in used:
                used.add(g)
                current[no] = g
                backtrack(i + 1, used, current)
                used.discard(g)
                del current[no]

    backtrack(0, set(), {})
    if not matchings:
        return {}

    assigned = {}  # No -> group, kept only when invariant across all matchings
    for no in slot_nos:
        options = {mm[no] for mm in matchings}
        if len(options) == 1:
            assigned[no] = next(iter(options))
    return {no: thirds[g] for no, g in assigned.items()}


def resolve_bracket(schedule, states, group_teams, results) -> dict:
    """Resolve placeholder knockout fixtures to real teams where decided.

    Returns {match No: "Home vs Away"} for every knockout row, with each side
    replaced by its real team when known and left as the original placeholder
    text otherwise. Only completed results drive resolution — nothing assumed.
    """
    placement = {}  # ("Winner"|"Runner-up", group) -> team
    for g, teams in group_teams.items():
        order = _group_complete_order(states, teams)
        if order and len(order) >= 2:
            placement[("Winner", g)] = order[0]
            placement[("Runner-up", g)] = order[1]

    third_by_no = _assign_third_slots(schedule, states, group_teams)

    winner_of = {}  # frozenset({teamA, teamB}) -> winner (decided games only)
    for r in results:
        h, a = canonical_team(r.get("home", "")), canonical_team(r.get("away", ""))
        hs, as_ = r.get("home_score"), r.get("away_score")
        if h and a and hs is not None and as_ is not None and hs != as_:
            winner_of[frozenset((h, a))] = h if hs > as_ else a

    win_by_no = {}  # "M74" -> winning team, filled round by round
    resolved = {}

    def resolve_side(tok, third_team):
        m = _RE_WINNER.match(tok)
        if m:
            return placement.get(("Winner", m.group(1)))
        m = _RE_RUNNER.match(tok)
        if m:
            return placement.get(("Runner-up", m.group(1)))
        if _RE_THIRD.match(tok):
            return third_team
        m = _RE_WMATCH.match(tok)
        if m:
            return win_by_no.get("M" + m.group(1))
        return tok  # already a literal team name

    rows_by_stage = {}
    for m in schedule:
        rows_by_stage.setdefault(str(m.get("Stage", "")), []).append(m)

    for stage in _KO_STAGES:
        for m in rows_by_stage.get(stage, []):
            no = str(m.get("No", "")).strip()
            parts = str(m.get("Match", "")).split(" vs ")
            if len(parts) != 2:
                continue
            sides = [resolve_side(p.strip(), third_by_no.get(no)) for p in parts]
            if no:
                resolved[no] = " vs ".join(sides[i] or parts[i].strip() for i in (0, 1))
            if no and sides[0] and sides[1]:
                w = winner_of.get(frozenset((sides[0], sides[1])))
                if w:
                    win_by_no[no] = w

    return resolved


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


def _parse_date(value):
    """Parse a results-CSV Date cell. Accepts ISO (2026-07-06, what the fetcher
    writes) or the schedule's '06 Jul 2026' style. Blank/unknown -> None."""
    s = str(value or "").strip()
    if not s:
        return None
    for fmt in ("%Y-%m-%d", "%d %b %Y", "%d %B %Y"):
        try:
            return _dt.datetime.strptime(s, fmt).date()
        except ValueError:
            continue
    return None


# Schedule "Stage" text -> our ROUND_ORDER key, for dating knockout results.
_SCHED_STAGE_KEY = {
    "Round of 32": "R32", "Round of 16": "R16",
    "Quarter-Final": "QF", "Semi-Final": "SF", "Final": "Final",
}


def _schedule_date_maps(schedule: list[dict]):
    """Build date lookups from schedule rows ({Date, Match, Stage}).

    Returns (group_dates, stage_last):
      group_dates: {(home, away): date} for every group fixture (both orders).
      stage_last:  {round_key: latest scheduled date for that knockout round}.
    Knockout fixtures list placeholder teams ("Winner A"), so individual games
    can't be dated by team — we fall back to the round's final scheduled date.
    """
    group_dates: dict = {}
    stage_last: dict = {}
    for m in schedule:
        try:
            d = _dt.datetime.strptime(m["Date"], "%d %b %Y").date()
        except (ValueError, KeyError, TypeError):
            continue
        stage = m.get("Stage", "")
        if stage.startswith("Group "):
            parts = m.get("Match", "").split(" vs ")
            if len(parts) == 2:
                h, a = parts[0].strip(), parts[1].strip()
                group_dates[(h, a)] = d
                group_dates[(a, h)] = d
        else:
            key = _SCHED_STAGE_KEY.get(stage)
            if key and (stage_last.get(key) is None or d > stage_last[key]):
                stage_last[key] = d
    return group_dates, stage_last


def compute_score_timeline(results: list[dict], participants_df, expectations: dict,
                           all_teams: list[str], group_teams: dict,
                           schedule: list[dict]) -> list[dict]:
    """Cumulative total score per participant after each match day.

    Returns chronological points [{"date": date, <player>: total, ...}], with a
    leading zero baseline so every line starts at 0. For each date the score is
    recomputed from all results up to and including that day, so the final point
    matches the live leaderboard. Results that can't be dated are skipped.

    A result's own Date wins when present (exact day, incl. knockouts); failing
    that we fall back to the schedule (group fixtures by team pair, knockout
    rounds by the round's final scheduled date).
    """
    group_dates, stage_last = _schedule_date_maps(schedule)

    dated = []
    for r in results:
        d = _parse_date(r.get("date"))
        if d is None:
            d = group_dates.get((r.get("home"), r.get("away")))
        if d is None:
            d = stage_last.get(r.get("stage"))
        if d is not None:
            dated.append((d, r))
    if not dated:
        return []

    dates = sorted({d for d, _ in dated})
    timeline = []
    for day in dates:
        upto = [r for rd, r in dated if rd <= day]
        states = compute_team_states(build_events(upto), list(all_teams), group_teams)
        scored = compute_scores(participants_df, expectations, states)
        point = {"date": day}
        point.update({p["name"]: p["total"] for p in scored["players"]})
        timeline.append(point)

    baseline = {"date": dates[0] - _dt.timedelta(days=1)}
    baseline.update({k: 0 for k in timeline[0] if k != "date"})
    return [baseline] + timeline


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
