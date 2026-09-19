#!/usr/bin/env python3
"""Fetch a PlayMetrics league, compute opponent-adjusted power rankings, and
render a self-contained web page.

The PlayMetrics site is a single-page app that reads a JSON API. That API sends
no CORS headers, so a browser on another domain cannot call it directly -- which
is why the data is pulled here at build time and baked into the page rather than
fetched live in the browser.

Usage:
    python3 scripts/build.py                 # refresh from the live API
    python3 scripts/build.py --offline       # rebuild the page from data/rankings.json
"""
import argparse
import json
import pathlib
import re
import sys
import time
import urllib.error
import urllib.request
from datetime import datetime, timezone

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))
import ratings  # noqa: E402

API_BASE = "https://api.gb.playmetrics.com/external/lss/"

# Identifies the league. These three values come straight out of the public
# league URL: /g/leagues/<governing_body_id>-<league_id>-<key>/...
GOVERNING_BODY_ID = 1321
LEAGUE_ID = 2470
LEAGUE_KEY = "07598d11"

# The team the page opens on.
FEATURED_LEAGUE_TEAM_ID = 64255

ROOT = pathlib.Path(__file__).resolve().parents[1]
TEMPLATE = ROOT / "templates" / "page.html"
OUT_PAGE = ROOT / "index.html"
OUT_DATA = ROOT / "data" / "rankings.json"

TEAM_URL = (
    "https://playmetricssports.com/g/leagues/"
    "{gb}-{league}-{key}/teams/{team}/team_view.html"
)


def api_post(endpoint, payload, retries=4):
    """POST to the league API, retrying transient network failures."""
    body = json.dumps(payload).encode()
    req = urllib.request.Request(
        API_BASE + endpoint,
        data=body,
        headers={"Content-Type": "application/json", "Accept": "application/json"},
    )
    delay = 2
    for attempt in range(retries):
        try:
            with urllib.request.urlopen(req, timeout=30) as resp:
                return json.loads(resp.read())
        except (urllib.error.URLError, TimeoutError, json.JSONDecodeError) as exc:
            if attempt == retries - 1:
                raise RuntimeError(f"{endpoint} failed after {retries} tries: {exc}")
            time.sleep(delay)
            delay *= 2


def league_payload(**extra):
    payload = {
        "governing_body_id": GOVERNING_BODY_ID,
        "league_id": LEAGUE_ID,
        "key": LEAGUE_KEY,
    }
    payload.update(extra)
    return payload


def short_name(name):
    """Trim the age-group and club boilerplate that prefixes every team name.

    'U11 (15) NCFCY Chelsea' -> 'Chelsea'. Anything that does not match the
    usual shape is left alone rather than mangled.
    """
    trimmed = re.sub(r"^U\d+\s*\(\d+\)\s*", "", name).strip()
    trimmed = re.sub(r"^NCFCY\s+", "", trimmed).strip()
    return trimmed or name


def extract_teams(division):
    """Team list for a division, keyed by the roster id used in the schedule."""
    teams = []
    for entry in division.get("teams", []):
        team = entry.get("team", {})
        if team.get("id") is None:
            continue
        teams.append(
            {
                "id": team["id"],
                "league_team_id": entry.get("id"),
                "name": team.get("name", "Unknown"),
                "short": short_name(team.get("name", "Unknown")),
                "club": (entry.get("club") or {}).get("name", ""),
                "cross_divisional": bool(team.get("is_cross_divisional")),
            }
        )
    return teams


def extract_games(division):
    """Normalize the schedule.

    A game counts toward the ratings only when it has actually been played with
    a visible score and is not excluded from standings. Postponed games carry a
    placeholder 0-0 with show_score false, so filtering on status alone would
    silently invent draws.
    """
    known = {t["id"] for t in extract_teams(division)}
    games = []
    for g in division.get("schedule", []):
        home, away = g.get("home_team_id"), g.get("away_team_id")
        if home not in known or away not in known:
            continue  # cross-divisional or placeholder fixture
        hs, as_ = g.get("home_team_score"), g.get("away_team_score")
        counts = (
            g.get("status") == "Played"
            and bool(g.get("show_score"))
            and not g.get("standings_exclusion")
            and hs is not None
            and as_ is not None
        )
        games.append(
            {
                "id": g.get("id"),
                "home_id": home,
                "away_id": away,
                "home_score": hs if hs is not None else 0,
                "away_score": as_ if as_ is not None else 0,
                "counts": counts,
                "status": g.get("status", ""),
                "round": g.get("round_name", ""),
                "date": g.get("date_short", ""),
                "start": g.get("start_datetime", ""),
                "field": (g.get("field") or {}).get("name", ""),
            }
        )
    games.sort(key=lambda g: g["start"] or "")
    return games


def quality_label(opponent_power_rank, total_teams):
    """Bucket an opponent by where they sit in the division."""
    if not total_teams:
        return "unknown"
    pct = opponent_power_rank / total_teams
    if pct <= 1 / 3:
        return "strong"
    if pct <= 2 / 3:
        return "middle"
    return "weak"


