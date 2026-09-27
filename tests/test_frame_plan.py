import os
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "tools"))

from build import compile_frame_plan, engine_input_paths, logo_source_path, stage_file, snapshot_inputs, load_json, verify_bound_code_inputs  # noqa: E402
from contracts import sha256_file  # noqa: E402


class FramePlanTests(unittest.TestCase):
    def test_total_is_sum_of_segment_rounding(self):
        segs = [
            {"n": 1, "kind": "clip", "durSec": 1.015},
            {"n": 2, "kind": "clip", "durSec": 1.015},
            {"n": 3, "kind": "cta", "durSec": 1.015},
        ]
        rows, total = compile_frame_plan(segs, 30)
        self.assertEqual(total, sum(row["frames"] for row in rows))
        self.assertEqual(rows[-1]["endFrame"], total)
        self.assertEqual(sum(seg["durFrames"] for seg in segs), total)

    def test_payout_v14_boundaries_are_exact(self):
        durations = [13.2, 16.5, 25.08, 14.9, 13.2, 22.138, 17.96, 10.76, 8.12, 8.38, 20.1, 4.36]
        segs = [{"n": i + 1, "kind": "clip" if i < 11 else "cta", "durSec": d}
                for i, d in enumerate(durations)]
        rows, total = compile_frame_plan(segs, 30)
        self.assertEqual(total, 5241)
        self.assertEqual(rows[-1]["startFrame"], 5110)

    def test_half_frames_match_javascript_rounding(self):
        segs = [{"n": 1, "kind": "clip", "durSec": 0.75}]
        _, total = compile_frame_plan(segs, 30)
        self.assertEqual(total, 23)

    def test_invalid_frame_rate_is_rejected_even_for_empty_timeline(self):
        for fps in (0, -30, float("nan"), float("inf"), True, "30"):
            with self.subTest(fps=fps), self.assertRaisesRegex(ValueError, "fps"):
                compile_frame_plan([], fps)

    def test_invalid_duration_is_rejected(self):
        for seconds in (0, -1, float("inf"), float("nan")):
            with self.subTest(seconds=seconds), self.assertRaisesRegex(ValueError, "shot 4"):
                compile_frame_plan([{"n": 4, "kind": "clip", "durSec": seconds}], 30)


