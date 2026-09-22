"""Turn the ratings into probabilities, and the probabilities into a season.

`ratings.py` answers "how good is this team?" and hands back a projected goal
margin. That is enough for a line next to a fixture, but not enough to say what
a team's season is likely to look like. This module adds the two pieces that
are:

  1. A spread around the projection, so a margin becomes a win/draw/loss
     probability. The spread is measured, not assumed -- see `loo_predictions`.
  2. A Monte Carlo replay of the remaining schedule, so the probabilities
     become a finishing position.

Everything here is derived from the already-built payload, so it works the same
on a live fetch and on an offline rebuild.
"""
import math
import random
from bisect import bisect_left
from collections import Counter

from ratings import GOAL_CAP, MARGIN_CAP, POINTS_LOSS, POINTS_TIE, POINTS_WIN
import ratings

# A game is a draw when the margin lands on zero, so the win/loss tails start
# half a goal out. This is the ordinary continuity correction for reading a
# discrete count off a continuous curve, not a tuned parameter.
DRAW_BAND = 0.5

# Floor and ceiling on the measured spread. The floor stops a division with a
# handful of tidy results from claiming near-certainty; the ceiling stops one
# with two games per team from washing every projection out to a coin flip.
SIGMA_FLOOR = 1.5
SIGMA_CEILING = 3.2

# Monte Carlo runs. 20,000 puts the standard error on a 50% probability near
# 0.35 of a percentage point, which is finer than the ratings deserve, and the
# whole thing still takes under a second.
SIM_RUNS = 20000

# Fixed, so a rebuild that finds no new results produces the same page rather
# than a page whose odds wobble by half a point every twelve hours.
SIM_SEED = 1905


def normal_cdf(z):
    return 0.5 * (1.0 + math.erf(z / math.sqrt(2.0)))


def replay_games(division):
    """Rebuild the division's played games from the teams' resumes.

    The résumés carry both sides of every game, so taking only the home entries
    reconstructs each game exactly once. Doing it this way means nothing has to
    be refetched or kept in the saved data for an offline rebuild.
    """
    games = []
    for team in division.get("teams", []):
        for entry in team.get("resume", []):
            if not entry["home"]:
                continue
            games.append(
                {
                    "home_id": team["id"],
                    "away_id": entry["opponent_id"],
                    "home_score": entry["gf"],
                    "away_score": entry["ga"],
                    "counts": True,
                }
            )
    return games


def _capped(margin):
    return max(-MARGIN_CAP, min(MARGIN_CAP, margin))


def loo_predictions(divisions):
    """Predict every played game in the league from a fit that leaves it out.

    Scoring the model on games it has already seen would flatter it badly --
    in-sample the misses run about 1.4 goals, out-of-sample about 2.3 -- and
    every number downstream of this is a claim about a game nobody has seen.
    Returns (projected margin, actual margin) for each game, home side first.
    """
    rows = []
    for division in divisions:
        ids = [t["id"] for t in division.get("teams", [])]
        games = replay_games(division)
        if len(ids) < 3 or len(games) < 2:
            continue
        for held_out in range(len(games)):
            rest = games[:held_out] + games[held_out + 1 :]
            try:
                fit = ratings.massey(ids, rest)
            except ValueError:
                continue  # holding a game out can disconnect the division
            game = games[held_out]
            rows.append(
                (
                    fit[game["home_id"]] - fit[game["away_id"]],
                    _capped(game["home_score"] - game["away_score"]),
                )
            )
    return rows


def sigma_from(predictions):
    """How far the projected margin actually misses, in goals."""
    if not predictions:
        return SIGMA_CEILING
    squared = sum((actual - mu) ** 2 for mu, actual in predictions)
    rmse = (squared / len(predictions)) ** 0.5
    return max(SIGMA_FLOOR, min(SIGMA_CEILING, rmse))


def loo_expected(division):
    """Projected margin for each played game in one division, game left out.

    Aligned with `replay_games(division)`. This is what lets a résumé say a
    result beat its projection rather than merely that it was a win: the
    projection is made without the benefit of the game being judged.
    """
    ids = [t["id"] for t in division.get("teams", [])]
    games = replay_games(division)
    out = []
    for held_out in range(len(games)):
        rest = games[:held_out] + games[held_out + 1 :]
        try:
            fit = ratings.massey(ids, rest)
        except ValueError:
            out.append(None)
            continue
        game = games[held_out]
        out.append(fit[game["home_id"]] - fit[game["away_id"]])
    return games, out


def margin_distribution(mu, sigma):
    """Probability of each whole-goal margin, from -4 to +4.

    A continuous curve read off at whole goals: the margin lands on k when the
    underlying number falls within half a goal of k. Both tails are piled onto
    the caps, which is what the league's own goal-differential rule does to a
    real scoreline anyway.
    """
    out = {}
    for k in range(-MARGIN_CAP, MARGIN_CAP + 1):
        if k == -MARGIN_CAP:
            p = normal_cdf((k + 0.5 - mu) / sigma)
        elif k == MARGIN_CAP:
            p = 1.0 - normal_cdf((k - 0.5 - mu) / sigma)
        else:
            p = normal_cdf((k + 0.5 - mu) / sigma) - normal_cdf((k - 0.5 - mu) / sigma)
        out[k] = p
    return out


