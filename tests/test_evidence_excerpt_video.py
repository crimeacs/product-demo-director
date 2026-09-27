"""The editorial readout stays readable, complete, and honest on the first phone frame."""
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path

from PIL import Image, ImageChops, ImageStat


ENGINE = Path(__file__).resolve().parents[1] / "engine"


class EvidenceExcerptVideoTests(unittest.TestCase):
    def test_phone_fields_first_frame_reading_hold_and_long_copy_rejection(self):
        cli = ENGINE / "node_modules" / "@remotion" / "cli" / "remotion-cli.js"
        if not shutil.which("node") or not shutil.which("ffmpeg") or not cli.exists():
            self.skipTest("Install FFmpeg and engine dependencies to verify evidence rendering")
        with tempfile.TemporaryDirectory(prefix=".evidence-video-test-", dir=ENGINE) as directory:
            folder = Path(directory)
            (folder / "entry.tsx").write_text('''
import React from 'react';
import {Composition,registerRoot} from 'remotion';
import {Timeline,type TimelineProps} from '../src/Timeline';
const excerpt={finding:'30-day returns window',source:'allbirds.com · returns policy',
  limitation:'Not independently substantiated.',label:'Recorded finding · source statement'};
const props:TimelineProps={fps:30,totalSec:.4,music:null,sfx:{},
  theme:{bg:'#f8f7f3',ink:'#151613',accent:'#ed5a24',line:'rgba(0,0,0,.1)',grad:'#eee9e0'},
  segments:[{kind:'title',durSec:.4,durFrames:12,transition:'cut',evidenceExcerpt:excerpt}]};
registerRoot(()=> <>
  <Composition id="EvidencePhone" component={Timeline} defaultProps={props}
    fps={30} durationInFrames={12} width={320} height={180}/>
  <Composition id="EvidenceFull" component={Timeline} defaultProps={props}
    fps={30} durationInFrames={12} width={1920} height={1080}/>
  <Composition id="EvidenceCentered" component={Timeline}
    defaultProps={{...props,segments:[{...props.segments[0],direction:{align:'center'}}]}}
    fps={30} durationInFrames={12} width={320} height={180}/>
  <Composition id="ClosingCentered" component={Timeline}
    defaultProps={{...props,totalSec:3,segments:[{kind:'cta',durSec:3,durFrames:90,studio:true,
      brand:'Acme Verify',title:'See the evidence. Make your decision.',
      titleLines:['See the evidence.','Make your decision.'],subtitle:'verify.example.com',
      direction:{align:'center'}}]}}
    fps={30} durationInFrames={90} width={320} height={180}/>
  <Composition id="EvidenceOverflow" component={Timeline}
    defaultProps={{...props,segments:[{...props.segments[0],
      evidenceExcerpt:{...excerpt,limitation:'Source evidence limitation '.repeat(30)}}]}}
    fps={30} durationInFrames={12} width={320} height={180}/>
</>);
''', encoding="utf-8")
            output = folder / "phone.mp4"
            rendered = subprocess.run([
                "node", str(cli), "render", str(folder / "entry.tsx"), "EvidencePhone", str(output),
                "--codec", "h264", "--concurrency", "1", "--log", "error",
            ], cwd=ENGINE, capture_output=True, text=True, timeout=150)
            self.assertEqual(rendered.returncode, 0, rendered.stdout + rendered.stderr)
            decoded = subprocess.run([
                "ffmpeg", "-v", "error", "-i", str(output), "-map", "0:v:0",
                "-pix_fmt", "rgb24", "-f", "rawvideo", "-",
            ], capture_output=True, timeout=30)
            self.assertEqual(decoded.returncode, 0, decoded.stderr.decode())
            self.assertEqual(len(decoded.stdout), 12 * 320 * 180 * 3)
            pictures = [Image.frombytes("RGB", (320, 180), decoded.stdout[i * 172800:(i + 1) * 172800])
                        for i in range(12)]
            bands = {"provenance": (22, 17, 298, 35), "finding": (22, 49, 298, 85),
                     "source": (22, 99, 298, 130), "limitation": (28, 135, 298, 169)}
            for picture in (0, 7, 11):
                for field, box in bands.items():
                    with self.subTest(picture=picture, field=field):
                        crop = pictures[picture].crop(box)
                        dark = [(x, y) for y in range(crop.height) for x in range(crop.width)
                                if all(channel < 90 for channel in crop.getpixel((x, y)))]
                        self.assertGreater(len(dark), 65)
                        self.assertGreaterEqual(max(y for _, y in dark) - min(y for _, y in dark), 9)
                for point in ((5, 5), (315, 175), (160, 176)):
                    self.assertTrue(all(abs(actual - expected) < 8 for actual, expected in
                                        zip(pictures[picture].getpixel(point), (248, 247, 243))))
            # Once the brief finding arrival ends, every field is a true reading
            # hold. No hidden line staggering or continuing drift remains.
            self.assertLess(max(ImageStat.Stat(ImageChops.difference(pictures[7], pictures[11])).mean), 0.5)
            full = subprocess.run([
                "node", str(cli), "still", str(folder / "entry.tsx"), "EvidenceFull", str(folder / "full.png"),
                "--frame", "0", "--log", "error",
            ], cwd=ENGINE, capture_output=True, text=True, timeout=150)
            self.assertEqual(full.returncode, 0, full.stdout + full.stderr)
            for composition, picture in (("EvidenceCentered", 7), ("ClosingCentered", 60)):
                filename = folder / f"{composition}.png"
                centered = subprocess.run([
                    "node", str(cli), "still", str(folder / "entry.tsx"), composition, str(filename),
                    "--frame", str(picture), "--log", "error",
                ], cwd=ENGINE, capture_output=True, text=True, timeout=150)
                self.assertEqual(centered.returncode, 0, centered.stdout + centered.stderr)
                pixels = Image.open(filename).convert("RGB")
                ink_threshold = 90 if composition == "EvidenceCentered" else 160
                if composition == "EvidenceCentered":
                    text_bands = list(bands.values())
                else:
                    occupied = [y for y in range(180) if sum(all(channel < ink_threshold for channel in pixels.getpixel((x, y)))
                                                             for x in range(320)) >= 3]
                    runs = []
                    for y in occupied:
                        if runs and y <= runs[-1][-1] + 3:
                            runs[-1].append(y)
                        else:
                            runs.append([y])
                    text_bands = [(0, run[0], 320, run[-1] + 1) for run in runs if len(run) >= 3]
                    self.assertGreaterEqual(len(text_bands), 4)  # Brand, two title lines, and URL.
                for x0, y0, x1, y1 in text_bands:
                    ink_x = [x for y in range(y0, y1) for x in range(x0, x1)
                             if all(channel < ink_threshold for channel in pixels.getpixel((x, y)))]
                    self.assertTrue(ink_x)
                    self.assertAlmostEqual(160, (min(ink_x) + max(ink_x)) / 2, delta=2,
                                           msg=f"{composition}: text band {y0}–{y1}")
            overflow = subprocess.run([
                "node", str(cli), "still", str(folder / "entry.tsx"), "EvidenceOverflow", str(folder / "overflow.png"),
                "--frame", "0", "--log", "error",
            ], cwd=ENGINE, capture_output=True, text=True, timeout=150)
            self.assertNotEqual(0, overflow.returncode)
            self.assertIn("cannot fit at a phone-readable size", overflow.stdout + overflow.stderr)


if __name__ == "__main__":
    unittest.main()