class BuildStagingTests(unittest.TestCase):
    def test_code_guard_rejects_changed_or_missing_bound_code_and_preserves_delivery(self):
        for kind in ("engine", "builder"):
            for missing in (False, True):
                with self.subTest(kind=kind, missing=missing), tempfile.TemporaryDirectory() as directory:
                    root = Path(directory)
                    source = root / "source.py"
                    source.write_bytes(b"original")
                    records = [{"kind": kind, "name": "source.py", "path": str(source),
                                "sha256": sha256_file(str(source))}]
                    verify_bound_code_inputs(records)
                    prior_video, prior_artifact = root / "demo.mp4", root / "demo.artifact.json"
                    prior_video.write_bytes(b"previous delivery")
                    prior_artifact.write_bytes(b"previous receipt")
                    temporary = root / ".rendering.mp4"
                    temporary.write_bytes(b"unbound new render")
                    if missing:
                        source.unlink()
                    else:
                        source.write_bytes(b"modified")
                    with self.assertRaisesRegex(ValueError, "bound render code changed.*retry"):
                        verify_bound_code_inputs(records, str(temporary))
                    self.assertFalse(temporary.exists())
                    self.assertEqual(prior_video.read_bytes(), b"previous delivery")
                    self.assertEqual(prior_artifact.read_bytes(), b"previous receipt")

    def test_json_receipt_hashes_the_bytes_that_were_parsed(self):
        with tempfile.TemporaryDirectory() as directory:
            source = Path(directory) / "script.json"
            source.write_text('{"title": "original"}\n')
            hashes = {}
            parsed = load_json(str(source), hashes)
            expected = sha256_file(str(source))
            source.write_text('{"title": "changed"}\n')
            self.assertEqual("original", parsed["title"])
            self.assertEqual(expected, hashes[str(source)])
            self.assertNotEqual(sha256_file(str(source)), hashes[str(source)])

    def test_identical_asset_is_reused_and_changed_asset_is_replaced(self):
        with tempfile.TemporaryDirectory() as directory:
            source, destination = Path(directory) / "source", Path(directory) / "staged" / "asset"
            source.write_bytes(b"first")
            self.assertTrue(stage_file(str(source), str(destination)))
            initial = destination.stat()
            self.assertFalse(stage_file(str(source), str(destination)))
            self.assertEqual(destination.stat().st_mtime_ns, initial.st_mtime_ns)
            source.write_bytes(b"other")
            self.assertTrue(stage_file(str(source), str(destination)))
            self.assertEqual(destination.read_bytes(), b"other")

    def test_changed_source_does_not_publish_under_stale_build_identity(self):
        with tempfile.TemporaryDirectory() as directory:
            source, destination = Path(directory) / "source", Path(directory) / "asset"
            source.write_bytes(b"first")
            digest = sha256_file(str(source))
            destination.write_bytes(b"safe")
            source.write_bytes(b"changed during the build")
            with self.assertRaisesRegex(ValueError, "input changed"):
                stage_file(str(source), str(destination), digest)
            self.assertEqual(destination.read_bytes(), b"safe")
            self.assertEqual(sorted(path.name for path in Path(directory).iterdir()), ["asset", "source"])

    def test_engine_identity_includes_imported_modules_and_config(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "src" / "nested").mkdir(parents=True)
            for name in ("src/Timeline.tsx", "src/nested/timing.ts", "src/theme.css",
                         "remotion.config.ts", "package-lock.json"):
                (root / name).write_text("test")
            names = {str(Path(path).relative_to(root)) for path in engine_input_paths(directory)}
            self.assertEqual(names, {"src/Timeline.tsx", "src/nested/timing.ts", "src/theme.css",
                                     "remotion.config.ts", "package-lock.json"})

    def test_nested_logos_keep_their_source_directory(self):
        expected = os.path.join("/project", "assets", "brand", "mark.svg")
        self.assertEqual(logo_source_path("/project", "brand/mark.svg"), expected)
        self.assertEqual(logo_source_path("/project", "assets/brand/mark.svg"), expected)

    def test_project_relative_logo_fallback_preserves_assets_precedence(self):
        with tempfile.TemporaryDirectory() as directory:
            project = Path(directory)
            (project / "logo.png").write_bytes(b"root")
            self.assertEqual(logo_source_path(directory, "logo.png"), str(project / "logo.png"))
            (project / "assets").mkdir()
            (project / "assets" / "logo.png").write_bytes(b"asset")
            self.assertEqual(logo_source_path(directory, "logo.png"), str(project / "assets" / "logo.png"))

    def test_snapshot_retains_authored_timing_after_live_project_changes(self):
        with tempfile.TemporaryDirectory() as directory:
            project = Path(directory)
            timing = project / "timing.json"
            timing.write_bytes(b'{"words":["original"]}')
            video = project / "video.mp4"
            video.write_bytes(b"video")
            records = [{"kind": "narration-timing", "name": "timing.json", "path": str(timing), "sha256": sha256_file(str(timing))},
                       {"kind": "picture", "name": "video.mp4", "path": str(video), "sha256": sha256_file(str(video))}]
            snapshot_inputs(records, str(project / "build"), {str(video): str(video)})
            timing.write_bytes(b"new live edit")
            self.assertEqual(Path(records[0]["snapshotPath"]).read_bytes(), b'{"words":["original"]}')
            self.assertEqual(records[1]["snapshotPath"], str(video))


if __name__ == "__main__":
    unittest.main()
