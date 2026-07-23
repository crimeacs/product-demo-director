import json
import os
import subprocess
import sys
import tempfile
import unittest

from tools.contracts import validate_script


ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))


class CliScaffoldTests(unittest.TestCase):
    def run_pdd(self, *args, home):
        env = os.environ.copy()
        env["HOME"] = home
        return subprocess.run(
            [sys.executable, os.path.join(ROOT, "pdd"), *args],
            cwd=ROOT,
            env=env,
            capture_output=True,
            text=True,
        )

    def test_new_project_is_single_focus_and_narration_paced(self):
        with tempfile.TemporaryDirectory() as directory:
            project = os.path.join(directory, "announcement")
            subprocess.run([sys.executable, os.path.join(ROOT, "pdd"), "new", project,
                            "--name", "Example Product"], cwd=ROOT, check=True,
                           capture_output=True, text=True)
            with open(os.path.join(project, "script.json")) as handle:
                script = json.load(handle)
            preflight_codes = {
                finding.code
                for finding in validate_script(
                    script, project, allow_pending_narration=True
                )
            }
        production = script["production"]
        self.assertEqual(production["profile"], "announcement")
        self.assertTrue(production["singleFocus"])
        self.assertTrue(production["autoPaceNarration"])
        self.assertFalse(any(shot["kind"] == "split" for shot in script["shots"]))
        self.assertEqual({entry["shotN"] for entry in script["narrationMap"]},
                         {shot["n"] for shot in script["shots"]})
        self.assertTrue(script["narration"]["fromMap"])
        self.assertEqual(sum(shot["durSec"] for shot in script["shots"]), 60)
        authored_story = json.dumps({
            "narrationMap": script["narrationMap"],
            "shots": script["shots"],
        })
        self.assertEqual(script["brand"]["name"], "Example Product")
        self.assertIn("Example Product", authored_story)
        self.assertNotIn("Product Demo Director", authored_story)
        self.assertNotIn("open-source pipeline", authored_story)
        self.assertNotIn("STORY_BEAT_PLACEMENT", preflight_codes)

    def test_install_skill_defaults_to_both_and_is_idempotent(self):
        with tempfile.TemporaryDirectory() as home:
            first = self.run_pdd("install-skill", home=home)
            self.assertEqual(first.returncode, 0, first.stderr)
            destinations = (
                os.path.join(home, ".agents", "skills", "product-demo-director"),
                os.path.join(home, ".claude", "skills", "product-demo-director"),
            )
            for destination in destinations:
                self.assertTrue(os.path.islink(destination))
                self.assertEqual(os.path.realpath(destination), os.path.realpath(ROOT))

            second = self.run_pdd("install-skill", home=home)
            self.assertEqual(second.returncode, 0, second.stderr)
            self.assertEqual(second.stdout.count("already installed"), 2)

    def test_install_skill_can_target_codex_only(self):
        with tempfile.TemporaryDirectory() as home:
            result = self.run_pdd(
                "install-skill", "--target", "codex", home=home
            )
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertTrue(
                os.path.islink(
                    os.path.join(
                        home, ".agents", "skills", "product-demo-director"
                    )
                )
            )
            self.assertFalse(
                os.path.lexists(
                    os.path.join(
                        home, ".claude", "skills", "product-demo-director"
                    )
                )
            )

    def test_install_skill_refuses_unrelated_path_before_creating_other_link(self):
        with tempfile.TemporaryDirectory() as home:
            occupied = os.path.join(
                home, ".agents", "skills", "product-demo-director"
            )
            os.makedirs(occupied)

            result = self.run_pdd("install-skill", home=home)
            self.assertNotEqual(result.returncode, 0)
            self.assertIn("Refusing to overwrite unrelated existing path", result.stderr)
            self.assertFalse(
                os.path.lexists(
                    os.path.join(
                        home, ".claude", "skills", "product-demo-director"
                    )
                )
            )

    def test_install_skill_refuses_symlink_to_another_repo(self):
        with tempfile.TemporaryDirectory() as home, tempfile.TemporaryDirectory() as other:
            occupied = os.path.join(
                home, ".claude", "skills", "product-demo-director"
            )
            os.makedirs(os.path.dirname(occupied))
            os.symlink(other, occupied)

            result = self.run_pdd(
                "install-skill", "--target", "claude", home=home
            )
            self.assertNotEqual(result.returncode, 0)
            self.assertIn(
                "Refusing to overwrite unrelated existing symlink", result.stderr
            )
            self.assertEqual(os.path.realpath(occupied), os.path.realpath(other))


if __name__ == "__main__":
    unittest.main()
