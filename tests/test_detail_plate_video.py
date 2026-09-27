"""Render complete native UI objects, their four edges, and source timing."""
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path


ENGINE = Path(__file__).resolve().parents[1] / "engine"


class DetailPlateVideoTests(unittest.TestCase):
    def test_native_object_edges_clean_canvas_and_mapped_source_time(self):
        cli = ENGINE / "node_modules" / "@remotion" / "cli" / "remotion-cli.js"
        if not shutil.which("node") or not shutil.which("ffmpeg") or not cli.exists():
            self.skipTest("Install FFmpeg and engine dependencies to verify detail rendering")
        with tempfile.TemporaryDirectory(prefix=".detail-video-test-", dir=ENGINE) as directory:
            folder = Path(directory)
            public = folder / "public"
            public.mkdir()

            def frame(width, height, roi, inside):
                x0, y0, rw, rh = roi
                colors = []
                for y in range(height):
                    for x in range(width):
                        color = (255, 0, 255)  # Adjacent desktop must never appear outside the plate.
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

            fixtures = [("landscape.mp4", 160, 90, (40, 20, 80, 40)),
                        ("portrait.mp4", 90, 160, (10, 100, 70, 35))]
            for name, width, height, roi in fixtures:
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
const screenRect={x:10,y:25,width:80,height:55};
const portrait={kind:'clip' as const,durSec:.1,durFrames:3,src:'portrait.mp4',
  sourceWidth:90,sourceHeight:160,transition:'cut' as const,
  title:'Recorded control',caption:'Native UI stays put',captionFontSize:12,
  sourceDetail:{sourceRect:{x:100/9,y:62.5,width:700/9,height:21.875},screenRect,entranceSec:0,radiusPx:0}};
const props:TimelineProps={fps:30,totalSec:.7,music:null,sfx:{},theme:{bg:'#102030',line:'rgba(0,0,0,0)'},segments:[
  {kind:'clip',durSec:.5,durFrames:15,src:'landscape.mp4',sourceWidth:160,sourceHeight:90,
    title:'A complete recorded control explains why the reviewer made this decision',
    caption:'Separate recorded shopper test',captionFontSize:12,transition:'cut',objectFit:'cover',
    sourceDetail:{sourceRect:{x:25,y:200/9,width:50,height:400/9},screenRect,entranceSec:.4,radiusPx:0},
    sourcePlan:[{startFrame:0,frames:15,sourceStartSec:.1,sourceEndSec:.1,playbackRate:0,hold:true}]},
  {...portrait,objectFit:'cover'},
  {...portrait,objectFit:'contain'},
]};
registerRoot(()=> <><Composition id="DetailPlateRegression" component={Timeline} defaultProps={props}
  fps={30} durationInFrames={21} width={320} height={180}/>
  <Composition id="DetailPlateFullSize" component={Timeline}
    defaultProps={{...props,segments:[{...props.segments[0],captionFontSize:72}]}}
    fps={30} durationInFrames={15} width={1920} height={1080}/>
  <Composition id="DetailReadoutWarm" component={Timeline}
    defaultProps={{...props,totalSec:.1,theme:{bg:'#f8f7f3',ink:'#151613',line:'rgba(0,0,0,0)'},
      segments:[{...portrait,captionStyle:'readout',
        sourceDetail:{...portrait.sourceDetail,titleAlign:'center'}}]}}
    fps={30} durationInFrames={3} width={320} height={180}/></>);
