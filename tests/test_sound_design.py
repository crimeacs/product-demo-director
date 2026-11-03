"""Actual PCM and artifact checks for deterministic editorial sound accents."""
from array import array
import math
from pathlib import Path
import sys
import tempfile
import unittest
import wave
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "tools"))

from sound_design import BUILTIN_SOUNDS, SAMPLE_RATE, ensure_sound, synthesize  # noqa: E402


class SoundDesignTests(unittest.TestCase):
    def pcm(self, payload):
        samples = array("h")
        samples.frombytes(payload)
        if sys.byteorder != "little":
            samples.byteswap()
        return samples

    def test_pcm_is_deterministic_stereo_nonzero_and_has_clean_ends(self):
        durations = {"studio_air": 0.62, "studio_tick": 0.16, "studio_resolve": 1.35}
        for name in sorted(BUILTIN_SOUNDS):
            with self.subTest(name=name):
                payload = synthesize(name)
                self.assertEqual(payload, synthesize(name))
                self.assertEqual(round(durations[name] * SAMPLE_RATE) * 4, len(payload))
                samples = self.pcm(payload)
                for channel in [samples[0::2], samples[1::2]]:
                    self.assertEqual((0, 0), (channel[0], channel[-1]))
                    peak = max(map(abs, channel))
                    self.assertGreater(peak, 100)
                    self.assertLess(peak, 32767)
                    self.assertGreater(math.sqrt(sum(value ** 2 for value in channel) / len(channel)), 20)
                    self.assertLess(abs(sum(channel) / len(channel)), 32767 * 0.005)
                if name == "studio_air":
                    self.assertNotEqual(samples[0::2], samples[1::2])

    def test_generated_wav_is_valid_and_identical_calls_do_not_rewrite_it(self):
        with tempfile.TemporaryDirectory() as directory:
            target = Path(directory) / "nested"
            path = Path(ensure_sound("studio_resolve", target))
            before = path.stat()
            with wave.open(str(path), "rb") as audio:
                self.assertEqual((2, 2, SAMPLE_RATE), (audio.getnchannels(), audio.getsampwidth(), audio.getframerate()))
                self.assertEqual(synthesize("studio_resolve"), audio.readframes(audio.getnframes()))
            self.assertEqual(str(path), ensure_sound("studio_resolve", target))
            self.assertEqual(before.st_mtime_ns, path.stat().st_mtime_ns)
            self.assertEqual([path], list(target.iterdir()))

    def test_stale_or_corrupt_generated_sound_is_replaced_with_valid_content(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "studio_tick.wav"
            path.write_bytes(b"stale broken audio")
            self.assertEqual(str(path), ensure_sound("studio_tick", directory))
            with wave.open(str(path), "rb") as audio:
                self.assertEqual(synthesize("studio_tick"), audio.readframes(audio.getnframes()))
            self.assertEqual([path], list(Path(directory).iterdir()))

    def test_failed_publish_keeps_previous_sound_and_cleans_temporary_file(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "studio_tick.wav"
            path.write_bytes(b"previous version")
            with patch("sound_design.os.replace", side_effect=OSError("simulated disk error")):
                with self.assertRaisesRegex(OSError, "simulated disk error"):
                    ensure_sound("studio_tick", directory)
            self.assertEqual(b"previous version", path.read_bytes())
            self.assertEqual([path], list(Path(directory).iterdir()))

    def test_unknown_sound_cannot_create_an_audio_file(self):
        for name in ["unknown", "../studio_air", "/tmp/injected"]:
            with self.subTest(name=name), tempfile.TemporaryDirectory() as directory:
                with self.assertRaises(ValueError):
                    ensure_sound(name, directory)
                self.assertEqual([], list(Path(directory).iterdir()))


if __name__ == "__main__":
    unittest.main()
