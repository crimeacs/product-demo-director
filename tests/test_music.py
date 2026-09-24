import os
import sys
import unittest


sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "tools"))

from music import MUSIC_MODEL, _last_trailing_silence, _silent_gaps, composition_plan, timed_prompt  # noqa: E402


class MusicTailTests(unittest.TestCase):
    def test_detects_trailing_silence(self):
        log = "silence_start: 59.75\nsilence_end: 62.50 | silence_duration: 2.75"
        self.assertEqual(59.75, _last_trailing_silence(log, 62.5))

    def test_ignores_internal_and_tiny_tail_silence(self):
        internal = "silence_start: 12\nsilence_end: 14 | silence_duration: 2"
        tiny = "silence_start: 62.0\nsilence_end: 62.5 | silence_duration: 0.5"
        self.assertIsNone(_last_trailing_silence(internal, 62.5))
        self.assertIsNone(_last_trailing_silence(tiny, 62.5))


class SilentBedTests(unittest.TestCase):
    def test_leading_silence_is_a_gap(self):
        log = "silence_start: -0.01\nsilence_end: 14.9 | silence_duration: 14.9"
        self.assertEqual([(0.0, 14.9)], _silent_gaps(log))

    def test_short_breaths_are_not_gaps(self):
        self.assertEqual([], _silent_gaps("silence_start: 20\nsilence_end: 21.2 | silence_duration: 1.2"))


class CompositionPlanTests(unittest.TestCase):
    def test_no_sections_keeps_prompt_mode(self):
        self.assertIsNone(composition_plan({"music": "calm pulse"}, 60))

    def test_sections_land_on_cut_times_and_fill_runtime(self):
        script = {"music": "minimal electronic pulse, warm synth",
                  "musicSections": [{"name": "hook", "styles": ["sparse"], "untilSec": 5.6},
                                    {"name": "product", "styles": ["driving"], "untilSec": 24.6},
                                    {"name": "close", "styles": ["resolve"]}]}
        plan = composition_plan(script, 62.5, "music_v2")
        durations = [c["duration_ms"] for c in plan["chunks"]]
        self.assertEqual([5600, 19000, 37900], durations)
        self.assertEqual(62500, sum(durations))
        self.assertTrue(all("vocals" in c["negative_styles"] for c in plan["chunks"]))
        self.assertIn("driving", plan["chunks"][1]["positive_styles"])
        legacy = composition_plan(script, 62.5, "music_v1")
        self.assertEqual(durations, [s["duration_ms"] for s in legacy["sections"]])
        self.assertTrue(all(s["lines"] == [] for s in legacy["sections"]))

    def test_sections_respect_provider_minimum(self):
        plan = composition_plan({"musicSections": [{"name": "blip", "untilSec": 1}, {"name": "rest"}]}, 30)
        self.assertEqual(3000, plan["chunks"][0]["duration_ms"])

    def test_timed_prompt_names_every_section_with_times(self):
        script = {"musicSections": [{"name": "hook", "styles": ["sparse"], "untilSec": 5.6},
                                    {"name": "close", "styles": ["resolve"]}]}
        text = timed_prompt(script, 62.5, "warm synth")
        self.assertIn("0:00-0:05 hook: sparse", text)
        self.assertIn("0:05-1:02 close: resolve", text)
        self.assertIn("Instrumental only", text)

    def test_default_model_is_music_v2(self):
        self.assertEqual("music_v2", os.environ.get("MUSIC_MODEL", MUSIC_MODEL))


if __name__ == "__main__":
    unittest.main()
