import os
import sys
import unittest


sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "tools"))

from music import _last_trailing_silence  # noqa: E402


class MusicTailTests(unittest.TestCase):
    def test_detects_trailing_silence(self):
        log = "silence_start: 59.75\nsilence_end: 62.50 | silence_duration: 2.75"
        self.assertEqual(59.75, _last_trailing_silence(log, 62.5))

    def test_ignores_internal_and_tiny_tail_silence(self):
        internal = "silence_start: 12\nsilence_end: 14 | silence_duration: 2"
        tiny = "silence_start: 62.0\nsilence_end: 62.5 | silence_duration: 0.5"
        self.assertIsNone(_last_trailing_silence(internal, 62.5))
        self.assertIsNone(_last_trailing_silence(tiny, 62.5))


if __name__ == "__main__":
    unittest.main()
