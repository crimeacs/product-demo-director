import copy
import hashlib
import json
import os
from pathlib import Path
import sys
import tempfile
import unittest
from unittest import mock

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "tools"))

import vo
from contracts import validate_script
from pace import PaceError, pace_script


def alignment(text):
    return {
        "characters": list(text),
        "character_start_times_seconds": [index * 0.01 for index in range(len(text))],
        "character_end_times_seconds": [(index + 1) * 0.01 for index in range(len(text))],
    }


class AlignmentIntegrityTests(unittest.TestCase):
    def test_pronunciation_changes_audio_and_timings_without_changing_authored_copy(self):
        script = {
            "pronounce": {"Kestrlo": "Kestrel-oh"},
            "narrationMap": [{"text": "Kestrlo works."}, {"text": "Try Kestrlo."}],
        }
        spoken = "Kestrel-oh works.\n\nTry Kestrel-oh."
        self.assertEqual(vo.apply_character_alignment(script, spoken, alignment(spoken)), 2)
        first, second = script["narrationMap"]
        self.assertEqual(first["text"], "Kestrlo works.")
        self.assertEqual(first["sourceCharEnd"], len("Kestrel-oh works."))
        self.assertEqual(second["sourceCharStart"], spoken.index("Try"))

    def test_bad_late_cue_does_not_partially_update_existing_timings(self):
        script = {"narrationMap": [{"text": "First."}, {"text": "Absent."}]}
        before = copy.deepcopy(script)
        with self.assertRaisesRegex(ValueError, "not present"):
            vo.apply_character_alignment(script, "First. Second.", alignment("First. Second."))
        self.assertEqual(script, before)

    def test_alignment_rejects_nonfinite_backwards_and_negative_timing(self):
        for field, values in (
            ("character_start_times_seconds", [0, float("nan")]),
            ("character_end_times_seconds", [0.1, float("inf")]),
            ("character_start_times_seconds", [0.02, 0.01]),
            ("character_start_times_seconds", [-0.01, 0.01]),
        ):
            with self.subTest(field=field, values=values):
                payload = alignment("Hi")
                payload[field] = values
                with self.assertRaises(ValueError):
                    vo.apply_character_alignment({"narrationMap": [{"text": "Hi"}]}, "Hi", payload)

    def test_invalid_narration_offset_cannot_poison_timing_json(self):
        for offset in (-1, "bad", float("inf")):
            with self.subTest(offset=offset):
                with self.assertRaisesRegex(ValueError, "startsAtSec"):
                    vo.apply_character_alignment({
                        "narration": {"startsAtSec": offset},
                        "narrationMap": [{"text": "Hi"}],
                    }, "Hi", alignment("Hi"))


class VoiceRecoveryTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.project = Path(self.temp.name)
        self.script_path = self.project / "script.json"
        self.audio = self.project / "audio"
        self.audio.mkdir()
        self.addCleanup(mock.patch.stopall)
        mock.patch.dict(os.environ, {"ELEVENLABS_API_KEY": "test-key"}, clear=True).start()
        mock.patch.object(sys, "argv", ["vo.py", "--project", str(self.project)]).start()
        mock.patch.object(vo, "_audio_duration", return_value=2.0).start()
        mock.patch("builtins.print").start()

    def save(self, script):
        self.script_path.write_text(json.dumps(script))

    def synth(self, spoken, out, script, override=None):
        Path(out).write_bytes(b"new performance")
        return None

    def test_default_master_path_is_saved_and_unchanged_cache_avoids_paid_call(self):
        self.save({"narration": {"text": "One thought."}, "shots": []})
        with mock.patch.object(vo, "synth_elevenlabs", side_effect=self.synth) as provider:
            vo.main()
            vo.main()
        self.assertEqual(provider.call_count, 1)
        written = json.loads(self.script_path.read_text())
        self.assertEqual(written["narration"]["file"], "audio/master.mp3")
        self.assertEqual(written["narration"]["sha256"], hashlib.sha256(b"new performance").hexdigest())

    def test_replaced_audio_is_regenerated_instead_of_relocked_as_the_requested_read(self):
        self.save({"narration": {"text": "One thought."}, "shots": []})
        with mock.patch.object(vo, "synth_elevenlabs", side_effect=self.synth) as provider:
            vo.main()
            (self.audio / "master.mp3").write_bytes(b"unrelated audio")
            vo.main()
        self.assertEqual(provider.call_count, 2)
        self.assertEqual((self.audio / "master.mp3").read_bytes(), b"new performance")

    def test_failed_alignment_preserves_existing_master_and_script(self):
        self.save({
            "narration": {"fromMap": True},
            "narrationMap": [{"text": "One thought."}],
            "shots": [],
        })
        original_script = self.script_path.read_bytes()
        (self.audio / "master.mp3").write_bytes(b"approved performance")
        (self.audio / "master-manifest.json").write_text('{"approved": true}')

        def bad_alignment(spoken, out, script, override):
            Path(out).write_bytes(b"bad new performance")
            return None, {"alignment": alignment("Wrong words.")}

        with mock.patch.object(vo, "synth_elevenlabs_aligned", side_effect=bad_alignment):
            with self.assertRaisesRegex(SystemExit, "does not match"):
                vo.main()
        self.assertEqual((self.audio / "master.mp3").read_bytes(), b"approved performance")
        self.assertEqual((self.audio / "master-manifest.json").read_text(), '{"approved": true}')
        self.assertEqual(self.script_path.read_bytes(), original_script)
        self.assertFalse(list(self.audio.glob(".master-*")))

    def test_invalid_timing_cache_recovers_by_synthesizing_again(self):
        self.save({"narration": {"fromMap": True}, "narrationMap": [{"text": "Hi."}]})

        def aligned(spoken, out, script, override):
            self.synth(spoken, out, script)
            return None, {"alignment": alignment(spoken)}

        with mock.patch.object(vo, "synth_elevenlabs_aligned", side_effect=aligned) as provider:
            vo.main()
            vo.main()
            self.assertEqual(provider.call_count, 1)
            (self.audio / "master-timing.json").write_text("interrupted write")
            vo.main()
        self.assertEqual(provider.call_count, 2)
        self.assertEqual(json.loads((self.audio / "master-timing.json").read_text())["cueCount"], 1)

    def test_gemini_master_voice_override_reaches_synthesis(self):
        self.save({"narration": {"text": "Hi.", "voice": "Puck"}, "gemini_voice": "Charon"})
        with mock.patch.dict(os.environ, {"GEMINI_API_KEY": "test-key"}, clear=True):
            with mock.patch.object(vo, "synth_gemini", side_effect=self.synth) as provider:
                vo.main()
        self.assertEqual(provider.call_args.args[2]["gemini_voice"], "Puck")
        self.assertEqual(json.loads((self.audio / "master-manifest.json").read_text())["voiceId"], "Puck")

    def test_failed_per_shot_batch_preserves_all_previously_approved_audio(self):
        self.save({"shots": [{"n": 1, "vo": "First."}, {"n": 2, "vo": "Second."}]})
        (self.audio / "s1.mp3").write_bytes(b"approved first")
        (self.audio / "s2.mp3").write_bytes(b"approved second")
        (self.audio / "manifest.json").write_text('[{"n": 1, "sig": "old"}]')

        def synth(spoken, out, script):
            Path(out).write_bytes(b"partial generation")
            return "temporary provider failure" if spoken == "Second." else None

        with mock.patch.object(vo, "synth_elevenlabs", side_effect=synth):
            with self.assertRaisesRegex(SystemExit, "shots \\[2\\]"):
                vo.main()
        self.assertEqual((self.audio / "s1.mp3").read_bytes(), b"approved first")
        self.assertEqual((self.audio / "s2.mp3").read_bytes(), b"approved second")
        self.assertEqual((self.audio / "manifest.json").read_text(), '[{"n": 1, "sig": "old"}]')
        self.assertFalse(list(self.audio.glob(".s*-*")))


