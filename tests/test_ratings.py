"""Tests for the rating math.

The headline test replays a real division and checks that our tally of the
results reproduces the league's own published standings, row for row. That is
what proves the two goal caps are being applied the way the league applies
them -- goals capped at 4 for GF/GA, margin capped at 4 for GD.
"""
import json
import pathlib
import sys
import unittest

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1] / "scripts"))

import ratings  # noqa: E402
from build import build_division, extract_games, extract_teams  # noqa: E402

FIXTURE = pathlib.Path(__file__).parent / "fixtures" / "division_19780.json"


def load_fixture():
    return json.loads(FIXTURE.read_text())


class TestSolve(unittest.TestCase):
    def test_solves_known_system(self):
        # 2x + y = 5 ; x + 3y = 10  ->  x = 1, y = 3
        x = ratings.solve([[2.0, 1.0], [1.0, 3.0]], [5.0, 10.0])
        self.assertAlmostEqual(x[0], 1.0, places=9)
        self.assertAlmostEqual(x[1], 3.0, places=9)

    def test_rejects_singular_matrix(self):
        with self.assertRaises(ValueError):
            ratings.solve([[1.0, 2.0], [2.0, 4.0]], [1.0, 2.0])


class TestAgainstOfficialStandings(unittest.TestCase):
    """Our recomputed table must match what PlayMetrics publishes."""

    def setUp(self):
        self.data = load_fixture()
        self.teams = extract_teams(self.data)
        self.games = [g for g in extract_games(self.data) if g["counts"]]
        self.rec = ratings.tally_records([t["id"] for t in self.teams], self.games)

    def test_counts_only_completed_games(self):
        # 15 played; the 3 "Rescheduled" rows carry a placeholder 0-0 and must
        # not be counted as real draws.
        self.assertEqual(len(self.games), 15)

    def test_matches_published_standings_row_for_row(self):
        official = {
            row["team_id"]: row
            for group in self.data["standings"]["groups"]
            for row in group["team_standings"]
        }
        self.assertEqual(len(official), 10)
        for team_id, row in official.items():
            with self.subTest(team=team_id):
                mine = self.rec[team_id]
                self.assertEqual(mine["gp"], row["GP"])
                self.assertEqual(mine["w"], row["W"])
                self.assertEqual(mine["l"], row["L"])
                self.assertEqual(mine["t"], row["T"])
                self.assertEqual(mine["gf"], row["GF"])
                self.assertEqual(mine["ga"], row["GA"])
                self.assertEqual(mine["gd"], row["GD"])
                self.assertEqual(mine["pts"], row["PTS"])

    def test_goal_and_margin_caps_are_independent(self):
        # WF United Gold lost 0-4, 2-6 and 0-4. Goals-against caps to 12, but
        # the margin cap makes the differential -12, not the -10 that
        # capped-GF minus capped-GA would give.
        gold = next(t["id"] for t in self.teams if "Gold" in t["name"])
        self.assertEqual(self.rec[gold]["ga"], 12)
        self.assertEqual(self.rec[gold]["gf"], 2)
        self.assertEqual(self.rec[gold]["gd"], -12)


class TestRatingProperties(unittest.TestCase):
    def setUp(self):
        data = load_fixture()
        self.team_ids = [t["id"] for t in extract_teams(data)]
        self.games = extract_games(data)
        self.result = ratings.rank_teams(self.team_ids, self.games)

    def test_colley_centers_on_half(self):
        vals = list(self.result["colley"].values())
        self.assertAlmostEqual(sum(vals) / len(vals), 0.5, places=6)

    def test_massey_centers_on_zero(self):
        self.assertAlmostEqual(sum(self.result["massey"].values()), 0.0, places=6)

    def test_every_team_ranked_exactly_once(self):
        self.assertEqual(sorted(self.result["power_rank"].values()), list(range(1, 11)))

    def test_scores_stay_in_range(self):
        for score in self.result["power_score"].values():
            self.assertGreaterEqual(score, 0.0)
            self.assertLessEqual(score, 100.0)


