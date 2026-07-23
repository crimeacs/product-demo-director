import os
import sys
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "tools"))

from build import lint  # noqa: E402


class BuildLintTests(unittest.TestCase):
    @staticmethod
    def run_lint(segs, narration_map=None):
        script = {"shots": [{"n": seg["n"]} for seg in segs]}
        if narration_map is not None:
            script["narrationMap"] = narration_map
        return lint(script, segs, None, "default")

    def test_long_static_card_is_allowed_while_mapped_narration_keeps_it_active(self):
        segs = [
            {"n": 1, "kind": "clip", "durSec": 3.0},
            {"n": 2, "kind": "title", "durSec": 10.0},
        ]
        errors, warnings = self.run_lint(segs, [
            {"shotN": 2, "startSec": 3.5, "endSec": 12.5},
        ])
        self.assertEqual(errors, [])
        self.assertEqual(warnings, [])

    def test_long_trailing_hold_after_mapped_narration_is_warned(self):
        segs = [{"n": 1, "kind": "cta", "durSec": 10.0}]
        _, warnings = self.run_lint(segs, [
            {"shotN": 1, "startSec": 0.0, "endSec": 4.0},
        ])
        self.assertEqual(len(warnings), 1)
        self.assertIn("6s trailing unnarrated hold", warnings[0])

    def test_long_internal_gap_between_mapped_cues_is_warned(self):
        segs = [{"n": 1, "kind": "stat", "durSec": 12.0}]
        _, warnings = self.run_lint(segs, [
            {"shotN": 1, "startSec": 0.0, "endSec": 2.0},
            {"shotN": 1, "startSec": 7.0, "endSec": 12.0},
        ])
        self.assertEqual(len(warnings), 1)
        self.assertIn("5s internal unnarrated hold", warnings[0])

    def test_unaligned_map_entry_keeps_legacy_total_duration_warning(self):
        segs = [{"n": 1, "kind": "title", "durSec": 8.0}]
        _, warnings = self.run_lint(segs, [
            {"shotN": 1, "text": "Timing is pending."},
        ])
        self.assertEqual(
            warnings,
            ["static title held 8.0s (>4.5s reads as dead air)"],
        )


if __name__ == "__main__":
    unittest.main()
