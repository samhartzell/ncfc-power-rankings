"""Tests for the name parsing and the crests.

The point of these is that the page never has to guess: every team in the
league resolves to a crest with usable colors, and the teams named for a real
club get that club's.
"""
import json
import pathlib
import re
import sys
import unittest

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1] / "scripts"))

import clubs  # noqa: E402

DATA = pathlib.Path(__file__).resolve().parents[1] / "data" / "rankings.json"
HEX = re.compile(r"^#[0-9A-Fa-f]{6}$")
PATTERNS = {
    "solid", "stripes", "hoops", "halves",
    "diagonal", "sash", "sleeves", "cross", "band",
}


class TestParse(unittest.TestCase):
    def test_strips_age_group_and_host_club(self):
        parsed = clubs.parse("U11 (15) NCFCY Chelsea")
        self.assertEqual(parsed["display"], "Chelsea")
        self.assertEqual(parsed["org"], "NCFC")
        self.assertTrue(parsed["host"])
        self.assertFalse(parsed["girls"])
        self.assertEqual(parsed["site"], "")

    def test_keeps_other_clubs_as_a_tag(self):
        parsed = clubs.parse("U10 (16) TYSC Finley United")
        self.assertEqual(parsed["display"], "Finley United")
        self.assertEqual(parsed["org"], "TYSC")
        self.assertFalse(parsed["host"])

    def test_pulls_out_site_code_and_girls_marker(self):
        parsed = clubs.parse("U13 (13) NCFC Rowdies DCH")
        self.assertEqual(parsed["display"], "Rowdies")
        self.assertEqual(parsed["site"], "DCH")

        parsed = clubs.parse("U12 (14) NCFCY Royals HSFV G")
        self.assertEqual(parsed["display"], "Royals")
        self.assertEqual(parsed["site"], "HSFV")
        self.assertTrue(parsed["girls"])

    def test_drops_a_trailing_fc_so_divisions_read_alike(self):
        # 'Arsenal FC' in one division and 'Arsenal' in another are the same name.
        self.assertEqual(clubs.parse("U11 (15) NCFCY Arsenal FC")["display"], "Arsenal")
        self.assertEqual(clubs.parse("U11 (15) NCFCY Arsenal")["display"], "Arsenal")

    def test_leaves_an_unrecognized_shape_alone(self):
        self.assertEqual(clubs.parse("Some Other Team")["display"], "Some Other Team")


class TestMonogram(unittest.TestCase):
    def test_one_word_takes_three_letters(self):
        self.assertEqual(clubs.monogram("Predators"), "PRE")

    def test_two_words_keep_the_second_readable(self):
        self.assertEqual(clubs.monogram("Red Dragons"), "RDR")
        self.assertEqual(clubs.monogram("Finley United"), "FUN")

    def test_three_or_more_words_use_initials(self):
        self.assertEqual(clubs.monogram("WF United Black"), "WUB")


class TestIdentity(unittest.TestCase):
    def test_a_real_club_brings_its_own_colors(self):
        chelsea = clubs.identity("Chelsea")
        self.assertTrue(chelsea["real"])
        self.assertEqual(chelsea["club"], "Chelsea")
        self.assertEqual(chelsea["comp"], "Premier League")
        self.assertEqual(chelsea["colors"][0], "#034694")

    def test_an_alias_resolves(self):
        self.assertEqual(clubs.identity("City")["club"], "Manchester City")
        self.assertEqual(clubs.identity("Villa")["club"], "Aston Villa")

    def test_a_color_in_the_name_becomes_the_kit(self):
        kit = clubs.identity("WF United Red")
        self.assertFalse(kit["real"])
        self.assertEqual(kit["source"], "name")
        self.assertEqual(kit["colors"][0], clubs.COLOR_WORDS["red"][0])

    def test_everything_else_still_gets_a_crest(self):
        kit = clubs.identity("Predators")
        self.assertFalse(kit["real"])
        self.assertIsNone(kit["club"])
        self.assertTrue(HEX.match(kit["colors"][0]))

    def test_the_same_name_always_gets_the_same_crest(self):
        self.assertEqual(clubs.identity("Zephyr"), clubs.identity("Zephyr"))

    def test_every_club_entry_is_well_formed(self):
        for key, entry in clubs.CLUBS.items():
            with self.subTest(club=key):
                self.assertIn(entry["pattern"], PATTERNS)
                self.assertEqual(len(entry["colors"]), 3)
                for color in entry["colors"]:
                    self.assertTrue(HEX.match(color), f"{key}: {color}")
                self.assertTrue(entry["code"].isupper())
                self.assertLessEqual(len(entry["code"]), 4)

    def test_every_alias_points_somewhere(self):
        for alias, key in clubs.ALIASES.items():
            with self.subTest(alias=alias):
                self.assertIn(key, clubs.CLUBS)


