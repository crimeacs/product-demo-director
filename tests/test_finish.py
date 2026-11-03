import json
import os
import shutil
import subprocess
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "tools"))

from finish import can_copy_picture, colorspace_filter, parse_loudnorm_json, preserve_parent_artifact  # noqa: E402
from contracts import sha256_file  # noqa: E402
from qa import canonical_json_sha256  # noqa: E402
import finish  # noqa: E402
import qa  # noqa: E402


class FinishTests(unittest.TestCase):
    def test_picture_copy_requires_every_delivery_property(self):
        video = {"codec_name": "h264", "pix_fmt": "yuv420p", "color_range": "tv",
                 "color_space": "bt709", "color_transfer": "bt709", "color_primaries": "bt709"}
        self.assertTrue(can_copy_picture(video))
        for key in video:
            with self.subTest(key=key):
                missing = dict(video)
                del missing[key]
                self.assertFalse(can_copy_picture(missing))
        self.assertFalse(can_copy_picture({**video, "pix_fmt": "yuvj420p", "color_range": "pc"}))

    def test_loudnorm_measurement_is_parsed_for_second_pass(self):
        text = '''noise
        {"input_i":"-23.10","input_tp":"-4.20","input_lra":"3.00",
         "input_thresh":"-33.10","output_i":"-18.00","target_offset":"0.10"}
        '''
        self.assertEqual(parse_loudnorm_json(text), {
            "measured_I": -23.1, "measured_TP": -4.2, "measured_LRA": 3.0,
            "measured_thresh": -33.1, "offset": 0.1,
        })

    def test_unknown_remotion_color_metadata_gets_explicit_bt709_transform(self):
        value = colorspace_filter({"pix_fmt": "yuvj420p", "color_space": "bt470bg"})
        self.assertIn("ispace=bt470bg", value)
        self.assertIn("irange=pc", value)
        self.assertIn("all=bt709", value)
        self.assertIn("format=yuv420p", value)

    def test_same_stem_conversion_preserves_parent_manifest(self):
        with tempfile.TemporaryDirectory() as temp:
            original = os.path.join(temp, "demo.artifact.json")
            parent = {"buildId": "original"}
            with open(original, "w") as fh:
                json.dump(parent, fh)
            preserved = preserve_parent_artifact(original, parent, os.path.join(temp, "demo.mov"),
                                                  os.path.join(temp, "demo.mp4"))
            self.assertNotEqual(original, preserved)
            with open(original, "w") as fh:
                json.dump({"buildId": "finished"}, fh)
            with open(preserved) as fh:
                self.assertEqual(json.load(fh), parent)


@unittest.skipUnless(shutil.which("ffmpeg") and shutil.which("ffprobe"), "FFmpeg is required")
class FinishIntegrationTests(unittest.TestCase):
    def test_finished_media_retains_parent_provenance_and_passes_bound_qa(self):
        with tempfile.TemporaryDirectory() as temp:
            source = os.path.join(temp, "demo.mov")
            output = os.path.join(temp, "demo.mp4")
            subprocess.run([
                "ffmpeg", "-v", "error", "-f", "lavfi", "-i", "color=c=blue:s=160x90:r=30:d=1",
                "-f", "lavfi", "-i", "sine=frequency=440:sample_rate=48000:duration=1",
                "-c:v", "libx264", "-pix_fmt", "yuv420p", "-c:a", "aac", "-shortest", source,
            ], check=True, capture_output=True)
            props = {"fps": 30, "totalFrames": 30, "segments": [{"durFrames": 30}]}
            with open(os.path.join(temp, "demo.props.json"), "w") as fh:
                json.dump(props, fh)
            parent = {"buildId": "original", "propsSha256": canonical_json_sha256(props),
                      "expected": {"frames": 30, "fps": 30}, "output": {"sha256": sha256_file(source)}}
            artifact_path = os.path.join(temp, "demo.artifact.json")
            with open(artifact_path, "w") as fh:
                json.dump(parent, fh)
            result = subprocess.run([
                sys.executable, finish.__file__, "--input", source, "--out", output,
                "--require-artifact", "--preset", "ultrafast",
            ], capture_output=True, text=True)
            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
            # Finishing the compliant delivery again must retain the exact encoded picture packets.
            copied = os.path.join(temp, "copied.mp4")
            result = subprocess.run([
                sys.executable, finish.__file__, "--input", output, "--out", copied,
                "--require-artifact", "--no-loudnorm",
            ], capture_output=True, text=True)
            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
            with open(os.path.join(temp, "copied.artifact.json")) as fh:
                copied_artifact = json.load(fh)
            self.assertEqual("copy", copied_artifact["finishConfig"]["videoMode"])
            self.assertIsNone(copied_artifact["finishConfig"]["crf"])
            def packet_hashes(path):
                result = subprocess.run([
                    "ffprobe", "-v", "error", "-select_streams", "v:0", "-show_packets",
                    "-show_data_hash", "sha256", "-show_entries", "packet=data_hash", "-of", "json", path,
                ], capture_output=True, text=True, check=True)
                return [packet["data_hash"] for packet in json.loads(result.stdout)["packets"]]
            self.assertEqual(packet_hashes(output), packet_hashes(copied))
            result = subprocess.run([
                sys.executable, qa.__file__, "--video", copied, "--require-artifact", "--strict", "--no-visuals",
            ], capture_output=True, text=True)
            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
            with open(artifact_path) as fh:
                artifact = json.load(fh)
            self.assertEqual(artifact["expected"]["durationSec"], 1.0)
            self.assertEqual(artifact["expected"]["frames"], 30)
            preserved = artifact["parentArtifact"]
            self.assertNotEqual(preserved["path"], artifact_path)
            self.assertEqual(preserved["sha256"], sha256_file(preserved["path"]))
            with open(preserved["path"]) as fh:
                self.assertEqual(json.load(fh), parent)
            result = subprocess.run([
                sys.executable, qa.__file__, "--video", output, "--require-artifact", "--strict", "--no-visuals",
            ], capture_output=True, text=True)
            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)


if __name__ == "__main__":
    unittest.main()
