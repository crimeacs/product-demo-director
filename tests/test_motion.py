import os
import sys
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "tools"))

from motion import build_mix  # noqa: E402


class MotionMixTests(unittest.TestCase):
    def test_cue_inputs_follow_music_input(self):
        cues = [{"t": 0.35, "cue": "data_tick"}, {"t": 4.25, "cue": "pivot_boom"}]
        inputs, parts, labels = build_mix("s.mp4", 33.2, {"music": "m.mp3", "musicOffsetSec": 10}, cues, "p", "sfx")
        self.assertEqual(inputs.count("-i"), 4)          # video, music, two cues
        self.assertTrue(parts[0].startswith("[1:a]"))    # music is input 1
        self.assertTrue(parts[1].startswith("[2:a]"))    # first cue is input 2, despite the -ss tokens
        self.assertTrue(parts[2].startswith("[3:a]"))
        self.assertIn("adelay=4250|4250", parts[2])
        self.assertEqual(labels, ["[m]", "[s0]", "[s1]"])

    def test_cues_without_music_start_at_input_one(self):
        inputs, parts, labels = build_mix("s.mp4", 10, {}, [{"t": 1, "cue": "click"}], "p", "sfx")
        self.assertTrue(parts[0].startswith("[1:a]"))
        self.assertEqual(labels, ["[s0]"])


if __name__ == "__main__":
    unittest.main()