class TestScheduleStrengthActuallyMatters(unittest.TestCase):
    """The point of the whole exercise: identical records, different opponents.

    Two unbeaten teams, A and D. A beats the two strongest other teams; D beats
    the two weakest. A must come out ahead.
    """

    def build(self):
        # B and C are strong (they beat E and F); E and F are weak.
        def game(h, a, hs, a_s):
            return {
                "home_id": h, "away_id": a, "home_score": hs, "away_score": a_s,
                "counts": True,
            }

        teams = ["A", "B", "C", "D", "E", "F"]
        games = [
            game("A", "B", 2, 1),   # A beats a strong team
            game("A", "C", 2, 1),   # A beats a strong team
            game("D", "E", 2, 1),   # D beats a weak team
            game("D", "F", 2, 1),   # D beats a weak team
            game("B", "E", 3, 0),   # B looks strong
            game("C", "F", 3, 0),   # C looks strong
            game("E", "F", 1, 1),   # E and F stay weak
        ]
        return teams, games

    def test_harder_schedule_outranks_easier_one(self):
        teams, games = self.build()
        result = ratings.rank_teams(teams, games)
        self.assertLess(
            result["power_rank"]["A"],
            result["power_rank"]["D"],
            "team that beat the stronger opponents should rank higher",
        )

    def test_strength_of_schedule_reflects_opponents_faced(self):
        teams, games = self.build()
        result = ratings.rank_teams(teams, games)
        self.assertGreater(result["sos"]["A"], result["sos"]["D"])

    def test_margin_is_capped(self):
        # A 9-0 result must be worth no more than a 4-0 result.
        teams = ["A", "B", "C"]
        blowout = [
            {"home_id": "A", "away_id": "B", "home_score": 9, "away_score": 0, "counts": True},
            {"home_id": "B", "away_id": "C", "home_score": 1, "away_score": 1, "counts": True},
        ]
        capped = [
            {"home_id": "A", "away_id": "B", "home_score": 4, "away_score": 0, "counts": True},
            {"home_id": "B", "away_id": "C", "home_score": 1, "away_score": 1, "counts": True},
        ]
        a = ratings.rank_teams(teams, blowout)["massey"]["A"]
        b = ratings.rank_teams(teams, capped)["massey"]["A"]
        self.assertAlmostEqual(a, b, places=9)


class TestPostedLine(unittest.TestCase):
    """Projected margins go up on the half goal, the way a line is posted."""

    def test_rounds_to_the_nearest_half_goal(self):
        cases = {
            0.0: 0.0,
            0.1: 0.0,
            0.24: 0.0,
            0.3: 0.5,
            0.7: 0.5,
            1.28: 1.5,
            1.7: 1.5,
            2.2: 2.0,
            3.99: 4.0,
        }
        for margin, expected in cases.items():
            self.assertEqual(ratings.to_line(margin), expected, f"margin {margin}")

    def test_halves_round_up(self):
        # Exactly between two lines, take the longer one.
        self.assertEqual(ratings.to_line(0.25), 0.5)
        self.assertEqual(ratings.to_line(0.75), 1.0)
        self.assertEqual(ratings.to_line(1.25), 1.5)

    def test_sign_is_preserved(self):
        # A negative margin means the away team, and stays negative.
        self.assertEqual(ratings.to_line(-1.28), -1.5)
        self.assertEqual(ratings.to_line(-2.2), -2.0)
        self.assertEqual(ratings.to_line(-0.1), 0.0)

    def test_every_line_is_a_multiple_of_the_step(self):
        for tenth in range(-60, 61):
            line = ratings.to_line(tenth / 10)
            self.assertAlmostEqual(
                line / ratings.MARGIN_STEP,
                round(line / ratings.MARGIN_STEP),
                places=9,
                msg=f"margin {tenth / 10} produced {line}",
            )

    def test_already_posted_lines_do_not_move(self):
        for line in (0.0, 0.5, 1.0, 1.5, 2.0, 2.5, 3.0, -1.5, -3.0):
            self.assertEqual(ratings.to_line(line), line)


class TestUpcomingFixtures(unittest.TestCase):
    """The lines that reach the page are the posted ones, not raw projections."""

    def test_every_projected_margin_is_a_posted_line(self):
        raw = load_fixture()
        div = build_division({"id": raw["id"], "name": raw["name"]}, raw)
        self.assertTrue(div["upcoming"], "fixture should have unplayed games")
        for f in div["upcoming"]:
            line = f["margin"]
            self.assertGreaterEqual(line, 0.0)
            self.assertAlmostEqual(
                line / ratings.MARGIN_STEP,
                round(line / ratings.MARGIN_STEP),
                places=9,
                msg=f"{f['home']} v {f['away']} posted {line}",
            )


class TestEmptyDivision(unittest.TestCase):
    def test_no_games_played_is_not_an_error(self):
        teams = ["A", "B", "C"]
        result = ratings.rank_teams(teams, [])
        for score in result["power_score"].values():
            self.assertAlmostEqual(score, 50.0, places=6)


if __name__ == "__main__":
    unittest.main(verbosity=2)
