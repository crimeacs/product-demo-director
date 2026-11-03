"""Regression coverage for source-safe motion compilation and author intent."""
import copy
import math
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "tools"))

from direction import compile_direction, validate_direction  # noqa: E402


class DirectionTests(unittest.TestCase):
    def script(self, **shot_values):
        return {"fps": 30, "creativeDirection": {"style": "studio"}, "shots": [
            {"n": 1, "kind": "clip", "src": "proof.mp4", "durSec": 4, **shot_values}
        ]}

    def codes(self, script):
        return {finding["code"] for finding in validate_direction(script)}

    def test_compiler_rejects_invalid_fps_and_duration_without_type_or_division_errors(self):
        for value in [None, False, True, 0, -1, "30", [], {}, float("nan"), float("inf"), 10 ** 400]:
            for key, code in [("fps", "FPS_INVALID"), ("durSec", "SHOT_DURATION_INVALID")]:
                with self.subTest(value=value, key=key):
                    script = self.script()
                    (script if key == "fps" else script["shots"][0])[key] = value
                    self.assertIn(code, self.codes(script))
                    with self.assertRaisesRegex(ValueError, code):
                        compile_direction(script)
        script = self.script(durSec=1e308)
        script["fps"] = 1e308
        with self.assertRaisesRegex(ValueError, "frame count must be finite"):
            compile_direction(script)

    def test_malformed_structures_return_findings(self):
        cases = [None, [], {"shots": None}, {"shots": "wrong"}, {"shots": [None]},
                 self.script(kind=[]), self.script(direction=[]), self.script(camera={}),
                 self.script(annotations=[None]), self.script(soundCues=[None])]
        for script in cases:
            with self.subTest(script=script):
                self.assertTrue(validate_direction(script))
                with self.assertRaises(ValueError):
                    compile_direction(script)
        for value in ["proof.mp4", [None], [{"src": []}], [{"src": "proof.mp4", "preserveFraming": "false"}]]:
            script = self.script()
            script["production"] = {"sourceLocks": value}
            self.assertIn("SOURCE_LOCK_INVALID", self.codes(script))

    def test_camera_times_scales_and_focus_are_strict_and_finite(self):
        path = [{"atSec": 0, "scale": 1, "focusX": 50, "focusY": 50},
                {"atSec": 2, "scale": 1.8, "focusX": 75, "focusY": 35, "ease": "settle"}]
        self.assertEqual([], validate_direction(self.script(camera=path)))
        for field, values, code in [
            ("atSec", [-1, 0, 4.01, float("nan"), "2"], "CAMERA_TIMING_INVALID"),
            ("scale", [0.99, 3.01, True, float("inf")], "CAMERA_SCALE_INVALID"),
            ("focusX", [-1, 100.01, float("nan")], "CAMERA_FOCUS_INVALID"),
            ("focusY", [-1, 100.01, False], "CAMERA_FOCUS_INVALID"),
            ("ease", ["bounce", {}, []], "CAMERA_EASE_INVALID"),
        ]:
            for value in values:
                with self.subTest(field=field, value=value):
                    broken = copy.deepcopy(path)
                    broken[1][field] = value
                    self.assertIn(code, self.codes(self.script(camera=broken)))

    def test_camera_conflicts_with_legacy_framing_are_explicit(self):
        camera = [{"atSec": 0, "scale": 1.5}]
        for legacy in ["scale", "startScale", "endScale", "focusX", "focusY", "panX", "panY",
                       "clickAtSec", "clickX", "clickY"]:
            self.assertIn("CAMERA_CONFLICT", self.codes(self.script(camera=camera, **{legacy: 1})))
        self.assertIn("CAMERA_CONFLICT", self.codes(self.script(camera=camera, zooms=[{"atSec": 1, "durSec": 1}])))
        self.assertIn("CAMERA_INVALID", self.codes(self.script(camera=camera, kind="title")))

    def test_camera_default_limit_is_legacy_compatible_and_explicit_override_caps_at_eight(self):
        self.assertEqual([], validate_direction(self.script(camera=[{"atSec": 0, "scale": 2.25}])))
        script = self.script(camera=[{"atSec": 0, "scale": 2.5}])
        self.assertIn("CAMERA_SCALE_INVALID", self.codes(script))
        script["production"] = {"maxZoomScale": 2.5}
        self.assertEqual([], validate_direction(script))
        script["production"]["maxZoomScale"] = 9
        script["shots"][0]["camera"][0]["scale"] = 8
        self.assertEqual([], validate_direction(script))
        script["shots"][0]["camera"][0]["scale"] = 8.01
        self.assertIn("CAMERA_SCALE_INVALID", self.codes(script))

    def test_studio_score_requires_actual_finite_evidence_and_positive_denominator(self):
        self.assertIn("SCORE_INVALID", self.codes(self.script(kind="score")))
        for score in [None, True, "72", -1, 100.01, float("nan"), float("inf")]:
            with self.subTest(score=score):
                self.assertIn("SCORE_INVALID", self.codes(self.script(kind="score", score=score)))
        for maximum in [0, -1, False, "100", None, float("nan"), float("inf")]:
            self.assertIn("SCORE_MAX_INVALID", self.codes(self.script(kind="score", score=1, scoreMax=maximum)))
        for score in [0, 2.5, 5]:
            self.assertEqual([], validate_direction(self.script(kind="score", score=score, scoreMax=5)))
        with self.assertRaisesRegex(ValueError, "SCORE_INVALID"):
            compile_direction(self.script(kind="score"))

    def test_studio_bars_require_actual_takes_and_valid_score_thresholds(self):
        self.assertIn("TAKES_INVALID", self.codes(self.script(kind="bars")))
        for takes in [None, [], "46, 80", [False], [-1], [101], [float("nan")], [float("inf")], [{}]]:
            with self.subTest(takes=takes):
                self.assertIn("TAKES_INVALID", self.codes(self.script(kind="bars", takes=takes)))
        for pass_line in [None, -1, 11, False, "8", float("nan"), float("inf")]:
            self.assertIn("PASS_LINE_INVALID", self.codes(self.script(kind="bars", takes=[4, 8], scoreMax=10, passLine=pass_line)))
        for maximum in [0, -1, float("nan"), float("inf")]:
            self.assertIn("SCORE_MAX_INVALID", self.codes(self.script(kind="bars", takes=[4, 8], scoreMax=maximum)))
        valid = self.script(kind="bars", takes=[0, 2.5, 5], scoreMax=5, passLine=4)
        self.assertEqual([], validate_direction(valid))
        with self.assertRaisesRegex(ValueError, "TAKES_INVALID"):
            compile_direction(self.script(kind="bars"))

    def test_classic_score_and_bar_defaults_remain_backward_compatible(self):
        for kind in ["score", "bars"]:
            for creative in [None, {"style": "classic"}]:
                script = self.script(kind=kind)
                if creative is None:
                    del script["creativeDirection"]
                else:
                    script["creativeDirection"] = creative
                self.assertEqual([], validate_direction(script))
                self.assertEqual("classic", compile_direction(script)["style"])

    def test_title_lines_preserve_claims_and_emphasis_requires_exact_nonempty_text(self):
        title = "From first click to verified result."
        valid = self.script(kind="title", title=title,
                            titleLines=["From first click", "to verified result."], emphasis="verified result.")
        self.assertEqual([], validate_direction(valid))
        for lines in [["From first click", "to guaranteed result."], ["verified result.", "From first click to"]]:
            self.assertIn("TITLE_TEXT_CHANGED", self.codes(self.script(kind="title", title=title, titleLines=lines)))
        for lines in [[], [""], ["a"] * 6, "From first click", [None]]:
            self.assertIn("TITLE_LINES_INVALID", self.codes(self.script(kind="title", title=title, titleLines=lines)))
        for emphasis in ["", " ", "guaranteed", "Verified", None, []]:
            self.assertIn("EMPHASIS_INVALID", self.codes(self.script(kind="title", title=title, emphasis=emphasis)))

    def test_annotation_geometry_and_timing_cannot_escape_source_or_shot(self):
        annotation = {"atSec": 1, "endSec": 3, "x": 10, "y": 20, "width": 60, "height": 40,
                      "kind": "spotlight", "label": "Verified result"}
        self.assertEqual([], validate_direction(self.script(annotations=[annotation])))
        for change, code in [({"atSec": -1}, "DIRECTION_TIMING_INVALID"),
                             ({"endSec": 4.1}, "ANNOTATION_TIMING_INVALID"),
                             ({"endSec": 1}, "ANNOTATION_TIMING_INVALID"),
                             ({"x": 50}, "ANNOTATION_BOUNDS_INVALID"),
                             ({"height": 0}, "ANNOTATION_BOUNDS_INVALID"),
                             ({"width": float("nan")}, "ANNOTATION_BOUNDS_INVALID"),
                             ({"kind": "fake-ui"}, "ANNOTATION_INVALID")]:
            self.assertIn(code, self.codes(self.script(annotations=[{**annotation, **change}])))
        self.assertIn("ANNOTATION_INVALID", self.codes(self.script(kind="title", annotations=[annotation])))

    def test_authored_paths_are_preserved_by_value_and_input_is_never_mutated(self):
        path = [{"atSec": 0, "scale": 1}, {"atSec": 1, "scale": 2, "focusX": 65, "ease": "drive"},
                {"atSec": 3, "scale": 2, "focusX": 65}]
        script = self.script(camera=path, direction={"intent": "focus", "energy": 0.9, "focus": {"x": 10, "y": 20}})
        before = copy.deepcopy(script)
        row = compile_direction(script)["shots"][0]
        self.assertEqual(path, row["camera"])
        row["camera"][1]["scale"] = 1
        row["direction"]["focus"]["x"] = 99
        self.assertEqual(before, script)

    def test_classic_compilation_retains_legacy_transitions_and_does_not_invent_motion(self):
        shots = [
            {"n": 1, "kind": "title", "durSec": 2, "title": "Proof"},
            {"n": 2, "kind": "clip", "durSec": 4, "src": "proof.mp4",
             "direction": {"intent": "focus", "focus": {"x": 75, "y": 50}}},
            {"n": 3, "kind": "clip", "durSec": 4, "src": "proof.mp4"},
            {"n": 4, "kind": "clip", "durSec": 4, "src": "other.mp4"},
            {"n": 5, "kind": "title", "durSec": 2, "flash": True},
            {"n": 6, "kind": "cta", "durSec": 2, "transition": "cut"},
        ]
        for creative in [{}, {"creativeDirection": {"style": "classic"}}]:
            rows = compile_direction({"shots": shots, **creative})["shots"]
            self.assertEqual(["cut", "xfade", "cut", "xfade", "cut", "cut"], [row["transition"] for row in rows])
            self.assertTrue(all(row["transitionSec"] == 0.3 for row in rows))
            self.assertTrue(all(not row["studio"] and not row["camera"] and not row["soundCues"] for row in rows))
            self.assertTrue(all(row["direction"]["layout"] == "fullbleed" for row in rows))

    def test_locks_are_enforced_but_explicit_false_framing_lock_allows_direction(self):
        focus = {"intent": "focus", "layout": "stage", "focus": {"x": 80, "y": 30}}
        for lock in ["proof.mp4", {"src": "proof.mp4"}, {"src": "proof.mp4", "preserveFraming": True}]:
            script = self.script(direction=focus)
            script["production"] = {"sourceLocks": [lock]}
            row = compile_direction(script)["shots"][0]
            self.assertEqual([], row["camera"])
            self.assertEqual("fullbleed", row["direction"]["layout"])
            script["shots"][0]["camera"] = [{"atSec": 0, "scale": 1.2}]
            self.assertIn("SOURCE_FRAMING_CHANGED", self.codes(script))
        script = self.script(direction=focus)
        script["production"] = {"sourceLocks": [{"src": "proof.mp4", "preserveFraming": False}]}
        self.assertTrue(compile_direction(script)["shots"][0]["camera"])
        script["shots"][0]["preserveFraming"] = True
        self.assertFalse(compile_direction(script)["shots"][0]["camera"])

    def test_generated_camera_requires_grounded_focus_and_respects_limits_and_reading_time(self):
        focus = {"intent": "focus", "energy": 1, "focus": {"x": 80, "y": 30}}
        self.assertEqual([], compile_direction(self.script(direction={"intent": "focus"}))["shots"][0]["camera"])
        script = self.script(direction=focus)
        script["production"] = {"maxZoomScale": 1.1}
        camera = compile_direction(script)["shots"][0]["camera"]
        self.assertEqual(1.1, camera[-1]["scale"])
        self.assertEqual((80, 30), (camera[-1]["focusX"], camera[-1]["focusY"]))
        self.assertLess(camera[-1]["atSec"], 2)
        script["shots"][0]["camera"] = [{"atSec": 0, "scale": 1.2}]
        self.assertIn("CAMERA_SCALE_INVALID", self.codes(script))
        for duration in [1 / 30, 2 / 30, 0.12, 0.5, 1.4]:
            row = compile_direction(self.script(durSec=duration, direction=focus))["shots"][0]
            if duration == 1 / 30:
                self.assertEqual([], row["camera"])
            else:
                self.assertLessEqual(row["camera"][-1]["atSec"], (math.floor(duration * 30 + 0.5) - 1) / 30)
            self.assertGreaterEqual(row["transitionSec"], 0)
            self.assertLessEqual(row["transitionSec"], max(0, duration - 1 / 30))

    def test_legacy_authored_motion_and_human_framing_are_not_overwritten(self):
        focus = {"intent": "focus", "focus": {"x": 80, "y": 30}}
        for legacy in [{"zooms": [{"atSec": 0, "durSec": 2}]}, {"clickAtSec": 0}, {"scale": 1.1},
                       {"startScale": 1.1}, {"endScale": 1.1}, {"panX": 3}, {"panY": -3}, {"focusX": 80}]:
            self.assertEqual([], compile_direction(self.script(direction=focus, **legacy))["shots"][0]["camera"])
        self.assertEqual([], compile_direction(self.script(direction=focus, sourceType="human"))["shots"][0]["camera"])
        authored = [{"atSec": 0, "scale": 1.1}, {"atSec": 3, "scale": 1.2}]
        self.assertEqual(authored, compile_direction(self.script(camera=authored, sourceType="human"))["shots"][0]["camera"])

    def test_sound_defaults_are_sparse_and_explicit_quiet_choices_win(self):
        script = {"creativeDirection": {"style": "studio"}, "shots": [
            {"n": 1, "kind": "title", "title": "Watch", "durSec": 2},
            {"n": 2, "kind": "clip", "src": "proof.mp4", "durSec": 3},
            {"n": 3, "kind": "clip", "src": "proof.mp4", "durSec": 3},
            {"n": 4, "kind": "cta", "title": "Try it", "durSec": 2},
        ]}
        rows = compile_direction(script)["shots"]
        self.assertEqual([[], ["studio_air"], [], ["studio_resolve"]], [[cue["sound"] for cue in row["soundCues"]] for row in rows])
        for options in [{"soundCues": []}, {"accent": "success_chime"}]:
            script["shots"][3].update(options)
            self.assertEqual([], compile_direction(script)["shots"][3]["soundCues"])
        quiet = [{"atSec": 0.2, "sound": "studio_tick", "volume": 0}]
        self.assertEqual(quiet, compile_direction(self.script(soundCues=quiet))["shots"][0]["soundCues"])
        for style in ["studio", "classic"]:
            script = self.script(soundCues=quiet)
            script["creativeDirection"] = {"style": style, "soundDesign": "silent"}
            self.assertEqual([], compile_direction(script)["shots"][0]["soundCues"])

    def test_sound_and_direction_numbers_are_finite_and_within_bounds(self):
        for cue in [{"atSec": 4, "sound": "studio_tick"}, {"atSec": float("nan"), "sound": "studio_tick"},
                    {"atSec": 0, "sound": []}, {"atSec": 0, "sound": "studio_air", "volume": -0.1},
                    {"atSec": 0, "sound": "studio_air", "volume": float("inf")}]:
            self.assertTrue(validate_direction(self.script(soundCues=[cue])))
        for direction in [{"energy": True}, {"energy": float("nan")}, {"energy": 1.1},
                          {"focus": {"x": 101, "y": 50}}, {"focus": {"x": 40}}, {"layout": []}]:
            self.assertIn("DIRECTION_INVALID", self.codes(self.script(direction=direction)))
        for transition_sec in [0, -1, 1.21, float("nan"), True]:
            self.assertIn("TRANSITION_INVALID", self.codes(self.script(transitionSec=transition_sec)))

    def test_caption_font_size_is_explicit_and_bounded_in_composition_pixels(self):
        for size in [16, 72, 160]:
            self.assertEqual([], validate_direction(self.script(captionFontSize=size)))
        for size in [None, False, "72", 15.99, 160.01, float("nan"), float("inf")]:
            self.assertIn("CAPTION_SIZE_INVALID", self.codes(self.script(captionFontSize=size)))

    def test_composition_alignment_is_explicit_validated_and_keeps_legacy_default(self):
        legacy = compile_direction(self.script())["shots"][0]
        self.assertNotIn("align", legacy["direction"])
        for alignment in ("left", "center"):
            script = self.script(direction={"align": alignment})
            original = copy.deepcopy(script)
            self.assertEqual([], validate_direction(script))
            self.assertEqual(alignment, compile_direction(script)["shots"][0]["direction"]["align"])
            self.assertEqual(original, script)
        for invalid in (None, True, [], {}, "right", "Center"):
            with self.subTest(alignment=invalid):
                self.assertIn("DIRECTION_INVALID", self.codes(self.script(direction={"align": invalid})))

    def test_source_window_preserves_connected_camera_and_product_human_actor(self):
        window = {"x": 25, "y": 20, "width": 50, "height": 60}
        path = [{"atSec": 0, "scale": 1}, {"atSec": 1, "scale": 2, "focusX": 50, "focusY": 50}]
        script = self.script(sourceWindow=window, sourceType="product", actor="human", camera=path)
        before = copy.deepcopy(script)
        row = compile_direction(script)["shots"][0]
        self.assertEqual(path, row["camera"])
        self.assertEqual(window, row["sourceWindow"])
        self.assertEqual(before, script)
        for edit, code in [({"kind": "title"}, "SOURCE_WINDOW_INVALID"),
                           ({"sourceType": "human"}, "SOURCE_WINDOW_HUMAN_FORBIDDEN"),
                           ({"preserveFraming": True}, "SOURCE_FRAMING_CHANGED"),
                           ({"sourceDetail": {"sourceRect": window}}, "SOURCE_WINDOW_CONFLICT")]:
            changed = copy.deepcopy(script)
            changed["shots"][0].update(edit)
            self.assertIn(code, self.codes(changed))
        script["production"] = {"sourceLocks": ["proof.mp4"]}
        self.assertIn("SOURCE_FRAMING_CHANGED", self.codes(script))

    def test_source_window_requires_complete_targets_and_finite_source_geometry(self):
        window = {"x": 25, "y": 20, "width": 50, "height": 60}
        shot = {"sourceWindow": window, "framing": {"sourceWidth": 1920, "sourceHeight": 1080,
                "beats": [{"atSec": 0, "endSec": 4, "rect": dict(window)}]}}
        self.assertEqual([], validate_direction(self.script(**shot)))
        shot["framing"]["beats"][0]["rect"]["width"] += 0.001
        self.assertIn("SOURCE_WINDOW_TARGET_CROP", self.codes(self.script(**shot)))
        shot["framing"]["presentation"] = "detail"
        self.assertIn("SOURCE_WINDOW_CONFLICT", self.codes(self.script(**shot)))
        for value in [None, [], {}, {**window, "x": True}, {**window, "height": float("nan")},
                      {**window, "width": 0}, {**window, "x": -0.000001}, {**window, "width": 75.000001}]:
            self.assertIn("SOURCE_WINDOW_INVALID", self.codes(self.script(sourceWindow=value)))
        self.assertEqual([], validate_direction(self.script(sourceWindow={
            "x": 1384 / 19.2, "y": 0, "width": 536 / 19.2, "height": 100})))
        self.assertIn("SOURCE_WINDOW_TARGET_CROP", self.codes(self.script(sourceWindow=window,
            annotations=[{"atSec": 0, "endSec": 4, "x": 24, "y": 30, "width": 10, "height": 10}])))


if __name__ == "__main__":
    unittest.main()
