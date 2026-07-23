import hashlib
import json
import os
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "tools"))

from build import (  # noqa: E402
    bind_capture_source_inputs,
    bind_claim_evidence_inputs,
    compute_build_id,
)
from contracts import sha256_file  # noqa: E402
from judge import verify_artifact  # noqa: E402


class ArtifactManifestTests(unittest.TestCase):
    def test_judge_accepts_only_the_bound_video(self):
        with tempfile.TemporaryDirectory() as temp:
            video = os.path.join(temp, "demo.mp4")
            artifact = os.path.join(temp, "artifact.json")
            payload = b"rendered-video"
            with open(video, "wb") as fh:
                fh.write(payload)
            with open(artifact, "w") as fh:
                json.dump({"buildId": "abc", "output": {
                    "sha256": hashlib.sha256(payload).hexdigest()}}, fh)
            self.assertEqual(verify_artifact(video, artifact, True)["buildId"], "abc")
            with open(video, "ab") as fh:
                fh.write(b"stale")
            with self.assertRaisesRegex(RuntimeError, "artifact hash mismatch"):
                verify_artifact(video, artifact, True)

    def test_required_manifest_cannot_be_skipped(self):
        with tempfile.TemporaryDirectory() as temp:
            video = os.path.join(temp, "demo.mp4")
            with open(video, "wb") as fh:
                fh.write(b"video")
            with self.assertRaisesRegex(RuntimeError, "required but missing"):
                verify_artifact(video, os.path.join(temp, "missing.json"), True)

    def test_stem_manifest_wins_over_stale_generic_manifest(self):
        with tempfile.TemporaryDirectory() as temp:
            video = os.path.join(temp, "candidate.mp4")
            payload = b"candidate"
            with open(video, "wb") as fh:
                fh.write(payload)
            with open(os.path.join(temp, "artifact.json"), "w") as fh:
                json.dump({"output": {"sha256": "0" * 64}}, fh)
            with open(os.path.join(temp, "candidate.artifact.json"), "w") as fh:
                json.dump({"buildId": "candidate-build", "output": {
                    "sha256": hashlib.sha256(payload).hexdigest()}}, fh)
            self.assertEqual(verify_artifact(video, required=True)["buildId"], "candidate-build")

    def test_every_render_input_changes_the_build_identity(self):
        base = [{"kind": "picture", "name": "case.mp4", "sha256": "a" * 64}]
        changed = [{"kind": "picture", "name": "case.mp4", "sha256": "b" * 64}]
        config = {"fps": 30, "profile": "yc_3m"}
        self.assertNotEqual(compute_build_id(base, config), compute_build_id(changed, config))
        self.assertNotEqual(compute_build_id(base, config),
                            compute_build_id(base, {"fps": 25, "profile": "yc_3m"}))

    def test_capture_source_manifest_is_bound_and_changes_build_identity(self):
        with tempfile.TemporaryDirectory() as project:
            source_dir = os.path.join(project, "_src")
            os.makedirs(source_dir)
            source = os.path.join(source_dir, "session.json")
            script = {"production": {"sourceManifests": ["_src/session.json"]}}

            def records():
                bound = []

                def bind(kind, name, path):
                    record = {
                        "kind": kind,
                        "name": name,
                        "sha256": sha256_file(path),
                    }
                    bound.append(record)
                    return record

                bind_capture_source_inputs(script, project, bind)
                return bound

            with open(source, "w") as fh:
                json.dump({"phase": "prompt"}, fh)
            before = records()
            self.assertEqual(before[0]["kind"], "capture-source")
            self.assertEqual(before[0]["name"], "_src/session.json")

            with open(source, "w") as fh:
                json.dump({"phase": "delivery"}, fh)
            after = records()
            self.assertNotEqual(
                compute_build_id(before, {"fps": 30}),
                compute_build_id(after, {"fps": 30}),
            )

    def test_local_claim_evidence_is_deduplicated_and_bound_to_build_identity(self):
        with tempfile.TemporaryDirectory() as project:
            evidence_dir = os.path.join(project, "evidence")
            os.makedirs(evidence_dir)
            evidence = os.path.join(evidence_dir, "verified.json")
            script = {
                "claims": [
                    {
                        "id": "verified-capability",
                        "evidence": [
                            "evidence/verified.json",
                            "https://example.com/external-proof",
                        ],
                    },
                    {"id": "same-proof", "evidence": "./evidence/verified.json"},
                ],
            }

            def records():
                bound = []

                def bind(kind, name, path):
                    record = {
                        "kind": kind,
                        "name": name,
                        "sha256": sha256_file(path),
                    }
                    bound.append(record)
                    return record

                bind_claim_evidence_inputs(script, project, bind)
                return bound

            with open(evidence, "w") as fh:
                json.dump({"verified": True}, fh)
            before = records()
            self.assertEqual(before, [{
                "kind": "claim-evidence",
                "name": "evidence/verified.json",
                "sha256": sha256_file(evidence),
            }])

            with open(evidence, "w") as fh:
                json.dump({"verified": False}, fh)
            after = records()
            self.assertNotEqual(
                compute_build_id(before, {"fps": 30}),
                compute_build_id(after, {"fps": 30}),
            )

    def test_claim_evidence_rejects_project_and_symlink_escapes(self):
        with tempfile.TemporaryDirectory() as project, tempfile.TemporaryDirectory() as outside:
            external = os.path.join(outside, "proof.json")
            with open(external, "w") as fh:
                json.dump({"verified": True}, fh)

            with self.assertRaisesRegex(ValueError, "must be project-relative"):
                bind_claim_evidence_inputs(
                    {"claims": [{"evidence": external}]},
                    project,
                    lambda *_: None,
                )

            os.symlink(external, os.path.join(project, "proof.json"))
            with self.assertRaisesRegex(ValueError, "escapes the project"):
                bind_claim_evidence_inputs(
                    {"claims": [{"evidence": "proof.json"}]},
                    project,
                    lambda *_: None,
                )


if __name__ == "__main__":
    unittest.main()
