import hashlib
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from tools.review import collect_review, write_review


class ReviewTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.project = Path(self.temp.name)
        self.out = self.project / "out"
        self.out.mkdir()
        self.destination = self.out / "review.html"
        self.script = {"fps": 30, "brand": {"name": "Film"}, "shots": [
            {"n": 20, "kind": "title", "title": "The problem", "durSec": 2},
            {"n": 7, "kind": "cta", "title": "The change", "durSec": 3}],
            "narrationMap": [{"shotN": 7, "text": "A complete spoken thought."}]}
        self.write("script.json", self.script)
        self.patch = patch("tools.review.validate_script", return_value=[])
        self.patch.start()
        self.addCleanup(self.patch.stop)

    def write(self, path, value):
        target = self.project / path
        target.parent.mkdir(exist_ok=True, parents=True)
        target.write_text(json.dumps(value))
        return target

    def prepare_delivery(self):
        video = self.out / "demo-final.mp4"
        video.write_bytes(b"test delivery")
        digest = hashlib.sha256(video.read_bytes()).hexdigest()
        script_hash = hashlib.sha256((self.project / "script.json").read_bytes()).hexdigest()
        props = {"fps": 30, "segments": self.script["shots"]}
        props_hash = hashlib.sha256(json.dumps(props, sort_keys=True, separators=(",", ":")).encode()).hexdigest()
        self.write("out/demo-final.props.json", props)
        self.artifact = {"buildId": "bound-build", "scriptSha256": script_hash,
                         "propsSha256": props_hash, "output": {"sha256": digest}}
        self.write("out/demo-final.artifact.json", self.artifact)
        self.write("out/demo-final.build-plan.json", {
            "buildId": "bound-build", "script": {"sha256": script_hash}, "propsSha256": props_hash,
            "fps": 30, "segments": [{"n": 20, "frames": 75}, {"n": 7, "frames": 90}]})
        self.qa = {"status": "pass", "fullDecode": "pass", "video": {"sha256": digest},
                   "artifact": {"buildId": "bound-build"}, "issues": [],
                   "audio": {"integratedLufs": -18.2}}
        self.write("out/qa-demo-final/qa-report.json", self.qa)
        return video

    def test_story_preview_needs_no_media_or_services(self):
        data = collect_review(self.project, self.destination)
        self.assertEqual(data["status"], "Story preview")
        self.assertEqual(data["totalFrames"], 150)
        self.assertEqual(data["shots"][1]["narration"], "A complete spoken thought.")
        self.assertFalse(data["verified"])
        self.assertFalse(data["canSeek"])

    def test_shared_narration_cue_is_shown_on_each_member_and_not_other_shots(self):
        self.script["shots"].append({"n": 99, "kind": "title", "title": "Next", "durSec": 2})
        self.script["narrationMap"] = [{"shotNs": [20, 7], "text": "One unmodified spoken thought."}]
        self.write("script.json", self.script)
        data = collect_review(self.project, self.destination)
        self.assertEqual(["One unmodified spoken thought.", "One unmodified spoken thought.", ""],
                         [shot["narration"] for shot in data["shots"]])
        self.script["narrationMap"][0]["shotN"] = 20
        self.write("script.json", self.script)
        invalid = collect_review(self.project, self.destination)
        self.assertEqual(["", "", ""], [shot["narration"] for shot in invalid["shots"]])

    def test_bound_plan_uses_rendered_durations_in_picture_order(self):
        self.prepare_delivery()
        data = collect_review(self.project, self.destination)
        self.assertTrue(data["verified"])
        self.assertTrue(data["canSeek"])
        self.assertEqual(data["shots"][1]["n"], 7)
        self.assertEqual(data["shots"][1]["startSec"], 2.5)
        self.assertEqual(data["audio"]["integratedLufs"], -18.2)

    def test_modified_video_never_inherits_a_pass_or_seek_plan(self):
        video = self.prepare_delivery()
        video.write_bytes(b"a different cut")
        data = collect_review(self.project, self.destination)
        self.assertFalse(data["verified"])
        self.assertFalse(data["canSeek"])
        self.assertEqual(data["audio"], {})
        self.assertIn("QA_STALE", {issue["code"] for issue in data["issues"]})

    def test_modified_script_cannot_borrow_old_frame_plan(self):
        self.prepare_delivery()
        self.script["shots"][0]["durSec"] = 4
        self.write("script.json", self.script)
        data = collect_review(self.project, self.destination)
        self.assertFalse(data["verified"])
        self.assertFalse(data["canSeek"])
        self.assertEqual(data["shots"][1]["startSec"], 4)
        self.assertIn("STORY_CHANGED", {issue["code"] for issue in data["issues"]})

    def test_changed_source_input_invalidates_delivery_readiness(self):
        self.prepare_delivery()
        source = self.project / "brand.json"
        source.write_text("{}")
        self.artifact["inputs"] = [{"name": "brand.json", "path": str(source), "sha256": "old"}]
        self.write("out/demo-final.artifact.json", self.artifact)
        data = collect_review(self.project, self.destination)
        self.assertFalse(data["verified"])
        self.assertIn("SOURCE_CHANGED", {issue["code"] for issue in data["issues"]})

    def test_failed_qa_without_findings_still_blocks(self):
        self.prepare_delivery()
        self.qa["status"] = "fail"
        self.write("out/qa-demo-final/qa-report.json", self.qa)
        data = collect_review(self.project, self.destination)
        self.assertFalse(data["verified"])
        self.assertGreater(data["errors"], 0)

    def test_html_treats_story_content_as_data(self):
        attack = '</script><script>alert("example")</script>'
        self.script["shots"][0]["title"] = attack
        self.script["brand"]["name"] = attack
        self.write("script.json", self.script)
        write_review(self.project, self.destination, thumbnails=False)
        document = self.destination.read_text()
        self.assertNotIn(attack, document)
        self.assertIn('\\u003c/script>', document)
        self.assertNotIn("__REVIEW_DATA__", document)

    def test_malformed_optional_receipt_is_actionable(self):
        self.prepare_delivery()
        (self.out / "qa-demo-final" / "qa-report.json").write_text("not json")
        data = collect_review(self.project, self.destination)
        self.assertFalse(data["verified"])
        self.assertIn("REPORT_INVALID", {issue["code"] for issue in data["issues"]})

    def test_preserves_existing_output_when_input_is_invalid(self):
        self.destination.write_text("previous review")
        (self.project / "script.json").write_text("broken")
        with self.assertRaises(ValueError):
            write_review(self.project, self.destination)
        self.assertEqual(self.destination.read_text(), "previous review")

    def test_output_cannot_replace_media(self):
        video = self.prepare_delivery()
        with self.assertRaisesRegex(ValueError, "html"):
            write_review(self.project, video)
        self.assertEqual(video.read_bytes(), b"test delivery")

    def test_missing_receipt_identity_cannot_verify(self):
        self.prepare_delivery()
        del self.artifact["buildId"]
        self.qa["artifact"] = {}
        self.write("out/demo-final.artifact.json", self.artifact)
        self.write("out/qa-demo-final/qa-report.json", self.qa)
        self.assertFalse(collect_review(self.project, self.destination)["verified"])

    def test_malformed_nested_receipts_are_reported(self):
        for key in ("output", "inputs"):
            with self.subTest(key=key):
                self.prepare_delivery()
                self.artifact[key] = "invalid"
                self.write("out/demo-final.artifact.json", self.artifact)
                data = collect_review(self.project, self.destination)
                self.assertFalse(data["verified"])
                self.assertIn("REPORT_INVALID", {item["code"] for item in data["issues"]})

    def test_reordered_plan_does_not_enable_wrong_seek_points(self):
        self.prepare_delivery()
        plan_path = self.out / "demo-final.build-plan.json"
        plan = json.loads(plan_path.read_text())
        plan["segments"].reverse()
        plan_path.write_text(json.dumps(plan))
        data = collect_review(self.project, self.destination)
        self.assertFalse(data["canSeek"])
        self.assertFalse(data["verified"])
        self.assertEqual(data["shots"][1]["startSec"], 2)

    def framing_plan(self):
        return {"schemaVersion": 1, "buildId": self.artifact["buildId"],
                "propsSha256": self.artifact["propsSha256"], "shots": [
                    {"n": 20, "framingReport": {"schemaVersion": 1, "advisory": True,
                        "status": "needs-review", "viewerWidthPx": 320, "minTextPx": 12,
                        "beats": [{"label": "Evidence row", "atSec": 0.5, "endSec": 2,
                                   "projectedTextPx": 8.5, "camera": {"scale": 4.5},
                                   "subjectVisible": True, "safeAreaMet": True}],
                        "findings": [{"severity": "warning", "code": "FRAMING_TEXT_TOO_SMALL",
                                      "message": "Measured text projects below the target."}]}},
                    {"n": 7}]}

    def test_bound_framing_is_advisory_and_missing_measurements_remain_unknown(self):
        self.prepare_delivery()
        self.write("out/demo-final.direction-plan.json", self.framing_plan())
        data = collect_review(self.project, self.destination)
        self.assertTrue(data["framing"]["available"])
        self.assertEqual(data["framing"]["unreportedShots"], [7])
        self.assertEqual(data["framing"]["shots"][0]["beats"][0]["projectedTextPx"], 8.5)
        self.assertTrue(data["verified"])
        self.assertEqual(data["warnings"], 0)
        self.assertIn("Framing report", {link["label"] for link in data["links"]})

    def test_framing_cannot_borrow_another_build_or_props(self):
        self.prepare_delivery()
        for change in ({"buildId": "different"}, {"propsSha256": "different"}):
            with self.subTest(change=change):
                self.write("out/demo-final.direction-plan.json", {**self.framing_plan(), **change})
                data = collect_review(self.project, self.destination)
                self.assertFalse(data["framing"]["available"])
                self.assertNotIn("shots", data["framing"])
                self.assertNotIn("Framing report", {link["label"] for link in data["links"]})

    def test_native_detail_downscale_keeps_bound_readability_report_and_unknown_text(self):
        self.prepare_delivery()
        plan = self.framing_plan()
        report = plan["shots"][0]["framingReport"]
        report.update(presentation="detail", status="unknown", findings=[{
            "severity": "info", "code": "FRAMING_TEXT_UNMEASURED",
            "message": "No glyph height was measured; text legibility is unknown."}])
        report["beats"][0].update(projectedTextPx=None, camera={"scale": 0.1961569490282362})
        self.write("out/demo-final.direction-plan.json", plan)
        data = collect_review(self.project, self.destination)
        self.assertTrue(data["framing"]["available"])
        shot = data["framing"]["shots"][0]
        self.assertEqual(shot["status"], "unknown")
        self.assertIsNone(shot["beats"][0]["projectedTextPx"])
        self.assertAlmostEqual(shot["beats"][0]["scale"], 0.1961569490282362)
        self.assertEqual(shot["findings"][0]["code"], "FRAMING_TEXT_UNMEASURED")
        self.assertIn("Framing report", {link["label"] for link in data["links"]})

    def test_native_detail_acceptance_does_not_relax_camera_or_invalid_scale_validation(self):
        self.prepare_delivery()
        for presentation, value in (("camera", 0.6), (None, 0.6), ("other", 0.6),
                                    ("detail", 0), ("detail", -0.1), ("detail", True),
                                    ("detail", float("nan")), ("detail", float("inf"))):
            with self.subTest(presentation=presentation, value=value):
                plan = self.framing_plan()
                report = plan["shots"][0]["framingReport"]
                if presentation is not None:
                    report["presentation"] = presentation
                report["beats"][0]["camera"]["scale"] = value
                self.write("out/demo-final.direction-plan.json", plan)
                self.assertFalse(collect_review(self.project, self.destination)["framing"]["available"])

    def test_framing_requires_the_actual_picture_and_rendered_props(self):
        video = self.prepare_delivery()
        self.write("out/demo-final.direction-plan.json", self.framing_plan())
        video.write_bytes(b"different picture")
        self.assertFalse(collect_review(self.project, self.destination)["framing"]["available"])
        video.write_bytes(b"test delivery")
        self.write("out/demo-final.props.json", {"fps": 60, "segments": []})
        self.assertFalse(collect_review(self.project, self.destination)["framing"]["available"])

    def test_unknown_or_malformed_framing_never_turns_into_a_readability_pass(self):
        self.prepare_delivery()
        self.assertFalse(collect_review(self.project, self.destination)["framing"]["available"])
        for value in (None, "large", float("nan"), -1):
            with self.subTest(value=value):
                plan = self.framing_plan()
                plan["shots"][0]["framingReport"]["viewerWidthPx"] = value
                self.write("out/demo-final.direction-plan.json", plan)
                data = collect_review(self.project, self.destination)
                self.assertFalse(data["framing"]["available"])
                self.assertTrue(data["verified"], "advisory failures must not affect media QA")

    def test_review_offers_actual_small_screen_sizes_and_bound_measurements(self):
        self.prepare_delivery()
        self.write("out/demo-final.direction-plan.json", self.framing_plan())
        write_review(self.project, self.destination, thumbnails=False)
        page = self.destination.read_text()
        self.assertIn('data-preview-width="320"', page)
        self.assertIn('data-preview-width="390"', page)
        self.assertIn('data-preview-width="0" aria-pressed="true"', page)
        self.assertIn('width:var(--preview-width,100%);max-width:100%', page)
        self.assertIn("Small-screen readability", page)


if __name__ == "__main__":
    unittest.main()
