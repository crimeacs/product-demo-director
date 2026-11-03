import hashlib
import io
import json
import os
import sys
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import Mock, patch

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "tools"))

from judge import (DEFAULT_MODEL, LIVE_RUBRIC, RUBRIC, _judge_config, _structural, calibrate, judge_video, main,
                   probe_paths, uploaded_video, validate_motion_review)  # noqa: E402


class JudgeModelTests(unittest.TestCase):
    def test_default_is_a_pinned_gemini_3_model(self):
        self.assertTrue(DEFAULT_MODEL.startswith("gemini-3"))
        self.assertNotIn("latest", DEFAULT_MODEL)

    def test_gemini_3_thinks_instead_of_forcing_temperature(self):
        from google.genai import types
        cfg = _judge_config(types, "gemini-3.1-pro-preview")
        self.assertIsNone(cfg.temperature)
        self.assertEqual("HIGH", cfg.thinking_config.thinking_level.name)
        self.assertEqual(0.0, _judge_config(types, "gemini-2.5-flash").temperature)


class JudgeProfileTests(unittest.TestCase):
    def setUp(self):
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        self.video = os.path.join(directory.name, "review.mp4")
        with open(self.video, "wb") as output:
            output.write(b"exact local media bytes used by the mocked provider")

    @staticmethod
    def fake_sdk():
        fake_types = SimpleNamespace(**{key: (lambda **kwargs: SimpleNamespace(**kwargs))
                                      for key in ("Part", "FileData", "VideoMetadata", "Content", "GenerateContentConfig")})
        fake_genai = SimpleNamespace(types=fake_types)
        return patch.dict(sys.modules, {"google": SimpleNamespace(genai=fake_genai), "google.genai": fake_genai})

    @staticmethod
    def client(response):
        client = Mock()
        uploaded = SimpleNamespace(name="files/review", state=SimpleNamespace(name="ACTIVE"),
                                   uri="fake://review", mime_type="video/mp4")
        client.files.upload.return_value = uploaded
        client.files.get.return_value = uploaded
        client.models.generate_content.return_value = response
        return client

    @staticmethod
    def motion_response():
        return {"overall": 18, "scores": {"motion_design": 30, "reading_holds": 65},
                "sequence_summary": "An input becomes a result, but the move begins before the viewer can read it.",
                "temporal_findings": [{"start_sec": 1.2, "end_sec": 1.8,
                    "layer": "camera", "severity": "major", "confidence": "high",
                    "observation": "The camera moves off the result while its text is being revealed.",
                    "viewer_effect": "The viewer cannot finish reading the result.",
                    "correction": {"change_class": "recut", "action": "Hold the result before moving."}}],
                "unverified": ["Individual source frames between samples cannot be assessed."],
                "would_keep_watching": False}

    def test_invalid_model_scores_and_types_are_not_calibrated_as_good(self):
        for scores in ({}, {"polish": 101}, {"polish": float("nan")}, {"polish": True}):
            with self.subTest(scores=scores), self.assertRaises(ValueError):
                calibrate({"scores": scores}, "")
        with self.assertRaises(ValueError):
            calibrate({"scores": {"polish": 90}, "would_keep_watching": "false"}, "")

    def test_uploaded_video_is_deleted_on_success_and_review_failure(self):
        for fails in (False, True):
            client = Mock()
            uploaded = SimpleNamespace(name="files/review", state=SimpleNamespace(name="ACTIVE"))
            client.files.upload.return_value = uploaded
            client.files.get.return_value = uploaded
            if fails:
                with self.assertRaisesRegex(RuntimeError, "review failed"):
                    with uploaded_video(client, "demo.mp4"):
                        raise RuntimeError("review failed")
            else:
                with uploaded_video(client, "demo.mp4") as result:
                    self.assertIs(result, uploaded)
            client.files.delete.assert_called_once_with(name="files/review")

    def test_processing_failure_or_timeout_never_yields_and_always_cleans_up(self):
        for state, error in (("FAILED", RuntimeError), ("PROCESSING", TimeoutError)):
            client = Mock()
            client.files.upload.return_value = SimpleNamespace(name="files/review")
            client.files.get.return_value = SimpleNamespace(state=SimpleNamespace(name=state))
            with patch("judge.time.sleep"), self.assertRaises(error):
                with uploaded_video(client, "demo.mp4"):
                    self.fail("review must not see a file that is not active")
            client.files.delete.assert_called_once_with(name="files/review")

    def test_invalid_sampling_is_rejected_before_upload(self):
        client = Mock()
        for fps, runs in ((0, 3), (float("nan"), 3), (float("inf"), 3), (24.0001, 3),
                          (True, 3), (None, 3), ("24", 3), (4, 0), (4, True)):
            with self.assertRaises(ValueError):
                judge_video(client, "demo.mp4", "", "", fps, "model", runs)
        client.files.upload.assert_not_called()

    def test_cli_rejects_invalid_sampling_before_credentials_or_client_creation(self):
        with patch.object(sys, "argv", ["judge.py", "--video", self.video, "--fps", "30"]), \
                patch("judge.get_key") as key, patch("sys.stderr", io.StringIO()), self.assertRaises(SystemExit) as stopped:
            main()
        self.assertEqual(2, stopped.exception.code)
        key.assert_not_called()

    def test_partial_review_is_visible_and_uses_lower_middle_run(self):
        client = Mock()
        uploaded = SimpleNamespace(name="files/review", state=SimpleNamespace(name="ACTIVE"),
                                   uri="fake://review", mime_type="video/mp4")
        client.files.upload.return_value = uploaded
        client.files.get.return_value = uploaded
        keys = ("non_repetition", "pace_rhythm", "visual_interest", "wow_moment", "hook_1s",
                "clarity_one_thing", "motion_design")
        def response(score):
            return SimpleNamespace(text=json.dumps({"scores": dict.fromkeys(keys, score)}))
        client.models.generate_content.side_effect = [response(30), RuntimeError("temporary failure"), response(90)]
        fake_types = SimpleNamespace(**{key: (lambda **kwargs: SimpleNamespace(**kwargs))
                                      for key in ("Part", "FileData", "VideoMetadata", "Content", "GenerateContentConfig")})
        fake_genai = SimpleNamespace(types=fake_types)
        with patch.dict(sys.modules, {"google": SimpleNamespace(genai=fake_genai), "google.genai": fake_genai}), \
                patch("builtins.print"), patch("judge.media_duration", return_value=4):
            result = judge_video(client, self.video, "", "", 4, "model", 3)
        self.assertEqual(result["overall"], 30)
        self.assertEqual(result["runs_overall"], [30, 90])
        self.assertEqual(result["review_status"], "partial")
        self.assertEqual(result["runs_completed"], 2)
        self.assertEqual(result["runs_requested"], 3)
        self.assertIn("temporary failure", result["run_errors"][0])
        attempts = result["review_receipt"]["attempts"]
        self.assertEqual(["complete", "provider_error", "complete"], [item["status"] for item in attempts])
        self.assertTrue(all(item["providerUsage"] is None for item in attempts))
        client.files.delete.assert_called_once_with(name="files/review")

    def test_motion_review_sends_actual_24fps_and_binds_media_models_and_provider_usage(self):
        usage = {"prompt_token_count": 210, "candidates_token_count": 80, "total_token_count": 290,
                 "prompt_tokens_details": [{"modality": "VIDEO", "token_count": 190}]}
        response = SimpleNamespace(text=json.dumps(self.motion_response()), model_version="provider-model-version",
                                   response_id="response-1", usage_metadata=SimpleNamespace(model_dump=lambda **kw: usage))
        client = self.client(response)
        with open(self.video, "rb") as video:
            expected_hash = hashlib.sha256(video.read()).hexdigest()
        artifact = {"path": "/bound/artifact.json", "sha256": expected_hash, "buildId": "build-1", "propsSha256": None}
        with self.fake_sdk(), patch("judge.media_duration", return_value=4):
            result = judge_video(client, self.video, "A recorded workflow", "", 24, "requested-model", 1,
                                 lenses=["motion"], artifact=artifact)
        sent = client.models.generate_content.call_args.kwargs
        self.assertEqual(24, sent["contents"].parts[0].video_metadata.fps)
        self.assertIn("complete temporal sequence", sent["contents"].parts[1].text)
        self.assertIn("nominal interval 0.041667 seconds", sent["contents"].parts[1].text)
        self.assertNotIn("DEFAULT is to click away", sent["contents"].parts[1].text)
        self.assertEqual(18, result["overall"])  # Low taste scores remain an advisory completed review.
        self.assertEqual("complete", result["review_status"])
        self.assertEqual("recut", result["temporal_findings"][0]["correction"]["change_class"])
        receipt = result["review_receipt"]
        self.assertEqual((24, 24, None), (receipt["requestedFps"], receipt["effectiveFps"], receipt["providerObservedFps"]))
        self.assertEqual(expected_hash, receipt["artifact"]["sha256"])
        self.assertEqual("build-1", receipt["artifact"]["buildId"])
        self.assertTrue(receipt["artifact"]["manifestVerified"])
        attempt = receipt["attempts"][0]
        self.assertEqual("requested-model", attempt["modelRequested"])
        self.assertEqual("provider-model-version", attempt["modelReturned"])
        self.assertEqual(usage, attempt["providerUsage"])
        self.assertEqual("response-1", attempt["responseId"])
        self.assertEqual(64, len(attempt["promptSha256"]))
        json.dumps(result, allow_nan=False)

    def test_motion_review_rejects_out_of_runtime_times_and_keeps_failed_response_usage(self):
        data = self.motion_response()
        data["temporal_findings"][0]["end_sec"] = 7
        client = self.client(SimpleNamespace(text=json.dumps(data), usage_metadata={"total_token_count": 27}))
        with self.fake_sdk(), patch("judge.media_duration", return_value=4), self.assertRaisesRegex(RuntimeError, "timestamps") as failed:
            judge_video(client, self.video, "", "", 24, "model", 1, lenses=["motion"])
        receipt = failed.exception.review_receipt
        self.assertEqual("failed", receipt["status"])
        self.assertEqual("invalid_response", receipt["attempts"][0]["status"])
        self.assertEqual({"total_token_count": 27}, receipt["attempts"][0]["providerUsage"])
        client.files.delete.assert_called_once_with(name="files/review")

    def test_motion_scores_share_explicit_100_point_units_and_are_not_rescaled(self):
        data = self.motion_response()
        data["overall"] = 65
        data["scores"] = {"motion_design": 6, "temporal_continuity": 8, "reading_holds": 7,
                          "source_fidelity": 3, "polish": 7}
        client = self.client(SimpleNamespace(text=json.dumps(data)))
        with self.fake_sdk(), patch("judge.media_duration", return_value=4):
            result = judge_video(client, self.video, "", "", 24, "model", 1, lenses=["motion"])
        prompt = client.models.generate_content.call_args.kwargs["contents"].parts[1].text
        self.assertIn("ALL score fields, including overall and every entry in scores", prompt)
        self.assertIn("integer values from 0 to 100", prompt)
        self.assertIn("Do not use a 0-10 scale", prompt)
        # A low score can be intentional; do not guess an alternate scale from its magnitude.
        self.assertEqual(65, result["overall"])
        self.assertEqual(data["scores"], result["scores"])

    def test_motion_findings_require_evidence_layer_and_actionable_correction(self):
        for field, value in [("layer", "effects"), ("observation", ""), ("viewer_effect", None),
                             ("start_sec", -1), ("end_sec", float("nan")), ("confidence", "certain"),
                             ("correction", {"change_class": "add-wow", "action": "More effects"})]:
            response = self.motion_response()
            response["temporal_findings"][0][field] = value
            with self.subTest(field=field), self.assertRaises(ValueError):
                validate_motion_review(response, 4)
        response = self.motion_response()
        response["temporal_findings"] = []
        self.assertEqual([], validate_motion_review(response, 4)["temporal_findings"])

    def test_changed_video_cannot_receive_a_successful_receipt(self):
        response = SimpleNamespace(text=json.dumps(self.motion_response()))
        client = self.client(response)
        def change_during_review(**kwargs):
            with open(self.video, "ab") as video:
                video.write(b"changed")
            return response
        client.models.generate_content.side_effect = change_during_review
        with self.fake_sdk(), patch("judge.media_duration", return_value=4), self.assertRaisesRegex(RuntimeError, "changed during review") as failed:
            judge_video(client, self.video, "", "", 24, "model", 1, lenses=["motion"])
        self.assertEqual("failed", failed.exception.review_receipt["status"])
        client.files.delete.assert_called_once_with(name="files/review")

    def test_upload_mutation_stops_before_any_provider_review(self):
        client = self.client(SimpleNamespace(text=json.dumps(self.motion_response())))
        def upload(**kwargs):
            with open(self.video, "ab") as video:
                video.write(b"changed while uploading")
            return SimpleNamespace(name="files/review")
        client.files.upload.side_effect = upload
        with patch("judge.media_duration", return_value=4), self.assertRaisesRegex(RuntimeError, "changed during review upload"):
            judge_video(client, self.video, "", "", 24, "model", 1, lenses=["motion"])
        client.models.generate_content.assert_not_called()
        client.files.delete.assert_called_once_with(name="files/review")

    def test_failed_cli_review_persists_its_receipt(self):
        path = os.path.join(os.path.dirname(self.video), "failed-review.json")
        failed = RuntimeError("invalid temporal response")
        failed.review_receipt = {"status": "failed", "requestedFps": 24, "effectiveFps": 24,
                                 "attempts": [{"providerUsage": {"total_token_count": 27}}]}
        sdk = SimpleNamespace(genai=SimpleNamespace(Client=Mock(return_value=Mock())))
        with patch.object(sys, "argv", ["judge.py", "--video", self.video, "--fps", "24", "--lens", "motion", "--out", path]), \
                patch.dict(sys.modules, {"google": sdk}), patch("judge.get_key", return_value="test-key"), \
                patch("judge.verify_artifact", return_value=None), patch("judge.judge_video", side_effect=failed), \
                patch("sys.stdout", io.StringIO()), self.assertRaises(SystemExit) as stopped:
            main()
        self.assertEqual(1, stopped.exception.code)
        with open(path) as saved:
            report = json.load(saved)
        self.assertEqual(failed.review_receipt, report["review_receipt"])

    def test_three_minute_live_product_has_no_arbitrary_short_promo_penalty(self):
        props = {"profile": "yc_3m", "segments": [
            {"kind": "clip", "durSec": 14.5, "src": "same.mp4", "stateId": f"s{i}", "storyBeat": f"b{i}"}
            for i in range(12)
        ]}
        self.assertEqual(_structural(props)[:2], (0, 0))

    def test_continuous_source_is_not_repetition_in_live_profile(self):
        props = {"profile": "investor", "segments": [
            {"kind": "clip", "durSec": 4, "src": "same.mp4", "stateId": "a", "storyBeat": "input"},
            {"kind": "clip", "durSec": 4, "src": "same.mp4", "stateId": "b", "storyBeat": "result"},
        ]}
        self.assertEqual(_structural(props)[0], 0)

    def test_replayed_identical_state_is_penalized(self):
        props = {"profile": "investor", "segments": [
            {"kind": "clip", "durSec": 4, "src": "a.mp4", "stateId": "done", "storyBeat": "payoff"},
            {"kind": "clip", "durSec": 4, "src": "b.mp4", "stateId": "done", "storyBeat": "payoff"},
        ]}
        self.assertEqual(_structural(props)[0], 6)

    def test_live_rubric_does_not_apply_short_feed_assumptions(self):
        self.assertIn("do not apply short social-ad assumptions", LIVE_RUBRIC)
        self.assertIn("DEFAULT is to click away", RUBRIC)

    def test_product_truth_failure_caps_live_demo(self):
        scores = {key: 95 for key in (
            "hook_1s", "pace_rhythm", "non_repetition", "visual_interest", "motion_design",
            "vo_performance", "sound_design", "clarity_one_thing", "proof_credibility",
            "polish", "wow_moment", "causal_progression", "authority_boundary")}
        scores["product_truth"] = 40
        data = {"overall": 95, "scores": scores, "repeated_elements": [], "dead_seconds": [],
                "would_keep_watching": True}
        with tempfile.TemporaryDirectory() as temp:
            props_path = os.path.join(temp, "props.json")
            with open(props_path, "w") as fh:
                json.dump({"profile": "yc_3m", "segments": [
                    {"kind": "clip", "durSec": 10, "stateId": "a", "storyBeat": "test"}
                ]}, fh)
            self.assertEqual(calibrate(data, props_path)["overall"], 49)

    def test_probe_uses_bundled_bad_and_requires_explicit_good_reference(self):
        bad, good = probe_paths()
        self.assertTrue(bad.endswith("examples/calibration/known_bad.mp4"))
        self.assertEqual(good, "")
        with tempfile.TemporaryDirectory() as temp:
            supplied = os.path.join(temp, "approved-final.mp4")
            _, good = probe_paths(supplied)
            self.assertEqual(good, os.path.abspath(supplied))


if __name__ == "__main__":
    unittest.main()
