"""Tests for the probability model and the season simulation.

The ratings have a check that pins them to reality: the recomputed standings
have to match the league's published ones. A probability has no such anchor --
nobody publishes the true odds of a U11 game -- so what is checked here is that
the arithmetic is sound, that the model scores better than knowing nothing, and
that the simulation cannot produce a season the schedule could not.
"""
import json
import pathlib
import sys
import unittest

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1] / "scripts"))

import projections  # noqa: E402
import ratings  # noqa: E402
from build import build_division, build_featured  # noqa: E402

FIXTURE = pathlib.Path(__file__).parent / "fixtures" / "division_19780.json"
CHELSEA_LEAGUE_TEAM_ID = 64255


def load_fixture():
    return json.loads(FIXTURE.read_text())


def built_division():
    raw = load_fixture()
    return build_division({"id": raw["id"], "name": raw["name"]}, raw)


def built_payload():
    division = built_division()
    return {
        "league": "Test",
        "featured_division": division["id"],
        "featured_team": CHELSEA_LEAGUE_TEAM_ID,
        "divisions": [division],
    }


class TestDistributions(unittest.TestCase):
    def test_normal_cdf_known_points(self):
        self.assertAlmostEqual(projections.normal_cdf(0.0), 0.5, places=9)
        self.assertAlmostEqual(projections.normal_cdf(1.96), 0.975, places=3)
        self.assertAlmostEqual(projections.normal_cdf(-1.96), 0.025, places=3)

    def test_margin_distribution_is_a_distribution(self):
        for mu in (-3.0, -0.4, 0.0, 1.25, 5.0):
            dist = projections.margin_distribution(mu, 2.3)
            self.assertEqual(sorted(dist), list(range(-4, 5)))
            self.assertAlmostEqual(sum(dist.values()), 1.0, places=9)
            for p in dist.values():
                self.assertGreaterEqual(p, 0.0)

    def test_margin_distribution_peaks_near_the_projection(self):
        dist = projections.margin_distribution(2.0, 1.5)
        self.assertEqual(max(dist, key=dist.get), 2)

    def test_outcome_probs_sum_to_one_and_favour_the_projection(self):
        win, draw, loss = projections.outcome_probs(1.5, 2.3)
        self.assertAlmostEqual(win + draw + loss, 1.0, places=9)
        self.assertGreater(win, loss)

    def test_outcome_probs_are_symmetric(self):
        win, draw, loss = projections.outcome_probs(1.2, 2.0)
        flipped = projections.outcome_probs(-1.2, 2.0)
        self.assertAlmostEqual(flipped[0], loss, places=9)
        self.assertAlmostEqual(flipped[1], draw, places=9)
        self.assertAlmostEqual(flipped[2], win, places=9)

    def test_a_pick_em_is_a_coin_flip(self):
        win, _, loss = projections.outcome_probs(0.0, 2.3)
        self.assertAlmostEqual(win, loss, places=9)

    def test_a_wider_spread_makes_a_favourite_less_certain(self):
        tight = projections.outcome_probs(2.0, 1.0)[0]
        loose = projections.outcome_probs(2.0, 3.0)[0]
        self.assertGreater(tight, loose)


class TestSampler(unittest.TestCase):
    def test_inverse_cdf_lands_in_the_right_bucket(self):
        sampler = projections._Sampler([("a", 0.25), ("b", 0.5), ("c", 0.25)])
        self.assertEqual(sampler.draw(0.10), "a")
        self.assertEqual(sampler.draw(0.40), "b")
        self.assertEqual(sampler.draw(0.90), "c")

    def test_the_top_of_the_range_is_covered(self):
        sampler = projections._Sampler([(1, 0.5), (2, 0.5)])
        self.assertEqual(sampler.draw(0.999999), 2)


