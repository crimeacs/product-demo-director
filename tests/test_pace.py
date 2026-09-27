import os
import sys
import unittest
import copy

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "tools"))

from pace import PaceError, apply_plan, pace_script  # noqa: E402


class PaceTests(unittest.TestCase):
    def script(self):
        return {
            "fps": 30,
            "production": {"narrationCutPaddingSec": 0.04, "minNarrationTailSec": 0.75},
            "editorialContract": {"targetRuntimeSec": 10},
            "narrationMap": [
                {"shotN": 1, "text": "One.", "startSec": 0.2, "endSec": 3.2},
                {"shotN": 2, "text": "Two.", "startSec": 3.8, "endSec": 6.5},
                {"shotN": 3, "text": "Three.", "startSec": 7.0, "endSec": 8.8},
            ],
            "shots": [
                {"n": 1, "kind": "clip", "durSec": 2.5},
                {"n": 2, "kind": "clip", "durSec": 3.5},
                {"n": 3, "kind": "cta", "durSec": 4.0},
            ],
        }

    def test_moves_cuts_to_sentence_safe_frames_and_keeps_exact_runtime(self):
        plan = pace_script(self.script())
        self.assertEqual(plan["totalFrames"], 300)
        first_cut = plan["shots"][0]["endSec"]
        second_cut = plan["shots"][1]["endSec"]
        self.assertGreaterEqual(first_cut, 3.24)
        self.assertLessEqual(first_cut, 3.76)
        self.assertGreaterEqual(second_cut, 6.54)
        self.assertLessEqual(second_cut, 6.96)
        self.assertEqual(plan["shots"][-1]["endFrame"], 300)

    def test_plan_is_deterministic_and_applies_frame_durations(self):
        script = self.script()
        one = pace_script(script)
        two = pace_script(self.script())
        self.assertEqual(one, two)
        apply_plan(script, one)
        self.assertAlmostEqual(sum(shot["durSec"] for shot in script["shots"]), 10.0)
        self.assertTrue(script["editorialContract"]["narrationPaced"])

    def test_impossible_gap_fails_instead_of_cutting_speech(self):
        script = self.script()
        script["narrationMap"][1]["startSec"] = 3.1
        with self.assertRaises(PaceError):
            pace_script(script)

    def test_missing_shot_mapping_fails(self):
        script = self.script()
        script["narrationMap"] = script["narrationMap"][:-1]
        with self.assertRaises(PaceError):
            pace_script(script)

    def test_pacing_cannot_resize_an_authored_source_timeline(self):
        script = self.script()
        script["shots"][0]["sourceTimeline"] = [
            {"fromSec": 0, "toSec": 2.5, "durSec": 2.5, "mode": "realtime"},
        ]
        before = copy.deepcopy(script)
        with self.assertRaisesRegex(PaceError, "pace narration before mapping"):
            pace_script(script)
        self.assertEqual(before, script)

    def test_existing_map_is_preserved_when_paced_frame_duration_is_unchanged(self):
        script = self.script()
        plan = pace_script(script)
        apply_plan(script, plan)
        duration = script["shots"][0]["durSec"]
        mapping = [{"fromSec": 0, "toSec": duration, "durSec": duration, "mode": "realtime"}]
        script["shots"][0]["sourceTimeline"] = copy.deepcopy(mapping)
        apply_plan(script, pace_script(script))
        self.assertEqual(mapping, script["shots"][0]["sourceTimeline"])

    def test_applying_old_pace_plan_fails_atomically_if_it_would_resize_a_map(self):
        script = self.script()
        plan = pace_script(script)
        script["shots"][1]["sourceTimeline"] = [
            {"fromSec": 0, "toSec": 3.5, "durSec": 3.5, "mode": "realtime"},
        ]
        before = copy.deepcopy(script)
        with self.assertRaisesRegex(PaceError, "pace narration before mapping"):
            apply_plan(script, plan)
        self.assertEqual(before, script)


if __name__ == "__main__":
    unittest.main()
