"""A source isolation window follows the real camera without exposing adjacent UI."""
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path


ENGINE = Path(__file__).resolve().parents[1] / "engine"


class SourceWindowVideoTests(unittest.TestCase):
    def test_complete_source_edges_camera_movement_brand_canvas_and_source_hold(self):
        cli = ENGINE / "node_modules" / "@remotion" / "cli" / "remotion-cli.js"
        if not shutil.which("node") or not shutil.which("ffmpeg") or not cli.exists():
            self.skipTest("Install FFmpeg and engine dependencies to verify source isolation")
        with tempfile.TemporaryDirectory(prefix=".source-window-test-", dir=ENGINE) as directory:
            folder = Path(directory)
            public = folder / "public"
            public.mkdir()

            def frame(width, height, roi, inside):
                x0, y0, rw, rh = roi
                colors = []
                for y in range(height):
                    for x in range(width):
                        color = (255, 0, 255)
                        if x0 <= x < x0 + rw and y0 <= y < y0 + rh:
                            color = inside
                            if y < y0 + 3:
                                color = (255, 0, 0)
                            elif y >= y0 + rh - 3:
                                color = (0, 0, 255)
                            elif x < x0 + 3:
                                color = (255, 255, 0)
                            elif x >= x0 + rw - 3:
                                color = (0, 255, 255)
                        colors.extend(color)
                return bytes(colors)

            for name, width, height, roi in [("landscape.mp4", 160, 90, (40, 25, 80, 40)),
                                             ("portrait.mp4", 90, 160, (10, 100, 70, 35))]:
                pixels = frame(width, height, roi, (0, 255, 0)) * 3 + frame(width, height, roi, (255, 255, 255)) * 3
                encoded = subprocess.run([
                    "ffmpeg", "-v", "error", "-f", "rawvideo", "-pix_fmt", "rgb24", "-s", f"{width}x{height}",
                    "-r", "30", "-i", "pipe:0", "-an", "-c:v", "libx264", "-crf", "0",
                    "-pix_fmt", "yuv444p", str(public / name),
                ], input=pixels, capture_output=True, timeout=30)
                self.assertEqual(encoded.returncode, 0, encoded.stderr.decode())
            (folder / "entry.tsx").write_text('''
import React from 'react';
import {Composition, registerRoot} from 'remotion';
import {Timeline,type TimelineProps} from '../src/Timeline';
const portrait={kind:'clip' as const,durSec:.1,durFrames:3,src:'portrait.mp4',
 sourceWidth:90,sourceHeight:160,transition:'cut' as const,
 sourceWindow:{x:100/9,y:62.5,width:700/9,height:21.875}};
const props:TimelineProps={fps:30,totalSec:.9,music:null,sfx:{},theme:{bg:'#f4ece2',ink:'#0000ff'},segments:[
 {kind:'clip',durSec:.2,durFrames:6,src:'landscape.mp4',sourceWidth:160,sourceHeight:90,
  transition:'cut',objectFit:'cover',sourceWindow:{x:25,y:250/9,width:50,height:400/9},
  camera:[{atSec:0,scale:1,focusX:50,focusY:50},{atSec:.1,scale:1.5,focusX:55,focusY:50}],
  sourcePlan:[{startFrame:0,frames:6,sourceStartSec:.1,sourceEndSec:.1,playbackRate:0,hold:true}]},
 {...portrait,objectFit:'contain',camera:[{atSec:0,scale:2,focusX:50,focusY:73.4375}]},
 {...portrait,objectFit:'cover',camera:[{atSec:0,scale:1,focusX:50,focusY:73.4375}]},
 {kind:'clip',durSec:.5,durFrames:15,src:'landscape.mp4',sourceWidth:160,sourceHeight:90,
  transition:'cut',sourceWindow:{x:25,y:250/9,width:50,height:400/9},
  annotations:[{atSec:0,endSec:.5,x:25,y:250/9,width:50,height:400/9,label:'SOURCE'}],
  sourcePlan:[{startFrame:0,frames:15,sourceStartSec:0,sourceEndSec:0,playbackRate:0,hold:true}]},
]};
registerRoot(()=> <Composition id="SourceWindowRegression" component={Timeline} defaultProps={props}
 fps={30} durationInFrames={27} width={160} height={90}/>);
''', encoding="utf-8")
            output = folder / "rendered.mp4"
            rendered = subprocess.run([
                "node", str(cli), "render", str(folder / "entry.tsx"), "SourceWindowRegression", str(output),
                "--public-dir", str(public), "--codec", "h264", "--concurrency", "1", "--log", "error",
                # Test native mask geometry at thin colored borders without yuv420 chroma bleed.
                "--pixel-format", "yuv444p", "--crf", "1",
            ], cwd=ENGINE, capture_output=True, text=True, timeout=150)
            self.assertEqual(rendered.returncode, 0, rendered.stdout + rendered.stderr)
            decoded = subprocess.run([
                "ffmpeg", "-v", "error", "-i", str(output), "-map", "0:v:0", "-pix_fmt", "rgb24", "-f", "rawvideo", "-",
            ], capture_output=True, timeout=30)
            self.assertEqual(decoded.returncode, 0, decoded.stderr.decode())
            self.assertEqual(len(decoded.stdout), 27 * 160 * 90 * 3)
            canvas = (244, 236, 226)
            samples = [
                # Native object at rest, with no adjacent magenta UI or black bars.
                (0, 20, 45, canvas), (0, 80, 10, canvas), (0, 80, 45, (255, 255, 255)),
                (0, 41, 45, (255, 255, 0)), (0, 118, 45, (0, 255, 255)),
                (0, 80, 26, (255, 0, 0)), (0, 80, 63, (0, 0, 255)),
                # The same source mask follows a connected 1.5x camera pan.
                (3, 3, 45, canvas), (3, 140, 45, canvas), (3, 80, 45, (255, 255, 255)),
                (3, 10, 45, (255, 255, 0)), (3, 125, 45, (0, 255, 255)),
                (3, 80, 17, (255, 0, 0)), (3, 80, 72, (0, 0, 255)),
                # Source percentages use the complete fitted portrait plane for either fit.
                (6, 20, 45, canvas), (6, 80, 10, canvas), (6, 80, 45, (0, 255, 0)),
                (6, 42, 45, (255, 255, 0)), (6, 117, 45, (0, 255, 255)),
                (9, 5, 45, canvas), (9, 80, 4, canvas), (9, 80, 45, (0, 255, 0)),
                (9, 20, 45, (255, 255, 0)), (9, 139, 45, (0, 255, 255)),
            ]
            for picture, x, y, expected in samples:
                offset = ((picture * 90 + y) * 160 + x) * 3
                actual = tuple(decoded.stdout[offset:offset + 3])
                with self.subTest(frame=picture, x=x, y=y):
                    self.assertTrue(all(abs(a - b) < 28 for a, b in zip(actual, expected)),
                                    f"got {actual}, expected {expected}")
            # Editorial labels live beside the native source mask. Their blue
            # glyphs to the left of x=40 disappeared when the whole overlay was clipped.
            ink = 0
            for y in range(35, 70):
                for x in range(20, 37):
                    offset = ((20 * 90 + y) * 160 + x) * 3
                    r, g, b = decoded.stdout[offset:offset + 3]
                    ink += b > 170 and r < 100 and g < 100
            self.assertGreater(ink, 12, "Complete annotation label must remain visible outside the source window")


if __name__ == "__main__":
    unittest.main()
