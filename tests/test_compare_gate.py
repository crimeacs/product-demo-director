import json
import os
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "tools"))

from compare import gate_decision, require_qa  # noqa: E402


class CompareGateTests(unittest.TestCase):
    def test_candidate_must_sweep(self):
        self.assertEqual(gate_decision(["candidate", "champion"])[0], "inconclusive")
        self.assertEqual(gate_decision(["champion", "champion"])[0], "retain-champion")
        self.assertEqual(gate_decision(["candidate", "candidate"])[0], "ship")

    def test_small_numeric_gain_is_noise_even_after_sweep(self):
        status, _ = gate_decision(["candidate", "candidate"], 68.0, 69.5, 2.0)
        self.assertEqual(status, "inconclusive")

    def test_gain_must_exceed_noise_floor(self):
        status, _ = gate_decision(["candidate", "candidate"], 68.0, 70.1, 2.0)
        self.assertEqual(status, "ship")

    def test_invalid_numbers_and_incomplete_scores_cannot_ship(self):
        for champion, candidate, floor in [
            (68, float("nan"), 2), (68, float("inf"), 2), (None, 75, 2),
            (68, None, 2), (68, 75, float("nan")), (68, 75, -1), (68, 101, 2),
        ]:
            with self.subTest(champion=champion, candidate=candidate, floor=floor):
                with self.assertRaises(ValueError):
                    gate_decision(["candidate", "candidate"], champion, candidate, floor)

    def test_incomplete_or_invalid_votes_are_rejected(self):
        for votes in ([], ["candidate"], ["candidate", "unknown"]):
            with self.assertRaises(ValueError):
                gate_decision(votes)

    def test_qa_status_cannot_hide_failed_decode_or_error_issues(self):
        with tempfile.TemporaryDirectory() as temp:
            path = os.path.join(temp, "qa-report.json")
            for report in (
                {"status": "pass"},
                {"status": "pass", "fullDecode": "fail"},
                {"status": "pass", "fullDecode": "pass", "issues": [{"severity": "error"}]},
            ):
                with open(path, "w") as fh:
                    json.dump(report, fh)
                with self.assertRaisesRegex(RuntimeError, "did not pass"):
                    require_qa(path)


if __name__ == "__main__":
    unittest.main()