''', encoding="utf-8")
            output = folder / "rendered.mp4"
            rendered = subprocess.run([
                "node", str(cli), "render", str(folder / "entry.tsx"), "DetailPlateRegression", str(output),
                "--public-dir", str(public), "--codec", "h264", "--concurrency", "1", "--log", "error",
            ], cwd=ENGINE, capture_output=True, text=True, timeout=150)
            self.assertEqual(rendered.returncode, 0, rendered.stdout + rendered.stderr)
            decoded = subprocess.run([
                "ffmpeg", "-v", "error", "-i", str(output), "-map", "0:v:0", "-pix_fmt", "rgb24", "-f", "rawvideo", "-",
            ], capture_output=True, timeout=30)
            self.assertEqual(decoded.returncode, 0, decoded.stderr.decode())
            self.assertEqual(len(decoded.stdout), 21 * 320 * 180 * 3)

            def pixel(frame, x, y):
                offset = ((frame * 180 + y) * 320 + x) * 3
                return tuple(decoded.stdout[offset:offset + 3])

            for picture in (14, 15, 18):
                for x, y, expected in [(160, 48, (255, 0, 0)), (160, 140, (0, 0, 255)),
                                       (64, 94, (255, 255, 0)), (255, 94, (0, 255, 255)),
                                       (30, 100, (16, 32, 48)), (290, 100, (16, 32, 48)),
                                       (160, 176, (16, 32, 48)),
                                       (160, 94, (255, 255, 255) if picture == 14 else (0, 255, 0))]:
                    with self.subTest(frame=picture, x=x, y=y):
                        actual = pixel(picture, x, y)
                        self.assertTrue(all(abs(a - b) < 24 for a, b in zip(actual, expected)),
                                        f"got {actual}, expected {expected}")
            # The complete object moves together by two output pixels, then holds.
            first_red = lambda frame: next(y for y in range(35, 60)
                                           if pixel(frame, 160, y)[0] > 220 and pixel(frame, 160, y)[1] < 30)
            self.assertEqual(first_red(0) - first_red(12), 2)
            self.assertEqual(first_red(12), first_red(14))
            # A fitted two-line title stays above the complete ROI. The readable
            # provenance label has its own band, separated from the blue edge.
            bright = lambda frame, x, y: all(channel > 175 for channel in pixel(frame, x, y))
            self.assertTrue(any(bright(10, x, y) for y in range(9, 23) for x in range(32, 288)))
            self.assertTrue(any(bright(10, x, y) for y in range(23, 38) for x in range(32, 288)))
            self.assertTrue(any(bright(10, x, y) for y in range(150, 169) for x in range(10, 310)))
            self.assertFalse(any(bright(10, x, y) for y in range(0, 8) for x in range(320)))
            self.assertFalse(any(bright(10, x, y) for y in range(143, 150) for x in range(320)))
            # Zero entrance means the entire composition is ready on the cut:
            # native edges do not travel, and the readout neither fades in nor
            # disappears before the last picture of these three-frame shots.
            for start in (15, 18):
                self.assertEqual([first_red(picture) for picture in range(start, start + 3)],
                                 [first_red(start)] * 3)
                for picture in range(start, start + 3):
                    with self.subTest(zero_entrance_frame=picture):
                        self.assertTrue(any(bright(picture, x, y)
                                            for y in range(23, 38) for x in range(32, 288)))
                        self.assertTrue(any(bright(picture, x, y)
                                            for y in range(150, 169) for x in range(10, 310)))
            # The actual-font check also runs at production resolution, where
            # a one-pixel rounding tolerance cannot hide overflowing glyphs.
            full_size = subprocess.run([
                "node", str(cli), "still", str(folder / "entry.tsx"), "DetailPlateFullSize", str(folder / "full.png"),
                "--public-dir", str(public), "--frame", "10", "--log", "error",
            ], cwd=ENGINE, capture_output=True, text=True, timeout=150)
            self.assertEqual(full_size.returncode, 0, full_size.stdout + full_size.stderr)
            # On a light product canvas, the authored readout must retain dark
            # readable text without painting the old grey subtitle rectangle.
            readout_file = folder / "readout.mp4"
            readout_render = subprocess.run([
                "node", str(cli), "render", str(folder / "entry.tsx"), "DetailReadoutWarm", str(readout_file),
                "--public-dir", str(public), "--codec", "h264", "--concurrency", "1", "--log", "error",
            ], cwd=ENGINE, capture_output=True, text=True, timeout=150)
            self.assertEqual(readout_render.returncode, 0, readout_render.stdout + readout_render.stderr)
            readout_pixels = subprocess.run([
                "ffmpeg", "-v", "error", "-i", str(readout_file), "-map", "0:v:0",
                "-pix_fmt", "rgb24", "-f", "rawvideo", "-",
            ], capture_output=True, timeout=30)
            self.assertEqual(readout_pixels.returncode, 0, readout_pixels.stderr.decode())
            self.assertEqual(len(readout_pixels.stdout), 3 * 320 * 180 * 3)
            def readout_pixel(picture, x, y):
                offset = ((picture * 180 + y) * 320 + x) * 3
                return tuple(readout_pixels.stdout[offset:offset + 3])
            for picture in range(3):
                with self.subTest(readout_frame=picture):
                    self.assertGreater(sum(all(channel < 80 for channel in readout_pixel(picture, x, y))
                                           for y in range(150, 169) for x in range(10, 310)), 30)
                    for x in range(120, 200):
                        self.assertTrue(all(abs(actual - expected) < 10 for actual, expected in
                                            zip(readout_pixel(picture, x, 151), (248, 247, 243))))
                    for y0, y1 in ((23, 38), (150, 169)):
                        ink_x = [x for y in range(y0, y1) for x in range(320)
                                 if all(channel < 80 for channel in readout_pixel(picture, x, y))]
                        self.assertTrue(ink_x)
                        self.assertAlmostEqual(160, (min(ink_x) + max(ink_x)) / 2, delta=2)


if __name__ == "__main__":
    unittest.main()