def build_division(meta, division):
    teams = extract_teams(division)
    games = extract_games(division)
    if not teams:
        return None

    team_ids = [t["id"] for t in teams]
    result = ratings.rank_teams(team_ids, games)
    played = [g for g in games if g["counts"]]
    by_id = {t["id"]: t for t in teams}
    n = len(teams)

    rows = []
    for tid in result["order"]:
        team = by_id[tid]
        rec = result["record"][tid]
        resume = []
        for g in played:
            if tid not in (g["home_id"], g["away_id"]):
                continue
            at_home = g["home_id"] == tid
            opp = g["away_id"] if at_home else g["home_id"]
            mine = g["home_score"] if at_home else g["away_score"]
            theirs = g["away_score"] if at_home else g["home_score"]
            resume.append(
                {
                    "opponent": by_id[opp]["short"],
                    "opponent_id": opp,
                    "opponent_rank": result["power_rank"][opp],
                    "quality": quality_label(result["power_rank"][opp], n),
                    "home": at_home,
                    "gf": mine,
                    "ga": theirs,
                    "outcome": "W" if mine > theirs else "L" if mine < theirs else "T",
                    "date": g["date"],
                    "round": g["round"],
                }
            )
        rows.append(
            {
                "id": tid,
                "league_team_id": team["league_team_id"],
                "name": team["name"],
                "short": team["short"],
                "url": TEAM_URL.format(
                    gb=GOVERNING_BODY_ID,
                    league=LEAGUE_ID,
                    key=LEAGUE_KEY,
                    team=team["league_team_id"],
                ),
                "power_rank": result["power_rank"][tid],
                "power_score": round(result["power_score"][tid], 1),
                "rating": round(result["massey"][tid], 2),
                "colley": round(result["colley"][tid], 3),
                "sos": round(result["sos"][tid], 1),
                "sos_rank": result["sos_rank"][tid],
                "table_rank": result["table_rank"][tid],
                "movement": result["table_rank"][tid] - result["power_rank"][tid],
                "record": result["record"][tid],
                "resume": resume,
            }
        )

    upcoming = []
    for g in games:
        if g["counts"] or g["status"] == "Rescheduled":
            continue
        margin = ratings.predict_margin(result, g["home_id"], g["away_id"])
        favorite = g["home_id"] if margin >= 0 else g["away_id"]
        upcoming.append(
            {
                "home": by_id[g["home_id"]]["short"],
                "away": by_id[g["away_id"]]["short"],
                "home_id": g["home_id"],
                "away_id": g["away_id"],
                "favorite": by_id[favorite]["short"],
                "favorite_id": favorite,
                "margin": round(abs(margin), 1),
                "date": g["date"],
                "round": g["round"],
                "field": g["field"],
            }
        )

    return {
        "id": meta["id"],
        "name": meta["name"],
        "gender": meta.get("gender", ""),
        "games_played": len(played),
        "games_total": len([g for g in games if g["status"] != "Rescheduled"]),
        "rounds_complete": len({g["round"] for g in played}),
        "teams": rows,
        "upcoming": upcoming,
    }


def fetch_all():
    league = api_post("league", league_payload())
    divisions = []
    featured_division = None
    for meta in league.get("divisions", []):
        print(f"  fetching {meta['name']} ({meta['id']})", file=sys.stderr)
        raw = api_post("division", league_payload(division_id=meta["id"]))
        built = build_division(meta, raw)
        if not built:
            continue
        divisions.append(built)
        if any(t["league_team_id"] == FEATURED_LEAGUE_TEAM_ID for t in built["teams"]):
            featured_division = built["id"]

    return {
        "league": league.get("name", "League"),
        "generated_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "source_url": TEAM_URL.format(
            gb=GOVERNING_BODY_ID,
            league=LEAGUE_ID,
            key=LEAGUE_KEY,
            team=FEATURED_LEAGUE_TEAM_ID,
        ),
        "featured_division": featured_division,
        "featured_team": FEATURED_LEAGUE_TEAM_ID,
        "settings": {
            "massey_weight": ratings.MASSEY_WEIGHT,
            "colley_weight": ratings.COLLEY_WEIGHT,
            "ridge": ratings.MASSEY_RIDGE,
            "goal_cap": ratings.GOAL_CAP,
            "margin_cap": ratings.MARGIN_CAP,
        },
        "divisions": divisions,
    }


def render(payload):
    template = TEMPLATE.read_text()
    marker = "/*__RANKINGS_DATA__*/null"
    if marker not in template:
        raise RuntimeError(f"template is missing the {marker} placeholder")
    # </script> inside the JSON would close the tag early.
    blob = json.dumps(payload, separators=(",", ":")).replace("</", "<\\/")
    OUT_PAGE.write_text(template.replace(marker, blob))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--offline",
        action="store_true",
        help="re-render the page from the saved data instead of calling the API",
    )
    args = parser.parse_args()

    if args.offline:
        payload = json.loads(OUT_DATA.read_text())
        print("rebuilding page from saved data", file=sys.stderr)
    else:
        print("fetching league data", file=sys.stderr)
        payload = fetch_all()
        OUT_DATA.parent.mkdir(parents=True, exist_ok=True)
        OUT_DATA.write_text(json.dumps(payload, indent=2) + "\n")

    render(payload)
    total = sum(d["games_played"] for d in payload["divisions"])
    print(
        f"built {OUT_PAGE.relative_to(ROOT)}: "
        f"{len(payload['divisions'])} divisions, {total} games rated",
        file=sys.stderr,
    )


if __name__ == "__main__":
    main()
