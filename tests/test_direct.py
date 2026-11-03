import copy
import hashlib
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

from tools.direct import _atomic_write_json, direct_project, propose_direction


ROOT = Path(__file__).resolve().parents[1]


class DirectTests(unittest.TestCase):
    def script(self):
        return {
            "fps": 30,
            "narration": {"file": "audio/master.wav"},
            "narrationMap": [{"id": "why", "shotN": 1, "text": "Keep the exact authored thought."}],
            "shots": [
                {"n": 1, "kind": "title", "durSec": 2, "title": "Find the useful moment."},
                {"n": 2, "kind": "clip", "durSec": 5, "src": "uncaptured.mp4", "direction": {"intent": "focus"}},
                {"n": 3, "kind": "cta", "durSec": 3, "title": "Start your next story."},
            ],
        }

    def test_preview_is_read_only_and_does_not_need_assets_or_audio(self):
        with tempfile.TemporaryDirectory() as directory:
            project = Path(directory)
            source = json.dumps(self.script()).encode()
            (project / "script.json").write_bytes(source)
            plan = direct_project(project)
            self.assertEqual((project / "script.json").read_bytes(), source)
            self.assertFalse((project / "out").exists())
            self.assertEqual(plan["style"], "studio")
            self.assertEqual(plan["status"], "draft")
            self.assertFalse(plan["renderBound"])
            self.assertEqual(plan["sourceScriptSha256"], hashlib.sha256(source).hexdigest())

    def test_write_changes_only_creative_direction_and_saves_unbound_plan(self):
        with tempfile.TemporaryDirectory() as directory:
            project = Path(directory)
            original = self.script()
            (project / "script.json").write_text(json.dumps(original))
            result = direct_project(project, write=True)
            saved = json.loads((project / "script.json").read_text())
            self.assertEqual(saved.pop("creativeDirection"), {
                "style": "studio", "tone": "precise", "soundDesign": "sparse",
            })
            self.assertEqual(saved, original)
            self.assertEqual(json.loads((project / "out" / "direction-plan.json").read_text()), result)
            self.assertFalse(result["renderBound"])
            self.assertFalse(list(project.glob(".*.tmp")))

    def test_respects_existing_silence_and_tone(self):
        script = self.script()
        script["creativeDirection"] = {"style": "classic", "tone": "editorial", "soundDesign": "silent"}
        source = copy.deepcopy(script)
        proposed, plan = propose_direction(script)
        self.assertEqual(script, source)
        self.assertEqual(proposed["creativeDirection"], {"style": "studio", "tone": "editorial", "soundDesign": "silent"})
        self.assertTrue(all(not shot["soundCues"] for shot in plan["shots"]))

    def test_never_invents_focus_coordinates(self):
        script = self.script()
        proposed, plan = propose_direction(script)
        self.assertEqual(proposed["shots"], script["shots"])
        self.assertEqual(plan["shots"][1]["camera"], [])
        self.assertNotIn("focus", plan["shots"][1]["direction"])

    def test_authored_camera_and_story_are_preserved(self):
        script = self.script()
        camera = [{"atSec": 0, "scale": 1.1, "focusX": 52, "focusY": 49},
                  {"atSec": 2, "scale": 1.5, "focusX": 72, "focusY": 41}]
        script["shots"][1]["camera"] = camera
        proposed, plan = propose_direction(script)
        self.assertEqual(plan["shots"][1]["camera"], camera)
        self.assertEqual(proposed["shots"], script["shots"])
        self.assertEqual(proposed["narrationMap"], script["narrationMap"])

    def test_invalid_direction_leaves_script_and_existing_plan_untouched(self):
        with tempfile.TemporaryDirectory() as directory:
            project = Path(directory)
            script = self.script()
            script["shots"][1]["direction"]["focus"] = {"x": 150, "y": 50}
            source = json.dumps(script).encode()
            (project / "script.json").write_bytes(source)
            (project / "out").mkdir()
            existing_plan = b'{"previous": true}\n'
            (project / "out" / "direction-plan.json").write_bytes(existing_plan)
            with self.assertRaisesRegex(ValueError, "DIRECTION_INVALID"):
                direct_project(project, write=True)
            self.assertEqual((project / "script.json").read_bytes(), source)
            self.assertEqual((project / "out" / "direction-plan.json").read_bytes(), existing_plan)

    def test_invalid_script_inputs_fail_before_compilation(self):
        cases = [([], "SCRIPT_INVALID"), ({"shots": []}, "SHOTS_MISSING")]
        for field, value, code in (("fps", 0, "FPS_INVALID"), ("fps", True, "FPS_INVALID"),
                                   ("production", {"sourceLocks": [{"src": []}]}, "SOURCE_LOCKS_INVALID")):
            script = self.script()
            script[field] = value
            cases.append((script, code))
        for value in (0, -1, True, float("nan"), 0.001):
            script = self.script()
            script["shots"][1]["durSec"] = value
            cases.append((script, "SHOT_DURATION_INVALID"))
        for script, code in cases:
            with self.subTest(script=script), self.assertRaisesRegex(ValueError, code):
                propose_direction(script)

    def test_atomic_replace_failure_preserves_original_and_cleans_temporary(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "script.json"
            path.write_text('{"original": true}\n')
            with patch("tools.direct.os.replace", side_effect=OSError("simulated interrupted write")):
                with self.assertRaises(OSError):
                    _atomic_write_json(path, {"replacement": True})
            self.assertEqual(path.read_text(), '{"original": true}\n')
            self.assertEqual(list(Path(directory).iterdir()), [path])

    def test_cli_preview_prints_parseable_json_and_invalid_input_has_no_traceback(self):
        with tempfile.TemporaryDirectory() as directory:
            project = Path(directory)
            (project / "script.json").write_text(json.dumps(self.script()))
            result = subprocess.run([sys.executable, str(ROOT / "pdd"), "direct", directory],
                                    capture_output=True, text=True)
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertEqual(json.loads(result.stdout)["style"], "studio")
            (project / "script.json").write_text("[]")
            invalid = subprocess.run([sys.executable, str(ROOT / "pdd"), "direct", directory, "--write"],
                                     capture_output=True, text=True)
            self.assertNotEqual(invalid.returncode, 0)
            self.assertIn("SCRIPT_INVALID", invalid.stderr)
            self.assertNotIn("Traceback", invalid.stderr)

    def test_new_projects_start_with_studio_direction(self):
        with tempfile.TemporaryDirectory() as directory:
            project = Path(directory) / "project"
            result = subprocess.run([sys.executable, str(ROOT / "pdd"), "new", str(project)],
                                    capture_output=True, text=True)
            self.assertEqual(result.returncode, 0, result.stderr)
            script = json.loads((project / "script.json").read_text())
            self.assertEqual(script["creativeDirection"], {"style": "studio", "tone": "precise", "soundDesign": "sparse"})


if __name__ == "__main__":
    unittest.main()
