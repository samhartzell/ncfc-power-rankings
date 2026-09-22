"""Tests for the schedule detail and the team report built on top of it.

The team page makes two promises the league page does not: that every game
still owed is listed, and that the details beside it -- kickoff time, field,
home or away -- came from the league rather than from somewhere convenient.
These checks hold the pipeline to both.
"""
import json
import pathlib
import sys
import unittest

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1] / "scripts"))

import projections  # noqa: E402
import ratings  # noqa: E402
from build import build_division, build_featured, extract_games, extract_teams  # noqa: E402

FIXTURE = pathlib.Path(__file__).parent / "fixtures" / "division_19780.json"
CHELSEA_LEAGUE_TEAM_ID = 64255


def load_fixture():
    return json.loads(FIXTURE.read_text())


def built_division():
    raw = load_fixture()
    return build_division({"id": raw["id"], "name": raw["name"]}, raw)


class TestScheduleDetail(unittest.TestCase):
    def setUp(self):
        self.raw = load_fixture()
        self.games = extract_games(self.raw)

    def test_kickoff_detail_comes_through_unchanged(self):
        opener = self.games[0]
        source = min(self.raw["schedule"], key=lambda g: g["start_datetime"])
        self.assertEqual(opener["time"], source["time"])
        self.assertEqual(opener["field"], source["field"]["name"])
        self.assertEqual(opener["address"], source["field"]["address"])

    def test_the_weekday_is_read_off_the_league_s_own_date(self):
        for game in self.games:
            source = next(g for g in self.raw["schedule"] if g["id"] == game["id"])
            with self.subTest(game=game["id"]):
                self.assertTrue(source["date"].startswith(game["day"]))
                self.assertNotIn(",", game["day"])

    def test_a_game_with_no_field_yet_does_not_break_the_build(self):
        raw = load_fixture()
        for entry in raw["schedule"]:
            entry["field"] = None
        division = build_division({"id": raw["id"], "name": raw["name"]}, raw)
        for fixture in division["upcoming"]:
            self.assertEqual(fixture["field"], "")
            self.assertEqual(fixture["address"], "")


class TestRescheduledGamesKeepTheirNewDate(unittest.TestCase):
    """The league moves a game by rewriting its row, not by emptying it.

    A "Rescheduled" row arrives with a new date, time, field and round label
    already on it, so the flag says the fixture moved -- not that nobody knows
    when it is.
    """

    def setUp(self):
        self.raw = load_fixture()
        self.division = built_division()

    def test_every_scheduled_game_lands_in_exactly_one_list(self):
        played = self.division["games_played"]
        upcoming = len(self.division["upcoming"])
        self.assertEqual(played + upcoming, len(self.raw["schedule"]))
        self.assertEqual(self.division["games_total"], len(self.raw["schedule"]))

    def test_the_rescheduled_games_are_flagged_as_moved(self):
        expected = sum(1 for g in self.raw["schedule"] if g["status"] == "Rescheduled")
        self.assertEqual(expected, 3)
        self.assertEqual(self.division["games_moved"], expected)
        self.assertEqual(sum(1 for f in self.division["upcoming"] if f["moved"]), expected)

    def test_a_rescheduled_game_carries_the_date_the_league_posted(self):
        by_pair = {(g["home_team_id"], g["away_team_id"]): g for g in self.raw["schedule"]}
        moved = [f for f in self.division["upcoming"] if f["moved"]]
        self.assertTrue(moved)
        for fixture in moved:
            source = by_pair[(fixture["home_id"], fixture["away_id"])]
            with self.subTest(pair=(fixture["home_id"], fixture["away_id"])):
                self.assertEqual(fixture["date"], source["date_short"])
                self.assertEqual(fixture["time"], source["time"])
                self.assertEqual(fixture["field"], source["field"]["name"])

    def test_the_fixture_list_stays_in_kickoff_order(self):
        starts = [
            next(g["start_datetime"] for g in self.raw["schedule"]
                 if (g["home_team_id"], g["away_team_id"]) == (f["home_id"], f["away_id"]))
            for f in self.division["upcoming"]
        ]
        self.assertEqual(starts, sorted(starts))

    def test_rescheduled_games_stay_out_of_the_played_count(self):
        # They carry a placeholder 0-0, so counting them would invent draws.
        self.assertEqual(
            self.division["games_played"],
            sum(1 for g in extract_games(self.raw) if g["counts"]),
        )