class TestReplay(unittest.TestCase):
    """The résumés have to reconstruct the schedule they came from."""

    def setUp(self):
        self.division = built_division()
        self.games = projections.replay_games(self.division)

    def test_every_played_game_comes_back_exactly_once(self):
        self.assertEqual(len(self.games), self.division["games_played"])

    def test_the_scorelines_survive_the_round_trip(self):
        raw = {
            (g["home_id"], g["away_id"]): (g["home_score"], g["away_score"])
            for g in self.games
        }
        for team in self.division["teams"]:
            for entry in team["resume"]:
                key = ((team["id"], entry["opponent_id"]) if entry["home"]
                       else (entry["opponent_id"], team["id"]))
                scores = raw[key]
                mine = scores[0] if entry["home"] else scores[1]
                theirs = scores[1] if entry["home"] else scores[0]
                self.assertEqual((mine, theirs), (entry["gf"], entry["ga"]))


class TestMeasuredSpread(unittest.TestCase):
    def setUp(self):
        self.divisions = [built_division()]
        self.predictions = projections.loo_predictions(self.divisions)

    def test_one_prediction_per_played_game(self):
        self.assertEqual(len(self.predictions), self.divisions[0]["games_played"])

    def test_holding_a_game_out_makes_the_model_look_worse(self):
        """The whole reason for the leave-one-out pass.

        Scored on games it has already been fitted to, the model flatters
        itself. If this ever inverts, the fit is leaking.
        """
        ids = [t["id"] for t in self.divisions[0]["teams"]]
        games = projections.replay_games(self.divisions[0])
        fit = ratings.massey(ids, games)
        in_sample = sum(
            (max(-4, min(4, g["home_score"] - g["away_score"]))
             - (fit[g["home_id"]] - fit[g["away_id"]])) ** 2
            for g in games
        ) / len(games)
        out_of_sample = sum((a - mu) ** 2 for mu, a in self.predictions) / len(self.predictions)
        self.assertGreater(out_of_sample, in_sample)

    def test_sigma_is_clamped_to_the_stated_range(self):
        sigma = projections.sigma_from(self.predictions)
        self.assertGreaterEqual(sigma, projections.SIGMA_FLOOR)
        self.assertLessEqual(sigma, projections.SIGMA_CEILING)

    def test_no_games_is_not_an_error(self):
        self.assertEqual(projections.sigma_from([]), projections.SIGMA_CEILING)
        self.assertEqual(projections.loo_predictions([]), [])

    def test_a_perfect_record_of_predictions_still_respects_the_floor(self):
        # Zero error would claim certainty a four-game season cannot support.
        self.assertEqual(projections.sigma_from([(1.0, 1.0)] * 20),
                         projections.SIGMA_FLOOR)


class TestCalibration(unittest.TestCase):
    def setUp(self):
        divisions = [built_division()]
        self.predictions = projections.loo_predictions(divisions)
        self.report = projections.calibration(self.predictions, 2.3)

    def test_every_prediction_lands_in_exactly_one_bucket(self):
        self.assertEqual(sum(b["games"] for b in self.report["buckets"]),
                         self.report["games"])

    def test_it_beats_quoting_the_base_rate(self):
        self.assertLess(self.report["brier"], self.report["baseline"])
        self.assertGreater(self.report["skill"], 0.0)

    def test_no_games_is_not_an_error(self):
        empty = projections.calibration([], 2.3)
        self.assertEqual(empty["games"], 0)
        self.assertEqual(empty["buckets"], [])


