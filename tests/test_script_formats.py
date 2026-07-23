import os
import sys
import unittest


sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "tools"))

from contracts import SAVE_THE_CAT_BEATS  # noqa: E402
from script import finalize, validate_script  # noqa: E402


class ScriptFormatTests(unittest.TestCase):
    def save_the_cat_draft(self):
        groups = [
            SAVE_THE_CAT_BEATS[0:3],
            SAVE_THE_CAT_BEATS[3:6],
            SAVE_THE_CAT_BEATS[6:9],
            SAVE_THE_CAT_BEATS[9:11],
            SAVE_THE_CAT_BEATS[11:13],
            SAVE_THE_CAT_BEATS[13:15],
        ]
        return {
            "shots": [
                {
                    "n": index,
                    "kind": "clip",
                    "src": "product.mp4",
                    "inSec": (index - 1) * 5,
                    "durSec": 5,
                    "sourceType": "product",
                    "liveState": True,
                    "storyBeats": list(beats),
                }
                for index, beats in enumerate(groups, 1)
            ]
        }

    def test_save_the_cat_draft_accepts_complete_ordered_beats(self):
        errors = validate_script(self.save_the_cat_draft(), {"product.mp4"}, 30, "save-the-cat")
        self.assertEqual([], errors)

    def test_save_the_cat_draft_rejects_a_missing_midpoint(self):
        draft = self.save_the_cat_draft()
        draft["shots"][2]["storyBeats"].remove("midpoint")
        errors = validate_script(draft, {"product.mp4"}, 30, "save-the-cat")
        self.assertTrue(any("midpoint" in error for error in errors))

    def test_save_the_cat_rejects_fifteen_title_cards(self):
        draft = {
            "shots": [
                {"n": index, "kind": "title", "title": beat, "durSec": 2, "storyBeat": beat}
                for index, beat in enumerate(SAVE_THE_CAT_BEATS, 1)
            ]
        }
        errors = validate_script(draft, set(), 30, "save-the-cat")
        self.assertTrue(any("cards exceed" in error for error in errors))

    def test_save_the_cat_rejects_string_story_beats(self):
        draft = self.save_the_cat_draft()
        draft["shots"][0]["storyBeats"] = "opening-image"
        errors = validate_script(draft, {"product.mp4"}, 30, "save-the-cat")
        self.assertTrue(any("must be an array" in error for error in errors))

    def test_finalize_merges_required_defaults_into_partial_production(self):
        draft = self.save_the_cat_draft()
        draft["production"] = {"profile": "sales"}
        finalized = finalize(draft, "save-the-cat", 30, {})
        self.assertEqual("sales", finalized["production"]["profile"])
        self.assertEqual("save-the-cat", finalized["production"]["storyFramework"])
        self.assertTrue(finalized["production"]["requireLiveProgression"])

    def test_launch_film_rejects_split_screen(self):
        draft = self.save_the_cat_draft()
        draft["shots"][0] = {
            "n": 1, "kind": "split", "srcL": "product.mp4", "srcR": "product.mp4",
            "durSec": 5, "storyBeats": list(SAVE_THE_CAT_BEATS[0:3]),
        }
        errors = validate_script(draft, {"product.mp4"}, 30, "launch-film")
        self.assertTrue(any("split-screen" in error for error in errors))

    def test_launch_film_defaults_to_announcement_single_focus(self):
        finalized = finalize(self.save_the_cat_draft(), "launch-film", 60, {})
        production = finalized["production"]
        self.assertEqual(production["profile"], "announcement")
        self.assertTrue(production["singleFocus"])
        self.assertTrue(production["requireContinuityIds"])
        self.assertEqual(production["storyFramework"], "save-the-cat")


if __name__ == "__main__":
    unittest.main()
