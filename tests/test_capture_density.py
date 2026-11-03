import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import Mock, patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "tools"))
try:
    import capture
    import shoot
except ModuleNotFoundError:
    capture = shoot = None


@unittest.skipIf(capture is None, "Playwright dependency is required")
class CaptureDensityTests(unittest.TestCase):
    def test_opt_in_density_is_applied_before_the_recorders_first_frame(self):
        playwright = Mock()
        with patch("capture._browser_executable", return_value=""):
            capture._launch(playwright)
            self.assertFalse(any("device-scale" in value for value in playwright.chromium.launch.call_args.kwargs["args"]))
            capture._launch(playwright, device_scale_factor=3)
            self.assertIn("--force-device-scale-factor=3", playwright.chromium.launch.call_args.kwargs["args"])

    def test_opt_in_density_preserves_legacy_viewport_and_validates_before_browser(self):
        legacy = capture.capture_geometry()
        self.assertEqual(legacy["viewport"], {"width": 1920, "height": 1080})
        self.assertEqual(legacy["device_scale_factor"], 2)
        self.assertEqual(legacy["record_video_size"], legacy["viewport"])
        for density in (1, 2, 3, 4):
            geometry = capture.capture_geometry(capture_scale=density)
            self.assertEqual(geometry["viewport"], legacy["viewport"])
            self.assertEqual(geometry["device_scale_factor"], density)
            self.assertEqual(geometry["record_video_size"], {"width": 1920*density, "height": 1080*density})
        with patch("capture.sync_playwright") as browser:
            for invalid in (0, 5, 1.5, True, "3"):
                with self.subTest(invalid=invalid), self.assertRaises(ValueError):
                    capture.run("https://unused.invalid", [], "unused.webm", capture_scale=invalid)
            browser.assert_not_called()

    def test_web_shoot_forwards_opt_in_and_preserves_normalized_resolution(self):
        with tempfile.TemporaryDirectory() as directory, patch("capture.run") as record, \
                patch("shoot.normalize") as normalize:
            shot = {"name": "detail", "url": "https://unused.invalid", "steps": [{"wait": 1}], "captureScale": 3}
            shoot.shoot_web(shot, directory, str(Path(directory)/"detail.mp4"), directory, str(Path(directory)/"steps.json"))
            self.assertEqual(3, record.call_args.kwargs["capture_scale"])
            self.assertIs(True, normalize.call_args.kwargs["preserve_resolution"])
            del shot["captureScale"]
            shoot.shoot_web(shot, directory, str(Path(directory)/"detail.mp4"), directory, str(Path(directory)/"steps.json"))
            self.assertIsNone(record.call_args.kwargs["capture_scale"])
            self.assertIs(False, normalize.call_args.kwargs["preserve_resolution"])


