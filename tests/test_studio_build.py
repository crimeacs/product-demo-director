"""Exercise the real dry-build boundary: script -> validated, staged, bound studio props."""

import hashlib
import json
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import unittest
import wave


ROOT = Path(__file__).resolve().parents[1]
BUILD = ROOT / "tools" / "build.py"


def digest(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


class StudioBuildTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.fixture_directory = tempfile.TemporaryDirectory()
        cls.addClassCleanup(cls.fixture_directory.cleanup)
        cls.source = Path(cls.fixture_directory.name) / "source.mp4"
        cls.media_available = bool(shutil.which("ffmpeg") and shutil.which("ffprobe"))
        if cls.media_available:
            result = subprocess.run(
                ["ffmpeg", "-v", "error", "-f", "lavfi", "-i", "color=c=0x38504a:s=64x36:r=30:d=2.5",
                 "-an", "-c:v", "libx264", "-pix_fmt", "yuv420p", str(cls.source)],
                capture_output=True, text=True, timeout=30,
            )
            if result.returncode:
                raise AssertionError(f"Could not create test footage: {result.stderr}")

    def setUp(self):
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        self.workspace = Path(directory.name)
        self.project = self.workspace / "project"
        self.project.mkdir()
        self.engine = self.workspace / "engine"
        (self.engine / "src").mkdir(parents=True)
        # Dry builds bind the engine but do not launch it. This fixture isolates the tests from
        # downloaded fonts, npm installation, public sample media, and concurrent engine edits.
        (self.engine / "package-lock.json").write_text('{"name":"dry-build-fixture","lockfileVersion":3}\n')
        (self.engine / "src" / "fixture.ts").write_text("export const dryBuildFixture = true;\n")

    def write_script(self, script):
        path = self.project / "script.json"
        path.write_text(json.dumps(script, indent=2) + "\n")
        return path

    def add_source(self):
        if not self.media_available:
            self.skipTest("ffmpeg and ffprobe are required for source staging integration")
        assets = self.project / "assets"
        assets.mkdir(exist_ok=True)
        destination = assets / "source.mp4"
        shutil.copyfile(self.source, destination)
        return destination

    def build(self, *extra):
        result = subprocess.run(
            [sys.executable, str(BUILD), "--project", str(self.project), "--engine", str(self.engine),
             "--dry", "--contracts", "strict", *extra],
            cwd=ROOT, capture_output=True, text=True, timeout=30,
        )
        self.assertEqual(0, result.returncode, result.stdout + "\n" + result.stderr)
        out = self.project / "out"
        return tuple(json.loads((out / name).read_text()) for name in
                     ("props.json", "build-plan.json", "direction-plan.json"))

    @staticmethod
    def studio_script():
        return {
            "fps": 30,
            "creativeDirection": {"style": "studio", "tone": "precise", "soundDesign": "sparse"},
            "shots": [
                {"n": 1, "kind": "title", "title": "Follow the source", "durSec": 1},
                {"n": 2, "kind": "clip", "src": "source.mp4", "inSec": 0.25, "durSec": 2,
                 "sourceType": "product", "liveState": True},
                {"n": 3, "kind": "cta", "title": "Inspect the result", "durSec": 1.5},
            ],
        }

    def test_studio_build_stages_repeatable_procedural_sound_and_binds_direction_plan(self):
        source = self.add_source()
        self.write_script(self.studio_script())
        props, plan, direction = self.build()

        self.assertEqual("reveal", props["segments"][1]["transition"])
        self.assertEqual({"studio_air", "studio_resolve"}, set(props["sfx"]))
        self.assertEqual("compiled", direction["status"])
        self.assertEqual(props["buildId"], plan["buildId"])
        self.assertEqual(plan["buildId"], direction["buildId"])
        canonical = json.dumps(props, sort_keys=True, separators=(",", ":")).encode()
        expected_props_hash = hashlib.sha256(canonical).hexdigest()
        self.assertEqual(expected_props_hash, plan["propsSha256"])
        self.assertEqual(expected_props_hash, direction["propsSha256"])
        self.assertEqual(props["totalFrames"], direction["totalFrames"])
        self.assertEqual([1, 2, 3], [shot["n"] for shot in direction["shots"]])

        staged = Path(plan["publicDir"])
        self.assertEqual(digest(source), digest(staged / props["segments"][1]["src"]))
        bound_sfx = {entry["name"]: entry for entry in plan["inputs"] if entry["kind"] == "sfx"}
        original_hashes = {}
        for name, relative in props["sfx"].items():
            path = staged / relative
            self.assertTrue(path.is_file())
            with wave.open(str(path)) as cue:
                self.assertEqual(48000, cue.getframerate())
                self.assertEqual(2, cue.getnchannels())
                self.assertGreater(cue.getnframes(), 0)
            original_hashes[name] = digest(path)
            self.assertEqual(original_hashes[name], bound_sfx[relative]["sha256"])
            # A stale cached cue must be regenerated, then rebound to the same deterministic bytes.
            (self.project / "out" / "sound-library" / path.name).write_bytes(b"stale cue")

        rebuilt_props, rebuilt_plan, rebuilt_direction = self.build()
        self.assertEqual(props, rebuilt_props)
        self.assertEqual(plan["buildId"], rebuilt_plan["buildId"])
        self.assertEqual(direction["propsSha256"], rebuilt_direction["propsSha256"])
        for name, relative in rebuilt_props["sfx"].items():
            self.assertEqual(original_hashes[name], digest(Path(rebuilt_plan["publicDir"]) / relative))

    def test_silent_studio_ignores_missing_legacy_accent_and_authored_cues(self):
        script = {
            "fps": 30,
            "creativeDirection": {"style": "studio", "soundDesign": "silent"},
            "shots": [{"n": 1, "kind": "cta", "title": "Keep the evidence", "durSec": 2,
                       "accent": "impact",
                       "soundCues": [{"atSec": 0.5, "sound": "studio_tick", "volume": 0.2}]}],
        }
        self.write_script(script)
        self.assertFalse((self.engine / "public" / "sfx" / "impact.mp3").exists())
        props, plan, direction = self.build()
        self.assertEqual({}, props["sfx"])
        self.assertNotIn("accent", props["segments"][0])
        self.assertEqual([], props["segments"][0]["soundCues"])
        self.assertEqual([], direction["shots"][0]["soundCues"])
        self.assertFalse(any(entry["kind"] == "sfx" for entry in plan["inputs"]))

    def test_source_window_is_bound_without_rewriting_source_camera_or_timing(self):
        source = self.add_source()
        script = self.studio_script()
        shot = script["shots"][1]
        shot.update(sourceWindow={"x": 25, "y": 20, "width": 50, "height": 60},
                    camera=[{"atSec": 0, "scale": 1}, {"atSec": 1, "scale": 2, "focusX": 50, "focusY": 50}])
        path = self.write_script(script)
        original = path.read_bytes()
        props, plan, direction = self.build()
        seg = props["segments"][1]
        self.assertEqual(shot["sourceWindow"], seg["sourceWindow"])
        self.assertEqual(shot["sourceWindow"], direction["shots"][1]["sourceWindow"])
        self.assertEqual(shot["camera"], seg["camera"])
        self.assertEqual((64, 36), (seg["sourceWidth"], seg["sourceHeight"]))
        self.assertEqual(shot["inSec"], seg["inSec"])
        self.assertEqual(digest(source), digest(Path(plan["publicDir"]) / seg["src"]))
        self.assertEqual(original, path.read_bytes())

    def test_build_preserves_authored_narration_and_source_script(self):
        if not shutil.which("ffprobe"):
            self.skipTest("ffprobe is required to verify the supplied narration master")
        audio = self.project / "audio"
        audio.mkdir()
        master = audio / "master.wav"
        with wave.open(str(master), "wb") as output:
            output.setnchannels(1)
            output.setsampwidth(2)
            output.setframerate(24000)
            output.writeframes(b"\x00\x00" * 12000)
        script = {
            "fps": 30,
            "creativeDirection": {"style": "studio", "soundDesign": "silent"},
            "narration": {"file": "audio/master.wav", "text": "Evidence stays intact.", "volume": 0.8},
            "narrationMap": [{"shotN": 1, "startSec": 0, "endSec": 0.5,
                              "text": "Evidence stays intact.", "beat": "resolve"}],
            "shots": [{"n": 1, "kind": "cta", "title": "Read the evidence", "durSec": 2}],
        }
        script_path = self.write_script(script)
        script_before, narration_before = script_path.read_bytes(), master.read_bytes()
        props, plan, _ = self.build()
        self.assertEqual(script_before, script_path.read_bytes())
        self.assertEqual(narration_before, master.read_bytes())
        self.assertEqual(0.8, props["narration"]["volume"])
        self.assertAlmostEqual(0.5, props["narration"]["durationSec"])
        self.assertEqual(narration_before, (Path(plan["publicDir"]) / props["narration"]["src"]).read_bytes())
        self.assertEqual(script["narrationMap"], json.loads(script_path.read_text())["narrationMap"])

    def test_authored_transition_durations_reach_props_and_bound_plan(self):
        script = {
            "fps": 30,
            "creativeDirection": {"style": "studio", "soundDesign": "silent"},
            "shots": [
                {"n": 1, "kind": "title", "title": "A question", "durSec": 2},
                {"n": 2, "kind": "title", "title": "An explanation", "durSec": 2,
                 "transition": "reveal", "transitionSec": 0.8},
                {"n": 3, "kind": "cta", "title": "A result", "durSec": 1,
                 "transition": "push", "transitionSec": 0.4},
            ],
        }
        self.write_script(script)
        props, _, direction = self.build()
        for index, (kind, duration) in enumerate((("reveal", 0.8), ("push", 0.4)), 1):
            for shot in (props["segments"][index], direction["shots"][index]):
                self.assertEqual(kind, shot["transition"])
                self.assertAlmostEqual(duration, shot["transitionSec"])

    def test_legacy_scripts_keep_three_tenths_crossfade_without_studio_sounds(self):
        script = {
            "fps": 30,
            "shots": [{"n": 1, "kind": "title", "title": "Start", "durSec": 1},
                      {"n": 2, "kind": "cta", "title": "Finish", "durSec": 2}],
        }
        self.write_script(script)
        props, _, direction = self.build()
        self.assertEqual("classic", direction["style"])
        self.assertFalse(props["segments"][1]["studio"])
        self.assertEqual("xfade", props["segments"][1]["transition"])
        self.assertAlmostEqual(0.3, props["segments"][1]["transitionSec"])
        self.assertEqual({}, props["sfx"])
        self.assertEqual([], props["segments"][1]["soundCues"])

    def test_fps_override_controls_motion_entry_frame_budget(self):
        self.write_script({"fps": 30, "creativeDirection": {"style": "studio", "soundDesign": "silent"},
                           "shots": [{"n": 1, "kind": "title", "title": "First", "durSec": 1},
                                     {"n": 2, "kind": "title", "title": "Insert", "durSec": 0.05,
                                      "transition": "reveal", "transitionSec": 0.5}]})
        props, _, direction = self.build("--fps", "60")
        self.assertEqual(60, direction["fps"])
        self.assertEqual(3, props["segments"][1]["durFrames"])
        self.assertAlmostEqual(2 / 60, props["segments"][1]["transitionSec"])

    def test_source_map_compiles_holds_and_binds_editorial_and_source_snapshots(self):
        self.add_source()
        script = self.studio_script()
        shot = script["shots"][1]
        shot.update(inSec=0.25, durSec=3, sourceTimeline=[
            {"fromSec": 0.25, "toSec": 1.25, "durSec": 1, "mode": "realtime"},
            {"fromSec": 1.25, "toSec": 1.25, "durSec": 1.5, "mode": "hold"},
            {"fromSec": 1.25, "toSec": 2.25, "durSec": 0.5, "mode": "navigation"},
        ], sourceBeats=[{"id": "visible-proof", "sourceSec": 1.25, "kind": "proof",
                         "leadInSec": 0.5, "readHoldSec": 1.5}])
        self.write_script(script)
        props, plan, direction = self.build()
        spans = props["segments"][1]["sourcePlan"]
        self.assertEqual([30, 45, 15], [span["frames"] for span in spans])
        self.assertEqual([1, 0, 2], [span["playbackRate"] for span in spans])
        self.assertEqual(spans, direction["shots"][1]["sourcePlan"])
        editorial = json.loads((self.project / "out" / "editorial-report.json").read_text())
        self.assertTrue(editorial["advisory"])
        self.assertEqual(plan["propsSha256"], editorial["propsSha256"])
        self.assertEqual(plan["buildId"], editorial["buildId"])
        self.assertAlmostEqual(2, editorial["metrics"]["firstDeclaredProofSec"])
        for record in plan["inputs"]:
            self.assertEqual(record["sha256"], digest(record["snapshotPath"]))

    def test_voice_extension_cannot_silently_stretch_a_source_timeline(self):
        self.add_source()
        audio = self.project / "audio"
        audio.mkdir()
        with wave.open(str(audio / "s2.wav"), "wb") as output:
            output.setnchannels(1)
            output.setsampwidth(2)
            output.setframerate(24000)
            output.writeframes(b"\x00\x00" * 72000)
        (audio / "manifest.json").write_text(json.dumps([{"n": 2, "file": "s2.wav", "seconds": 3}]))
        script = self.studio_script()
        script["shots"][1]["sourceTimeline"] = [
            {"fromSec": 0.25, "toSec": 2.25, "durSec": 2, "mode": "realtime"}]
        self.write_script(script)
        result = subprocess.run([sys.executable, str(BUILD), "--project", str(self.project),
                                 "--engine", str(self.engine), "--dry", "--contracts", "off"],
                                capture_output=True, text=True, timeout=30)
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("SOURCE_TIMELINE_DURATION", result.stdout + result.stderr)

    def test_optional_editorial_audit_preserves_legacy_unassigned_narration_cues(self):
        self.write_script({"fps": 30,
                           "shots": [{"n": 1, "kind": "title", "title": "Evidence", "durSec": 2}],
                           "narrationMap": [{"text": "Evidence.", "beat": "proof", "startSec": 0,
                                             "endSec": 1}]})
        props, _, _ = self.build()
        self.assertEqual(60, props["totalFrames"])
        report = json.loads((self.project / "out" / "editorial-report.json").read_text())
        self.assertTrue(report["advisory"])
        self.assertNotEqual("clear-declared", report["status"])

    def test_fps_override_applies_to_source_map_preflight(self):
        self.add_source()
        self.write_script({"fps": 24, "shots": [
            {"n": 1, "kind": "clip", "src": "source.mp4", "inSec": 0, "durSec": 0.05,
             "sourceTimeline": [
                 {"fromSec": 0, "toSec": 0.025, "durSec": 0.025, "mode": "realtime"},
                 {"fromSec": 0.025, "toSec": 0.05, "durSec": 0.025, "mode": "realtime"}]}]})
        props, _, _ = self.build("--fps", "60")
        self.assertEqual([2, 1], [span["frames"] for span in props["segments"][0]["sourcePlan"]])

    def test_measured_closeup_build_binds_geometry_report_code_and_authored_inputs(self):
        self.add_source()
        script = self.studio_script()
        shot = script["shots"][1]
        shot.update(caption="Recorded evidence", captionFontSize=72, framing={
            "sourceWidth": 64, "sourceHeight": 36, "viewerWidthPx": 320, "minTextPx": 12,
            "beats": [{"atSec": 0, "endSec": 2, "textHeightPx": 1,
                       "rect": {"x": 40, "y": 40, "width": 20, "height": 20}}],
        })
        script_path = self.write_script(script)
        authored_bytes = script_path.read_bytes()
        props, plan, direction = self.build()
        segment = props["segments"][1]
        self.assertGreater(segment["camera"][0]["scale"], 3)
        self.assertAlmostEqual(4.4, segment["camera"][0]["scale"])
        self.assertEqual(segment["camera"], direction["shots"][1]["camera"])
        self.assertEqual((64, 36), (segment["sourceWidth"], segment["sourceHeight"]))
        self.assertEqual(72, segment["captionFontSize"])
        self.assertEqual(authored_bytes, script_path.read_bytes())
        self.assertNotIn("camera", json.loads(script_path.read_text())["shots"][1])

        report = direction["shots"][1]["framingReport"]
        self.assertTrue(report["advisory"])
        self.assertEqual("needs-review", report["status"])
        self.assertIn("FRAMING_OUTPUT_MAGNIFIED", {item["code"] for item in report["findings"]})
        self.assertAlmostEqual(22, report["beats"][0]["projectedTextPx"])
        self.assertEqual(plan["buildId"], direction["buildId"])
        self.assertEqual(plan["propsSha256"], direction["propsSha256"])
        dependency = next(record for record in plan["inputs"] if record["name"] == "tools/framing.py")
        self.assertEqual(digest(ROOT / "tools" / "framing.py"), dependency["sha256"])
        self.assertEqual(dependency["sha256"], digest(dependency["snapshotPath"]))

    def test_framing_dimension_mismatch_is_rejected_even_with_contracts_disabled(self):
        self.add_source()
        script = self.studio_script()
        script["shots"][1]["framing"] = {
            "sourceWidth": 1920, "sourceHeight": 1080,
            "beats": [{"atSec": 0, "endSec": 2,
                       "rect": {"x": 40, "y": 40, "width": 20, "height": 20}}],
        }
        script_path = self.write_script(script)
        authored_bytes = script_path.read_bytes()
        result = subprocess.run([sys.executable, str(BUILD), "--project", str(self.project),
                                 "--engine", str(self.engine), "--dry", "--contracts", "off"],
                                cwd=ROOT, capture_output=True, text=True, timeout=30)
        self.assertNotEqual(0, result.returncode)
        self.assertIn("framing source dimensions do not match the probed display geometry", result.stderr)
        self.assertEqual(authored_bytes, script_path.read_bytes())
        self.assertFalse((self.project / "out" / "props.json").exists())

    def test_small_text_remains_advisory_under_strict_technical_contracts(self):
        self.add_source()
        script = self.studio_script()
        script["shots"][1]["framing"] = {
            "sourceWidth": 64, "sourceHeight": 36,
            "beats": [{"atSec": 0, "endSec": 2, "textHeightPx": 1,
                       "rect": {"x": 10, "y": 10, "width": 80, "height": 80}}],
        }
        self.write_script(script)
        result = subprocess.run([sys.executable, str(BUILD), "--project", str(self.project),
                                 "--engine", str(self.engine), "--dry", "--contracts", "strict"],
                                cwd=ROOT, capture_output=True, text=True, timeout=30)
        self.assertEqual(0, result.returncode, result.stdout + result.stderr)
        self.assertIn("FRAMING advisory shot 2: FRAMING_TEXT_TOO_SMALL", result.stdout)
        direction = json.loads((self.project / "out" / "direction-plan.json").read_text())
        report = direction["shots"][1]["framingReport"]
        self.assertEqual("needs-review", report["status"])
        self.assertAlmostEqual(5.5, report["beats"][0]["projectedTextPx"])

    def test_detail_build_preserves_native_region_source_timing_and_composition_metadata(self):
        source = self.add_source()
        script = self.studio_script()
        shot = script["shots"][1]
        shot.update(title="Saved policy", eyebrow="Recorded product", caption="Complete native component",
                    sourceTimeline=[
                        {"fromSec": 0.25, "toSec": 1.25, "durSec": 1, "mode": "realtime"},
                        {"fromSec": 1.25, "toSec": 1.25, "durSec": 1, "mode": "hold"}],
                    framing={"presentation": "detail", "sourceWidth": 64, "sourceHeight": 36,
                             "screenRect": {"x": 10, "y": 25, "width": 80, "height": 50},
                             "beats": [{"atSec": 0, "endSec": 2, "textHeightPx": 3,
                                        "rect": {"x": 25, "y": 25, "width": 50, "height": 50}}]})
        path = self.write_script(script)
        authored_bytes = path.read_bytes()
        props, plan, direction = self.build()
        segment, directed = props["segments"][1], direction["shots"][1]
        expected_detail = {"sourceRect": {"x": 25, "y": 25, "width": 50, "height": 50},
                           "screenRect": {"x": 10, "y": 25, "width": 80, "height": 50},
                           "entranceSec": 0.4, "radiusPx": 0}
        self.assertEqual(expected_detail, segment["sourceDetail"])
        self.assertEqual(expected_detail, directed["sourceDetail"])
        self.assertEqual([], segment["camera"])
        self.assertEqual([], directed["camera"])
        self.assertEqual((64, 36), (segment["sourceWidth"], segment["sourceHeight"]))
        self.assertEqual("Saved policy", segment["title"])
        self.assertEqual("Recorded product", segment["eyebrow"])
        self.assertEqual("Complete native component", segment["caption"])
        self.assertEqual([False, True], [span["hold"] for span in segment["sourcePlan"]])
        self.assertEqual([0.25, 1.25], [span["sourceStartSec"] for span in segment["sourcePlan"]])
        self.assertEqual(digest(source), digest(Path(plan["publicDir"]) / segment["src"]))
        self.assertEqual(authored_bytes, path.read_bytes())
        report = directed["framingReport"]
        self.assertEqual("detail", report["presentation"])
        self.assertEqual(expected_detail, report["sourceDetail"])
        self.assertAlmostEqual(30, report["beats"][0]["sourceToOutputScale"])
        self.assertAlmostEqual(15, report["beats"][0]["projectedTextPx"])
        self.assertEqual(plan["buildId"], direction["buildId"])
        self.assertEqual(plan["propsSha256"], direction["propsSha256"])

    def test_detail_build_rejects_masking_away_a_supplied_recorded_click(self):
        self.add_source()
        script = self.studio_script()
        script["shots"][1]["framing"] = {
            "presentation": "detail", "sourceWidth": 64, "sourceHeight": 36,
            "beats": [{"atSec": 0, "endSec": 2,
                       "rect": {"x": 25, "y": 25, "width": 50, "height": 50}}]}
        self.write_script(script)
        (self.project / "assets" / "source.events.json").write_text(json.dumps({
            "schemaVersion": 2, "timebase": "edited-media-seconds",
            "events": [{"type": "click", "t": 1, "xPct": 90, "yPct": 50}],
        }))
        result = subprocess.run([sys.executable, str(BUILD), "--project", str(self.project),
                                 "--engine", str(self.engine), "--dry", "--contracts", "strict"],
                                cwd=ROOT, capture_output=True, text=True, timeout=30)
        self.assertNotEqual(0, result.returncode)
        self.assertIn("CURSOR_DETAIL_CROP", result.stdout + result.stderr)
        self.assertFalse((self.project / "out" / "props.json").exists())

    def test_detail_full_shot_span_follows_canonical_frames_without_rewriting_script(self):
        self.add_source()
        for duration, frames in ((2.01, 60), (2.02, 61)):
            with self.subTest(duration=duration):
                script = self.studio_script()
                shot = script["shots"][1]
                shot.update(durSec=duration, framing={
                    "presentation": "detail", "sourceWidth": 64, "sourceHeight": 36,
                    "beats": [{"atSec": 0, "endSec": duration,
                               "rect": {"x": 25, "y": 25, "width": 50, "height": 50}}]})
                path = self.write_script(script)
                authored_bytes = path.read_bytes()
                props, plan, direction = self.build()
                segment = props["segments"][1]
                self.assertEqual(frames, segment["durFrames"])
                self.assertEqual(frames / 30, segment["durSec"])
                self.assertEqual(frames, plan["segments"][1]["frames"])
                self.assertEqual(frames / 30, direction["shots"][1]["framingReport"]["beats"][0]["endSec"])
                self.assertEqual(authored_bytes, path.read_bytes())

    def test_detail_partial_span_is_not_repaired_by_frame_normalization(self):
        self.add_source()
        script = self.studio_script()
        script["shots"][1].update(durSec=2.01, framing={
            "presentation": "detail", "sourceWidth": 64, "sourceHeight": 36,
            "beats": [{"atSec": 0, "endSec": 2,
                       "rect": {"x": 25, "y": 25, "width": 50, "height": 50}}]})
        path = self.write_script(script)
        authored_bytes = path.read_bytes()
        result = subprocess.run([sys.executable, str(BUILD), "--project", str(self.project),
                                 "--engine", str(self.engine), "--dry", "--contracts", "off"],
                                cwd=ROOT, capture_output=True, text=True, timeout=30)
        self.assertNotEqual(0, result.returncode)
        self.assertIn("FRAMING_DETAIL_TIMING_INVALID", result.stdout + result.stderr)
        self.assertFalse((self.project / "out" / "props.json").exists())
        self.assertEqual(authored_bytes, path.read_bytes())


if __name__ == "__main__":
    unittest.main()
