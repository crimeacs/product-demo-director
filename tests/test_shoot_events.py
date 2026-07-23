import json
import os
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "tools"))

from events import normalize_events_file, transform_events  # noqa: E402


class CaptureEventTests(unittest.TestCase):
    def test_trim_and_speed_transform_event_time(self):
        events = [{"t": 2.4, "type": "click", "xPct": 50, "yPct": 50}]
        transformed = transform_events(events, trim_lead=0.4, speed=2.0)
        self.assertEqual(transformed[0]["t"], 1.0)
        self.assertEqual(transformed[0]["rawT"], 2.4)

    def test_events_inside_trim_are_removed(self):
        self.assertEqual(transform_events([{"t": 0.2}], trim_lead=0.4, speed=1), [])

    def test_normalized_file_records_transform_without_capture_dependency(self):
        with tempfile.TemporaryDirectory() as directory:
            raw = os.path.join(directory, "raw.events.json")
            edited = os.path.join(directory, "nested", "clip.events.json")
            with open(raw, "w", encoding="utf-8") as handle:
                json.dump([{"t": 2.4, "type": "click"}], handle)

            result = normalize_events_file(raw, edited, trim_lead=0.4, speed=2.0)

            self.assertEqual(result, edited)
            with open(edited, encoding="utf-8") as handle:
                payload = json.load(handle)
            self.assertEqual(payload["sourceViewport"], {"width": 1920, "height": 1080})
            self.assertEqual(payload["events"][0]["t"], 1.0)

    def test_non_positive_speed_is_rejected(self):
        with self.assertRaisesRegex(ValueError, "greater than zero"):
            transform_events([{"t": 1.0}], speed=0)


if __name__ == "__main__":
    unittest.main()