class TestTeamReport(unittest.TestCase):
    # Built once: the report runs a full season simulation, and rebuilding it
    # per test would turn a fast suite into a slow one for no extra coverage.
    @classmethod
    def setUpClass(cls):
        cls.raw = load_fixture()
        cls.division = built_division()
        cls.payload = {
            "league": "Test",
            "featured_division": cls.division["id"],
            "featured_team": CHELSEA_LEAGUE_TEAM_ID,
            "divisions": [cls.division],
        }
        cls.featured = build_featured(cls.payload)
        cls.team = next(
            t for t in cls.division["teams"]
            if t["league_team_id"] == CHELSEA_LEAGUE_TEAM_ID
        )

    def schedule_rows(self):
        """Every row of the league's own schedule involving the featured team."""
        known = {t["id"] for t in extract_teams(self.raw)}
        return [
            g for g in self.raw["schedule"]
            if self.team["id"] in (g.get("home_team_id"), g.get("away_team_id"))
            and g.get("home_team_id") in known and g.get("away_team_id") in known
        ]

    def test_the_whole_season_is_accounted_for(self):
        rows = self.schedule_rows()
        self.assertEqual(len(self.featured["played"]) + len(self.featured["remaining"]),
                         len(rows))

    def test_every_unplayed_game_is_listed(self):
        owed = {
            g["id"] for g in self.schedule_rows()
            if g["status"] != "Played"
        }
        self.assertEqual(len(self.featured["remaining"]), len(owed))

    def test_the_rescheduled_game_is_flagged_and_sorted_by_its_new_date(self):
        moved = [f for f in self.featured["remaining"] if f["moved"]]
        self.assertEqual(len(moved), 1)
        # Chelsea's Round 5 game was pushed to Saturday, October 3, which puts
        # it ahead of the Round 6 fixture the rest of the division plays --
        # where the old "listed last" rule buried it.
        self.assertEqual(moved[0]["date"], "Oct  3, 2026")
        self.assertEqual(moved[0]["time"], "11:30 AM")
        after = self.featured["remaining"][self.featured["remaining"].index(moved[0]) + 1]
        self.assertEqual(after["date"], "Oct  4, 2026")
        self.assertIsNot(self.featured["remaining"][-1], moved[0])

    def test_home_and_away_match_the_schedule(self):
        by_opponent = {}
        for row in self.schedule_rows():
            if row["status"] == "Played":
                continue
            at_home = row["home_team_id"] == self.team["id"]
            opponent = row["away_team_id"] if at_home else row["home_team_id"]
            by_opponent[opponent] = at_home
        for fixture in self.featured["remaining"]:
            with self.subTest(opponent=fixture["opponent_id"]):
                self.assertEqual(fixture["home"], by_opponent[fixture["opponent_id"]])

    def test_a_relabelled_round_is_not_reported_as_a_bye(self):
        # The moved game took Round 6's label, leaving Round 5 empty and Round
        # 6 doubled. Chelsea plays all eight games, so it has no free weekend.
        rounds = [g["round"] for g in self.featured["played"]]
        rounds += [f["round"] for f in self.featured["remaining"]]
        self.assertNotIn("Round 5", rounds)
        self.assertEqual(rounds.count("Round 6"), 2)
        self.assertEqual(self.featured["byes"], [])

    def test_every_fixture_carries_a_full_set_of_odds(self):
        for fixture in self.featured["remaining"]:
            with self.subTest(opponent=fixture["opponent_id"]):
                total = fixture["win"] + fixture["draw"] + fixture["loss"]
                self.assertAlmostEqual(total, 1.0, places=3)
                self.assertAlmostEqual(sum(p for _, p in fixture["margins"]), 1.0, places=3)

    def test_the_line_is_the_projection_posted_on_the_half_goal(self):
        for fixture in self.featured["remaining"]:
            with self.subTest(opponent=fixture["opponent_id"]):
                self.assertEqual(fixture["line"], ratings.to_line(fixture["raw_margin"]))

    def test_the_favourite_is_the_side_the_odds_favour(self):
        for fixture in self.featured["remaining"]:
            with self.subTest(opponent=fixture["opponent_id"]):
                if fixture["raw_margin"] > 0:
                    self.assertGreater(fixture["win"], fixture["loss"])
                elif fixture["raw_margin"] < 0:
                    self.assertLess(fixture["win"], fixture["loss"])

    def test_results_are_judged_against_a_projection_that_never_saw_them(self):
        replayed, expected = projections.loo_expected(self.division)
        by_pair = {(g["home_id"], g["away_id"]): mu
                   for g, mu in zip(replayed, expected)}
        for game in self.featured["played"]:
            pair = ((self.team["id"], game["opponent_id"]) if game["home"]
                    else (game["opponent_id"], self.team["id"]))
            mu = by_pair[pair]
            if not game["home"]:
                mu = -mu
            with self.subTest(opponent=game["opponent_id"]):
                self.assertAlmostEqual(game["expected"], round(mu, 2), places=9)
                actual = max(-ratings.MARGIN_CAP,
                             min(ratings.MARGIN_CAP, game["gf"] - game["ga"]))
                self.assertAlmostEqual(game["edge"], round(actual - mu, 2), places=9)

    def test_the_simulation_covers_the_whole_division_not_just_this_team(self):
        self.assertEqual(
            self.featured["sim"]["fixtures"], len(self.division["upcoming"])
        )
        self.assertEqual(len(self.featured["sim"]["teams"]), len(self.division["teams"]))

    def test_every_game_left_carries_what_each_result_would_cost(self):
        self.assertNotIn("leverage", self.featured["sim"])  # merged into the fixtures
        for fixture in self.featured["remaining"]:
            with self.subTest(opponent=fixture["opponent_id"]):
                swing = fixture["swing"]
                self.assertEqual(set(swing), {"W", "D", "L"})
                self.assertAlmostEqual(
                    sum(swing[r]["share"] for r in ("W", "D", "L")), 1.0, places=2)
                self.assertGreaterEqual(swing["W"]["first"], swing["L"]["first"])

    def test_remaining_strength_of_schedule_is_the_opponents_actually_left(self):
        by_id = {t["id"]: t for t in self.division["teams"]}
        scores = [by_id[f["opponent_id"]]["power_score"] for f in self.featured["remaining"]]
        self.assertAlmostEqual(self.featured["remaining_sos"],
                               round(sum(scores) / len(scores), 1), places=9)

    def test_a_team_that_is_not_in_the_league_gets_no_report(self):
        payload = dict(self.payload, featured_team=-1)
        self.assertIsNone(build_featured(payload))
        payload = dict(self.payload, featured_division=-1)
        self.assertIsNone(build_featured(payload))


if __name__ == "__main__":
    unittest.main(verbosity=2)