@unittest.skipUnless(capture and shutil.which("ffmpeg") and shutil.which("ffprobe"), "Playwright and FFmpeg required")
class CaptureDensityIntegrationTests(unittest.TestCase):
    def test_retina_video_and_png_retain_sub_css_pixel_detail_and_click_coordinates(self):
        # Fully local fixture: no app, account, credentials, or network requests.
        from PIL import Image
        fixture = '''<style>html,body{margin:0;width:100%;height:100%;background:#f00}
        #fine{width:100px;height:100px;background:repeating-linear-gradient(90deg,#000 0px,#000 .333333px,#fff .333333px,#fff .666666px)}
        button{position:fixed;left:220px;top:120px;width:40px;height:30px;padding:0;border:0}
        #edge{position:fixed;right:0;bottom:0;width:10px;height:10px;background:#0f0}
        #pulse{position:fixed;left:0;bottom:0;width:3px;height:3px;background:#00f;animation:pulse .2s linear infinite alternate}
        @keyframes pulse{to{transform:translateX(3px)}}</style>
        <div id="fine"></div><button onclick="this.textContent='done'">go</button><div id="edge"></div><div id="pulse"></div>'''
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            html = root/"fixture.html"
            html.write_text(fixture)
            raw = root/"raw.webm"
            with patch.object(capture, "W", 320), patch.object(capture, "H", 180), \
                    patch.object(capture, "auth_hook", side_effect=lambda context, page:
                                 context.route(re.compile(r"^https?://"), lambda route: route.abort())):
                capture.run(html.as_uri(), [{"click_selector": "button", "after": 400}, {"screenshot": "detail.png"}],
                            str(raw), capture_scale=3, cursor=False, quiet=True)
            metadata = json.loads((root/"raw.capture.json").read_text())
            self.assertEqual({"width": 320, "height": 180}, metadata["viewportCss"])
            self.assertEqual(3, metadata["launchDeviceScaleFactor"])
            self.assertEqual((960, 540), (metadata["video"]["width"], metadata["video"]["height"]))
            self.assertEqual(capture.file_sha256(raw), metadata["video"]["sha256"])
            events = json.loads((root/"raw.events.json").read_text())
            self.assertEqual((75.0, 75.0), (events[0]["xPct"], events[0]["yPct"]))
            self.assertEqual(960, metadata["screenshots"][0]["width"])
            self.assertEqual(capture.file_sha256(root/"detail.png"), metadata["screenshots"][0]["sha256"])

            output = root/"normalized.mp4"
            shoot.normalize(str(raw), str(output), trim_lead=0, preserve_resolution=True,
                            raw_events=str(root/"raw.events.json"), edited_events=str(root/"normalized.events.json"))
            normalized = json.loads((root/"normalized.capture.json").read_text())
            self.assertEqual((960, 540), (normalized["video"]["width"], normalized["video"]["height"]))
            self.assertEqual(metadata["video"], normalized["sourceVideo"])
            mapped_events = json.loads((root/"normalized.events.json").read_text())
            self.assertEqual({"width": 320, "height": 180}, mapped_events["sourceViewport"])
            self.assertEqual((75.0, 75.0), (mapped_events["events"][0]["xPct"], mapped_events["events"][0]["yPct"]))
            for video in (raw, output):
                # Capture can contain navigation/closing frames; this checks density in an
                # actually visible fixture frame, independently of recorder lifecycle timing.
                decoded = subprocess.run(["ffmpeg", "-v", "error", "-i", str(video),
                                          "-pix_fmt", "rgb24", "-f", "rawvideo", "-"],
                                         check=True, capture_output=True).stdout
                frame_bytes, corner = 960*540*3, (535*960+955)*3
                pictures = [decoded[i:i+frame_bytes] for i in range(0, len(decoded), frame_bytes)]
                visible = [pixels for pixels in pictures if pixels[corner+1] > 220 and pixels[corner] < 40]
                self.assertTrue(visible, f"{video.name} contains no complete recorded fixture")
                im = Image.frombytes("RGB", (960, 540), visible[len(visible)//2])
                gray = im.convert("L")
                values = [gray.getpixel((x, 50)) for x in range(40, 70)]
                contrast = sum(abs(b-a) for a,b in zip(values, values[1:]))/(len(values)-1)
                self.assertGreater(contrast, 180, "device-pixel bars must not become CSS-resolution upscaled blur")
            with Image.open(root/"detail.png") as im:
                self.assertEqual((960, 540), im.size)

            # The legacy call still delivers 1080p even if its input has another raster size.
            shoot.normalize(str(raw), str(root/"legacy.mp4"), trim_lead=0)
            self.assertEqual({"width": 1920, "height": 1080}, capture.media_dimensions(root/"legacy.mp4"))
            with raw.open("ab") as handle:
                handle.write(b"changed")
            with self.assertRaisesRegex(ValueError, "metadata does not match"):
                shoot.normalize(str(raw), str(root/"stale.mp4"), preserve_resolution=True)


if __name__ == "__main__":
    unittest.main()
