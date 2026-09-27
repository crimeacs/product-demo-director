"""Chronology, source availability, and frame-allocation regression tests."""
import copy
from pathlib import Path
import sys
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "tools"))

from source_timing import (compile_source_timeline, output_times_for_source,
                           source_time_at, validate_source_timing)  # noqa: E402


class SourceTimingTests(unittest.TestCase):
    def shot(self):
        return {"n": 6, "kind": "clip", "inSec": 2, "durSec": 5, "sourceTimeline": [
            {"fromSec": 2, "toSec": 4, "durSec": 1, "mode": "navigation"},
            {"fromSec": 4, "toSec": 6, "durSec": 2, "mode": "realtime"},
            {"fromSec": 6, "toSec": 6, "durSec": 2, "mode": "hold"},
        ]}

    def codes(self, shot, **script):
        return {item["code"] for item in validate_source_timing({"fps": 30, "shots": [shot], **script})}

    def test_navigation_action_and_reading_hold_compile_without_skipping_source(self):
        shot = self.shot()
        original = copy.deepcopy(shot)
        self.assertEqual(set(), self.codes(shot))
        self.assertEqual([
            {"startFrame": 0, "frames": 30, "sourceStartSec": 2, "sourceEndSec": 4, "playbackRate": 2, "hold": False},
            {"startFrame": 30, "frames": 60, "sourceStartSec": 4, "sourceEndSec": 6, "playbackRate": 1, "hold": False},
            {"startFrame": 90, "frames": 60, "sourceStartSec": 6, "sourceEndSec": 6, "playbackRate": 0, "hold": True},
        ], compile_source_timeline(shot, 30))
        self.assertEqual(original, shot)

    def test_compile_allocates_cumulative_half_up_frames_and_exact_shot_total(self):
        shot = {"durSec": 0.2, "sourceTimeline": [
            {"fromSec": 0, "toSec": 0.05, "durSec": 0.05, "mode": "realtime"},
            {"fromSec": 0.05, "toSec": 0.1, "durSec": 0.05, "mode": "realtime"},
            {"fromSec": 0.1, "toSec": 0.2, "durSec": 0.1, "mode": "realtime"},
        ]}
        result = compile_source_timeline(shot, 30)
        self.assertEqual([2, 1, 3], [span["frames"] for span in result])
        self.assertEqual([0, 2, 3], [span["startFrame"] for span in result])
        self.assertEqual(6, sum(span["frames"] for span in result))
        for span in result:
            self.assertAlmostEqual(span["sourceEndSec"], span["sourceStartSec"] + span["frames"] / 30 * span["playbackRate"])
        shot["durSec"] = 7 / 30
        self.assertEqual(7, sum(span["frames"] for span in compile_source_timeline(shot, 30)))

    def test_subframe_spans_are_rejected_instead_of_disappearing(self):
        shot = {"durSec": 1, "sourceTimeline": [
            {"fromSec": 0, "toSec": 0.001, "durSec": 0.001, "mode": "realtime"},
            {"fromSec": 0.001, "toSec": 1, "durSec": 0.999, "mode": "realtime"},
        ]}
        self.assertIn("SOURCE_TIMELINE_FRAMES", self.codes(shot))
        with self.assertRaisesRegex(ValueError, "SOURCE_TIMELINE_FRAMES"):
            compile_source_timeline(shot, 30)

    def test_gaps_reversals_and_mismatched_in_points_cannot_hide_actions(self):
        for start in [3.9, 4.1]:
            shot = self.shot()
            shot["sourceTimeline"][1]["fromSec"] = start
            self.assertIn("SOURCE_TIMELINE_DISCONTINUITY", self.codes(shot))
        shot = self.shot()
        shot["inSec"] = 3
        self.assertIn("SOURCE_TIMELINE_START", self.codes(shot))
        shot = self.shot()
        shot["sourceTimeline"][0]["toSec"] = 1
        self.assertIn("SOURCE_TIMELINE_INVALID", self.codes(shot))

    def test_sub_microsecond_normalization_noise_does_not_break_source_continuity(self):
        shot = self.shot()
        shot["sourceTimeline"][1]["fromSec"] += 0.0000004
        self.assertEqual(set(), self.codes(shot))

    def test_navigation_requires_explicit_authorization_and_obeys_project_and_absolute_caps(self):
        shot = self.shot()
        shot["sourceTimeline"][0]["mode"] = "realtime"
        self.assertIn("SOURCE_TIMELINE_RATE", self.codes(shot))
        shot["sourceTimeline"][0]["mode"] = "navigation"
        shot["sourceTimeline"][0]["durSec"] = 0.5
        shot["durSec"] = 4.5
        self.assertIn("SOURCE_TIMELINE_RATE", self.codes(shot))
        self.assertEqual(set(), self.codes(shot, production={"maxNavigationRate": 4}))
        self.assertEqual(4, compile_source_timeline(shot, 30)[0]["playbackRate"])
        for limit in [0, 4.01, True, "2", float("nan"), float("inf")]:
            self.assertIn("SOURCE_TIMELINE_RATE", self.codes(shot, production={"maxNavigationRate": limit}))
        shot["sourceTimeline"][0]["durSec"] = 0.4
        shot["durSec"] = 4.4
        with self.assertRaisesRegex(ValueError, "SOURCE_TIMELINE_RATE"):
            compile_source_timeline(shot, 30)

    def test_frame_rounding_cannot_sneak_past_navigation_limit_or_warp_protected_audio(self):
        shot = {"durSec": 0.049, "sourceTimeline": [
            {"fromSec": 0, "toSec": 0.098, "durSec": 0.049, "mode": "navigation"},
        ]}
        # Authored 2x becomes almost 3x when the output rounds to one frame.
        self.assertIn("SOURCE_TIMELINE_RATE", self.codes(shot))
        shot["sourceTimeline"][0]["toSec"] = 0.196
        with self.assertRaisesRegex(ValueError, "after frame rounding"):
            compile_source_timeline(shot, 30)
        shot.update(sound=True)
        shot["sourceTimeline"][0].update(mode="realtime", toSec=0.049)
        self.assertIn("SOURCE_TIMELINE_PROTECTED", self.codes(shot))

    def test_holds_cannot_advance_even_a_fraction_of_a_source_frame(self):
        shot = self.shot()
        shot["sourceTimeline"][-1]["toSec"] += 0.0000001
        self.assertIn("SOURCE_TIMELINE_RATE", self.codes(shot))

    def test_human_performance_source_audio_and_decisions_cannot_be_time_warped(self):
        for protection in [{"sourceType": "human"}, {"sound": True},
                           {"actor": "human", "actionRisk": "consequential"}]:
            with self.subTest(protection=protection):
                shot = {**self.shot(), **protection}
                self.assertIn("SOURCE_TIMELINE_PROTECTED", self.codes(shot))
                shot["sourceTimeline"] = [{"fromSec": 2, "toSec": 7, "durSec": 5, "mode": "realtime"}]
                self.assertEqual(set(), self.codes(shot))
                self.assertEqual(1, compile_source_timeline(shot, 30)[0]["playbackRate"])

    def test_total_playback_duration_must_match_shot_and_stay_finite(self):
        shot = self.shot()
        shot["durSec"] = 5.04
        self.assertIn("SOURCE_TIMELINE_DURATION", self.codes(shot))
        for field in ["fromSec", "toSec", "durSec"]:
            for value in [None, False, "2", float("nan"), float("inf"), 10 ** 400]:
                with self.subTest(field=field, value=value):
                    shot = self.shot()
                    shot["sourceTimeline"][0][field] = value
                    self.assertIn("SOURCE_TIMELINE_INVALID", self.codes(shot))
        for duration in [None, False, 0, -1, float("nan"), float("inf")]:
            shot = self.shot()
            shot["durSec"] = duration
            self.assertIn("SOURCE_TIMELINE_DURATION", self.codes(shot))

    def test_invalid_schema_returns_findings_without_crashing(self):
        for spans in [None, [], {}, "bad", [None], [{"fromSec": 0, "toSec": 1, "durSec": 1, "mode": []}]]:
            self.assertIn("SOURCE_TIMELINE_INVALID", self.codes({**self.shot(), "sourceTimeline": spans}))
        self.assertIn("SOURCE_TIMELINE_INVALID", self.codes({**self.shot(), "kind": "title"}))
        for fps in [0, -1, False, None, float("nan"), float("inf")]:
            self.assertIn("SOURCE_TIMELINE_INVALID", self.codes(self.shot(), fps=fps))

    def test_source_mapping_samples_navigation_action_and_hold_correctly(self):
        shot = self.shot()
        for output_time, source_time in [(-1, 2), (0, 2), (0.5, 3), (1, 4), (2, 5), (3, 6), (4, 6), (8, 6)]:
            self.assertAlmostEqual(source_time, source_time_at(shot, output_time))
        samples = [source_time_at(shot, step / 100) for step in range(501)]
        self.assertEqual(samples, sorted(samples))

    def test_inverse_mapping_deduplicates_shared_edges_and_reports_hold_window(self):
        shot = self.shot()
        self.assertEqual([], output_times_for_source(shot, 1.9))
        self.assertEqual([], output_times_for_source(shot, 6.1))
        self.assertEqual([0], output_times_for_source(shot, 2))
        self.assertEqual([0.5], output_times_for_source(shot, 3))
        self.assertEqual([1], output_times_for_source(shot, 4))
        self.assertEqual([2], output_times_for_source(shot, 5))
        self.assertEqual([3, 5], output_times_for_source(shot, 6))
        for step in range(81):
            source = 2 + step * 0.05
            for output in output_times_for_source(shot, source):
                self.assertAlmostEqual(source, source_time_at(shot, output))

    def test_audits_can_share_the_exact_compiled_frame_mapping(self):
        shot = {"durSec": 0.2, "sourceTimeline": [
            {"fromSec": 0, "toSec": 0.05, "durSec": 0.05, "mode": "realtime"},
            {"fromSec": 0.05, "toSec": 0.05, "durSec": 0.15, "mode": "hold"},
        ]}
        self.assertEqual([0.05, 0.2], output_times_for_source(shot, 0.05))
        self.assertEqual([2 / 30, 0.2], output_times_for_source(shot, 0.05, fps=30))
        self.assertAlmostEqual(0.025, source_time_at(shot, 1 / 30, fps=30))
        self.assertEqual(0.05, source_time_at(shot, 5 / 30, fps=30))

    def test_legacy_trim_remains_identity_and_helpers_reject_nonfinite_queries(self):
        shot = {"inSec": 4.5, "durSec": 9}
        self.assertEqual([], compile_source_timeline(shot, 30))
        self.assertEqual(6.5, source_time_at(shot, 2))
        self.assertEqual([2], output_times_for_source(shot, 6.5))
        self.assertEqual([], output_times_for_source(shot, 14))
        self.assertEqual([9], output_times_for_source(shot, 13.5))
        for value in [float("nan"), float("inf"), None, "2", False]:
            with self.assertRaises(ValueError):
                source_time_at(shot, value)
            with self.assertRaises(ValueError):
                output_times_for_source(shot, value)


if __name__ == "__main__":
    unittest.main()
