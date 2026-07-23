import os
import sys
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "tools"))

from compare import gate_decision  # noqa: E402


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


if __name__ == "__main__":
    unittest.main()
