"""Daily results fetcher — run on a schedule (GitHub Action), not by the app.

Fetches the latest World Cup 2026 results from TheSportsDB, derives each
team's group record and furthest round, and writes them to results_cache.csv
(plus a results_updated.txt timestamp). The Streamlit app then just reads
that committed file, so it always shows data refreshed within the last day
without every visitor hitting the API.

Exit code is non-zero on failure so the scheduler surfaces the problem and
the previous (good) cache file is left untouched.
"""

import sys
import datetime

import pandas as pd

import scoring

CACHE_FILE = "results_cache.csv"
UPDATED_FILE = "results_updated.txt"
EXPECTATIONS_FILE = "team_expectations.csv"


def _all_teams():
    df = pd.read_csv(EXPECTATIONS_FILE)
    return list(df["Team"])


def main():
    all_teams = _all_teams()

    # fetch_events() raises on a real network/HTTP failure (→ exit 1 below).
    # An empty result just means no playable data yet — that's a clean no-op,
    # not a failure, so the daily job shouldn't go red before the tournament.
    events = scoring.fetch_events()
    finished = [e for e in events if e.get("finished")]
    if not finished:
        print("No completed matches found yet — leaving the cache untouched. "
              "(Expected before kick-off; if matches have already been played, "
              "the data source may be incomplete or unstructured.)")
        return

    states = scoring.compute_team_states(events, all_teams)

    rows = [
        {"Team": t, "wins": s["wins"], "draws": s["draws"],
         "losses": s["losses"], "round_reached": s["round_reached"],
         "gf": s.get("gf", 0), "ga": s.get("ga", 0)}
        for t, s in states.items()
    ]
    pd.DataFrame(rows).to_csv(CACHE_FILE, index=False)

    stamp = datetime.datetime.now(datetime.timezone.utc).isoformat()
    with open(UPDATED_FILE, "w", encoding="utf-8") as fh:
        fh.write(stamp + "\n")

    played = sum(1 for s in states.values() if s["wins"] + s["draws"] + s["losses"] > 0)
    print(f"Wrote {len(rows)} teams to {CACHE_FILE} ({played} with results played). Updated {stamp}.")


if __name__ == "__main__":
    try:
        main()
    except Exception as exc:  # noqa: BLE001 — surface any failure to the scheduler
        print(f"ERROR: {exc}", file=sys.stderr)
        sys.exit(1)
