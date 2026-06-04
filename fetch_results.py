"""Daily results fetcher — run on a schedule (GitHub Action), not by the app.

Fetches World Cup 2026 scorelines from TheSportsDB and writes them to
results_cache.csv as match-level rows (Home, Away, HomeScore, AwayScore,
Stage, Date — the match's ISO date). The app merges this with the
hand-editable results.csv (manual entries win) and derives standings from
there.

Because TheSportsDB leaves the stage/group fields empty for this tournament,
each played match is matched against our own schedule.csv (which knows the
teams, groups and stages) by team name. Knockout fixtures — whose teams aren't
in our schedule until the draw is known — fall back to a best-effort matchday
→ round mapping; the manual results.csv is the reliable path for those.

Exit code is non-zero only on a genuine network/HTTP failure; "no completed
matches yet" is a clean no-op so the daily job doesn't go red before kick-off.
"""

import sys

import pandas as pd

import scoring

CACHE_FILE = "results_cache.csv"
SCHEDULE_FILE = "schedule.csv"
EXPECTATIONS_FILE = "team_expectations.csv"
COLUMNS = ["Home", "Away", "HomeScore", "AwayScore", "Stage", "Date"]

# Best-effort matchday → knockout stage (48-team format: 3 group rounds first).
ROUND_TO_STAGE = {4: "R32", 5: "R16", 6: "QF", 7: "SF", 8: "Final"}


def _group_lookup():
    """{frozenset(home, away): (home, away)} for every group fixture."""
    sched = pd.read_csv(SCHEDULE_FILE, dtype=str).fillna("")
    lookup = {}
    for _, m in sched.iterrows():
        if not m["Stage"].startswith("Group "):
            continue
        parts = m["Match"].split(" vs ")
        if len(parts) != 2:
            continue
        home, away = parts[0].strip(), parts[1].strip()
        lookup[frozenset((home, away))] = (home, away)
    return lookup


def _match_row(ev, groups):
    """Map a fetched event onto a result row, or None if it can't be placed."""
    home, away = ev["home"], ev["away"]
    hs, as_ = ev["home_score"], ev["away_score"]
    if not (ev["finished"] and home and away and hs is not None and as_ is not None):
        return None

    rnd = ev["round"]
    date = ev.get("date", "")                 # ISO match date (dateEvent)
    pair = frozenset((home, away))
    # The matchday number decides group-vs-knockout first (rounds 1–3 are the
    # group stage). This matters when two teams who met in the group are drawn
    # together again in a knockout — the pairing alone would be ambiguous.
    is_group = rnd in (1, 2, 3) or (rnd is None and pair in groups)

    if is_group:
        if pair in groups:                    # orient scores to our schedule
            sched_home, sched_away = groups[pair]
            if home != sched_home:
                home, away, hs, as_ = away, home, as_, hs
            return {"Home": sched_home, "Away": sched_away, "HomeScore": hs, "AwayScore": as_, "Stage": "Group", "Date": date}
        return {"Home": home, "Away": away, "HomeScore": hs, "AwayScore": as_, "Stage": "Group", "Date": date}

    stage = ROUND_TO_STAGE.get(rnd)           # knockout best-effort
    if stage:
        return {"Home": home, "Away": away, "HomeScore": hs, "AwayScore": as_, "Stage": stage, "Date": date}
    return None


def main():
    groups = _group_lookup()
    events = scoring.fetch_events()           # raises on real network/HTTP error

    rows = [r for r in (_match_row(ev, groups) for ev in events) if r]
    if not rows:
        print("No completed matches found yet — leaving the cache untouched. "
              "(Expected before kick-off; the data source may also be incomplete.)")
        return

    pd.DataFrame(rows, columns=COLUMNS).to_csv(CACHE_FILE, index=False)
    print(f"Wrote {len(rows)} completed match(es) to {CACHE_FILE}.")


if __name__ == "__main__":
    try:
        main()
    except Exception as exc:  # noqa: BLE001 — surface real failures to the scheduler
        print(f"ERROR: {exc}", file=sys.stderr)
        sys.exit(1)
