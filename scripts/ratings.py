"""Rating models that adjust a team's results for the quality of its opponents.

Two complementary models are computed for each division, then blended:

  Colley  -- uses only wins and losses, ignores margin. Self-regularizing:
             every team starts at .500 and a team's rating is pulled toward
             the average rating of the teams it played. Robust with few games.

  Massey  -- uses goal margin, so beating a good team 4-0 counts for more
             than edging them 1-0. Ridge-regularized so that a 3-game sample
             cannot produce wild ratings.

Both are solved as small dense linear systems. A division here is at most a
few dozen teams, so a plain Gaussian elimination is far simpler than pulling
in numpy -- and it keeps the refresh workflow dependency-free.
"""

# The league caps goals at 4 per game for Goals For / Goals Against, and caps
# each game's margin at 4 for Goal Differential. Those are two separate caps:
# a 6-2 win is 4-2 for GF/GA but +4 for GD. Both caps are applied here so the
# ratings inherit the league's own anti-blowout policy -- running up the score
# past 4 earns a team nothing.
GOAL_CAP = 4
MARGIN_CAP = 4

# Weight on the margin-based model when blending. Margin carries more signal
# than win/loss in a short season, but win/loss is what the table rewards, so
# neither gets to dominate.
MASSEY_WEIGHT = 0.60
COLLEY_WEIGHT = 1.0 - MASSEY_WEIGHT

# Ridge term added to the Massey diagonal. Acts like a prior that every team is
# average; its pull fades automatically as teams accumulate games.
MASSEY_RIDGE = 1.0

# Projected margins are posted on the half goal, the way a betting line is: a
# 1.28 projection goes up as 1.5. Tenths of a goal are precision the ratings do
# not have on a sample this size, and a half-goal line reads as a call rather
# than a measurement.
MARGIN_STEP = 0.5

POINTS_WIN, POINTS_TIE, POINTS_LOSS = 3, 1, 0


def solve(matrix, rhs):
    """Solve A x = b by Gaussian elimination with partial pivoting."""
    n = len(rhs)
    a = [list(row) + [rhs[i]] for i, row in enumerate(matrix)]
    for col in range(n):
        pivot = max(range(col, n), key=lambda r: abs(a[r][col]))
        if abs(a[pivot][col]) < 1e-12:
            raise ValueError("singular matrix: division graph is degenerate")
        a[col], a[pivot] = a[pivot], a[col]
        for row in range(col + 1, n):
            factor = a[row][col] / a[col][col]
            if factor:
                for k in range(col, n + 1):
                    a[row][k] -= factor * a[col][k]
    x = [0.0] * n
    for row in range(n - 1, -1, -1):
        total = a[row][n] - sum(a[row][k] * x[k] for k in range(row + 1, n))
        x[row] = total / a[row][row]
    return x


def _index(team_ids):
    return {tid: i for i, tid in enumerate(team_ids)}


def colley(team_ids, games):
    """Colley ratings, centered on .500. Ties count as half a win, half a loss."""
    n = len(team_ids)
    idx = _index(team_ids)
    matrix = [[0.0] * n for _ in range(n)]
    rhs = [1.0] * n
    for i in range(n):
        matrix[i][i] = 2.0

    for g in games:
        h, a = idx[g["home_id"]], idx[g["away_id"]]
        matrix[h][h] += 1.0
        matrix[a][a] += 1.0
        matrix[h][a] -= 1.0
        matrix[a][h] -= 1.0
        if g["home_score"] > g["away_score"]:
            rhs[h] += 0.5
            rhs[a] -= 0.5
        elif g["away_score"] > g["home_score"]:
            rhs[a] += 0.5
            rhs[h] -= 0.5
    return dict(zip(team_ids, solve(matrix, rhs)))


def massey(team_ids, games, ridge=MASSEY_RIDGE):
    """Ridge-regularized Massey ratings on a goals scale, centered on zero.

    A team's rating is its expected margin against a league-average opponent,
    so the gap between two ratings is a predicted goal margin.
    """
    n = len(team_ids)
    idx = _index(team_ids)
    matrix = [[0.0] * n for _ in range(n)]
    rhs = [0.0] * n
    for i in range(n):
        matrix[i][i] = ridge

    for g in games:
        h, a = idx[g["home_id"]], idx[g["away_id"]]
        margin = g["home_score"] - g["away_score"]
        margin = max(-MARGIN_CAP, min(MARGIN_CAP, margin))
        matrix[h][h] += 1.0
        matrix[a][a] += 1.0
        matrix[h][a] -= 1.0
        matrix[a][h] -= 1.0
        rhs[h] += margin
        rhs[a] -= margin
    return dict(zip(team_ids, solve(matrix, rhs)))


def _mean(values):
    return sum(values) / len(values) if values else 0.0


