import copy
import hashlib
import json
import math
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tools"))

from editorial import audit_editorial  # noqa: E402
from tools.review import collect_review, write_review  # noqa: E402


def codes(report):
    return {finding["code"] for finding in report["findings"]}


class EditorialAuditTests(unittest.TestCase):
    def script(self):
        return {
            "fps": 30,
            "shots": [{"n": 1, "kind": "clip", "src": "source.mp4", "inSec": 10, "durSec": 5}],
        }

    def beat(self, kind="proof", source_sec=12, **extra):
        return {"id": "observed-result", "sourceSec": source_sec, "kind": kind, **extra}

    def test_missing_proof_is_unknown_even_when_story_metadata_calls_it_evidence(self):
        script = self.script()
        script["shots"][0]["storyBeat"] = "evidence"
        report = audit_editorial(script)
        self.assertTrue(report["advisory"])
        self.assertEqual("unknown", report["status"])
        self.assertEqual("unknown", report["metrics"]["proofStatus"])
        self.assertIsNone(report["metrics"]["firstDeclaredProofSec"])
        self.assertIn("PROOF_TIMING_UNKNOWN", codes(report))
        self.assertNotIn("score", report)

    def test_declared_proof_maps_source_clock_to_exact_output_frame_without_mutation(self):
        script = self.script()
        script["shots"][0]["sourceBeats"] = [self.beat(source_sec=11.001)]
        before = copy.deepcopy(script)
        report = audit_editorial(script)
        self.assertEqual(before, script)
        self.assertEqual(150, report["metrics"]["totalFrames"])
        self.assertEqual(31, report["sourceBeats"][0]["frame"])
        self.assertAlmostEqual(31 / 30, report["metrics"]["firstDeclaredProofSec"])
        self.assertEqual("clear-declared", report["status"])

    def test_event_on_exclusive_last_boundary_is_omitted(self):
        for source_sec in (9, 15, 20):
            with self.subTest(source_sec=source_sec):
                script = self.script()
                script["shots"][0]["sourceBeats"] = [self.beat(source_sec=source_sec)]
                report = audit_editorial(script)
                self.assertEqual("invalid", report["status"])
                self.assertIn("EDITORIAL_SOURCE_BEAT_OMITTED", codes(report))

    def test_action_preroll_and_proof_read_window_are_separate_advisories(self):
        script = self.script()
        script["shots"][0]["sourceBeats"] = [
            self.beat("action", 10.1, id="click", leadInSec=0.5),
            self.beat("proof", 14.8, readHoldSec=1.5),
        ]
        report = audit_editorial(script)
        self.assertIn("INITIATION_LEAD_IN_SHORT", codes(report))
        self.assertIn("PROOF_READ_WINDOW_SHORT", codes(report))
        self.assertEqual("needs-review", report["status"])
        self.assertFalse(any(finding["severity"] == "error" for finding in report["findings"]))

    def test_late_proof_threshold_can_be_changed_or_disabled(self):
        script = self.script()
        script["shots"].insert(0, {"n": 0, "kind": "title", "title": "Context", "durSec": 16, "storyBeat": "setup"})
        script["shots"][1]["sourceBeats"] = [self.beat()]
        report = audit_editorial(script)
        self.assertEqual(18, report["metrics"]["firstDeclaredProofSec"])
        self.assertIn("FIRST_PROOF_LATE", codes(report))
        self.assertIn("SETUP_SHARE_HIGH", codes(report))
        self.assertAlmostEqual(16 / 21, report["metrics"]["setupRatio"])
        script["production"] = {"editorial": {"firstProofBySec": 20, "maxSetupRatio": None}}
        self.assertNotIn("FIRST_PROOF_LATE", codes(audit_editorial(script)))
        script["production"]["editorial"]["firstProofBySec"] = None
        self.assertEqual("clear-declared", audit_editorial(script)["status"])

    def test_narration_anchor_checks_global_clock_and_same_shot(self):
        script = self.script()
        script["shots"].insert(0, {"n": 0, "kind": "title", "durSec": 4})
        script["shots"][1]["sourceBeats"] = [self.beat(source_sec=13, cueId="show-result")]
        script["narrationMap"] = [{"id": "show-result", "shotN": 1, "startSec": 4.1, "endSec": 8.5, "text": "The finding arrives."}]
        report = audit_editorial(script)
        self.assertAlmostEqual(2.9, report["sourceBeats"][0]["cueLagSec"])
        self.assertIn("EVIDENCE_ANCHOR_LATE", codes(report))
        self.assertEqual(1, report["metrics"]["anchoredCueCount"])
        self.assertEqual(1, report["metrics"]["timedAnchorCount"])
        script["narrationMap"][0].update(shotN=0, startSec=0, endSec=3)
        self.assertIn("SOURCE_BEAT_CUE_SHOT_MISMATCH", codes(audit_editorial(script)))

    def test_missing_or_duplicate_cue_reference_cannot_count_as_anchor(self):
        script = self.script()
        script["shots"][0]["sourceBeats"] = [self.beat(cueId="proof")]
        self.assertIn("SOURCE_BEAT_CUE_INVALID", codes(audit_editorial(script)))
        cue = {"id": "proof", "shotN": 1, "startSec": 0, "endSec": 3, "text": "Proof."}
        script["narrationMap"] = [dict(cue), dict(cue)]
        report = audit_editorial(script)
        self.assertIn("EDITORIAL_CUE_DUPLICATE", codes(report))
        self.assertIn("SOURCE_BEAT_CUE_INVALID", codes(report))
        self.assertEqual(0, report["metrics"]["anchoredCueCount"])

    def test_unaligned_draft_cue_reports_unknown_lag_without_invented_timing(self):
        script = self.script()
        script["shots"][0]["sourceBeats"] = [self.beat(cueId="proof")]
        script["narrationMap"] = [{"id": "proof", "shotN": 1, "text": "Read the evidence."}]
        report = audit_editorial(script)
        self.assertIn("CUE_ALIGNMENT_UNKNOWN", codes(report))
        self.assertNotIn("cueLagSec", report["sourceBeats"][0])
        self.assertEqual("unknown", report["status"])
        self.assertEqual(0, report["metrics"]["timedAnchorCount"])

    def test_cue_range_must_fit_assigned_shot(self):
        script = self.script()
        script["narrationMap"] = [{"id": "proof", "shotN": 1, "startSec": 4, "endSec": 7}]
        report = audit_editorial(script)
        self.assertIn("EDITORIAL_CUE_RANGE_INVALID", codes(report))
        self.assertEqual("invalid", report["status"])

    def span_script(self):
        return {"fps": 30, "shots": [
            {"n": 10, "kind": "clip", "src": "source.mp4", "inSec": 0, "durSec": 2},
            {"n": 20, "kind": "clip", "src": "source.mp4", "inSec": 2, "durSec": 2,
             "sourceBeats": [self.beat(source_sec=3, cueId="thought")]},
            {"n": 30, "kind": "clip", "src": "source.mp4", "inSec": 4, "durSec": 2}],
                "narrationMap": [{"id": "thought", "shotNs": [10, 20], "startSec": 1.2,
                                   "endSec": 3.8, "text": "A complete thought spans the detail cut."}]}

    def test_source_anchor_can_belong_to_any_member_of_contiguous_cue_span(self):
        script = self.span_script()
        before = copy.deepcopy(script)
        report = audit_editorial(script)
        self.assertFalse([finding for finding in report["findings"] if finding["severity"] == "error"])
        self.assertEqual(1, report["metrics"]["anchoredCueCount"])
        self.assertEqual(1, report["metrics"]["timedAnchorCount"])
        self.assertAlmostEqual(1.8, report["sourceBeats"][0]["cueLagSec"])
        self.assertEqual(before, script)
        script["narrationMap"][0].update(shotNs=[10], endSec=1.8)
        report = audit_editorial(script)
        self.assertIn("SOURCE_BEAT_CUE_SHOT_MISMATCH", codes(report))
        self.assertEqual(0, report["metrics"]["anchoredCueCount"])

    def test_invalid_narration_spans_never_supply_a_live_source_anchor(self):
        for span in ([10, 10], [10, 30], [20, 10], [10, 99], [], "10,20"):
            script = self.span_script()
            script["narrationMap"][0]["shotNs"] = span
            with self.subTest(span=span):
                report = audit_editorial(script)
                self.assertIn("EDITORIAL_CUE_SHOT_INVALID", codes(report))
                self.assertEqual(0, report["metrics"]["anchoredCueCount"])
        script = self.span_script()
        script["narrationMap"][0]["shotN"] = 20
        self.assertIn("EDITORIAL_CUE_SHOT_INVALID", codes(audit_editorial(script)))

    def test_narration_span_range_must_fit_combined_picture_interval(self):
        script = self.span_script()
        script["narrationMap"][0]["endSec"] = 4.5
        report = audit_editorial(script)
        self.assertIn("EDITORIAL_CUE_RANGE_INVALID", codes(report))
        self.assertEqual("invalid", report["status"])

    def test_legacy_unassigned_cue_is_unknown_but_cannot_supply_source_anchor(self):
        script = self.script()
        script["shots"][0]["sourceBeats"] = [self.beat()]
        script["narrationMap"] = [{"id": "legacy", "startSec": 0.1, "endSec": 3}]
        report = audit_editorial(script)
        self.assertEqual("unknown", report["status"])
        self.assertIn("CUE_SHOT_UNKNOWN", codes(report))
        self.assertEqual(1, report["metrics"]["cueCount"])
        self.assertEqual(1, report["metrics"]["unanchoredCueCount"])
        script["shots"][0]["sourceBeats"][0]["cueId"] = "legacy"
        self.assertIn("SOURCE_BEAT_CUE_SHOT_MISMATCH", codes(audit_editorial(script)))

    def test_fractional_and_float_frame_rates_preserve_compiler_timing(self):
        for fps in (30.0, 29.97):
            with self.subTest(fps=fps):
                script = self.script()
                script["fps"] = fps
                script["shots"][0]["sourceBeats"] = [self.beat(source_sec=11)]
                report = audit_editorial(script)
                self.assertEqual("clear-declared", report["status"])
                self.assertEqual(150, report["metrics"]["totalFrames"])
                self.assertAlmostEqual(30 / fps, report["metrics"]["firstDeclaredProofSec"])

    def test_long_narrated_shot_warns_on_each_unanchored_thought(self):
        script = self.script()
        script["shots"][0]["durSec"] = 16
        script["shots"][0]["sourceBeats"] = [self.beat(cueId="one")]
        script["narrationMap"] = [
            {"id": "one", "shotN": 1, "startSec": 0.5, "endSec": 5},
            {"id": "two", "shotN": 1, "startSec": 6, "endSec": 11},
            {"id": "three", "shotN": 1, "startSec": 12, "endSec": 15},
        ]
        report = audit_editorial(script)
        self.assertEqual(3, report["metrics"]["cueCount"])
        self.assertEqual(2, report["metrics"]["unanchoredCueCount"])
        self.assertEqual(1, report["metrics"]["longUnanchoredShotCount"])
        self.assertIn("LONG_SHOT_UNANCHORED_CUES", codes(report))
        script["production"] = {"editorial": {"maxUnanchoredShotSec": 20}}
        self.assertNotIn("LONG_SHOT_UNANCHORED_CUES", codes(audit_editorial(script)))

    def test_source_timeline_hold_uses_first_visible_frame_and_counts_navigation_duration(self):
        script = self.script()
        shot = script["shots"][0]
        shot["durSec"] = 6
        shot["sourceTimeline"] = [
            {"fromSec": 10, "toSec": 14, "durSec": 2, "mode": "navigation"},
            {"fromSec": 14, "toSec": 14, "durSec": 2, "mode": "hold"},
            {"fromSec": 14, "toSec": 16, "durSec": 2, "mode": "realtime"},
        ]
        shot["sourceBeats"] = [self.beat(source_sec=14, readHoldSec=2)]
        report = audit_editorial(script)
        self.assertEqual(60, report["sourceBeats"][0]["frame"])
        self.assertEqual(2, report["metrics"]["firstDeclaredProofSec"])
        self.assertEqual(2, report["metrics"]["navigationSec"])
        self.assertAlmostEqual(1 / 3, report["metrics"]["navigationRatio"])
        self.assertIn("NAVIGATION_SHARE_HIGH", codes(report))
        self.assertNotIn("PROOF_READ_WINDOW_SHORT", codes(report))

    def test_navigation_event_does_not_invent_navigation_duration(self):
        script = self.script()
        script["shots"][0]["sourceBeats"] = [self.beat("navigation")]
        report = audit_editorial(script)
        self.assertEqual(1, report["metrics"]["navigationEventCount"])
        self.assertEqual("unknown", report["metrics"]["navigationStatus"])
        self.assertIsNone(report["metrics"]["navigationSec"])

    def test_source_mapping_policy_errors_remain_errors_without_taste_gate(self):
        script = self.script()
        shot = script["shots"][0]
        shot.update(actor="human", actionRisk="consequential")
        shot["sourceTimeline"] = [{"fromSec": 10, "toSec": 20, "durSec": 5, "mode": "navigation"}]
        shot["sourceBeats"] = [self.beat()]
        report = audit_editorial(script)
        self.assertTrue(report["advisory"])
        self.assertEqual("invalid", report["status"])
        self.assertIn("SOURCE_TIMELINE_PROTECTED", codes(report))

    def test_malformed_schema_returns_findings_instead_of_crashing(self):
        malformed = [None, {"shots": []}, {"fps": False, "shots": [{}]}, {"shots": [None]},
                     {"shots": [{"n": 1, "durSec": float("nan")}]},
                     {"shots": [{"n": 1, "durSec": 10 ** 1000}]}]
        for script in malformed:
            with self.subTest(script=script):
                self.assertEqual("invalid", audit_editorial(script)["status"])
        script = self.script()
        for field, value in (("sourceSec", float("inf")), ("leadInSec", True),
                             ("readHoldSec", -1), ("id", []), ("cueId", [])):
            with self.subTest(field=field):
                beat = self.beat()
                beat[field] = value
                script["shots"][0]["sourceBeats"] = [beat]
                self.assertEqual("invalid", audit_editorial(script)["status"])
        script["shots"][0]["durSec"] = 15
        script["shots"][0]["sourceBeats"] = []
        script["narrationMap"] = [{"id": [], "shotN": 1}]
        self.assertEqual("invalid", audit_editorial(script)["status"])

    def test_duplicate_source_beats_and_nonclip_annotations_are_errors(self):
        script = self.script()
        script["shots"][0]["sourceBeats"] = [self.beat(), self.beat()]
        self.assertIn("EDITORIAL_SOURCE_BEAT_ID_INVALID", codes(audit_editorial(script)))
        script["shots"][0]["kind"] = "title"
        self.assertIn("EDITORIAL_SOURCE_BEATS_INVALID", codes(audit_editorial(script)))

    def test_thresholds_reject_nan_boolean_negative_and_misspelled_keys(self):
        script = self.script()
        for settings in ({"firstProofBySec": math.nan}, {"maxEvidenceLagSec": True},
                         {"maxUnanchoredShotSec": -1}, {"maxSetupRatio": 1.1}, {"firstProofBySeconds": 15}):
            with self.subTest(settings=settings):
                script["production"] = {"editorial": settings}
                self.assertEqual("invalid", audit_editorial(script)["status"])

    def test_cli_is_read_only_unless_write_is_explicit(self):
        with tempfile.TemporaryDirectory() as directory:
            project = Path(directory)
            script_path = project / "script.json"
            script_path.write_text(json.dumps(self.script()))
            before = script_path.read_bytes()
            command = [sys.executable, str(ROOT / "tools" / "editorial.py"), "--project", str(project)]
            result = subprocess.run(command, capture_output=True, text=True, timeout=15)
            self.assertEqual(0, result.returncode, result.stderr)
            self.assertEqual("unknown", json.loads(result.stdout)["status"])
            self.assertFalse((project / "out").exists())
            result = subprocess.run([*command, "--write"], capture_output=True, text=True, timeout=15)
            self.assertEqual(0, result.returncode, result.stderr)
            stored = json.loads((project / "out" / "editorial-report.json").read_text())
            self.assertEqual(json.loads(result.stdout), stored)
            self.assertEqual(before, script_path.read_bytes())
            self.assertEqual(str(script_path.resolve()), stored["script"]["path"])


class EditorialReviewBindingTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.project = Path(temporary.name)
        self.out = self.project / "out"
        self.out.mkdir()
        self.destination = self.out / "review.html"
        self.script = {"fps": 30, "shots": [{"n": 1, "kind": "title", "durSec": 2}]}
        self.write("script.json", self.script)
        self.video = self.out / "demo.mp4"
        self.video.write_bytes(b"rendered-picture")
        self.props = {"fps": 30, "segments": self.script["shots"]}
        self.write("out/demo.props.json", self.props)
        self.artifact = {"buildId": "matching-build", "scriptSha256": hashlib.sha256((self.project / "script.json").read_bytes()).hexdigest(),
                         "propsSha256": hashlib.sha256(json.dumps(self.props, sort_keys=True, separators=(",", ":")).encode()).hexdigest(),
                         "output": {"sha256": hashlib.sha256(self.video.read_bytes()).hexdigest()}}
        self.write("out/demo.artifact.json", self.artifact)
        self.write("out/demo.build-plan.json", {"fps": 30, "buildId": self.artifact["buildId"],
                   "propsSha256": self.artifact["propsSha256"], "script": {"sha256": self.artifact["scriptSha256"]},
                   "segments": [{"n": 1, "frames": 60}], "totalFrames": 60})
        self.write("out/qa-demo/qa-report.json", {"status": "pass", "fullDecode": "pass", "issues": [],
                   "video": {"sha256": self.artifact["output"]["sha256"]}, "artifact": {"buildId": self.artifact["buildId"]}})
        self.report = audit_editorial(self.script)
        self.report.update(buildId=self.artifact["buildId"], propsSha256=self.artifact["propsSha256"])
        validator = patch("tools.review.validate_script", return_value=[])
        validator.start()
        self.addCleanup(validator.stop)

    def write(self, name, data):
        path = self.project / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(data))
        return path

    def test_bound_advisory_findings_do_not_change_media_qa(self):
        self.report["status"] = "needs-review"
        self.report["findings"].append({"severity": "warning", "code": "FIRST_PROOF_LATE", "message": "Inspect the opening."})
        self.write("out/demo.editorial-report.json", self.report)
        data = collect_review(self.project, self.destination)
        self.assertTrue(data["editorial"]["available"])
        self.assertIsNone(data["editorial"]["metrics"]["firstDeclaredProofSec"])
        self.assertTrue(data["verified"])
        self.assertEqual(0, data["warnings"])
        self.assertIn("Editorial report", {link["label"] for link in data["links"]})

    def test_unbound_or_stale_reports_are_never_shown_as_render_evidence(self):
        for change in ({"buildId": "other"}, {"propsSha256": "other"}, {"buildId": None, "propsSha256": None}):
            with self.subTest(change=change):
                self.write("out/editorial-report.json", {**self.report, **change})
                data = collect_review(self.project, self.destination)
                self.assertFalse(data["editorial"]["available"])
                self.assertNotIn("metrics", data["editorial"])
                self.assertNotIn("Editorial report", {link["label"] for link in data["links"]})

    def test_report_requires_matching_picture_and_props(self):
        self.write("out/demo.editorial-report.json", self.report)
        self.video.write_bytes(b"different-cut")
        self.assertFalse(collect_review(self.project, self.destination)["editorial"]["available"])
        self.video.write_bytes(b"rendered-picture")
        self.write("out/demo.props.json", {**self.props, "extra": "different"})
        self.assertFalse(collect_review(self.project, self.destination)["editorial"]["available"])

    def test_changed_working_script_keeps_bound_cut_audit_but_disables_seek(self):
        self.write("out/demo.editorial-report.json", self.report)
        self.script["shots"][0]["durSec"] = 6
        self.write("script.json", self.script)
        data = collect_review(self.project, self.destination)
        self.assertTrue(data["editorial"]["available"])
        self.assertFalse(data["canSeek"])

    def test_malformed_advisory_is_unavailable_without_affecting_media_qa(self):
        for report in ({**self.report, "findings": [None]},
                       {**self.report, "metrics": {"firstDeclaredProofSec": float("nan")}}):
            with self.subTest(report=report):
                self.write("out/demo.editorial-report.json", report)
                data = collect_review(self.project, self.destination)
                self.assertFalse(data["editorial"]["available"])
                self.assertTrue(data["verified"])
        write_review(self.project, self.destination, thumbnails=False)
        self.assertIn("Story timing", self.destination.read_text())


if __name__ == "__main__":
    unittest.main()
