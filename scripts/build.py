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
import collections
import json
import pathlib
import sys
import time
import urllib.error
import urllib.request
from datetime import datetime, timezone

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))
import clubs  # noqa: E402
import projections  # noqa: E402
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
TEAM_TEMPLATE = ROOT / "templates" / "team.html"
SHARED_CSS = ROOT / "templates" / "shared.css"
CREST_JS = ROOT / "templates" / "crest.js"
OUT_PAGE = ROOT / "index.html"
OUT_TEAM_PAGE = ROOT / "team.html"
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
                "short": clubs.parse(team.get("name", "Unknown"))["display"],
                "club": (entry.get("club") or {}).get("name", ""),
                "cross_divisional": bool(team.get("is_cross_divisional")),
            }
        )
    return teams


def extract_games(division):
    """Normalize the schedule.

    A game counts toward the ratings only when it has actually been played with
    a visible score and is not excluded from standings. A rescheduled game
    carries a placeholder 0-0 with show_score false, so filtering on status
    alone would silently invent draws.
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
        field = g.get("field") or {}
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
                "day": (g.get("date", "").split(",") or [""])[0],
                "time": g.get("time", ""),
                "start": g.get("start_datetime", ""),
                "field": field.get("name", ""),
                # The address is kept and the map link is not: the API's link is
                # just a Google Maps search for that same address, so the page
                # builds it rather than carrying 400 copies of it.
                "address": field.get("address", ""),
            }
        )
    # A game the league has not slotted yet sorts last rather than first: an
    # empty string would otherwise sort ahead of every real kickoff.
    games.sort(key=lambda g: (not g["start"], g["start"]))
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
        if g["counts"]:
            continue
        margin = ratings.predict_margin(result, g["home_id"], g["away_id"])
        # Posted on the half goal like a betting line; the favorite still comes
        # from the raw projection, so a pick'em keeps the side it leaned to.
        line = ratings.to_line(margin)
        favorite = g["home_id"] if margin >= 0 else g["away_id"]
        fixture = {
            "home": by_id[g["home_id"]]["short"],
            "away": by_id[g["away_id"]]["short"],
            "home_id": g["home_id"],
            "away_id": g["away_id"],
            "favorite": by_id[favorite]["short"],
            "favorite_id": favorite,
            "margin": abs(line),
            "raw_margin": round(margin, 2),
            "date": g["date"],
            "day": g["day"],
            "time": g["time"],
            "round": g["round"],
            "field": g["field"],
            "address": g["address"],
            # The league marks a moved game "Rescheduled" and rewrites its
            # date, time, field and round label in place, so the row already
            # says when the game is. The flag is kept to say the fixture moved,
            # not to say it is dateless.
            "moved": g["status"] == "Rescheduled",
        }
        upcoming.append(fixture)

    return {
        "id": meta["id"],
        "name": meta["name"],
        "gender": meta.get("gender", ""),
        "games_played": len(played),
        "games_total": len(games),
        "rounds_complete": len({g["round"] for g in played}),
        "games_moved": sum(1 for f in upcoming if f["moved"]),
        "teams": rows,
        "upcoming": upcoming,
    }


def _round_key(name):
    """Sort 'Round 10' after 'Round 9' rather than after 'Round 1'."""
    digits = "".join(c for c in name if c.isdigit())
    return (0, int(digits)) if digits else (1, name)


def build_featured(payload):
    """Everything the team page needs about the one team the page is built for.

    The division pages answer "who is good?". This answers "what happens to us
    now?", which needs two things the ranking does not: a measured spread
    around each projection, and a replay of the games still to come. Both are
    computed here so the page ships as arithmetic already done.
    """
    division = next(
        (d for d in payload["divisions"] if d["id"] == payload.get("featured_division")),
        None,
    )
    if not division:
        return None
    team = next(
        (t for t in division["teams"] if t["league_team_id"] == payload["featured_team"]),
        None,
    )
    if not team:
        return None

    # The spread is measured across the whole league, not just this division:
    # one division of twenty games would give a noisy number, and how far a
    # projection misses is a property of the model, not of the division.
    predictions = projections.loo_predictions(payload["divisions"])
    sigma = projections.sigma_from(predictions)
    floor_weights = projections.floor_goal_weights(payload["divisions"])
    by_id = {t["id"]: t for t in division["teams"]}
    massey = {t["id"]: t["rating"] for t in division["teams"]}

    # What each result was worth against what the model expected of it, with
    # the game itself held out of the fit that made the expectation.
    replayed, expected = projections.loo_expected(division)
    margin_by_pair = {}
    for game, mu in zip(replayed, expected):
        if mu is not None:
            margin_by_pair[(game["home_id"], game["away_id"])] = mu

    played = []
    for entry in team["resume"]:
        pair = ((team["id"], entry["opponent_id"]) if entry["home"]
                else (entry["opponent_id"], team["id"]))
        mu = margin_by_pair.get(pair)
        if mu is not None and not entry["home"]:
            mu = -mu
        actual = max(-ratings.MARGIN_CAP,
                     min(ratings.MARGIN_CAP, entry["gf"] - entry["ga"]))
        played.append(
            {
                **entry,
                "expected": round(mu, 2) if mu is not None else None,
                "edge": round(actual - mu, 2) if mu is not None else None,
            }
        )

    remaining = []
    fixtures = division.get("upcoming", [])
    for fixture in fixtures:
        if team["id"] not in (fixture["home_id"], fixture["away_id"]):
            continue
        at_home = fixture["home_id"] == team["id"]
        opponent = fixture["away_id"] if at_home else fixture["home_id"]
        mu = massey[team["id"]] - massey[opponent]
        win, draw, loss = projections.outcome_probs(mu, sigma)
        remaining.append(
            {
                "opponent_id": opponent,
                "home": at_home,
                "round": fixture["round"],
                "date": fixture["date"],
                "day": fixture.get("day", ""),
                "time": fixture.get("time", ""),
                "field": fixture.get("field", ""),
                "address": fixture.get("address", ""),
                "moved": fixture.get("moved", False),
                "raw_margin": round(mu, 2),
                "line": ratings.to_line(mu),
                "win": round(win, 4),
                "draw": round(draw, 4),
                "loss": round(loss, 4),
                "margins": [
                    [k, round(v, 4)]
                    for k, v in sorted(projections.margin_distribution(mu, sigma).items())
                ],
            }
        )

    # Rounds the rest of the division plays and this team does not. A moved
    # game takes the round label of the weekend it lands on, which leaves a
    # hole in one round and two games in another. Netting the doubles off the
    # gaps keeps a relabelled fixture from being announced as a free weekend.
    played_rounds = [g["round"] for g in team["resume"]]
    owed_rounds = [f["round"] for f in remaining]
    counts = collections.Counter(played_rounds + owed_rounds)
    doubled = sum(n - 1 for n in counts.values() if n > 1)
    all_rounds = {g["round"] for t in division["teams"] for g in t["resume"]}
    all_rounds |= {f["round"] for f in fixtures}
    gaps = sorted(all_rounds - set(counts), key=_round_key)
    byes = gaps[doubled:]

    # Every fixture left in the division feeds the simulation, this team's and
    # everyone else's: a rival's remaining schedule decides where we finish
    # just as surely as our own does.
    sim = projections.simulate_season(
        division, fixtures, massey, sigma, floor_weights, focus_id=team["id"]
    )

    # What each result in each game would do to the season, attached to the
    # fixture it belongs to. Both lists walk the same fixtures in the same
    # order, so they pair off by position -- looking the entry up by opponent
    # would quietly pick the wrong game in a division that schedules a pairing
    # twice.
    swings = sim.pop("leverage", [])
    if len(swings) != len(remaining):
        raise RuntimeError("leverage and remaining fixtures disagree")
    for fixture, swing in zip(remaining, swings):
        if swing["opponent_id"] != fixture["opponent_id"]:
            raise RuntimeError("leverage is out of step with the schedule")
        fixture["swing"] = {result: swing[result] for result in ("W", "D", "L")}

    opponents_left = [by_id[f["opponent_id"]]["power_score"] for f in remaining]
    return {
        "team_id": team["id"],
        "league_team_id": team["league_team_id"],
        "division_id": division["id"],
        "sigma": round(sigma, 2),
        "calibration": projections.calibration(predictions, sigma),
        "played": played,
        "remaining": remaining,
        "byes": byes,
        "remaining_sos": round(sum(opponents_left) / len(opponents_left), 1)
        if opponents_left
        else None,
        "sim": sim,
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
            "margin_step": ratings.MARGIN_STEP,
        },
        "divisions": divisions,
    }


MARKER = "/*__RANKINGS_DATA__*/null"
# The two pages share their design tokens and their crest drawing. Both are
# kept in one place and inlined here, so a change reaches both pages and each
# page still ships as a single file that needs nothing but a browser.
PARTIALS = {"/*__SHARED_CSS__*/": SHARED_CSS, "/*__CREST_JS__*/": CREST_JS}


def render(payload):
    """Write both pages: the league-wide rankings and the featured team's own.

    Both are the same data seen from different distances, so both get the whole
    payload baked in and neither needs a server.
    """
    # Names, crests and colors are presentation, so they are attached here
    # rather than saved into data/rankings.json: a change to the club table
    # reaches the page on the next build with nothing refetched.
    payload = clubs.decorate(payload)
    # </script> inside the JSON would close the tag early.
    blob = json.dumps(payload, separators=(",", ":")).replace("</", "<\\/")
    for template_path, out_path in ((TEMPLATE, OUT_PAGE), (TEAM_TEMPLATE, OUT_TEAM_PAGE)):
        template = template_path.read_text()
        if MARKER not in template:
            raise RuntimeError(f"{template_path.name} is missing the {MARKER} placeholder")
        for placeholder, partial in PARTIALS.items():
            template = template.replace(placeholder, partial.read_text())
        out_path.write_text(template.replace(MARKER, blob))


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

    # Recomputed on every build, offline included: it is all derived from the
    # payload, so a change to the projection code reaches the page without a
    # refetch, the same way a change to the club table does.
    print("projecting the rest of the season", file=sys.stderr)
    payload["featured"] = build_featured(payload)

    if not args.offline:
        OUT_DATA.parent.mkdir(parents=True, exist_ok=True)
        OUT_DATA.write_text(json.dumps(payload, indent=2) + "\n")

    render(payload)
    total = sum(d["games_played"] for d in payload["divisions"])
    print(
        f"built {OUT_PAGE.relative_to(ROOT)} and {OUT_TEAM_PAGE.relative_to(ROOT)}: "
        f"{len(payload['divisions'])} divisions, {total} games rated",
        file=sys.stderr,
    )


if __name__ == "__main__":
    main()
