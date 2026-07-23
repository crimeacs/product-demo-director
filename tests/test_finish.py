import os
import sys
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "tools"))

from finish import colorspace_filter, parse_loudnorm_json  # noqa: E402


class FinishTests(unittest.TestCase):
    def test_loudnorm_measurement_is_parsed_for_second_pass(self):
        text = '''noise
        {"input_i":"-23.10","input_tp":"-4.20","input_lra":"3.00",
         "input_thresh":"-33.10","output_i":"-18.00","target_offset":"0.10"}
        '''
        self.assertEqual(parse_loudnorm_json(text), {
            "measured_I": -23.1, "measured_TP": -4.2, "measured_LRA": 3.0,
            "measured_thresh": -33.1, "offset": 0.1,
        })

    def test_unknown_remotion_color_metadata_gets_explicit_bt709_transform(self):
        value = colorspace_filter({"pix_fmt": "yuvj420p", "color_space": "bt470bg"})
        self.assertIn("ispace=bt470bg", value)
        self.assertIn("irange=pc", value)
        self.assertIn("all=bt709", value)
        self.assertIn("format=yuv420p", value)


if __name__ == "__main__":
    unittest.main()
