import json
import os
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "tools"))

from contracts import sha256_file  # noqa: E402
from qa import (  # noqa: E402
    _outside_allowed,
    artifact_binding_issues,
    canonical_json_sha256,
    container_duration_tolerance,
    default_sidecar_path,
    parse_black,
    parse_loudness,
    parse_silence,
)


class MediaQaParserTests(unittest.TestCase):
    def test_black_intervals(self):
        text = "black_start:2.1 black_end:2.5 black_duration:0.4"
        self.assertEqual(parse_black(text)[0]["durationSec"], 0.4)

    def test_silence_intervals(self):
        text = "silence_start: 10.7\nsilence_end: 12.2 | silence_duration: 1.5"
        self.assertEqual(parse_silence(text), [{"startSec": 10.7, "endSec": 12.2, "durationSec": 1.5}])

    def test_ebur128_summary(self):
        text = "noise\nSummary:\n I: -18.0 LUFS\n LRA: 3.3 LU\n Peak: -1.5 dBFS\n"
        self.assertEqual(parse_loudness(text), {
            "integratedLufs": -18.0, "loudnessRangeLu": 3.3, "truePeakDbtp": -1.5})

    def test_allowed_ranges_remove_only_fully_contained_intervals(self):
        intervals = [
            {"startSec": 1.0, "endSec": 1.5, "durationSec": 0.5},
            {"startSec": 3.0, "endSec": 4.0, "durationSec": 1.0},
        ]
        allowed = [{"startSec": 0.9, "endSec": 1.6}]
        self.assertEqual(_outside_allowed(intervals, allowed), [intervals[1]])

    def test_container_duration_tolerance_accounts_for_aac_padding(self):
        self.assertEqual(container_duration_tolerance(30), 0.10)
        self.assertEqual(container_duration_tolerance(25), 0.12)

    def test_default_sidecars_prefer_video_stem_then_legacy(self):
        with tempfile.TemporaryDirectory() as directory:
            preferred = os.path.join(directory, "candidate.artifact.json")
            legacy = os.path.join(directory, "artifact.json")
            self.assertEqual(default_sidecar_path(directory, "candidate", "artifact"), preferred)
            with open(legacy, "w") as fh:
                fh.write("{}")
            self.assertEqual(default_sidecar_path(directory, "candidate", "artifact"), legacy)
            with open(preferred, "w") as fh:
                fh.write("{}")
            self.assertEqual(default_sidecar_path(directory, "candidate", "artifact"), preferred)

    def test_artifact_bindings_accept_exact_project_script_and_props(self):
        with tempfile.TemporaryDirectory() as project:
            script_path = os.path.join(project, "script.json")
            props_path = os.path.join(project, "props.json")
            script = {"fps": 30, "shots": []}
            props = {"fps": 30, "totalFrames": 0, "segments": []}
            with open(script_path, "w") as fh:
                json.dump(script, fh)
            with open(props_path, "w") as fh:
                json.dump(props, fh, indent=2)
            artifact = {
                "project": project,
                "scriptSha256": sha256_file(script_path),
                "propsSha256": canonical_json_sha256(props),
            }
            self.assertEqual(
                artifact_binding_issues(artifact, project, script_path, props_path, props),
                [],
            )

    def test_artifact_bindings_reject_stale_or_unbound_sources(self):
        with tempfile.TemporaryDirectory() as project:
            script_path = os.path.join(project, "script.json")
            props_path = os.path.join(project, "props.json")
            props = {"fps": 30, "segments": [{"durFrames": 60}]}
            with open(script_path, "w") as fh:
                json.dump({"fps": 30, "shots": []}, fh)
            with open(props_path, "w") as fh:
                json.dump(props, fh)
            artifact = {
                "project": os.path.join(project, "other"),
                "scriptSha256": "bad-script",
                "propsSha256": canonical_json_sha256({"stale": True}),
            }
            codes = {
                issue["code"] for issue in
                artifact_binding_issues(artifact, project, script_path, props_path, props)
            }
            self.assertEqual(
                codes,
                {"ARTIFACT_PROJECT_MISMATCH", "SCRIPT_HASH_MISMATCH", "PROPS_HASH_MISMATCH"},
            )
            missing_codes = {
                issue["code"] for issue in
                artifact_binding_issues({}, project, script_path, props_path, props)
            }
            self.assertEqual(
                missing_codes,
                {
                    "ARTIFACT_PROJECT_MISSING",
                    "ARTIFACT_SCRIPT_HASH_MISSING",
                    "ARTIFACT_PROPS_HASH_MISSING",
                },
            )
            missing_props = artifact_binding_issues(
                {"propsSha256": "bound"},
                props_path=os.path.join(project, "missing.props.json"),
                props={},
            )
            self.assertEqual([issue["code"] for issue in missing_props], ["PROPS_MISSING"])


if __name__ == "__main__":
    unittest.main()
