import os
import sys
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "tools"))

from build import compile_frame_plan  # noqa: E402


class FramePlanTests(unittest.TestCase):
    def test_total_is_sum_of_segment_rounding(self):
        segs = [
            {"n": 1, "kind": "clip", "durSec": 1.015},
            {"n": 2, "kind": "clip", "durSec": 1.015},
            {"n": 3, "kind": "cta", "durSec": 1.015},
        ]
        rows, total = compile_frame_plan(segs, 30)
        self.assertEqual(total, sum(row["frames"] for row in rows))
        self.assertEqual(rows[-1]["endFrame"], total)
        self.assertEqual(sum(seg["durFrames"] for seg in segs), total)

    def test_payout_v14_boundaries_are_exact(self):
        durations = [13.2, 16.5, 25.08, 14.9, 13.2, 22.138, 17.96, 10.76, 8.12, 8.38, 20.1, 4.36]
        segs = [{"n": i + 1, "kind": "clip" if i < 11 else "cta", "durSec": d}
                for i, d in enumerate(durations)]
        rows, total = compile_frame_plan(segs, 30)
        self.assertEqual(total, 5241)
        self.assertEqual(rows[-1]["startFrame"], 5110)


if __name__ == "__main__":
    unittest.main()