def _stdev(values):
    if len(values) < 2:
        return 0.0
    mu = _mean(values)
    return (sum((v - mu) ** 2 for v in values) / len(values)) ** 0.5


def _z_scores(by_team):
    """Standardize a rating dict. Returns zeros when every team is identical."""
    values = list(by_team.values())
    mu, sd = _mean(values), _stdev(values)
    if sd < 1e-9:
        return {k: 0.0 for k in by_team}
    return {k: (v - mu) / sd for k, v in by_team.items()}


def tally_records(team_ids, games):
    """Win/loss/tie and capped goal totals, matching the league's standings rules."""
    rec = {
        tid: {"gp": 0, "w": 0, "l": 0, "t": 0, "gf": 0, "ga": 0, "gd": 0, "pts": 0}
        for tid in team_ids
    }
    for g in games:
        for me, opp in ((g["home_id"], g["away_id"]), (g["away_id"], g["home_id"])):
            mine = g["home_score"] if me == g["home_id"] else g["away_score"]
            theirs = g["away_score"] if me == g["home_id"] else g["home_score"]
            r = rec[me]
            r["gp"] += 1
            r["gf"] += min(mine, GOAL_CAP)
            r["ga"] += min(theirs, GOAL_CAP)
            r["gd"] += max(-MARGIN_CAP, min(MARGIN_CAP, mine - theirs))
            if mine > theirs:
                r["w"] += 1
                r["pts"] += POINTS_WIN
            elif mine < theirs:
                r["l"] += 1
                r["pts"] += POINTS_LOSS
            else:
                r["t"] += 1
                r["pts"] += POINTS_TIE
    return rec


def table_order(team_ids, rec):
    """Rank teams the way the league table does, for comparison against the model.

    Order: points, then goal differential, then goals for, then goals against.
    Head-to-head is the league's first tie-breaker but it only resolves a
    two-team tie cleanly, so it is left out here and the table rank is treated
    as an approximation of the official standings.
    """
    ordered = sorted(
        team_ids,
        key=lambda t: (-rec[t]["pts"], -rec[t]["gd"], -rec[t]["gf"], rec[t]["ga"]),
    )
    return {tid: i + 1 for i, tid in enumerate(ordered)}


def rank_teams(team_ids, games):
    """Blend both models into a 0-100 power score and assemble per-team detail."""
    played = [g for g in games if g.get("counts")]
    rec = tally_records(team_ids, played)

    col = colley(team_ids, played)
    mas = massey(team_ids, played)
    zc, zm = _z_scores(col), _z_scores(mas)

    blended = {t: MASSEY_WEIGHT * zm[t] + COLLEY_WEIGHT * zc[t] for t in team_ids}
    # 50 is an average team; roughly 15 points per standard deviation keeps a
    # typical division inside 20-80 without clipping.
    score = {t: max(0.0, min(100.0, 50.0 + 15.0 * blended[t])) for t in team_ids}

    opponents = {t: [] for t in team_ids}
    for g in played:
        opponents[g["home_id"]].append(g["away_id"])
        opponents[g["away_id"]].append(g["home_id"])

    # Strength of schedule is the average power score of the teams actually
    # faced -- the direct answer to "who did they play?".
    sos = {t: _mean([score[o] for o in opponents[t]]) for t in team_ids}

    order = sorted(team_ids, key=lambda t: (-score[t], -mas[t], t))
    power_rank = {tid: i + 1 for i, tid in enumerate(order)}
    sos_order = sorted(team_ids, key=lambda t: (-sos[t], t))
    sos_rank = {tid: i + 1 for i, tid in enumerate(sos_order)}
    tbl_rank = table_order(team_ids, rec)

    return {
        "order": order,
        "power_score": score,
        "colley": col,
        "massey": mas,
        "sos": sos,
        "sos_rank": sos_rank,
        "power_rank": power_rank,
        "table_rank": tbl_rank,
        "record": rec,
        "opponents": opponents,
    }


def predict_margin(ratings, home_id, away_id):
    """Projected goal margin from the home team's perspective.

    No home-field adjustment: these are club fields with short travel, and a
    15-game sample could not separate a real home effect from noise anyway.
    """
    return ratings["massey"][home_id] - ratings["massey"][away_id]


def to_line(margin):
    """Round a projected margin to the nearest half goal, halves going up.

    1.28 becomes 1.5, 2.2 becomes 2.0, and anything under a quarter goal
    becomes 0.0 -- a pick'em, which is what the page calls too close to call.
    The sign survives, so a negative line still means the away team.
    """
    steps = int(abs(margin) / MARGIN_STEP + 0.5)  # abs first, so int() floors
    line = steps * MARGIN_STEP
    return -line if margin < 0 else line
