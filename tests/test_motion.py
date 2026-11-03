import os
import sys
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "tools"))

from motion import build_mix, section_plan, word_time  # noqa: E402
import web_export  # noqa: E402


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

    def test_narration_is_placed_and_ducks_the_music(self):
        vo = [{"t": 0.2, "file": "vo/1.mp3"}, {"t": 6.0, "file": "vo/2.mp3"}]
        inputs, parts, labels = build_mix("s.mp4", 61, {"music": "m.mp3"}, [{"t": 1, "cue": "pop"}], "p", "sfx", vo)
        self.assertEqual(inputs.count("-i"), 5)                       # video, music, two lines, one cue
        self.assertTrue(any(p.startswith("[2:a]") and "adelay=200|200" in p for p in parts))
        self.assertTrue(any(p.startswith("[3:a]") and "adelay=6000|6000" in p for p in parts))
        self.assertTrue(any("sidechaincompress" in p and p.startswith("[m][vosc]") for p in parts))
        self.assertTrue(any(p.startswith("[4:a]") for p in parts))     # the cue comes after the narration inputs
        self.assertIn("[md]", labels); self.assertIn("[vo]", labels); self.assertNotIn("[m]", labels)

    def test_narration_without_music_is_not_ducked(self):
        _, parts, labels = build_mix("s.mp4", 10, {}, [], "p", "sfx", [{"t": 0, "file": "a.mp3"}])
        self.assertFalse(any("sidechaincompress" in p for p in parts))
        self.assertEqual(labels, ["[vo]"])

    def test_word_time_reads_character_alignment(self):
        al = {"characters": list("and finds her."), "character_start_times_seconds": [i * 0.1 for i in range(14)]}
        self.assertAlmostEqual(word_time(al, "finds"), 0.4)
        self.assertIsNone(word_time(al, "toy"))

    def test_section_plan_lands_boundaries_and_keeps_minimum(self):
        cfg = {"musicPrompt": "warm, playful", "musicSections": [{"name": "a", "untilSec": 2, "styles": ["x"]},
                                                                   {"name": "b", "untilSec": 20}, {"name": "c"}]}
        plan = section_plan(cfg, 30)
        self.assertEqual([s["duration_ms"] for s in plan["sections"]], [3000, 18000, 10000])
        self.assertIn("silence", plan["sections"][0]["negative_local_styles"])
        self.assertEqual(plan["positive_global_styles"][:2], ["warm", "playful"])

    def test_web_export_is_fast_start_and_complete(self):
        cmds = web_export.commands("f.mp4", "out", "film", 12.0)
        self.assertEqual(set(cmds), {"film-1080p.mp4", "film-720p.mp4", "film-1080p.webm", "poster.jpg"})
        for k in ("film-1080p.mp4", "film-720p.mp4"):
            self.assertIn("+faststart", cmds[k])
        self.assertIn("libvpx-vp9", cmds["film-1080p.webm"])
        self.assertIn("12.0", cmds["poster.jpg"])


if __name__ == "__main__":
    unittest.main()