class TestSimulation(unittest.TestCase):
    RUNS = 2000

    def setUp(self):
        self.division = built_division()
        self.chelsea = next(
            t for t in self.division["teams"]
            if t["league_team_id"] == CHELSEA_LEAGUE_TEAM_ID
        )
        self.fixtures = self.division["upcoming"] + self.division["postponed"]
        self.massey = {t["id"]: t["rating"] for t in self.division["teams"]}
        self.weights = projections.floor_goal_weights([self.division])
        self.sim = self.simulate()

    def simulate(self, seed=projections.SIM_SEED):
        return projections.simulate_season(
            self.division, self.fixtures, self.massey, 2.3, self.weights,
            runs=self.RUNS, seed=seed, focus_id=self.chelsea["id"],
        )

    def test_the_same_seed_gives_the_same_season(self):
        # A refresh that finds no new results must not reshuffle the odds.
        self.assertEqual(self.simulate()["focus"], self.sim["focus"])

    def test_a_different_seed_gives_a_different_season(self):
        self.assertNotEqual(self.simulate(seed=projections.SIM_SEED + 1)["focus"],
                            self.sim["focus"])

    def test_every_team_finishes_somewhere(self):
        for team in self.sim["teams"]:
            with self.subTest(team=team["id"]):
                self.assertEqual(len(team["finish"]), len(self.division["teams"]))
                self.assertAlmostEqual(sum(team["finish"]), 1.0, places=2)

    def test_each_position_is_taken_by_exactly_one_team(self):
        for position in range(len(self.division["teams"])):
            total = sum(t["finish"][position] for t in self.sim["teams"])
            self.assertAlmostEqual(total, 1.0, places=2)

    def test_projected_points_stay_inside_what_is_left_to_play(self):
        for team in self.sim["teams"]:
            row = next(t for t in self.division["teams"] if t["id"] == team["id"])
            left = sum(1 for f in self.fixtures
                       if team["id"] in (f["home_id"], f["away_id"]))
            with self.subTest(team=row["short"]):
                self.assertGreaterEqual(team["mean_points"], row["record"]["pts"])
                self.assertLessEqual(team["mean_points"],
                                     row["record"]["pts"] + 3 * left)

    def test_the_focus_team_cannot_score_points_it_has_no_games_for(self):
        left = len(build_featured(built_payload())["remaining"])
        now = self.chelsea["record"]["pts"]
        for points, _ in self.sim["focus"]["points"]["distribution"]:
            self.assertGreaterEqual(points, now)
            self.assertLessEqual(points, now + 3 * left)

    def test_winning_is_never_worse_than_losing(self):
        for entry in self.sim["leverage"]:
            with self.subTest(opponent=entry["opponent_id"]):
                self.assertGreaterEqual(entry["W"]["first"], entry["D"]["first"])
                self.assertGreaterEqual(entry["D"]["first"], entry["L"]["first"])
                self.assertLess(entry["W"]["mean_finish"], entry["L"]["mean_finish"])

    def test_the_three_results_account_for_every_run(self):
        for entry in self.sim["leverage"]:
            total = entry["W"]["share"] + entry["D"]["share"] + entry["L"]["share"]
            self.assertAlmostEqual(total, 1.0, places=2)

    def test_the_champion_always_has_enough_points_to_be_the_champion(self):
        best_possible = max(
            t["record"]["pts"] + 3 * sum(
                1 for f in self.fixtures if t["id"] in (f["home_id"], f["away_id"]))
            for t in self.division["teams"]
        )
        for points, _ in self.sim["champion_points"]["distribution"]:
            self.assertLessEqual(points, best_possible)

    def test_a_sweep_is_at_least_as_good_as_the_average_season(self):
        sweep = self.sim["focus"]["sweep"]
        if sweep["first"] is not None:
            self.assertGreaterEqual(sweep["first"], self.sim["focus"]["first"])
            self.assertGreaterEqual(sweep["top3"], self.sim["focus"]["top3"])

    def test_nothing_left_to_play_means_nothing_left_to_decide(self):
        finished = projections.simulate_season(
            self.division, [], self.massey, 2.3, self.weights,
            runs=50, focus_id=self.chelsea["id"],
        )
        for team in finished["teams"]:
            row = next(t for t in self.division["teams"] if t["id"] == team["id"])
            self.assertEqual(team["mean_points"], row["record"]["pts"])
            self.assertEqual(max(team["finish"]), 1.0)


class TestFloorGoals(unittest.TestCase):
    def test_weights_are_a_distribution_over_capped_goals(self):
        weights = projections.floor_goal_weights([built_division()])
        self.assertAlmostEqual(sum(w for _, w in weights), 1.0, places=9)
        for goals, _ in weights:
            self.assertGreaterEqual(goals, 0)
            self.assertLessEqual(goals, ratings.GOAL_CAP)

    def test_no_games_still_gives_something_to_sample(self):
        weights = projections.floor_goal_weights([])
        self.assertAlmostEqual(sum(w for _, w in weights), 1.0, places=9)


if __name__ == "__main__":
    unittest.main(verbosity=2)
