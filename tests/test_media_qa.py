import json
import os
import shutil
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "tools"))

from contracts import sha256_file  # noqa: E402
from qa import (  # noqa: E402
    _outside_allowed,
    _ffmpeg_image,
    analysis_issues,
    audio_coverage_gaps,
    artifact_binding_issues,
    canonical_json_sha256,
    container_duration_tolerance,
    default_sidecar_path,
    loudness_issues,
    parse_black,
    parse_loudness,
    parse_silence,
)
import qa  # noqa: E402


class MediaQaParserTests(unittest.TestCase):
    def test_failed_or_incomplete_analysis_cannot_pass(self):
        loudness = {"integratedLufs": -18.0, "loudnessRangeLu": 3.3, "truePeakDbtp": -1.5}
        failed = subprocess.CompletedProcess([], 1, "", "filter failed")
        self.assertEqual(analysis_issues(failed, loudness)[0]["code"], "MEDIA_ANALYSIS_FAILED")
        complete = subprocess.CompletedProcess([], 0, "", "")
        self.assertEqual(analysis_issues(complete, loudness), [])
        for missing in (None, float("nan"), float("inf")):
            self.assertEqual(analysis_issues(complete, {**loudness, "truePeakDbtp": missing})[0]["code"],
                             "LOUDNESS_MEASUREMENT_MISSING")

    def test_audio_coverage_checks_leading_and_trailing_absence(self):
        gaps = audio_coverage_gaps({"start_time": "1", "duration": "7"}, 10, 30)
        self.assertEqual(gaps, [
            {"startSec": 0.0, "endSec": 1.0, "durationSec": 1.0},
            {"startSec": 8.0, "endSec": 10, "durationSec": 2.0},
        ])
        self.assertEqual(_outside_allowed(gaps, [{"startSec": 0, "endSec": 1},
                                                {"startSec": 8, "endSec": 10}]), [])
        self.assertEqual(audio_coverage_gaps({"duration": "9.99"}, 10, 30), [])

    def test_nonfinite_loudness_contract_cannot_disable_the_gate(self):
        measured = {"integratedLufs": -30, "truePeakDbtp": 0}
        for contract in ({"targetLufs": "NaN"}, {"maxTruePeakDbtp": float("inf")},
                         {"targetLufs": -18, "lufsTolerance": float("nan")}, {"lufsTolerance": -1}):
            self.assertEqual(loudness_issues(measured, contract)[0]["code"], "QA_LOUDNESS_CONFIG_INVALID")
        self.assertEqual({item["code"] for item in loudness_issues(
            measured, {"targetLufs": -18, "maxTruePeakDbtp": -1.5})},
            {"LOUDNESS_OUT_OF_RANGE", "TRUE_PEAK_HIGH"})

    def test_stale_proof_image_cannot_mask_empty_ffmpeg_output(self):
        with tempfile.TemporaryDirectory() as temp:
            path = os.path.join(temp, "proof.png")
            with open(path, "wb") as fh:
                fh.write(b"old proof")
            with patch("qa.run"):
                with self.assertRaisesRegex(RuntimeError, "no image"):
                    _ffmpeg_image("video.mp4", "trim=start=999", path)

    def test_failed_analysis_writes_failing_strict_report(self):
        with tempfile.TemporaryDirectory() as temp:
            video = os.path.join(temp, "demo.mp4")
            with open(video, "wb") as fh:
                fh.write(b"video")
            probe = {"format": {"duration": "1"}, "streams": [
                {"codec_type": "video", "nb_read_frames": "30", "avg_frame_rate": "30/1"},
                {"codec_type": "audio"},
            ]}
            with patch.object(sys, "argv", ["qa.py", "--video", video, "--strict", "--no-visuals"]), \
                    patch("qa.ffprobe", return_value=probe), patch("qa.shutil.which", return_value="available"), \
                    patch("qa.analyze_media", return_value=subprocess.CompletedProcess([], 1, "", "filter failed")), \
                    patch("builtins.print"):
                with self.assertRaises(SystemExit) as raised:
                    qa.main()
            self.assertEqual(raised.exception.code, 1)
            with open(os.path.join(temp, "qa-demo", "qa-report.json")) as fh:
                report = json.load(fh)
            self.assertEqual(report["status"], "fail")
            self.assertEqual(report["fullDecode"], "fail")
            self.assertIn("MEDIA_ANALYSIS_FAILED", [issue["code"] for issue in report["issues"]])

    def test_black_intervals(self):
        text = "black_start:2.1 black_end:2.5 black_duration:0.4"
        self.assertEqual(parse_black(text)[0]["durationSec"], 0.4)

    def test_silence_intervals(self):
        text = "silence_start: 10.7\nsilence_end: 12.2 | silence_duration: 1.5"
        self.assertEqual(parse_silence(text), [{"startSec": 10.7, "endSec": 12.2, "durationSec": 1.5}])

    def test_scientific_notation_in_audio_timestamps_is_preserved(self):
        text = "silence_start: 2.08333e-05\nsilence_end: 1 | silence_duration: 0.999979"
        self.assertAlmostEqual(parse_silence(text)[0]["startSec"], 0.0000208333)

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


