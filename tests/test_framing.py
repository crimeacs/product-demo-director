"""Measured camera framing and honest small-screen readability estimates."""

import copy
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "tools"))

from direction import compile_direction, validate_direction
from framing import compile_framing, validate_framing


class FramingTests(unittest.TestCase):
    def test_detail_copy_stays_outside_plate_and_rejects_impossible_layout(self):
        valid = self.detail_shot(title="Saved policy", caption="Separate recorded shopper test", captionFontSize=72)
        self.assertEqual([], validate_framing(valid))
        valid["captionTop"] = 940
        self.assertEqual([], validate_framing(valid))
        valid.pop("captionTop")
        for changes, code in [
            ({"title": "A complete control with explanatory context " * 10}, "FRAMING_DETAIL_TITLE_INVALID"),
            ({"captionBottom": 108}, "FRAMING_DETAIL_CAPTION_INVALID"),
            ({"captionTop": 800}, "FRAMING_DETAIL_CAPTION_INVALID"),
            ({"captionTop": 1000}, "FRAMING_DETAIL_CAPTION_INVALID"),
            ({"caption": "W" * 100}, "FRAMING_DETAIL_CAPTION_INVALID"),
        ]:
            with self.subTest(changes=changes):
                shot = {**copy.deepcopy(valid), **changes}
                self.assertIn(code, {finding["code"] for finding in validate_framing(shot)})
                with self.assertRaisesRegex(ValueError, code):
                    compile_framing(shot)
        valid["framing"]["screenRect"] = {"x": 7, "y": 0, "width": 86, "height": 55}
        self.assertIn("FRAMING_DETAIL_TITLE_INVALID", {finding["code"] for finding in validate_framing(valid)})

    def test_detail_copy_preserves_false_caption_and_valid_multiline_title(self):
        shot = self.detail_shot(title="A complete recorded control explains why the reviewer made this decision",
                                caption=False, vo="W" * 100)
        self.assertEqual([], validate_framing(shot))
        shot["caption"] = ""
        self.assertEqual([], validate_framing(shot))
        shot.pop("caption")
        self.assertIn("FRAMING_DETAIL_CAPTION_INVALID", {finding["code"] for finding in validate_framing(shot)})

    def shot(self, **changes):
        return {"n": 1, "kind": "clip", "src": "actual.mp4", "durSec": 6,
                "framing": {"sourceWidth": 1920, "sourceHeight": 1080,
                            "beats": [{"atSec": 0, "endSec": 6,
                                       "rect": {"x": 45, "y": 30, "width": 15, "height": 12},
                                       "textHeightPx": 14}]}, **changes}

    def script(self, shot=None, **changes):
        return {"fps": 30, "creativeDirection": {"style": "studio"},
                "shots": [shot or self.shot()], **changes}

    def test_measured_subject_fills_view_and_text_projects_to_viewing_pixels(self):
        shot = self.shot()
        before = copy.deepcopy(shot)
        camera, report = compile_framing(shot)
        scale = 0.88 / 0.15
        self.assertEqual(before, shot)
        self.assertEqual(8, report["maxZoomScale"])
        self.assertAlmostEqual(scale, camera[0]["scale"])
        self.assertEqual((52.5, 36), (camera[0]["focusX"], camera[0]["focusY"]))
        beat = report["beats"][0]
        self.assertAlmostEqual(14 * scale * 320 / 1920, beat["projectedTextPx"])
        self.assertAlmostEqual(12 / (14 * 320 / 1920), beat["requiredScale"])
        self.assertAlmostEqual(320 * 0.88, beat["projectedRectPx"]["width"])
        self.assertTrue(beat["subjectVisible"])
        self.assertTrue(beat["safeAreaMet"])
        self.assertEqual("needs-review", report["status"])
        self.assertIn("FRAMING_OUTPUT_MAGNIFIED", {item["code"] for item in report["findings"]})
        self.assertTrue(report["advisory"])

    def test_reading_whole_panel_does_not_crop_context_to_fake_legibility(self):
        shot = self.shot()
        shot["framing"]["beats"][0]["rect"] = {"x": 25, "y": 20, "width": 50, "height": 50}
        camera, report = compile_framing(shot)
        self.assertAlmostEqual(1.76, camera[0]["scale"])
        self.assertTrue(report["beats"][0]["subjectVisible"])
        self.assertLess(report["beats"][0]["projectedTextPx"], 5)
        self.assertEqual("needs-review", report["status"])
        self.assertIn("FRAMING_TEXT_TOO_SMALL", {item["code"] for item in report["findings"]})

    def test_unknown_glyph_measurement_never_claims_readability(self):
        shot = self.shot()
        del shot["framing"]["beats"][0]["textHeightPx"]
        _, report = compile_framing(shot)
        self.assertIsNone(report["beats"][0]["projectedTextPx"])
        self.assertEqual("needs-review", report["status"])  # Text is unknown; output magnification is known.
        self.assertEqual("FRAMING_TEXT_UNMEASURED", report["findings"][0]["code"])

    def test_source_edge_rectangles_tolerate_only_float_rounding_noise(self):
        for left, width in ((850, 1070), (1384, 536)):
            shot = self.shot()
            rect = shot["framing"]["beats"][0]["rect"]
            rect.update(x=left / 19.2, width=width / 19.2)
            self.assertEqual([], validate_framing(shot))
            _, report = compile_framing(shot)
            self.assertTrue(report["beats"][0]["subjectVisible"])
            rect["width"] += 1e-6
            self.assertIn("FRAMING_RECT_INVALID", {item["code"] for item in validate_framing(shot)})
        shot = self.shot()
        shot["framing"]["beats"][0]["rect"]["x"] = -1e-6
        self.assertIn("FRAMING_RECT_INVALID", {item["code"] for item in validate_framing(shot)})

    def test_fractional_frame_duration_rounding_does_not_reject_full_shot_holds(self):
        for duration in (2.933333333333333, round(2.933333333333333, 6)):
            for presentation in ("camera", "detail"):
                shot = self.shot(durSec=duration)
                shot["framing"]["presentation"] = presentation
                shot["framing"]["beats"][0]["endSec"] = 2.9333333333333336
                self.assertEqual([], validate_framing(shot))
                camera, report = compile_framing(shot)
                self.assertEqual(duration, report["beats"][0]["endSec"])
                if camera:
                    self.assertLessEqual(camera[-1]["atSec"], duration)
                shot["framing"]["beats"][0]["endSec"] = duration + 0.001
                self.assertIn("FRAMING_TIMING_INVALID", {finding["code"] for finding in validate_framing(shot)})

    def test_explicit_scale_cap_is_respected_and_unmet_size_is_reported(self):
        camera, report = compile_framing(self.shot(), {"maxZoomScale": 2.25})
        self.assertEqual(2.25, camera[0]["scale"])
        self.assertEqual("needs-review", report["status"])
        tiny = self.shot()
        tiny["framing"]["beats"][0]["rect"] = {"x": 49, "y": 49, "width": 1, "height": 1}
        camera, _ = compile_framing(tiny, {"maxZoomScale": 15})
        self.assertEqual(8, camera[0]["scale"])

    def test_full_source_cover_bounds_reach_subject_outside_base_crop(self):
        shot = self.shot()
        shot["framing"].update(sourceWidth=1080, sourceHeight=1920)
        shot["framing"]["beats"][0]["rect"] = {"x": 30, "y": 5, "width": 40, "height": 5}
        camera, report = compile_framing(shot)
        self.assertEqual(7.5, camera[0]["focusY"])
        self.assertTrue(report["beats"][0]["subjectVisible"])
        self.assertTrue(report["beats"][0]["safeAreaMet"])
        self.assertAlmostEqual(90, report["beats"][0]["projectedRectPx"]["y"]
                               + report["beats"][0]["projectedRectPx"]["height"] / 2)

    def test_contain_and_cover_report_the_same_size_when_subject_fit_is_limiting(self):
        cover = self.shot()
        cover["framing"].update(sourceWidth=1080, sourceHeight=1920)
        cover["framing"]["beats"][0]["rect"] = {"x": 30, "y": 45, "width": 40, "height": 5}
        contain = {**cover, "objectFit": "contain"}
        _, a = compile_framing(cover)
        _, b = compile_framing(contain)
        self.assertAlmostEqual(a["beats"][0]["projectedTextPx"], b["beats"][0]["projectedTextPx"])
        self.assertTrue(b["beats"][0]["subjectVisible"])

    def test_edges_and_large_cover_subjects_report_unmet_insets_or_clipping(self):
        shot = self.shot()
        shot["framing"]["beats"][0]["rect"] = {"x": 0, "y": 40, "width": 15, "height": 12}
        _, report = compile_framing(shot)
        self.assertTrue(report["beats"][0]["subjectVisible"])
        self.assertFalse(report["beats"][0]["safeAreaMet"])
        self.assertIn("FRAMING_SAFE_AREA_MISSED", {item["code"] for item in report["findings"]})
        shot["framing"].update(sourceWidth=1080, sourceHeight=1920)
        shot["framing"]["beats"][0]["rect"] = {"x": 0, "y": 0, "width": 100, "height": 100}
        _, report = compile_framing(shot)
        self.assertFalse(report["beats"][0]["subjectVisible"])
        self.assertIn("FRAMING_SUBJECT_CLIPPED", {item["code"] for item in report["findings"]})

    def test_reading_holds_are_stationary_and_moves_arrive_before_next_reading_window(self):
        shot = self.shot()
        first = shot["framing"]["beats"][0]
        first["endSec"] = 2
        second = copy.deepcopy(first)
        second.update(atSec=3.5, endSec=6)
        second["rect"]["x"] = 65
        shot["framing"]["beats"].append(second)
        camera, report = compile_framing(shot)
        self.assertEqual([0, 2, 3.05, 3.5, 6], [point["atSec"] for point in camera])
        self.assertEqual(camera[0]["focusX"], camera[2]["focusX"])
        self.assertEqual(camera[3]["focusX"], camera[4]["focusX"])
        second["atSec"] = 2.1
        self.assertIn("FRAMING_TIMING_INVALID", {item["code"] for item in validate_framing(shot)})

    def moving_shot(self, second_x=55):
        shot = self.shot(sourceTimeline=[{"fromSec": 0, "toSec": 6, "durSec": 6, "mode": "realtime"}])
        first = shot["framing"]["beats"][0]
        first["endSec"] = 2
        second = copy.deepcopy(first)
        second.update(atSec=3.5, endSec=6)
        second["rect"]["x"] = second_x
        shot["framing"]["beats"].append(second)
        return shot

    def test_distance_budget_spends_only_available_gap_and_preserves_source_actions(self):
        shot = self.moving_shot()
        shot["framing"]["motion"] = {}
        before = copy.deepcopy(shot)
        camera, report = compile_framing(shot)
        move = report["motion"]["moves"][0]
        self.assertEqual(before, shot)
        self.assertGreater(move["durationSec"], 0.45)
        self.assertLess(move["durationSec"], 1.5)
        self.assertGreaterEqual(move["startSec"], 2)
        self.assertEqual(3.5, move["endSec"])
        self.assertEqual([0, 2, move["startSec"], 3.5, 6], [p["atSec"] for p in camera])
        self.assertTrue(move["feasible"])
        self.assertLessEqual(move["peakTravelScreensPerSecBound"], 1.5 + 1e-9)
        self.assertEqual("within-budget", report["motion"]["status"])

    def test_gentle_nearby_move_keeps_authored_minimum_duration(self):
        shot = self.moving_shot(second_x=46)
        legacy_camera, legacy_report = compile_framing(shot)
        self.assertNotIn("motion", legacy_report)
        shot["framing"]["motion"] = {}
        camera, report = compile_framing(shot)
        self.assertEqual(legacy_camera, camera)
        self.assertAlmostEqual(0.45, report["motion"]["moves"][0]["durationSec"])

    def test_fast_cart_pan_is_reported_without_stealing_reading_time(self):
        # Regression from the actual rejected cut: cart header to checkout at
        # ~3.3x travelled ~2490 output pixels in just 0.65 seconds.
        shot = self.shot(durSec=3)
        shot["framing"].update(safeInsetPct=2, transitionSec=0.65, motion={}, beats=[
            {"atSec": 0, "endSec": 0.85,
             "rect": {"x": 71.6666666667, "y": 0, "width": 28.3333333333, "height": 29.6296296296}},
            {"atSec": 1.5, "endSec": 3,
             "rect": {"x": 71.6666666667, "y": 71.4814814815, "width": 28.3333333333, "height": 28.5185185185}},
        ])
        camera, report = compile_framing(shot)
        move = report["motion"]["moves"][0]
        self.assertFalse(move["feasible"])
        self.assertGreater(move["travelScreens"], 2.3)
        self.assertGreater(move["requiredSec"], 2.8)
        self.assertGreater(move["peakTravelScreensPerSecBound"], 6)
        self.assertAlmostEqual(0.85, move["startSec"])
        self.assertEqual(1.5, move["endSec"])
        self.assertEqual([0, 0.85, 1.5, 3], [p["atSec"] for p in camera])
        self.assertIn("FRAMING_MOTION_BUDGET_EXCEEDED", {v["code"] for v in report["findings"]})
        self.assertEqual("needs-review", report["motion"]["status"])

    def test_motion_budget_is_independent_of_delivery_resolution(self):
        shot = self.moving_shot()
        shot["framing"]["motion"] = {}
        _, full = compile_framing(shot)
        _, phone = compile_framing(shot, width=320, height=180)
        for key in ("travelScreens", "zoomOctaves", "requiredSec", "durationSec"):
            self.assertAlmostEqual(full["motion"]["moves"][0][key], phone["motion"]["moves"][0][key])

    def test_zoom_budget_limits_centered_push_even_without_camera_pan(self):
        shot = self.shot(durSec=18)
        shot["framing"].update(motion={"maxZoomOctavesPerSec": 0.8}, beats=[
            {"atSec": 0, "endSec": 2, "rect": {"x": 0, "y": 0, "width": 100, "height": 100}},
            {"atSec": 14, "endSec": 18, "rect": {"x": 40, "y": 40, "width": 20, "height": 20}},
        ])
        _, report = compile_framing(shot)
        move = report["motion"]["moves"][0]
        self.assertGreater(move["zoomOctaves"], 2)
        self.assertGreater(move["durationSec"], 10)
        self.assertTrue(move["feasible"])
        self.assertLessEqual(move["peakZoomOctavesPerSecBound"], 0.8 + 1e-9)

    def test_motion_options_reject_silent_typos_and_invalid_limits(self):
        for motion in (None, False, [], {"maxSpeed": 1}, {"maxTravelScreensPerSec": 0},
                       {"maxZoomOctavesPerSec": float("nan")}, {"maxTravelScreensPerSec": 1e-300},
                       {"maxTravelScreensPerSec": True}):
            with self.subTest(motion=motion):
                shot = self.moving_shot()
                shot["framing"]["motion"] = motion
                self.assertIn("FRAMING_MOTION_INVALID", {v["code"] for v in validate_framing(shot)})
                with self.assertRaisesRegex(ValueError, "FRAMING_MOTION_INVALID"):
                    compile_framing(shot)
        detail = self.detail_shot()
        detail["framing"]["motion"] = {}
        self.assertIn("FRAMING_MOTION_INVALID", {v["code"] for v in validate_framing(detail)})

    def test_motion_diagnostics_reach_direction_report(self):
        shot = self.moving_shot()
        shot["framing"]["motion"] = {}
        directed = compile_direction(self.script(shot))["shots"][0]
        self.assertEqual("distance-aware", directed["framingReport"]["motion"]["mode"])
        self.assertTrue(directed["framingReport"]["motion"]["moves"][0]["feasible"])

    def test_direction_compiles_opt_in_framing_without_mutating_inputs_or_legacy_defaults(self):
        script = self.script()
        before = copy.deepcopy(script)
        row = compile_direction(script)["shots"][0]
        self.assertGreater(row["camera"][0]["scale"], 3)
        self.assertEqual("fullbleed", row["direction"]["layout"])
        self.assertEqual("needs-review", row["framingReport"]["status"])
        self.assertEqual(before, script)
        legacy = self.shot(camera=[{"atSec": 0, "scale": 3}])
        del legacy["framing"]
        self.assertIn("CAMERA_SCALE_INVALID", {item["code"] for item in validate_direction(self.script(legacy))})
        classic = compile_direction(self.script(creativeDirection={"style": "classic"}))["shots"][0]
        self.assertGreater(classic["camera"][0]["scale"], 3)

    def test_framing_conflicts_are_explicit_and_source_locks_win(self):
        cases = [self.shot(camera=[{"atSec": 0, "scale": 1}]), self.shot(scale=1),
                 self.shot(zooms=[{"atSec": 0, "durSec": 2}])]
        for shot in cases:
            self.assertIn("CAMERA_CONFLICT", {item["code"] for item in validate_direction(self.script(shot))})
        self.assertIn("SOURCE_FRAMING_CHANGED", {item["code"] for item in validate_direction(
            self.script(production={"sourceLocks": ["actual.mp4"]}))})
        self.assertIn("FRAMING_LAYOUT_INVALID", {item["code"] for item in validate_direction(
            self.script(self.shot(direction={"layout": "stage"})))})

    def detail_shot(self, **changes):
        shot = self.shot(**changes)
        shot["framing"]["presentation"] = "detail"
        return shot

    def test_detail_fits_complete_component_in_output_plate_without_camera(self):
        shot = self.detail_shot()
        original = copy.deepcopy(shot)
        camera, report = compile_framing(shot)
        self.assertEqual([], camera)
        self.assertEqual(original, shot)
        detail = report["sourceDetail"]
        self.assertEqual(shot["framing"]["beats"][0]["rect"], detail["sourceRect"])
        self.assertEqual({"x": 7, "y": 25, "width": 86, "height": 55}, detail["screenRect"])
        self.assertEqual(0, detail["radiusPx"])
        self.assertEqual(0.4, detail["entranceSec"])
        beat = report["beats"][0]
        # Source ROI is 288×129.6; available plate is 1651.2×594. Height limits fit.
        scale = 594 / 129.6
        self.assertAlmostEqual(scale, beat["sourceToOutputScale"])
        self.assertAlmostEqual(scale / 6, beat["sourceToViewerScale"])
        self.assertAlmostEqual(14 * scale / 6, beat["projectedTextPx"])
        self.assertAlmostEqual(99, beat["projectedRectPx"]["height"])
        self.assertAlmostEqual(160, beat["projectedRectPx"]["x"] + beat["projectedRectPx"]["width"] / 2)
        self.assertTrue(beat["subjectVisible"])
        self.assertTrue(beat["safeAreaMet"])

    def test_detail_allows_downscale_and_ignores_camera_limits_and_object_fit(self):
        shot = self.detail_shot()
        shot["framing"]["beats"][0]["rect"] = {"x": 0, "y": 0, "width": 100, "height": 100}
        camera, report = compile_framing(shot, {"maxZoomScale": 1})
        self.assertEqual([], camera)
        self.assertAlmostEqual(0.55, report["beats"][0]["sourceToOutputScale"])
        self.assertLess(report["beats"][0]["camera"]["scale"], 1)
        self.assertEqual("needs-review", report["status"])
        shot["framing"]["sourceWidth"] = 1440
        _, cover = compile_framing(shot, {"maxZoomScale": 1})
        shot["objectFit"] = "contain"
        _, contain = compile_framing(shot, {"maxZoomScale": 8})
        self.assertAlmostEqual(cover["beats"][0]["projectedTextPx"], contain["beats"][0]["projectedTextPx"])
        self.assertEqual(cover["beats"][0]["projectedRectPx"], contain["beats"][0]["projectedRectPx"])
        self.assertNotEqual(cover["beats"][0]["camera"]["scale"], contain["beats"][0]["camera"]["scale"])

    def test_detail_respects_custom_screen_rectangle_and_reports_viewer_upsampling(self):
        shot = self.detail_shot()
        shot["framing"]["screenRect"] = {"x": 10, "y": 20, "width": 70, "height": 60}
        shot["framing"]["beats"][0]["rect"] = {"x": 40, "y": 40, "width": 5, "height": 5}
        _, report = compile_framing(shot)
        rect = report["beats"][0]["projectedRectPx"]
        self.assertAlmostEqual(108, rect["height"])
        self.assertAlmostEqual(144, rect["x"] + rect["width"] / 2)
        self.assertGreater(report["beats"][0]["sourceToViewerScale"], 1)
        self.assertIn("FRAMING_SOURCE_MAGNIFIED", {finding["code"] for finding in report["findings"]})
        self.assertEqual("needs-review", report["status"])

    def test_output_density_warning_survives_phone_preview_and_three_x_capture_resolves_it(self):
        for presentation in ("detail", "camera"):
            low = self.shot()
            low["framing"]["presentation"] = presentation
            low["framing"]["beats"][0].update(
                rect={"x": 25, "y": 25, "width": 40, "height": 20}, textHeightPx=36)
            high = copy.deepcopy(low)
            high["framing"].update(sourceWidth=5760, sourceHeight=3240)
            high["framing"]["beats"][0]["textHeightPx"] = 108
            _, low_report = compile_framing(low)
            _, high_report = compile_framing(high)
            a, b = low_report["beats"][0], high_report["beats"][0]
            with self.subTest(presentation=presentation):
                self.assertGreater(a["sourceToOutputScale"], 2)
                self.assertLess(a["sourceToViewerScale"], 1)
                self.assertAlmostEqual(1/a["sourceToOutputScale"], a["sourcePixelsPerOutputPixel"])
                self.assertIn("FRAMING_OUTPUT_MAGNIFIED", {v["code"] for v in low_report["findings"]})
                self.assertNotIn("FRAMING_SOURCE_MAGNIFIED", {v["code"] for v in low_report["findings"]})
                self.assertLess(b["sourceToOutputScale"], 1)
                self.assertAlmostEqual(a["sourcePixelsPerOutputPixel"]*3, b["sourcePixelsPerOutputPixel"])
                self.assertAlmostEqual(a["projectedTextPx"], b["projectedTextPx"])
                for key in a["projectedRectPx"]:
                    self.assertAlmostEqual(a["projectedRectPx"][key], b["projectedRectPx"][key])
                self.assertNotIn("FRAMING_OUTPUT_MAGNIFIED", {v["code"] for v in high_report["findings"]})
                self.assertEqual("clear-declared", high_report["status"])

    def test_output_density_uses_physical_source_fit_and_five_percent_tolerance(self):
        for fit in ("cover", "contain"):
            shot = self.shot(objectFit=fit)
            shot["framing"].update(sourceWidth=1080, sourceHeight=1920)
            _, report = compile_framing(shot)
            beat = report["beats"][0]
            base_fit = (max if fit == "cover" else min)(1920/1080, 1080/1920)
            self.assertAlmostEqual(base_fit*beat["camera"]["scale"], beat["sourceToOutputScale"])
        shot = self.detail_shot()
        shot["framing"]["beats"][0]["rect"] = {"x": 25, "y": 25, "width": 40, "height": 20}
        shot["framing"]["screenRect"] = {"x": 29, "y": 25, "width": 42, "height": 30}
        _, report = compile_framing(shot)
        self.assertAlmostEqual(1.05, report["beats"][0]["sourceToOutputScale"])
        self.assertNotIn("FRAMING_OUTPUT_MAGNIFIED", {v["code"] for v in report["findings"]})
        shot["framing"]["screenRect"]["width"] = 42.08
        _, report = compile_framing(shot)
        self.assertIn("FRAMING_OUTPUT_MAGNIFIED", {v["code"] for v in report["findings"]})

    def test_detail_entrance_can_be_disabled_without_changing_legacy_default(self):
        shot = self.detail_shot()
        _, legacy = compile_framing(shot)
        self.assertEqual(0.4, legacy["sourceDetail"]["entranceSec"])
        for seconds in (0, 0.15, 1):
            shot["framing"]["entranceSec"] = seconds
            before = copy.deepcopy(shot)
            self.assertEqual([], validate_framing(shot))
            _, report = compile_framing(shot)
            self.assertEqual(seconds, report["sourceDetail"]["entranceSec"])
            directed = compile_direction(self.script(shot))["shots"][0]
            self.assertEqual(seconds, directed["sourceDetail"]["entranceSec"])
            self.assertEqual(before, shot)

    def test_centered_detail_heading_keeps_native_geometry_and_source_unchanged(self):
        shot = self.detail_shot()
        _, legacy = compile_framing(shot)
        self.assertNotIn("titleAlign", legacy["sourceDetail"])
        shot["direction"] = {"align": "center"}
        original = copy.deepcopy(shot)
        _, centered = compile_framing(shot)
        self.assertEqual("center", centered["sourceDetail"]["titleAlign"])
        self.assertEqual(legacy["beats"], centered["beats"])
        self.assertEqual(legacy["sourceDetail"]["sourceRect"], centered["sourceDetail"]["sourceRect"])
        self.assertEqual(legacy["sourceDetail"]["screenRect"], centered["sourceDetail"]["screenRect"])
        directed = compile_direction(self.script(shot))["shots"][0]
        self.assertEqual("center", directed["sourceDetail"]["titleAlign"])
        self.assertEqual(original, shot)

    def test_detail_entrance_rejects_invalid_values_and_camera_presentation(self):
        for value in (-0.01, 1.01, None, False, "0", float("nan")):
            with self.subTest(value=value):
                shot = self.detail_shot()
                shot["framing"]["entranceSec"] = value
                self.assertIn("FRAMING_DETAIL_ENTRANCE_INVALID", {v["code"] for v in validate_framing(shot)})
        shot = self.shot()
        shot["framing"]["entranceSec"] = 0
        self.assertIn("FRAMING_DETAIL_ENTRANCE_INVALID", {v["code"] for v in validate_framing(shot)})

    def test_detail_propagates_compiled_geometry_and_never_generates_focus_camera(self):
        shot = self.detail_shot(direction={"intent": "focus", "focus": {"x": 50, "y": 50}})
        row = compile_direction(self.script(shot))["shots"][0]
        self.assertEqual([], row["camera"])
        self.assertEqual(row["framingReport"]["sourceDetail"], row["sourceDetail"])
        row["sourceDetail"]["sourceRect"]["x"] = 1
        self.assertNotEqual(1, row["framingReport"]["sourceDetail"]["sourceRect"]["x"])
        self.assertNotEqual(1, shot["framing"]["beats"][0]["rect"]["x"])

    def test_detail_requires_one_whole_shot_and_rejects_annotation_or_camera_conflicts(self):
        for alter in ("partial", "multiple", "annotation", "camera", "lock"):
            shot = self.detail_shot()
            if alter == "partial":
                shot["framing"]["beats"][0]["endSec"] = 5
                expected = "FRAMING_DETAIL_TIMING_INVALID"
            elif alter == "multiple":
                first = shot["framing"]["beats"][0]
                first["endSec"] = 2
                second = copy.deepcopy(first)
                second.update(atSec=2.5, endSec=6)
                shot["framing"]["beats"].append(second)
                expected = "FRAMING_DETAIL_TIMING_INVALID"
            elif alter == "annotation":
                shot["annotations"] = [{"atSec": 0, "endSec": 6, "x": 40, "y": 40, "width": 20, "height": 20}]
                expected = "FRAMING_DETAIL_CONFLICT"
            elif alter == "camera":
                shot["camera"] = [{"atSec": 0, "scale": 1}]
                expected = "CAMERA_CONFLICT"
            else:
                shot["preserveFraming"] = True
                expected = "SOURCE_FRAMING_CHANGED"
            with self.subTest(alter=alter):
                self.assertIn(expected, {finding["code"] for finding in validate_direction(self.script(shot))})
        for screen in [None, [], {}, {"x": 90, "y": 0, "width": 11, "height": 20},
                       {"x": 0, "y": 0, "width": float("nan"), "height": 20}]:
            shot = self.detail_shot()
            shot["framing"]["screenRect"] = screen
            self.assertIn("FRAMING_SCREEN_RECT_INVALID", {finding["code"] for finding in validate_framing(shot)})
        shot = self.shot()
        shot["framing"]["screenRect"] = {"x": 0, "y": 0, "width": 100, "height": 100}
        self.assertIn("FRAMING_PRESENTATION_INVALID", {finding["code"] for finding in validate_framing(shot)})

    def test_malformed_measurements_return_errors_without_crashes(self):
        for framing in [None, [], {}, {"sourceWidth": float("nan")}, {"beats": [None]}]:
            shot = self.shot(framing=framing)
            self.assertTrue(validate_framing(shot))
            with self.assertRaises(ValueError):
                compile_direction(self.script(shot))
        for field in ("sourceWidth", "sourceHeight", "viewerWidthPx", "minTextPx", "safeInsetPct", "transitionSec"):
            for value in [None, "320", False, float("inf"), float("nan"), 10 ** 400]:
                shot = self.shot()
                shot["framing"][field] = value
                with self.subTest(field=field, value=value):
                    self.assertTrue(validate_framing(shot))
        for change in [{"atSec": 0.1}, {"endSec": 9}, {"textHeightPx": 0}, {"label": []},
                       {"rect": None}, {"rect": {"x": 90, "y": 0, "width": 11, "height": 10}},
                       {"rect": {"x": 0, "y": 0, "width": 5e-324, "height": 10}}]:
            shot = self.shot()
            shot["framing"]["beats"][0].update(change)
            self.assertTrue(validate_framing(shot))


if __name__ == "__main__":
    unittest.main()