def outcome_probs(mu, sigma):
    """(win, draw, loss) for the side the margin is quoted from."""
    loss = normal_cdf((-DRAW_BAND - mu) / sigma)
    win = 1.0 - normal_cdf((DRAW_BAND - mu) / sigma)
    return win, max(0.0, 1.0 - win - loss), loss


def calibration(predictions, sigma, buckets=5):
    """Score the probability model against every game the league has played.

    Each left-out prediction is bucketed by how likely a home win was called,
    then compared with how often the home side actually won. A model whose 70%
    calls come in at 70% is telling the truth.
    """
    if not predictions:
        return {"buckets": [], "games": 0, "brier": None}

    rows = [(outcome_probs(mu, sigma)[0], 1 if actual > 0 else 0) for mu, actual in predictions]
    tally = [[0.0, 0, 0] for _ in range(buckets)]
    for predicted, won in rows:
        slot = min(buckets - 1, int(predicted * buckets))
        tally[slot][0] += predicted
        tally[slot][1] += won
        tally[slot][2] += 1

    out = []
    for slot, (total, won, n) in enumerate(tally):
        if not n:
            continue
        out.append(
            {
                "low": round(slot / buckets, 2),
                "high": round((slot + 1) / buckets, 2),
                "predicted": round(total / n, 3),
                "actual": round(won / n, 3),
                "games": n,
            }
        )
    brier = sum((p - w) ** 2 for p, w in rows) / len(rows)
    # What the same score would be for a model that ignored the teams entirely
    # and quoted the league's home-win rate at every game. A Brier score only
    # means something next to the one you have to beat.
    base = sum(w for _, w in rows) / len(rows)
    baseline = sum((base - w) ** 2 for _, w in rows) / len(rows)
    return {
        "buckets": out,
        "games": len(rows),
        "brier": round(brier, 3),
        "baseline": round(baseline, 3),
        "skill": round(1 - brier / baseline, 3) if baseline else None,
    }


def floor_goal_weights(divisions):
    """How many goals the lower-scoring side tends to manage, from the record.

    Simulating a margin settles points and goal difference, but the league
    breaks a tie on goals scored too, so a scoreline is needed rather than a
    margin. Rather than assume a shape, the losing side's goals are drawn from
    what this league has actually produced.
    """
    counts = Counter()
    for division in divisions:
        for game in replay_games(division):
            home = min(game["home_score"], GOAL_CAP)
            away = min(game["away_score"], GOAL_CAP)
            counts[min(home, away)] += 1
    if not counts:
        return [(0, 0.3), (1, 0.4), (2, 0.3)]
    total = sum(counts.values())
    return [(goals, n / total) for goals, n in sorted(counts.items())]


class _Sampler:
    """Draw from a small discrete distribution by inverse CDF."""

    def __init__(self, pairs):
        self.values, self.cumulative = [], []
        running = 0.0
        for value, weight in pairs:
            running += weight
            self.values.append(value)
            self.cumulative.append(running)
        self.cumulative[-1] = 1.0

    def draw(self, u):
        return self.values[bisect_left(self.cumulative, u)]


def _standings_key(team_id, pts, gd, gf, ga):
    # Points, then goal difference, then goals for, then goals against -- the
    # league's order, minus head-to-head. Head-to-head is its first tie-break
    # but only resolves a clean two-team tie, so the id is the last resort here
    # and ties this deep are noted rather than pretended away.
    return (-pts, -gd, -gf, ga, team_id)


