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

import datetime
import re
import sys
import unicodedata

import pandas as pd

import scoring

CACHE_FILE = "results_cache.csv"
SCHEDULE_FILE = "schedule.csv"
EXPECTATIONS_FILE = "team_expectations.csv"
REFRESH_FILE = "last_refresh.txt"          # UTC ISO timestamp of the last run
COLUMNS = ["Home", "Away", "HomeScore", "AwayScore", "Stage", "Date"]

# Best-effort matchday → knockout stage (48-team format: 3 group rounds first).
ROUND_TO_STAGE = {4: "R32", 5: "R16", 6: "QF", 7: "SF", 8: "Final"}


def _norm(name):
    """Loose key for fuzzy team matching: lowercased, accent- and
    punctuation-stripped, with filler words like "islands" dropped. Lets a
    source spelling we haven't explicitly aliased (e.g. "Cape Verde Islands")
    still match its scheduled fixture instead of silently mis-keying it."""
    s = unicodedata.normalize("NFKD", str(name or "")).encode("ascii", "ignore").decode()
    s = re.sub(r"[^a-z0-9 ]", " ", s.lower())
    drop = {"islands", "island", "of", "the"}
    return " ".join(w for w in s.split() if w not in drop)


def _group_lookup():
    """Two lookups keyed by the two teams of each group fixture, both mapping to
    the canonical (home, away) schedule pair:
      exact: {frozenset(home, away): (home, away)}
      norm:  {frozenset(_norm(home), _norm(away)): (home, away)}  (fuzzy fallback)
    """
    sched = pd.read_csv(SCHEDULE_FILE, dtype=str).fillna("")
    exact, norm = {}, {}
    for _, m in sched.iterrows():
        if not m["Stage"].startswith("Group "):
            continue
        parts = m["Match"].split(" vs ")
        if len(parts) != 2:
            continue
        home, away = parts[0].strip(), parts[1].strip()
        exact[frozenset((home, away))] = (home, away)
        norm[frozenset((_norm(home), _norm(away)))] = (home, away)
    return exact, norm


def _match_row(ev, groups):
    """Map a fetched event onto a result row, or None if it can't be placed.

    `groups` is the (exact, norm) pair of lookups from _group_lookup().
    """
    exact, norm = groups
    home, away = ev["home"], ev["away"]
    hs, as_ = ev["home_score"], ev["away_score"]
    if not (ev["finished"] and home and away and hs is not None and as_ is not None):
        return None

    rnd = ev["round"]
    date = ev.get("date", "")                 # ISO match date (dateEvent)
    pair = frozenset((home, away))
    npair = frozenset((_norm(home), _norm(away)))
    # Resolve to the canonical schedule pair: exact name match first, then the
    # fuzzy normalized fallback (catches source spellings we don't alias).
    sched_pair = exact.get(pair) or norm.get(npair)
    # The matchday number decides group-vs-knockout first (rounds 1–3 are the
    # group stage). This matters when two teams who met in the group are drawn
    # together again in a knockout — the pairing alone would be ambiguous.
    is_group = rnd in (1, 2, 3) or (rnd is None and sched_pair is not None)

    if is_group:
        if sched_pair:                        # rename + orient scores to our schedule
            sched_home, sched_away = sched_pair
            if _norm(home) != _norm(sched_home):
                hs, as_ = as_, hs
            return {"Home": sched_home, "Away": sched_away, "HomeScore": hs, "AwayScore": as_, "Stage": "Group", "Date": date}
        print(f"WARNING: group match {home} vs {away} not found in schedule - "
              f"writing source names as-is (standings may not pick it up).", file=sys.stderr)
        return {"Home": home, "Away": away, "HomeScore": hs, "AwayScore": as_, "Stage": "Group", "Date": date}

    stage = ROUND_TO_STAGE.get(rnd)           # knockout best-effort
    if stage:
        return {"Home": home, "Away": away, "HomeScore": hs, "AwayScore": as_, "Stage": stage, "Date": date}
    return None


def main():
    groups = _group_lookup()
    events = scoring.fetch_events()           # raises on real network/HTTP error

    # Stamp the run time (UTC) on every successful fetch — even when no new
    # results are found — so the app can show when the refresh last ran.
    with open(REFRESH_FILE, "w") as f:
        f.write(datetime.datetime.now(datetime.timezone.utc).isoformat())

    rows = [r for r in (_match_row(ev, groups) for ev in events) if r]
    if not rows:
        print("No completed matches found yet — cache untouched; refresh time updated. "
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
