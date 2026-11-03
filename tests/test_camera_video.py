"""Verify closeup geometry on pixels painted by the real Timeline renderer."""
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path


ENGINE = Path(__file__).resolve().parents[1] / "engine"


class CameraVideoTests(unittest.TestCase):
    def test_full_source_cover_contain_and_eight_x_closeups_render_correctly(self):
        cli = ENGINE / "node_modules" / "@remotion" / "cli" / "remotion-cli.js"
        if not shutil.which("node") or not shutil.which("ffmpeg") or not cli.exists():
            self.skipTest("Install FFmpeg and engine dependencies to verify camera rendering")
        with tempfile.TemporaryDirectory(prefix=".camera-video-test-", dir=ENGINE) as directory:
            folder = Path(directory)
            public = folder / "public"
            public.mkdir()
            red, green, blue = bytes((255, 0, 0)), bytes((0, 255, 0)), bytes((0, 0, 255))
            fixtures = [
                ("portrait.mp4", 90, 160, red * (90 * 53) + green * (90 * 54) + blue * (90 * 53)),
                ("contained.mp4", 120, 90, green * (120 * 90)),
                ("closeup.mp4", 160, 90, ((red * 20 + green * 20) * 4) * 90),
            ]
            for name, width, height, pixels in fixtures:
                encoded = subprocess.run([
                    "ffmpeg", "-v", "error", "-f", "rawvideo", "-pix_fmt", "rgb24", "-s", f"{width}x{height}",
                    "-r", "30", "-i", "pipe:0", "-an", "-c:v", "libx264", "-crf", "0",
                    "-pix_fmt", "yuv420p", str(public / name),
                ], input=pixels * 6, capture_output=True, timeout=30)
                self.assertEqual(encoded.returncode, 0, encoded.stderr.decode())
            (folder / "entry.tsx").write_text('''
import React from 'react';
import {Composition, registerRoot} from 'remotion';
import {Timeline, type TimelineProps} from '../src/Timeline';
const props: TimelineProps = {fps:30,totalSec:.3,music:null,sfx:{},segments:[
  {kind:'clip',durSec:.1,durFrames:3,src:'portrait.mp4',sourceWidth:90,sourceHeight:160,
    objectFit:'cover',transition:'cut',camera:[{atSec:0,scale:4,focusX:50,focusY:10}]},
  {kind:'clip',durSec:.1,durFrames:3,src:'contained.mp4',sourceWidth:120,sourceHeight:90,
    objectFit:'contain',transition:'cut',camera:[{atSec:0,scale:2,focusX:0,focusY:50}],
    sourcePlan:[{startFrame:0,frames:3,sourceStartSec:0,sourceEndSec:0,playbackRate:0,hold:true}]},
  {kind:'clip',durSec:.1,durFrames:3,src:'closeup.mp4',sourceWidth:160,sourceHeight:90,
    objectFit:'cover',transition:'cut',camera:[{atSec:0,scale:8,focusX:10,focusY:50}]},
]};
registerRoot(() => <Composition id="CameraRegression" component={Timeline} defaultProps={props}
  fps={30} durationInFrames={9} width={160} height={90}/>);
''', encoding="utf-8")
            output = folder / "rendered.mp4"
            rendered = subprocess.run([
                "node", str(cli), "render", str(folder / "entry.tsx"), "CameraRegression", str(output),
                "--public-dir", str(public), "--codec", "h264", "--concurrency", "1", "--log", "error",
            ], cwd=ENGINE, capture_output=True, text=True, timeout=150)
            self.assertEqual(rendered.returncode, 0, rendered.stdout + rendered.stderr)
            decoded = subprocess.run([
                "ffmpeg", "-v", "error", "-i", str(output), "-map", "0:v:0", "-pix_fmt", "rgb24", "-f", "rawvideo", "-",
            ], capture_output=True, timeout=30)
            self.assertEqual(decoded.returncode, 0, decoded.stderr.decode())
            self.assertEqual(len(decoded.stdout), 9 * 160 * 90 * 3)
            samples = [
                (0, 80, 45, (255, 0, 0)),  # Top of portrait source was outside the initial cover crop.
                (0, 2, 2, (255, 0, 0)),
                (3, 2, 45, (0, 255, 0)),  # Contain's original left letterbox must not survive the 2x closeup.
                (3, 157, 45, (0, 255, 0)),
                (6, 80, 45, (255, 0, 0)),  # The old silent 3x cap would center on the green stripe.
            ]
            for frame, x, y, expected in samples:
                offset = ((frame * 90 + y) * 160 + x) * 3
                actual = tuple(decoded.stdout[offset:offset + 3])
                with self.subTest(frame=frame, x=x, y=y):
                    self.assertTrue(all(abs(a - b) < 20 for a, b in zip(actual, expected)),
                                    f"got {actual}, expected {expected}")


if __name__ == "__main__":
    unittest.main()