def simulate_season(division, fixtures, massey, sigma, floor_weights, runs=SIM_RUNS,
                    seed=SIM_SEED, focus_id=None):
    """Replay the rest of the schedule many times and count how it ends.

    Ratings are held fixed across a run: the model does not get to learn from
    the games it is inventing, which would let one simulated blowout compound
    into a runaway season. Each fixture is an independent draw around its own
    projected margin, using the spread measured in `loo_sigma`.
    """
    teams = division["teams"]
    ids = [t["id"] for t in teams]
    start = {
        t["id"]: (t["record"]["pts"], t["record"]["gd"], t["record"]["gf"], t["record"]["ga"])
        for t in teams
    }

    margin_samplers = []
    for fixture in fixtures:
        mu = massey[fixture["home_id"]] - massey[fixture["away_id"]]
        dist = margin_distribution(mu, sigma)
        margin_samplers.append(_Sampler(sorted(dist.items())))
    floor_sampler = _Sampler(floor_weights)

    rng = random.Random(seed)
    n_teams = len(ids)
    finishes = {tid: [0] * n_teams for tid in ids}
    points_total = {tid: 0 for tid in ids}
    points_hist = Counter()
    # What it actually takes to win this division, rather than what one team
    # is likely to manage: the champion's points total, run after run.
    champion_points = Counter()
    # And the simplest question a parent asks -- what if they win out?
    sweep_runs, sweep_first, sweep_top3 = 0, 0, 0
    # For every fixture the focus team plays, what happens to its season under
    # each of the three results. This is the "which game matters most" answer,
    # and it comes free: the runs are already there, they only need sorting.
    leverage = [
        {"W": Counter(), "D": Counter(), "L": Counter()} for _ in fixtures
    ] if focus_id else []

    for _ in range(runs):
        pts = {tid: start[tid][0] for tid in ids}
        gd = {tid: start[tid][1] for tid in ids}
        gf = {tid: start[tid][2] for tid in ids}
        ga = {tid: start[tid][3] for tid in ids}
        focus_results = []

        for i, fixture in enumerate(fixtures):
            home, away = fixture["home_id"], fixture["away_id"]
            margin = margin_samplers[i].draw(rng.random())
            low = floor_sampler.draw(rng.random())
            high = min(GOAL_CAP, low + abs(margin))
            home_goals, away_goals = (high, low) if margin > 0 else (
                (low, high) if margin < 0 else (low, low)
            )
            gf[home] += home_goals
            ga[home] += away_goals
            gf[away] += away_goals
            ga[away] += home_goals
            gd[home] += margin
            gd[away] -= margin
            if margin > 0:
                pts[home] += POINTS_WIN
                pts[away] += POINTS_LOSS
            elif margin < 0:
                pts[away] += POINTS_WIN
                pts[home] += POINTS_LOSS
            else:
                pts[home] += POINTS_TIE
                pts[away] += POINTS_TIE
            if focus_id and focus_id in (home, away):
                signed = margin if focus_id == home else -margin
                focus_results.append((i, "W" if signed > 0 else "L" if signed < 0 else "D"))

        order = sorted(ids, key=lambda t: _standings_key(t, pts[t], gd[t], gf[t], ga[t]))
        for place, tid in enumerate(order):
            finishes[tid][place] += 1
            points_total[tid] += pts[tid]
        champion_points[pts[order[0]]] += 1
        if focus_id:
            place = order.index(focus_id) + 1
            points_hist[pts[focus_id]] += 1
            for i, result in focus_results:
                leverage[i][result][place] += 1
            if focus_results and all(r == "W" for _, r in focus_results):
                sweep_runs += 1
                sweep_first += place == 1
                sweep_top3 += place <= 3

    def summarize(tid):
        dist = finishes[tid]
        return {
            "id": tid,
            "finish": [round(c / runs, 4) for c in dist],
            "first": round(dist[0] / runs, 4),
            "top3": round(sum(dist[:3]) / runs, 4),
            "last": round(dist[-1] / runs, 4),
            "mean_points": round(points_total[tid] / runs, 2),
            "mean_finish": round(sum((i + 1) * c for i, c in enumerate(dist)) / runs, 2),
        }

    out = {
        "runs": runs,
        "sigma": round(sigma, 2),
        "fixtures": len(fixtures),
        "teams": [summarize(tid) for tid in ids],
        "champion_points": _points_summary(champion_points, runs),
    }

    if focus_id:
        out["focus"] = summarize(focus_id)
        out["focus"]["points"] = _points_summary(points_hist, runs)
        out["focus"]["sweep"] = {
            "share": round(sweep_runs / runs, 4),
            "first": round(sweep_first / sweep_runs, 4) if sweep_runs else None,
            "top3": round(sweep_top3 / sweep_runs, 4) if sweep_runs else None,
        }
        out["leverage"] = []
        for i, fixture in enumerate(fixtures):
            if focus_id not in (fixture["home_id"], fixture["away_id"]):
                continue
            entry = {"fixture": i, "opponent_id":
                     fixture["away_id"] if fixture["home_id"] == focus_id else fixture["home_id"]}
            for result in ("W", "D", "L"):
                counter = leverage[i][result]
                n = sum(counter.values())
                entry[result] = {
                    "share": round(n / runs, 4),
                    "first": round(counter[1] / n, 4) if n else None,
                    "top3": round(sum(counter[p] for p in (1, 2, 3)) / n, 4) if n else None,
                    "mean_finish": round(
                        sum(p * c for p, c in counter.items()) / n, 2) if n else None,
                }
            out["leverage"].append(entry)
    return out


def _points_summary(hist, runs):
    total = sum(hist.values()) or 1
    mean = sum(p * c for p, c in hist.items()) / total
    ordered = sorted(hist.items())

    def quantile(q):
        target, running = q * total, 0
        for points, count in ordered:
            running += count
            if running >= target:
                return points
        return ordered[-1][0]

    return {
        "mean": round(mean, 1),
        "low": quantile(0.10),
        "high": quantile(0.90),
        "most_likely": max(hist.items(), key=lambda kv: (kv[1], kv[0]))[0],
        "distribution": [[p, round(c / total, 4)] for p, c in ordered],
    }
