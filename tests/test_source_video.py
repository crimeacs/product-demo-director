"""Render a tiny color fixture to verify actual Remotion source-time semantics."""
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path


ENGINE = Path(__file__).resolve().parents[1] / "engine"


class SourceVideoTests(unittest.TestCase):
    def test_source_trim_rate_hold_and_nested_sequence_match_rendered_pixels(self):
        cli = ENGINE / "node_modules" / "@remotion" / "cli" / "remotion-cli.js"
        if not shutil.which("node") or not shutil.which("ffmpeg") or not cli.exists():
            self.skipTest("Install FFmpeg and engine dependencies to verify source-time rendering")
        with tempfile.TemporaryDirectory(prefix=".source-video-test-", dir=ENGINE) as directory:
            folder = Path(directory)
            public = folder / "public"
            public.mkdir()
            # The 24fps source deliberately differs from the 30fps composition.
            # A wrong trim unit or rate order selects a visibly different second.
            colors = [(255, 0, 0), (0, 255, 0), (0, 0, 255), (255, 255, 0)]
            pixels = b"".join(bytes(color) * (160 * 90 * 24) for color in colors)
            encoded = subprocess.run([
                "ffmpeg", "-v", "error", "-f", "rawvideo", "-pix_fmt", "rgb24", "-s", "160x90",
                "-r", "24", "-i", "pipe:0", "-an", "-c:v", "libx264", "-crf", "0",
                "-pix_fmt", "yuv420p", str(public / "source.mp4"),
            ], input=pixels, capture_output=True, timeout=30)
            self.assertEqual(encoded.returncode, 0, encoded.stderr.decode())
            (folder / "entry.tsx").write_text('''
import React from 'react';
import {AbsoluteFill, Composition, Sequence, registerRoot, staticFile} from 'remotion';
import {SourceVideo} from '../src/SourceVideo';

const Fixture = () => <AbsoluteFill style={{background: 'black'}}>
  <Sequence from={7} durationInFrames={75} layout="none">
    <SourceVideo src={staticFile('source.mp4')} muted={true}
      style={{position:'absolute',left:0,top:0,width:160,height:90,objectFit:'contain'}}
      plan={[
        {startFrame:0,frames:30,sourceStartSec:1,sourceEndSec:3,playbackRate:2,hold:false},
        {startFrame:30,frames:15,sourceStartSec:71/24,sourceEndSec:71/24,playbackRate:0,hold:true},
        {startFrame:45,frames:30,sourceStartSec:0,sourceEndSec:1,playbackRate:1,hold:false},
      ]}/>
  </Sequence>
</AbsoluteFill>;
registerRoot(() => <Composition id="SourceVideoRegression" component={Fixture}
  fps={30} durationInFrames={82} width={160} height={90}/>);
''', encoding="utf-8")
            output = folder / "rendered.mp4"
            rendered = subprocess.run([
                "node", str(cli), "render", str(folder / "entry.tsx"), "SourceVideoRegression", str(output),
                "--public-dir", str(public), "--codec", "h264", "--concurrency", "1", "--log", "error",
            ], cwd=ENGINE, capture_output=True, text=True, timeout=150)
            self.assertEqual(rendered.returncode, 0, rendered.stdout + rendered.stderr)
            decoded = subprocess.run([
                "ffmpeg", "-v", "error", "-i", str(output), "-map", "0:v:0",
                "-vf", "crop=2:2:80:44,format=rgb24", "-f", "rawvideo", "-",
            ], capture_output=True, timeout=30)
            self.assertEqual(decoded.returncode, 0, decoded.stderr.decode())
            frames = decoded.stdout
            self.assertEqual(len(frames), 82 * 2 * 2 * 3)
            expected = {
                6: (0, 0, 0),            # Nothing leaks before the parent sequence.
                7: (0, 255, 0),          # Trim begins at source 1s, not 2s at 2x.
                17: (0, 255, 0),         # Ten composition frames later: source 1.667s.
                22: (0, 0, 255),         # Half a second at 2x advances a full source second.
                36: (0, 0, 255),         # Last moving frame stays before the exclusive endpoint.
                37: (0, 0, 255),         # Hold starts on the authored real source frame.
                51: (0, 0, 255),         # Hold never advances into the yellow fourth second.
                52: (255, 0, 0),         # The next sequence owns the exact boundary frame.
                81: (255, 0, 0),         # The 1x span lasts its entire compiled duration.
            }
            for frame, color in expected.items():
                actual = tuple(frames[frame * 12:frame * 12 + 3])
                with self.subTest(frame=frame):
                    self.assertTrue(all(abs(a - b) < 20 for a, b in zip(actual, color)),
                                    f"frame {frame}: got {actual}, expected {color}")


if __name__ == "__main__":
    unittest.main()
