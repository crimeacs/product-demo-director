import json
import os
import subprocess
import sys
import tempfile
import unittest

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
sys.path.insert(0, os.path.join(ROOT, "tools"))

from vo import (  # noqa: E402
    ALIGNMENT_PROVIDER_ERROR,
    apply_character_alignment,
    eleven_extras,
    narration_text,
    needs_character_alignment,
    select_provider,
)


class VoiceAlignmentTests(unittest.TestCase):
    def auto_paced_script(self):
        return {
            "production": {"autoPaceNarration": True},
            "narration": {"fromMap": True},
            "narrationMap": [{"text": "One complete thought."}],
        }

    def test_map_can_be_the_single_narration_source(self):
        script = {
            "narration": {"fromMap": True},
            "narrationMap": [{"text": "First thought."}, {"text": "Second thought."}],
        }
        self.assertEqual(narration_text(script), "First thought.\n\nSecond thought.")

    def test_character_alignment_populates_exact_cue_ranges(self):
        spoken = "First thought.\n\nSecond thought."
        starts = [index * 0.05 for index in range(len(spoken))]
        ends = [(index + 1) * 0.05 for index in range(len(spoken))]
        script = {
            "narration": {"fromMap": True, "startsAtSec": 0.5},
            "narrationMap": [
                {"id": "first", "text": "First thought."},
                {"id": "second", "text": "Second thought."},
            ],
        }
        count = apply_character_alignment(script, spoken, {
            "characters": list(spoken),
            "character_start_times_seconds": starts,
            "character_end_times_seconds": ends,
        })
        self.assertEqual(count, 2)
        self.assertEqual(script["narrationMap"][0]["startSec"], 0.5)
        self.assertGreater(script["narrationMap"][1]["startSec"],
                           script["narrationMap"][0]["endSec"])
        self.assertEqual(script["narrationMap"][1]["timingSource"],
                         "elevenlabs-character-alignment")

    def test_alignment_must_match_synthesized_text(self):
        script = {"narrationMap": [{"text": "Missing."}]}
        with self.assertRaises(ValueError):
            apply_character_alignment(script, "Spoken.", {
                "characters": list("Different."),
                "character_start_times_seconds": [0.0] * 10,
                "character_end_times_seconds": [0.1] * 10,
            })

    def test_auto_paced_mapped_narration_rejects_gemini_only_auto_selection(self):
        script = self.auto_paced_script()
        self.assertTrue(needs_character_alignment(script))
        with self.assertRaisesRegex(ValueError, "requires ElevenLabs character alignment") as error:
            select_provider("auto", script, {"GEMINI_API_KEY": "configured"})
        self.assertEqual(str(error.exception), ALIGNMENT_PROVIDER_ERROR)

    def test_cli_guard_runs_before_synthesis_or_audio_directory_creation(self):
        with tempfile.TemporaryDirectory() as project:
            with open(os.path.join(project, "script.json"), "w") as handle:
                json.dump(self.auto_paced_script(), handle)
            environment = os.environ.copy()
            for key in (
                "ELEVENLABS_API_KEY",
                "ELEVEN_API_KEY",
                "GEMINI_API_KEY",
                "GOOGLE_API_KEY",
            ):
                environment.pop(key, None)
            environment["GEMINI_API_KEY"] = "configured-but-never-called"

            result = subprocess.run(
                [
                    sys.executable,
                    os.path.join(ROOT, "tools", "vo.py"),
                    "--project",
                    project,
                ],
                cwd=ROOT,
                env=environment,
                capture_output=True,
                text=True,
            )

            self.assertNotEqual(result.returncode, 0)
            self.assertIn("requires ElevenLabs character alignment", result.stderr)
            self.assertFalse(os.path.exists(os.path.join(project, "audio")))

    def test_auto_paced_mapped_narration_rejects_explicit_gemini(self):
        with self.assertRaisesRegex(ValueError, "required by pace.py"):
            select_provider(
                "gemini",
                self.auto_paced_script(),
                {
                    "ELEVENLABS_API_KEY": "configured",
                    "GEMINI_API_KEY": "configured",
                },
            )

    def test_auto_paced_mapped_narration_selects_elevenlabs(self):
        self.assertEqual(
            select_provider(
                "auto",
                self.auto_paced_script(),
                {
                    "ELEVENLABS_API_KEY": "configured",
                    "GEMINI_API_KEY": "configured",
                },
            ),
            "elevenlabs",
        )

    def test_gemini_remains_valid_when_auto_pacing_is_disabled(self):
        mapped_without_auto_pace = {
            "production": {"autoPaceNarration": False},
            "narration": {"fromMap": True},
            "narrationMap": [{"text": "A master without automatic pacing."}],
        }
        legacy_per_shot = {"shots": [{"n": 1, "vo": "A legacy line."}]}
        environment = {"GEMINI_API_KEY": "configured"}
        self.assertEqual(
            select_provider("auto", mapped_without_auto_pace, environment),
            "gemini",
        )
        self.assertEqual(
            select_provider("gemini", legacy_per_shot, environment),
            "gemini",
        )


class ElevenExtrasTests(unittest.TestCase):
    def test_empty_by_default(self):
        self.assertEqual({}, eleven_extras({"narration": {"fromMap": True}}))

    def test_passes_only_valid_fields(self):
        script = {"narration": {"seed": 7, "language_code": "en", "apply_text_normalization": "on"}}
        self.assertEqual({"seed": 7, "language_code": "en", "apply_text_normalization": "on"},
                         eleven_extras(script))
        self.assertEqual({}, eleven_extras({"narration": {"seed": "7", "apply_text_normalization": "yes"}}))

    def test_v3_audio_tags_align_inside_their_thought(self):
        script = {"narration": {"fromMap": True},
                  "narrationMap": [{"text": "[wry] Friday night."}, {"text": "[confident] Send the queue."}]}
        spoken = narration_text(script)
        chars = list(spoken)
        alignment = {"characters": chars,
                     "character_start_times_seconds": [i * 0.05 for i in range(len(chars))],
                     "character_end_times_seconds": [i * 0.05 + 0.05 for i in range(len(chars))]}
        self.assertEqual(2, apply_character_alignment(script, spoken, alignment))
        self.assertEqual(0.0, script["narrationMap"][0]["startSec"])
        self.assertLess(script["narrationMap"][0]["endSec"], script["narrationMap"][1]["startSec"])


if __name__ == "__main__":
    unittest.main()
