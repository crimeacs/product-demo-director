import json
import os
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "tools"))

from judge import DEFAULT_MODEL, LIVE_RUBRIC, RUBRIC, _judge_config, _structural, calibrate, probe_paths  # noqa: E402


class JudgeModelTests(unittest.TestCase):
    def test_default_is_a_pinned_gemini_3_model(self):
        self.assertTrue(DEFAULT_MODEL.startswith("gemini-3"))
        self.assertNotIn("latest", DEFAULT_MODEL)

    def test_gemini_3_thinks_instead_of_forcing_temperature(self):
        from google.genai import types
        cfg = _judge_config(types, "gemini-3.1-pro-preview")
        self.assertIsNone(cfg.temperature)
        self.assertEqual("HIGH", cfg.thinking_config.thinking_level.name)
        self.assertEqual(0.0, _judge_config(types, "gemini-2.5-flash").temperature)


class JudgeProfileTests(unittest.TestCase):
    def test_three_minute_live_product_has_no_arbitrary_short_promo_penalty(self):
        props = {"profile": "yc_3m", "segments": [
            {"kind": "clip", "durSec": 14.5, "src": "same.mp4", "stateId": f"s{i}", "storyBeat": f"b{i}"}
            for i in range(12)
        ]}
        self.assertEqual(_structural(props)[:2], (0, 0))

    def test_continuous_source_is_not_repetition_in_live_profile(self):
        props = {"profile": "investor", "segments": [
            {"kind": "clip", "durSec": 4, "src": "same.mp4", "stateId": "a", "storyBeat": "input"},
            {"kind": "clip", "durSec": 4, "src": "same.mp4", "stateId": "b", "storyBeat": "result"},
        ]}
        self.assertEqual(_structural(props)[0], 0)

    def test_replayed_identical_state_is_penalized(self):
        props = {"profile": "investor", "segments": [
            {"kind": "clip", "durSec": 4, "src": "a.mp4", "stateId": "done", "storyBeat": "payoff"},
            {"kind": "clip", "durSec": 4, "src": "b.mp4", "stateId": "done", "storyBeat": "payoff"},
        ]}
        self.assertEqual(_structural(props)[0], 6)

    def test_live_rubric_does_not_apply_short_feed_assumptions(self):
        self.assertIn("do not apply short social-ad assumptions", LIVE_RUBRIC)
        self.assertIn("DEFAULT is to click away", RUBRIC)

    def test_product_truth_failure_caps_live_demo(self):
        scores = {key: 95 for key in (
            "hook_1s", "pace_rhythm", "non_repetition", "visual_interest", "motion_design",
            "vo_performance", "sound_design", "clarity_one_thing", "proof_credibility",
            "polish", "wow_moment", "causal_progression", "authority_boundary")}
        scores["product_truth"] = 40
        data = {"overall": 95, "scores": scores, "repeated_elements": [], "dead_seconds": [],
                "would_keep_watching": True}
        with tempfile.TemporaryDirectory() as temp:
            props_path = os.path.join(temp, "props.json")
            with open(props_path, "w") as fh:
                json.dump({"profile": "yc_3m", "segments": [
                    {"kind": "clip", "durSec": 10, "stateId": "a", "storyBeat": "test"}
                ]}, fh)
            self.assertEqual(calibrate(data, props_path)["overall"], 49)

    def test_probe_uses_bundled_bad_and_requires_explicit_good_reference(self):
        bad, good = probe_paths()
        self.assertTrue(bad.endswith("examples/calibration/known_bad.mp4"))
        self.assertEqual(good, "")
        with tempfile.TemporaryDirectory() as temp:
            supplied = os.path.join(temp, "approved-final.mp4")
            _, good = probe_paths(supplied)
            self.assertEqual(good, os.path.abspath(supplied))


if __name__ == "__main__":
    unittest.main()