class PacingIntegrityTests(unittest.TestCase):
    def script(self):
        return {
            "fps": 30,
            "editorialContract": {"targetRuntimeSec": 10},
            "shots": [
                {"n": 5, "durSec": 1, "visualOnly": True},
                {"n": 2, "durSec": 3},
                {"n": 9, "durSec": 1, "visualOnly": True},
                {"n": 1, "durSec": 3},
                {"n": 8, "durSec": 2, "visualOnly": True},
            ],
            "narrationMap": [
                {"shotN": 2, "startSec": 1.1, "endSec": 3.9},
                {"shotN": 1, "startSec": 5.1, "endSec": 7.9},
            ],
        }

    def test_visual_only_establishing_insert_and_end_card_remain_speech_free(self):
        script = self.script()
        plan = pace_script(script)
        self.assertEqual(plan["totalFrames"], 300)
        for shot in plan["shots"]:
            self.assertGreater(shot["frames"], 0)
            for cue in script["narrationMap"]:
                if shot["n"] == cue["shotN"]:
                    self.assertLessEqual(shot["startSec"], cue["startSec"])
                    self.assertGreaterEqual(shot["endSec"], cue["endSec"])

    def test_visual_insert_fails_when_no_frame_is_available(self):
        script = self.script()
        script["narrationMap"][1]["startSec"] = 3.9
        with self.assertRaisesRegex(PaceError, "no frame-safe cut"):
            pace_script(script)

    def test_duplicate_shot_numbers_are_not_silently_collapsed(self):
        script = self.script()
        script["shots"][2]["n"] = 2
        with self.assertRaisesRegex(PaceError, "unique"):
            pace_script(script)

    def test_overlapping_cues_in_one_shot_are_rejected(self):
        script = self.script()
        script["narrationMap"].insert(1, {"shotN": 2, "startSec": 3.5, "endSec": 3.8})
        with self.assertRaisesRegex(PaceError, "overlap"):
            pace_script(script)

    def test_fps_must_not_be_silently_truncated_or_defaulted(self):
        for fps in (0, True, "bad", 29.97, float("inf")):
            with self.subTest(fps=fps):
                script = self.script()
                script["fps"] = fps
                with self.assertRaisesRegex(PaceError, "fps"):
                    pace_script(script)

    def test_exactly_one_frame_per_shot_is_valid(self):
        script = {
            "fps": 10, "editorialContract": {"targetRuntimeSec": 0.2},
            "shots": [{"n": 1, "durSec": 0.1}, {"n": 2, "durSec": 0.1}],
            "narrationMap": [
                {"shotN": 1, "startSec": 0, "endSec": 0.1},
                {"shotN": 2, "startSec": 0.1, "endSec": 0.2},
            ],
        }
        self.assertEqual([shot["frames"] for shot in pace_script(script)["shots"]], [1, 1])

    def test_profile_narration_tail_is_respected_without_explicit_override(self):
        script = self.script()
        script["production"] = {"profile": "launch"}
        script["narrationMap"][-1]["endSec"] = 9.5
        with self.assertRaisesRegex(PaceError, "needs 0.750s tail"):
            pace_script(script)

    def test_half_frames_round_like_the_render_engine(self):
        script = {
            "fps": 10, "editorialContract": {"targetRuntimeSec": 0.55},
            "shots": [{"n": 1, "durSec": 0.25}, {"n": 2, "durSec": 0.3}],
            "narrationMap": [
                {"shotN": 1, "startSec": 0.02, "endSec": 0.15},
                {"shotN": 2, "startSec": 0.4, "endSec": 0.5},
            ],
        }
        plan = pace_script(script)
        self.assertEqual(plan["totalFrames"], 6)
        self.assertEqual(plan["shots"][0]["frames"], 3)


class NarrationContractIntegrityTests(unittest.TestCase):
    def codes(self, script, project="."):
        return {finding.code for finding in validate_script(script, project)}

    def test_arbitrary_ids_follow_picture_order_not_numeric_order(self):
        script = {
            "shots": [{"n": 20, "kind": "title", "durSec": 2},
                      {"n": 3, "kind": "title", "durSec": 2}],
            "narrationMap": [{"shotN": 20, "startSec": 0, "endSec": 1.5},
                             {"shotN": 3, "startSec": 2, "endSec": 3.5}],
        }
        self.assertNotIn("NARRATION_MAP_SHOT_ORDER", self.codes(script))
        script["narrationMap"][0]["shotN"] = 3
        script["narrationMap"][1]["shotN"] = 20
        self.assertIn("NARRATION_MAP_SHOT_ORDER", self.codes(script))
        self.assertIn("NARRATION_MAP_SHOT_RANGE", self.codes(script))

    def test_invalid_map_entries_return_findings_under_thought_cut_policy(self):
        script = {
            "production": {"narrationCutPolicy": "between-thoughts"},
            "shots": [{"n": 1, "kind": "title", "durSec": 2},
                      {"n": 2, "kind": "title", "durSec": 2}],
            "narrationMap": [None, "broken cue", {"startSec": 0.5, "endSec": 3}],
        }
        codes = self.codes(script)
        self.assertIn("NARRATION_MAP_ENTRY_INVALID", codes)
        self.assertIn("NARRATION_THOUGHT_CUT", codes)

    def test_missing_and_changed_timing_files_break_the_production_lock(self):
        with tempfile.TemporaryDirectory() as project:
            Path(project, "master.mp3").write_bytes(b"master")
            script = {
                "shots": [{"n": 1, "kind": "title", "durSec": 2}],
                "narration": {"file": "master.mp3", "timingFile": "timing.json", "timingSha256": "locked"},
            }
            with mock.patch("contracts.media_duration", return_value=1.0):
                self.assertIn("NARRATION_TIMING_MISSING", self.codes(script, project))
                Path(project, "timing.json").write_text("changed")
                self.assertIn("NARRATION_TIMING_HASH_MISMATCH", self.codes(script, project))

    def test_nonobject_shots_and_boolean_ids_fail_cleanly(self):
        self.assertIn("SHOT_INVALID", self.codes({"shots": [None]}))
        self.assertIn("SHOT_NUMBER_INVALID", self.codes({
            "shots": [{"n": True, "kind": "title", "durSec": 2}],
        }))


if __name__ == "__main__":
    unittest.main()