class TestAccents(unittest.TestCase):
    """The accent is what the page draws with, so it has to be visible on both
    backgrounds -- a white club cannot be drawn in white."""

    def assertReadable(self, colors):
        accent = clubs.accents(colors)
        # roughly 3:1 against the page behind it, in either theme
        self.assertLess(clubs._luminance(accent["light"]), 0.36)
        self.assertGreater(clubs._luminance(accent["dark"]), 0.24)

    def test_a_white_club_borrows_its_second_color(self):
        accent = clubs.accents(["#FFFFFF", "#00529F", "#FEBE10"])  # Real Madrid
        self.assertNotEqual(accent["light"], "#FFFFFF")
        self.assertReadable(["#FFFFFF", "#00529F", "#FEBE10"])

    def test_a_bright_but_saturated_club_keeps_its_color(self):
        # Dortmund yellow is the identity; it is darkened, not swapped out.
        accent = clubs.accents(["#FDE100", "#000000", "#000000"])
        r, g, b = clubs._rgb(accent["light"])
        self.assertGreater(r + g, 2 * b)

    def test_black_and_white_clubs_read_as_grey(self):
        accent = clubs.accents(["#241F20", "#FFFFFF", "#41B6E6"])  # Newcastle
        r, g, b = clubs._rgb(accent["light"])
        self.assertAlmostEqual(r, g, places=2)
        self.assertAlmostEqual(g, b, places=2)

    def test_every_club_accent_is_readable(self):
        for key, entry in clubs.CLUBS.items():
            with self.subTest(club=key):
                self.assertReadable(entry["colors"])


class TestSpreadPalette(unittest.TestCase):
    def test_invented_kits_in_one_division_do_not_collide(self):
        teams = [
            {"name": f"U12 (14) NCFCY Team{i}", **clubs.describe(f"U12 (14) NCFCY Team{i}")}
            for i in range(6)
        ]
        clubs.spread_palette(teams)
        primaries = [t["identity"]["colors"][0] for t in teams]
        self.assertEqual(len(primaries), len(set(primaries)))

    def test_a_real_club_is_never_moved(self):
        names = ["U11 (15) NCFCY Chelsea", "U11 (15) NCFCY Predators"]
        teams = [{"name": n, **clubs.describe(n)} for n in names]
        clubs.spread_palette(teams)
        self.assertEqual(teams[0]["identity"]["colors"][0], "#034694")


class TestAgainstTheLeague(unittest.TestCase):
    """Every team actually in the league has to come out the other side with a
    crest the page can draw."""

    @classmethod
    def setUpClass(cls):
        cls.payload = clubs.decorate(json.loads(DATA.read_text()))

    def test_every_team_has_a_drawable_crest(self):
        for division in self.payload["divisions"]:
            for team in division["teams"]:
                with self.subTest(team=team["name"]):
                    crest = team["identity"]
                    self.assertIn(crest["pattern"], PATTERNS)
                    self.assertEqual(len(crest["colors"]), 3)
                    for color in crest["colors"]:
                        self.assertTrue(HEX.match(color))
                    self.assertTrue(crest["code"])
                    self.assertTrue(HEX.match(crest["accent"]["light"]))
                    self.assertTrue(HEX.match(crest["accent"]["dark"]))

    def test_no_two_teams_in_a_division_share_a_name(self):
        for division in self.payload["divisions"]:
            labels = [
                (t["short"], t["org"], t["site"]) for t in division["teams"]
            ]
            with self.subTest(division=division["name"]):
                self.assertEqual(len(labels), len(set(labels)))

    def test_most_of_the_league_is_named_for_a_real_club(self):
        teams = [t for d in self.payload["divisions"] for t in d["teams"]]
        real = [t for t in teams if t["identity"]["real"]]
        self.assertGreater(len(real), len(teams) // 2)

    def test_opponent_names_match_the_team_names(self):
        for division in self.payload["divisions"]:
            names = {t["id"]: t["short"] for t in division["teams"]}
            for team in division["teams"]:
                for game in team["resume"]:
                    with self.subTest(team=team["name"]):
                        self.assertEqual(game["opponent"], names[game["opponent_id"]])


if __name__ == "__main__":
    unittest.main()