@unittest.skipUnless(shutil.which("ffmpeg") and shutil.which("ffprobe"), "FFmpeg is required")
class MediaQaIntegrationTests(unittest.TestCase):
    def test_audio_ending_before_picture_is_detected_as_unintended_silence(self):
        with tempfile.TemporaryDirectory() as temp:
            video = os.path.join(temp, "missing-tail.mp4")
            subprocess.run([
                "ffmpeg", "-v", "error", "-f", "lavfi", "-i", "color=c=blue:s=160x90:r=30:d=2",
                "-f", "lavfi", "-i", "sine=frequency=440:sample_rate=48000:duration=1",
                "-c:v", "libx264", "-pix_fmt", "yuv420p", "-c:a", "aac", video,
            ], check=True, capture_output=True)
            result = subprocess.run([sys.executable, qa.__file__, "--video", video, "--strict", "--no-visuals"],
                                    capture_output=True, text=True)
            self.assertEqual(result.returncode, 1, result.stdout + result.stderr)
            with open(os.path.join(temp, "qa-missing-tail", "qa-report.json")) as fh:
                report = json.load(fh)
            self.assertEqual(len(report["audio"]["coverageGaps"]), 1)
            self.assertIn("UNINTENDED_SILENCE", [issue["code"] for issue in report["issues"]])

    def test_black_and_silence_are_both_detected_in_the_combined_pass(self):
        with tempfile.TemporaryDirectory() as temp:
            video = os.path.join(temp, "broken.mp4")
            subprocess.run([
                "ffmpeg", "-v", "error", "-f", "lavfi", "-i", "color=c=black:s=160x90:r=30:d=1",
                "-f", "lavfi", "-i", "anullsrc=r=48000:cl=stereo:d=1",
                "-c:v", "libx264", "-pix_fmt", "yuv420p", "-c:a", "aac", "-shortest", video,
            ], check=True, capture_output=True)
            result = subprocess.run([sys.executable, qa.__file__, "--video", video, "--strict", "--no-visuals"],
                                    capture_output=True, text=True)
            self.assertEqual(result.returncode, 1, result.stdout + result.stderr)
            with open(os.path.join(temp, "qa-broken", "qa-report.json")) as fh:
                report = json.load(fh)
            codes = {issue["code"] for issue in report["issues"]}
            self.assertTrue({"BLACK_INTERVALS", "UNINTENDED_SILENCE"} <= codes, codes)

    def test_one_second_video_has_real_proof_sheets_and_audio_measurements(self):
        with tempfile.TemporaryDirectory() as temp:
            video = os.path.join(temp, "short.mp4")
            subprocess.run([
                "ffmpeg", "-v", "error", "-f", "lavfi", "-i", "color=c=blue:s=160x90:r=30:d=1",
                "-f", "lavfi", "-i", "sine=frequency=440:sample_rate=48000:duration=1",
                "-c:v", "libx264", "-pix_fmt", "yuv420p", "-c:a", "aac", "-shortest", video,
            ], check=True, capture_output=True)
            result = subprocess.run([sys.executable, qa.__file__, "--video", video, "--strict"],
                                    capture_output=True, text=True)
            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
            with open(os.path.join(temp, "qa-short", "qa-report.json")) as fh:
                report = json.load(fh)
            self.assertEqual(report["status"], "pass")
            self.assertIsNotNone(report["audio"]["integratedLufs"])
            for key in ("every5Seconds", "opening", "ending"):
                self.assertGreater(os.path.getsize(report["visualQa"][key]), 0)


if __name__ == "__main__":
    unittest.main()
