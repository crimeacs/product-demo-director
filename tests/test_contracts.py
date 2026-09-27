import copy
import hashlib
import json
import os
import sys
import tempfile
import unittest
import wave
from unittest.mock import patch
from types import SimpleNamespace

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "tools"))

from contracts import SAVE_THE_CAT_BEATS, validate_script, _cursor_inside_camera, media_dimensions  # noqa: E402


class ContractTests(unittest.TestCase):
    def project(self):
        temp = tempfile.TemporaryDirectory()
        os.makedirs(os.path.join(temp.name, "assets"))
        os.makedirs(os.path.join(temp.name, "audio"))
        with open(os.path.join(temp.name, "assets", "product.mp4"), "wb") as fh:
            fh.write(b"video")
        self.addCleanup(temp.cleanup)
        return temp.name

    def base(self):
        return {
            "fps": 30,
            "production": {"profile": "investor", "hardMaxSec": 180},
            "shots": [{"n": 1, "kind": "clip", "src": "product.mp4", "durSec": 4,
                       "sourceType": "product", "storyBeat": "test", "liveState": True}],
        }

    def codes(self, script, project):
        return {item.code for item in validate_script(script, project)}

    def test_valid_causal_script_passes(self):
        project = self.project()
        self.assertFalse([f for f in validate_script(self.base(), project) if f.severity == "error"])

    def test_product_replay_requires_bound_provenance_and_explicit_nonlive_state(self):
        project = self.project()
        script = self.base()
        shot = script["shots"][0]
        shot.update(visualTreatment="replay")
        self.assertTrue({"REPLAY_PROVENANCE_REQUIRED", "REPLAY_LIVE_STATE_CONFLICT"}
                        <= self.codes(script, project))
        with open(os.path.join(project, "replay.json"), "w") as handle:
            json.dump({"recordedData": "frozen case", "reconstruction": "native component"}, handle)
        script["production"]["sourceManifests"] = ["replay.json"]
        shot.update(liveState=False, replayProvenance="replay.json")
        self.assertFalse({code for code in self.codes(script, project) if code.startswith("REPLAY_")})
        shot["replayProvenance"] = "unbound.json"
        self.assertIn("REPLAY_PROVENANCE_REQUIRED", self.codes(script, project))
        shot.update(replayProvenance="replay.json", sourceType="generated")
        self.assertTrue({"VISUAL_TREATMENT_CONFLICT", "PRESENTATION_RATIO_HIGH"}
                        <= self.codes(script, project))

    def test_evidence_excerpt_requires_provenance_and_honest_presentation(self):
        project = self.project()
        script = self.base()
        script["production"]["maxCardRatio"] = 1
        script["claims"] = [{"id": "recorded-finding", "status": "verified", "evidence": ["assets/product.mp4"]}]
        shot = {"n": 1, "kind": "title", "title": "Recorded finding", "durSec": 6,
                "sourceType": "generated", "visualTreatment": "presentation", "claimIds": ["recorded-finding"],
                "evidenceExcerpt": {"finding": "30-day returns window", "source": "Recorded merchant policy",
                                    "limitation": "Not independently substantiated.", "label": "Editorial excerpt"}}
        script["shots"] = [shot]
        self.assertFalse({code for code in self.codes(script, project) if code.startswith("EVIDENCE_EXCERPT_")})
        shot["sourceType"] = "product"
        self.assertIn("EVIDENCE_EXCERPT_PRESENTATION_REQUIRED", self.codes(script, project))
        shot["sourceType"] = "generated"
        shot["claimIds"] = []
        self.assertIn("EVIDENCE_EXCERPT_SUPPORT_REQUIRED", self.codes(script, project))
        for bad in (None, {}, {**shot["evidenceExcerpt"], "source": ""},
                    {**shot["evidenceExcerpt"], "finding": "x" * 91}):
            with self.subTest(bad=bad):
                shot["evidenceExcerpt"] = bad
                self.assertIn("EVIDENCE_EXCERPT_INVALID", self.codes(script, project))

    @patch("contracts.media_duration", return_value=120.0)
    def test_encoded_proof_cards_count_toward_presentation_ratio(self, duration):
        project = self.project()
        script = self.base()
        script["production"]["maxCardRatio"] = 0.12
        # Regression: exporting proof pages as clips previously passed a 12% cap
        # even though nearly half this 67.3s film was presentation material.
        script["shots"] = [
            {"n": 1, "kind": "clip", "src": "product.mp4", "durSec": 34.03333333333333,
             "sourceType": "product", "visualTreatment": "recording"},
            *[{"n": index, "kind": "clip", "src": "product.mp4", "durSec": seconds,
               "sourceType": "generated"}
              for index, seconds in enumerate([5.1, 3.033333333333333, 2.9333333333333336,
                                               7.666666666666666], start=2)],
            {"n": 6, "kind": "clip", "src": "product.mp4", "durSec": 9.733333333333333,
             "sourceType": "external", "visualTreatment": "presentation"},
            {"n": 7, "kind": "cta", "title": "Next step", "durSec": 4.8},
        ]
        original = copy.deepcopy(script)
        findings = [item for item in validate_script(script, project)
                    if item.code == "PRESENTATION_RATIO_HIGH"]
        self.assertEqual(1, len(findings))
        self.assertEqual("error", findings[0].severity)
        self.assertIn("49.4%", findings[0].message)
        self.assertIn("33.27s / 67.30s", findings[0].message)
        self.assertIn("Counted shots: 2, 3, 4, 5, 6, 7", findings[0].message)
        self.assertEqual(original, script)

    @patch("contracts.media_duration", return_value=120.0)
    def test_presentation_sources_cannot_opt_out_as_recordings(self, duration):
        project = self.project()
        for declaration in ({"sourceType": "slide"}, {"sourceType": "generated"},
                            {"kind": "title", "sourceType": "product", "title": "Proof"}):
            with self.subTest(declaration=declaration):
                script = self.base()
                script["shots"][0].update(declaration)
                self.assertIn("PRESENTATION_RATIO_HIGH", self.codes(script, project))
                script["shots"][0]["visualTreatment"] = "recording"
                self.assertTrue({"VISUAL_TREATMENT_CONFLICT", "PRESENTATION_RATIO_HIGH"}
                                <= self.codes(script, project))

    @patch("contracts.media_duration", return_value=120.0)
    def test_real_recordings_do_not_count_as_presentation(self, duration):
        project = self.project()
        for source_type in ("product", "human", "external"):
            for live_state in (True, False):
                for treatment in (None, "recording"):
                    with self.subTest(source_type=source_type, live_state=live_state, treatment=treatment):
                        script = self.base()
                        script["shots"][0].update(sourceType=source_type, liveState=live_state)
                        if treatment:
                            script["shots"][0]["visualTreatment"] = treatment
                        self.assertNotIn("PRESENTATION_RATIO_HIGH", self.codes(script, project))
                        self.assertNotIn("VISUAL_TREATMENT_CONFLICT", self.codes(script, project))

    @patch("contracts.media_duration", return_value=120.0)
    def test_visual_treatment_validates_values_and_exact_ratio_boundary(self, duration):
        project = self.project()
        for value in (None, "", "presentaton", True, [], {}):
            with self.subTest(value=value):
                script = self.base()
                script["shots"][0]["visualTreatment"] = value
                self.assertIn("VISUAL_TREATMENT_INVALID", self.codes(script, project))
        script = self.base()
        script["production"]["maxCardRatio"] = 0.25
        script["shots"][0]["durSec"] = 3
        script["shots"].append({"n": 2, "kind": "clip", "src": "product.mp4", "durSec": 1,
                                "sourceType": "external", "visualTreatment": "presentation"})
        self.assertNotIn("PRESENTATION_RATIO_HIGH", self.codes(script, project))
        script["shots"][1]["durSec"] = 1.1
        self.assertIn("PRESENTATION_RATIO_HIGH", self.codes(script, project))

    def test_zero_runtime_tolerance_ignores_float_accumulation_noise(self):
        project = self.project()
        script = self.base()
        script["shots"] = [
            {"n": 1, "kind": "clip", "src": "product.mp4", "durSec": 0.1},
            {"n": 2, "kind": "title", "durSec": 0.2, "title": "Done"},
        ]
        script["editorialContract"] = {"targetRuntimeSec": 0.3, "runtimeToleranceSec": 0}
        self.assertNotIn("EDITORIAL_RUNTIME_MISMATCH", self.codes(script, project))

    def test_source_locked_human_footage_rejects_zoom(self):
        project = self.project()
        script = self.base()
        script["production"]["sourceLocks"] = ["product.mp4"]
        script["shots"][0]["zooms"] = [{"atSec": 0, "durSec": 2, "scale": 1.2}]
        self.assertIn("SOURCE_FRAMING_CHANGED", self.codes(script, project))

    def test_authored_camera_keeps_recorded_click_inside_actual_viewport(self):
        project = self.project()
        script = self.base()
        script["production"]["cursorSafeMarginPct"] = 5
        shot = script["shots"][0]
        shot["camera"] = [{"atSec": 0, "scale": 1},
                          {"atSec": 1, "scale": 2, "focusX": 75, "focusY": 50}]
        with open(os.path.join(project, "assets", "product.events.json"), "w") as output:
            json.dump({"events": [{"type": "click", "t": 2, "xPct": 10, "yPct": 50}]}, output)
        self.assertIn("CURSOR_CAMERA_CROP", self.codes(script, project))
        shot["camera"][-1]["focusX"] = 25
        self.assertNotIn("CURSOR_CAMERA_CROP", self.codes(script, project))

    def test_camera_cursor_check_projects_source_aspect_before_zoom(self):
        camera = [{"atSec": 0, "scale": 1}]
        self.assertTrue(_cursor_inside_camera(0, 50, camera, 0, 5, (1440, 1080), "contain"))
        self.assertFalse(_cursor_inside_camera(50, 10, camera, 0, 5, (1080, 1920), "cover"))
        self.assertTrue(_cursor_inside_camera(50, 50, camera, 0, 5, (1080, 1920), "cover"))

    def test_closeup_cursor_validation_matches_eight_x_renderer(self):
        camera = [{"atSec": 0, "scale": 8, "focusX": 75, "focusY": 25}]
        self.assertTrue(_cursor_inside_camera(75, 25, camera, 0, 5))
        self.assertFalse(_cursor_inside_camera(85, 25, camera, 0, 5))

    def test_cover_camera_can_reframe_a_click_outside_original_crop(self):
        camera = [{"atSec": 0, "scale": 4, "focusX": 50, "focusY": 25}]
        self.assertTrue(_cursor_inside_camera(50, 25, camera, 0, 5, (1080, 1920), "cover"))

    def test_contain_camera_is_bound_to_source_edge_instead_of_letterbox(self):
        camera = [{"atSec": 0, "scale": 2, "focusX": 0, "focusY": 50}]
        self.assertFalse(_cursor_inside_camera(0, 50, camera, 0, 5, (1440, 1080), "contain"))
        self.assertTrue(_cursor_inside_camera(10, 50, camera, 0, 5, (1440, 1080), "contain"))

    def test_camera_validation_uses_last_authored_duplicate_pose(self):
        camera = [{"atSec": 0, "scale": 1},
                  {"atSec": 0, "scale": 8, "focusX": 75, "focusY": 25}]
        self.assertFalse(_cursor_inside_camera(10, 50, camera, 0, 5))
        self.assertTrue(_cursor_inside_camera(75, 25, camera, 0, 5))

    def measured_framing(self, width=1920, height=1080):
        return {"sourceWidth": width, "sourceHeight": height,
                "beats": [{"atSec": 0, "endSec": 4,
                           "rect": {"x": 40, "y": 40, "width": 20, "height": 20},
                           "textHeightPx": 14}]}

    @patch("contracts.media_duration", return_value=10.0)
    @patch("contracts.media_picture_duration", return_value=10.0)
    @patch("contracts.media_dimensions", return_value=(1920, 1080))
    def test_source_window_checks_only_visible_source_clicks_and_reading_holds(self, dimensions, picture, duration):
        project = self.project()
        script = self.base()
        shot = script["shots"][0]
        shot.update(sourceWindow={"x": 40, "y": 40, "width": 20, "height": 20}, actor="human", inSec=2)
        events = [{"type": "click", "t": 1, "xPct": 10, "yPct": 50},
                  {"type": "click", "t": 3, "xPct": 50, "yPct": 50}]
        path = os.path.join(project, "assets", "product.events.json")
        with open(path, "w") as output:
            json.dump({"events": events}, output)
        self.assertFalse([finding for finding in validate_script(script, project) if finding.severity == "error"])
        # Source clocks outside the shot are irrelevant, including an excluded left boundary.
        events[1]["xPct"] = 20
        with open(path, "w") as output:
            json.dump({"events": events}, output)
        self.assertIn("CURSOR_SOURCE_WINDOW_CROP", self.codes(script, project))
        shot["inSec"] = 1
        shot["sourceTimeline"] = [{"mode": "hold", "fromSec": 1, "toSec": 1, "durSec": 4}]
        self.assertIn("CURSOR_SOURCE_WINDOW_CROP", self.codes(script, project))
        shot["inSec"] = 4
        shot["sourceTimeline"] = [{"mode": "hold", "fromSec": 4, "toSec": 4, "durSec": 4}]
        self.assertNotIn("CURSOR_SOURCE_WINDOW_CROP", self.codes(script, project))
        dimensions.return_value = None
        self.assertIn("SOURCE_WINDOW_DIMENSIONS_UNVERIFIED", self.codes(script, project))

    @patch("contracts.media_duration", return_value=5.0)
    @patch("contracts.media_dimensions", return_value=(1920, 1080))
    def test_measured_framing_dimensions_must_match_actual_display_geometry(self, dimensions, duration):
        project = self.project()
        script = self.base()
        shot = script["shots"][0]
        shot["framing"] = self.measured_framing()
        self.assertNotIn("FRAMING_SOURCE_DIMENSIONS_MISMATCH", self.codes(script, project))
        dimensions.assert_called_with(os.path.join(project, "assets", "product.mp4"))
        shot["framing"]["sourceWidth"] = 1680
        findings = validate_script(script, project)
        mismatch = [item for item in findings if item.code == "FRAMING_SOURCE_DIMENSIONS_MISMATCH"]
        self.assertEqual(1, len(mismatch))
        self.assertEqual("error", mismatch[0].severity)
        self.assertIn("1920×1080", mismatch[0].message)
        self.assertNotIn("camera", shot)  # Contracts validate geometry without compiling a path.

    @patch("contracts.media_duration", return_value=5.0)
    @patch("contracts.media_dimensions", return_value=None)
    def test_unverified_framing_dimensions_block_only_opted_in_shots(self, dimensions, duration):
        project = self.project()
        script = self.base()
        self.assertNotIn("FRAMING_SOURCE_DIMENSIONS_UNVERIFIED", self.codes(script, project))
        dimensions.assert_not_called()
        script["shots"][0]["framing"] = self.measured_framing()
        findings = validate_script(script, project)
        unchecked = [item for item in findings if item.code == "FRAMING_SOURCE_DIMENSIONS_UNVERIFIED"]
        self.assertEqual(1, len(unchecked))
        self.assertEqual("error", unchecked[0].severity)

    @patch("contracts.media_duration", return_value=5.0)
    def test_framing_uses_rotated_anamorphic_display_dimensions(self, duration):
        project = self.project()
        script = self.base()
        script["shots"][0]["framing"] = self.measured_framing(1080, 2048)
        probe = SimpleNamespace(returncode=0, stdout=json.dumps({"streams": [{
            "width": 1920, "height": 1080, "sample_aspect_ratio": "16:15",
            "side_data_list": [{"rotation": -90}],
        }]}))
        with patch("contracts.subprocess.run", return_value=probe):
            self.assertEqual((1080, 2048), media_dimensions("rotated.mp4"))
            self.assertNotIn("FRAMING_SOURCE_DIMENSIONS_MISMATCH", self.codes(script, project))
            script["shots"][0]["framing"] = self.measured_framing(1920, 1080)
            self.assertIn("FRAMING_SOURCE_DIMENSIONS_MISMATCH", self.codes(script, project))

    @patch("contracts.media_duration", return_value=10.0)
    @patch("contracts.media_dimensions", return_value=(1920, 1080))
    def test_repeated_framing_source_dimensions_are_probed_once_per_validation(self, dimensions, duration):
        project = self.project()
        script = self.base()
        script["shots"][0]["framing"] = self.measured_framing()
        script["shots"].append({**script["shots"][0], "n": 2})
        self.assertNotIn("FRAMING_SOURCE_DIMENSIONS_MISMATCH", self.codes(script, project))
        dimensions.assert_called_once()

    @patch("contracts.media_duration", return_value=8.0)
    @patch("contracts.media_dimensions", return_value=(1920, 1080))
    def test_detail_mask_checks_supplied_clicks_even_without_configured_margin(self, dimensions, duration):
        project = self.project()
        script = self.base()
        script["shots"][0]["framing"] = {**self.measured_framing(), "presentation": "detail"}
        event_path = os.path.join(project, "assets", "product.events.json")
        for x, expected in ((90, True), (50, False), (40, False)):
            with open(event_path, "w") as output:
                json.dump({"events": [{"type": "click", "t": 1, "xPct": x, "yPct": 50}]}, output)
            self.assertEqual(expected, "CURSOR_DETAIL_CROP" in self.codes(script, project))
        # A configured margin applies inside the source detail rectangle, not its outer stage.
        script["production"]["cursorSafeMarginPct"] = 10
        self.assertIn("CURSOR_DETAIL_CROP", self.codes(script, project))

    @patch("contracts.media_duration", return_value=8.0)
    def test_compiled_detail_geometry_keeps_cursor_checks_and_source_locks(self, duration):
        project = self.project()
        script = self.base()
        shot = script["shots"][0]
        shot["sourceDetail"] = {"sourceRect": {"x": 40, "y": 40, "width": 20, "height": 20},
                                "screenRect": {"x": 7, "y": 25, "width": 86, "height": 55},
                                "entranceSec": 0.4, "radiusPx": 0}
        with open(os.path.join(project, "assets", "product.events.json"), "w") as output:
            json.dump({"events": [{"type": "click", "t": 1, "xPct": 70, "yPct": 50}]}, output)
        self.assertIn("CURSOR_DETAIL_CROP", self.codes(script, project))
        shot["preserveFraming"] = True
        self.assertIn("SOURCE_FRAMING_CHANGED", self.codes(script, project))

    @patch("contracts.media_duration", return_value=8.0)
    @patch("contracts.media_picture_duration", return_value=8.0)
    @patch("contracts.media_dimensions", return_value=(1920, 1080))
    def test_detail_cursor_check_uses_actual_mapped_source_frames(self, dimensions, picture, duration):
        project = self.project()
        script = self.base()
        shot = script["shots"][0]
        shot.update(inSec=3, sourceTimeline=[{"fromSec": 3, "toSec": 3, "durSec": 4, "mode": "hold"}],
                    framing={**self.measured_framing(), "presentation": "detail"})
        event_path = os.path.join(project, "assets", "product.events.json")
        for source_time, expected in ((2, False), (3, True), (4, False)):
            with open(event_path, "w") as output:
                json.dump({"events": [{"type": "click", "t": source_time, "xPct": 80, "yPct": 50}]}, output)
            self.assertEqual(expected, "CURSOR_DETAIL_CROP" in self.codes(script, project))

    @patch("contracts.media_duration", return_value=8.0)
    @patch("contracts.media_dimensions", return_value=(1920, 1080))
    def test_detail_cannot_bypass_human_framing_contracts(self, dimensions, duration):
        project = self.project()
        script = self.base()
        script["production"]["lockHumanFraming"] = True
        shot = script["shots"][0]
        shot.update(sourceType="human", framing={**self.measured_framing(), "presentation": "detail"})
        self.assertIn("HUMAN_FRAMING_UNLOCKED", self.codes(script, project))
        shot["preserveFraming"] = True
        self.assertIn("SOURCE_FRAMING_CHANGED", self.codes(script, project))

    def test_repo_native_capture_source_manifest_must_be_a_list(self):
        project = self.project()
        script = self.base()
        script["production"]["sourceManifests"] = "_src/session.json"
        self.assertIn("SOURCE_MANIFESTS_INVALID", self.codes(script, project))

    def test_repo_native_capture_source_manifest_is_project_relative_and_present(self):
        project = self.project()
        script = self.base()
        script["production"]["sourceManifests"] = [
            "../outside.json",
            "_src/missing.json",
            "assets",
            42,
        ]
        codes = self.codes(script, project)
        self.assertIn("SOURCE_MANIFEST_PATH_ESCAPE", codes)
        self.assertIn("SOURCE_MANIFEST_MISSING", codes)
        self.assertIn("SOURCE_MANIFEST_NOT_FILE", codes)
        self.assertIn("SOURCE_MANIFEST_ENTRY_INVALID", codes)

    def test_repo_native_capture_source_manifest_accepts_a_project_file(self):
        project = self.project()
        os.makedirs(os.path.join(project, "_src"))
        with open(os.path.join(project, "_src", "session.json"), "w") as fh:
            json.dump({"phases": []}, fh)
        script = self.base()
        script["production"]["sourceManifests"] = ["_src/session.json"]
        self.assertNotIn("SOURCE_MANIFEST", " ".join(self.codes(script, project)))

    def test_repo_native_capture_source_manifest_rejects_symlink_escape(self):
        project = self.project()
        with tempfile.TemporaryDirectory() as outside:
            source = os.path.join(outside, "session.json")
            with open(source, "w") as fh:
                json.dump({"phases": []}, fh)
            os.makedirs(os.path.join(project, "_src"))
            os.symlink(source, os.path.join(project, "_src", "session.json"))
            script = self.base()
            script["production"]["sourceManifests"] = ["_src/session.json"]
            self.assertIn("SOURCE_MANIFEST_PATH_ESCAPE", self.codes(script, project))

    def test_same_screen_cut_is_blocked(self):
        project = self.project()
        script = self.base()
        script["production"]["enforceSameScreenContinuity"] = True
        script["shots"] = [
            {"n": 1, "kind": "clip", "src": "product.mp4", "durSec": 2, "continuityId": "case"},
            {"n": 2, "kind": "clip", "src": "product.mp4", "durSec": 2, "continuityId": "case"},
        ]
        self.assertIn("SAME_SCREEN_CUT", self.codes(script, project))

    def test_zoomed_cursor_safe_area_is_mathematical(self):
        project = self.project()
        events = [{"t": 1.0, "type": "click", "xPct": 90, "yPct": 50}]
        with open(os.path.join(project, "assets", "product.events.json"), "w") as fh:
            json.dump({"schemaVersion": 2, "events": events}, fh)
        script = self.base()
        script["production"]["cursorSafeMarginPct"] = 10
        script["production"]["requireCursorEvents"] = True
        script["shots"][0]["zooms"] = [{"atSec": 0, "durSec": 3, "scale": 2,
                                          "focusX": 50, "focusY": 50}]
        self.assertIn("CURSOR_ZOOM_CROP", self.codes(script, project))

    @patch("contracts.media_duration", return_value=5.0)
    def test_retimed_source_bounds_use_actual_source_endpoint(self, probe):
        project = self.project()
        script = self.base()
        shot = script["shots"][0]
        shot.update(durSec=7, sourceTimeline=[
            {"fromSec": 0, "toSec": 3, "durSec": 3, "mode": "realtime"},
            {"fromSec": 3, "toSec": 3, "durSec": 4, "mode": "hold"},
        ])
        self.assertNotIn("SOURCE_RANGE_OVERRUN", self.codes(script, project))
        shot.update(durSec=3, sourceTimeline=[
            {"fromSec": 0, "toSec": 6, "durSec": 3, "mode": "navigation"},
        ])
        self.assertIn("SOURCE_RANGE_OVERRUN", self.codes(script, project))

    @patch("contracts.media_duration", return_value=5.0)
    def test_hold_cannot_reference_the_exclusive_media_end(self, probe):
        project = self.project()
        script = self.base()
        script["shots"][0].update(durSec=6, sourceTimeline=[
            {"fromSec": 0, "toSec": 5, "durSec": 5, "mode": "realtime"},
            {"fromSec": 5, "toSec": 5, "durSec": 1, "mode": "hold"},
        ])
        self.assertIn("SOURCE_HOLD_OUT_OF_RANGE", self.codes(script, project))

    @patch("contracts.media_picture_duration", return_value=3.0)
    @patch("contracts.media_duration", return_value=5.0)
    def test_mapped_picture_bounds_ignore_longer_container_audio_tail(self, container_probe, picture_probe):
        project = self.project()
        script = self.base()
        script["shots"][0].update(durSec=4, sourceTimeline=[
            {"fromSec": 0, "toSec": 3, "durSec": 3, "mode": "realtime"},
            {"fromSec": 3, "toSec": 3, "durSec": 1, "mode": "hold"},
        ])
        self.assertIn("SOURCE_HOLD_OUT_OF_RANGE", self.codes(script, project))
        script["shots"][0].update(durSec=2, sourceTimeline=[
            {"fromSec": 0, "toSec": 4, "durSec": 2, "mode": "navigation"},
        ])
        self.assertIn("SOURCE_RANGE_OVERRUN", self.codes(script, project))
        # Preserve the legacy duration contract for unmapped clips.
        del script["shots"][0]["sourceTimeline"]
        script["shots"][0]["durSec"] = 4
        picture_probe.reset_mock()
        self.assertNotIn("SOURCE_RANGE_OVERRUN", self.codes(script, project))
        picture_probe.assert_not_called()

    @patch("contracts.media_picture_duration", return_value=None)
    @patch("contracts.media_duration", return_value=5.0)
    def test_unverified_picture_duration_warns_and_keeps_container_bounds(self, container_probe, picture_probe):
        project = self.project()
        script = self.base()
        script["shots"][0].update(durSec=3, sourceTimeline=[
            {"fromSec": 0, "toSec": 6, "durSec": 3, "mode": "navigation"},
        ])
        codes = self.codes(script, project)
        self.assertIn("SOURCE_PICTURE_DURATION_UNCHECKED", codes)
        self.assertIn("SOURCE_RANGE_OVERRUN", codes)

    def test_retimed_click_is_checked_at_its_actual_output_time(self):
        project = self.project()
        with open(os.path.join(project, "assets", "product.events.json"), "w") as handle:
            json.dump({"schemaVersion": 2, "events": [{"t": 4.5, "type": "click", "xPct": 80, "yPct": 50}]}, handle)
        script = self.base()
        script["production"]["cursorSafeMarginPct"] = 8
        script["shots"][0].update(durSec=3, sourceTimeline=[
            {"fromSec": 0, "toSec": 4, "durSec": 2, "mode": "navigation"},
            {"fromSec": 4, "toSec": 5, "durSec": 1, "mode": "realtime"},
        ], zooms=[{"atSec": 2, "durSec": 1, "scale": 2, "focusX": 25, "focusY": 50}])
        # The source click is at 4.5s, but its output presentation is at 2.5s.
        self.assertIn("CURSOR_ZOOM_CROP", self.codes(script, project))

    def test_held_click_remains_safe_through_intermediate_camera_poses(self):
        project = self.project()
        with open(os.path.join(project, "assets", "product.events.json"), "w") as handle:
            json.dump({"schemaVersion": 2, "events": [{"t": 1, "type": "click", "xPct": 80, "yPct": 50}]}, handle)
        script = self.base()
        script["production"]["cursorSafeMarginPct"] = 8
        script["shots"][0].update(durSec=3, sourceTimeline=[
            {"fromSec": 0, "toSec": 1, "durSec": 1, "mode": "realtime"},
            {"fromSec": 1, "toSec": 1, "durSec": 2, "mode": "hold"},
        ], camera=[{"atSec": 0, "scale": 1}, {"atSec": 1, "scale": 1},
                   {"atSec": 2, "scale": 2, "focusX": 25}, {"atSec": 3, "scale": 1}])
        self.assertIn("CURSOR_CAMERA_CROP", self.codes(script, project))

    def test_source_map_validation_is_enforced_by_production_contract(self):
        project = self.project()
        script = self.base()
        script["shots"][0]["sourceTimeline"] = [
            {"fromSec": 0, "toSec": 12, "durSec": 4, "mode": "navigation"},
        ]
        self.assertIn("SOURCE_TIMELINE_RATE", self.codes(script, project))

    def test_editorial_audit_does_not_repeat_source_timing_errors(self):
        project = self.project()
        script = self.base()
        script["shots"][0].update(sourceTimeline=[
            {"fromSec": 0, "toSec": 12, "durSec": 4, "mode": "navigation"},
        ], sourceBeats=[{"id": "proof", "sourceSec": 1, "kind": "proof"}])
        timing = [item for item in validate_script(script, project) if item.code.startswith("SOURCE_TIMELINE_")]
        self.assertTrue(timing)
        self.assertEqual(len(timing), len(set(timing)))

    def test_invalid_source_beat_declarations_fail_before_render(self):
        project = self.project()
        script = self.base()
        script["shots"][0]["sourceBeats"] = [{"id": "proof", "sourceSec": float("nan"), "kind": "proof"}]
        self.assertIn("EDITORIAL_SOURCE_BEAT_INVALID", self.codes(script, project))
        script["shots"][0]["sourceBeats"] = [{"id": "proof", "sourceSec": 1, "kind": "proof", "cueId": "missing"}]
        self.assertIn("SOURCE_BEAT_CUE_INVALID", self.codes(script, project))

    def test_source_beats_accept_pending_narration_without_turning_advice_into_errors(self):
        project = self.project()
        script = self.base()
        script["production"]["autoPaceNarration"] = True
        script["narration"] = {"file": "audio/master.mp3", "fromMap": True}
        script["narrationMap"] = [{"id": "proof", "shotN": 1, "text": "A sourced result.", "beat": "evidence",
                                    "startSec": 10, "endSec": 12}]
        script["shots"][0]["sourceBeats"] = [{"id": "visible-proof", "sourceSec": 1, "kind": "proof", "cueId": "proof"}]
        pending = {item.code for item in validate_script(script, project, allow_pending_narration=True)}
        self.assertNotIn("EDITORIAL_CUE_RANGE_INVALID", pending)
        self.assertNotIn("SOURCE_BEAT_CUE_INVALID", pending)
        self.assertIn("EDITORIAL_CUE_RANGE_INVALID", self.codes(script, project))

    def test_claims_require_verifiable_evidence(self):
        project = self.project()
        script = self.base()
        script["production"]["requireClaimEvidence"] = True
        script["claims"] = [{"id": "seven", "status": "draft", "evidence": "missing.json"}]
        script["shots"][0]["claimIds"] = ["seven"]
        codes = self.codes(script, project)
        self.assertIn("CLAIM_UNVERIFIED", codes)
        self.assertIn("CLAIM_EVIDENCE_MISSING", codes)

    def test_empty_or_directory_evidence_cannot_satisfy_a_claim(self):
        project = self.project()
        script = self.base()
        script["production"]["requireClaimEvidence"] = True
        evidence = os.path.join(project, "evidence.json")
        with open(evidence, "wb"):
            pass
        script["claims"] = [{"id": "api", "status": "verified", "evidence": [
            "https://example.com/api", "evidence.json"]}]
        self.assertIn("CLAIM_EVIDENCE_MISSING", self.codes(script, project))
        script["claims"][0]["evidence"] = "assets"
        self.assertIn("CLAIM_EVIDENCE_MISSING", self.codes(script, project))

    def test_nonempty_binary_and_remote_evidence_keep_existing_support(self):
        project = self.project()
        script = self.base()
        script["production"]["requireClaimEvidence"] = True
        with open(os.path.join(project, "capture.bin"), "wb") as handle:
            handle.write(b"\x00\xff\x80\x00")
        script["claims"] = [{"id": "api", "status": "verified", "evidence": [
            "capture.bin", "https://example.com/api"]}]
        self.assertNotIn("CLAIM_EVIDENCE_MISSING", self.codes(script, project))
        script["claims"][0]["evidence"] = "https://example.com/api"
        self.assertNotIn("CLAIM_EVIDENCE_MISSING", self.codes(script, project))

    def test_master_narration_cannot_double_mix(self):
        project = self.project()
        with open(os.path.join(project, "audio", "master.wav"), "wb") as fh:
            fh.write(b"audio")
        with open(os.path.join(project, "audio", "manifest.json"), "w") as fh:
            json.dump([{"n": 1, "file": "s1.mp3", "seconds": 1}], fh)
        script = self.base()
        script["narration"] = {"file": "audio/master.wav", "mix": True}
        self.assertIn("NARRATION_DOUBLE_MIX", self.codes(script, project))

    def test_generated_master_may_be_pending_only_during_first_preflight(self):
        project = self.project()
        script = self.base()
        script["narration"] = {"file": "audio/master.mp3", "text": "[quietly] Begin."}
        normal = {item.code for item in validate_script(script, project)}
        pending = {item.code for item in validate_script(
            script, project, allow_pending_narration=True
        )}
        self.assertIn("NARRATION_MISSING", normal)
        self.assertNotIn("NARRATION_MISSING", pending)
        self.assertIn("NARRATION_PENDING_GENERATION", pending)

    def test_master_narration_cannot_run_past_picture(self):
        project = self.project()
        path = os.path.join(project, "audio", "master.wav")
        with wave.open(path, "wb") as audio:
            audio.setnchannels(1)
            audio.setsampwidth(2)
            audio.setframerate(8000)
            audio.writeframes(b"\x00\x00" * 16000)
        script = self.base()
        script["shots"][0]["durSec"] = 1
        script["narration"] = {"file": "audio/master.wav"}
        self.assertIn("NARRATION_OVERRUN", self.codes(script, project))

    def test_low_friction_action_cannot_wait_for_human(self):
        project = self.project()
        script = self.base()
        script["shots"][0].update({"actor": "human", "actionRisk": "low-friction"})
        self.assertIn("LOW_FRICTION_HUMAN_GATE", self.codes(script, project))

    def test_consequential_action_requires_human(self):
        project = self.project()
        script = self.base()
        script["shots"][0].update({"actor": "agent", "actionRisk": "consequential"})
        self.assertIn("CONSEQUENTIAL_ACTION_NOT_HUMAN", self.codes(script, project))

    def test_exact_human_decision_count_is_enforced(self):
        project = self.project()
        script = self.base()
        script["production"]["exactHumanDecisions"] = 1
        self.assertIn("HUMAN_DECISION_COUNT_MISMATCH", self.codes(script, project))

    def test_same_screen_cut_with_real_state_change_is_allowed(self):
        project = self.project()
        script = self.base()
        script["production"]["enforceSameScreenContinuity"] = True
        script["shots"] = [
            {"n": 1, "kind": "clip", "src": "product.mp4", "durSec": 2,
             "continuityId": "case", "stateId": "waiting"},
            {"n": 2, "kind": "clip", "src": "product.mp4", "durSec": 2,
             "continuityId": "case", "stateId": "result",
             "transitionReason": "major product state changed"},
        ]
        self.assertNotIn("SAME_SCREEN_CUT", self.codes(script, project))

    def test_single_focus_rejects_split_screen(self):
        project = self.project()
        script = self.base()
        script["production"]["singleFocus"] = True
        script["shots"] = [{
            "n": 1, "kind": "split", "srcL": "product.mp4", "srcR": "product.mp4",
            "durSec": 2,
        }]
        self.assertIn("SPLIT_SCREEN_FORBIDDEN", self.codes(script, project))

    def test_single_focus_allows_explicit_legacy_split_opt_in(self):
        project = self.project()
        script = self.base()
        script["production"].update({"singleFocus": True, "allowSplitScreen": True})
        script["shots"] = [{
            "n": 1, "kind": "split", "srcL": "product.mp4", "srcR": "product.mp4",
            "durSec": 2,
        }]
        self.assertNotIn("SPLIT_SCREEN_FORBIDDEN", self.codes(script, project))

    def test_required_product_continuity_id_is_enforced(self):
        project = self.project()
        script = self.base()
        script["production"]["requireContinuityIds"] = True
        self.assertIn("CONTINUITY_ID_REQUIRED", self.codes(script, project))

    def test_transition_reason_without_state_change_cannot_bypass_same_screen_gate(self):
        project = self.project()
        script = self.base()
        script["production"]["enforceSameScreenContinuity"] = True
        script["shots"] = [
            {"n": 1, "kind": "clip", "src": "product.mp4", "durSec": 2,
             "continuityId": "case", "stateId": "waiting"},
            {"n": 2, "kind": "clip", "src": "product.mp4", "durSec": 2,
             "continuityId": "case", "stateId": "waiting",
             "transitionReason": "looks different"},
        ]
        self.assertIn("SAME_SCREEN_CUT", self.codes(script, project))

    def test_picture_cut_inside_narrated_thought_is_blocked(self):
        project = self.project()
        script = self.base()
        script["production"]["narrationCutPolicy"] = "between-thoughts"
        script["shots"] = [
            {"n": 1, "kind": "clip", "src": "product.mp4", "durSec": 2},
            {"n": 2, "kind": "clip", "src": "product.mp4", "durSec": 2},
        ]
        script["narrationMap"] = [{
            "id": "one", "text": "One complete spoken thought.",
            "startSec": 0.25, "endSec": 2.75,
        }]
        self.assertIn("NARRATION_THOUGHT_CUT", self.codes(script, project))

    def test_picture_cut_between_narrated_thoughts_is_allowed(self):
        project = self.project()
        script = self.base()
        script["production"]["narrationCutPolicy"] = "between-thoughts"
        script["shots"] = [
            {"n": 1, "kind": "clip", "src": "product.mp4", "durSec": 2},
            {"n": 2, "kind": "clip", "src": "product.mp4", "durSec": 2},
        ]
        script["narrationMap"] = [
            {"id": "one", "text": "First thought.", "startSec": 0.2, "endSec": 1.8},
            {"id": "two", "text": "Second thought.", "startSec": 2.2, "endSec": 3.8},
        ]
        self.assertNotIn("NARRATION_THOUGHT_CUT", self.codes(script, project))

    def continuous_master_script(self, project):
        master = os.path.join(project, "audio", "master.wav")
        with wave.open(master, "wb") as audio:
            audio.setnchannels(1)
            audio.setsampwidth(2)
            audio.setframerate(8000)
            audio.writeframes(b"\x00\x00" * 32000)
        timing = os.path.join(project, "audio", "timing.json")
        with open(timing, "w") as handle:
            json.dump({"alignment": {"characters": list("One complete spoken thought.")}}, handle)
        def digest(path):
            with open(path, "rb") as handle:
                return hashlib.sha256(handle.read()).hexdigest()
        script = self.base()
        script["production"]["narrationCutPolicy"] = "continuous-audio"
        script["shots"] = [{"n": number, "kind": "clip", "src": "product.mp4", "durSec": 2,
                            "inSec": (number - 1) * 2} for number in (1, 2, 3)]
        script["narration"] = {"file": "audio/master.wav", "timingFile": "audio/timing.json",
                               "text": "One complete spoken thought.", "sha256": digest(master),
                               "timingSha256": digest(timing)}
        script["narrationMap"] = [{"id": "thought", "shotNs": [1, 2], "startSec": 0.25,
                                   "endSec": 3.75, "text": "One complete spoken thought.", "beat": "proof"}]
        return script

    @patch("contracts.media_duration", side_effect=lambda path: 4 if path.endswith("master.wav") else 20)
    def test_continuous_audio_allows_picture_cut_with_bound_master_and_exact_text(self, duration):
        project = self.project()
        script = self.continuous_master_script(project)
        original = copy.deepcopy(script)
        self.assertFalse([item for item in validate_script(script, project) if item.severity == "error"])
        self.assertEqual(original, script)
        script["production"]["narrationCutPolicy"] = "between-thoughts"
        self.assertIn("NARRATION_THOUGHT_CUT", self.codes(script, project))

    @patch("contracts.media_duration", side_effect=lambda path: 4 if path.endswith("master.wav") else 20)
    def test_continuous_audio_preserves_master_hash_timing_hash_coverage_and_range_checks(self, duration):
        project = self.project()
        for alter, expected in (("audio-hash", "NARRATION_HASH_MISMATCH"),
                                ("timing-hash", "NARRATION_TIMING_HASH_MISMATCH"),
                                ("text", "NARRATION_MAP_COVERAGE_MISMATCH"),
                                ("range", "NARRATION_MAP_SHOT_RANGE"),
                                ("missing-timing", "CONTINUOUS_AUDIO_MASTER_REQUIRED"),
                                ("missing-master", "CONTINUOUS_AUDIO_MASTER_REQUIRED"),
                                ("unmixed", "CONTINUOUS_AUDIO_MASTER_REQUIRED"),
                                ("missing-map", "NARRATION_MAP_REQUIRED")):
            script = self.continuous_master_script(project)
            if alter == "audio-hash":
                script["narration"]["sha256"] = "0" * 64
            elif alter == "timing-hash":
                script["narration"]["timingSha256"] = "0" * 64
            elif alter == "text":
                script["narrationMap"][0]["text"] = "A different claim."
            elif alter == "range":
                script["narrationMap"][0]["endSec"] = 4.2
            elif alter == "missing-timing":
                script["narration"]["timingFile"] = "audio/missing.json"
            elif alter == "missing-master":
                script["narration"]["file"] = "audio/missing.wav"
            elif alter == "unmixed":
                script["narration"]["mix"] = False
            else:
                script.pop("narrationMap")
            with self.subTest(alter=alter):
                self.assertIn(expected, self.codes(script, project))

    @patch("contracts.media_duration", side_effect=lambda path: 4 if path.endswith("master.wav") else 20)
    def test_narration_spans_reject_ambiguous_unknown_duplicate_and_nonconsecutive_assignments(self, duration):
        project = self.project()
        for span in ([], [1, 1], [1, 3], [2, 1], [1, 4], [True, 2], "1,2"):
            script = self.continuous_master_script(project)
            script["narrationMap"][0]["shotNs"] = span
            with self.subTest(span=span):
                self.assertIn("NARRATION_MAP_SHOT_INVALID", self.codes(script, project))
        script = self.continuous_master_script(project)
        script["narrationMap"][0]["shotN"] = 1
        self.assertIn("NARRATION_MAP_SHOT_INVALID", self.codes(script, project))
        script = self.continuous_master_script(project)
        script["production"]["autoPaceNarration"] = True
        codes = self.codes(script, project)
        self.assertIn("NARRATION_MAP_SPAN_AUTOPACE_CONFLICT", codes)
        self.assertIn("CONTINUOUS_AUDIO_AUTOPACE_CONFLICT", codes)

    @patch("contracts.media_duration", return_value=20)
    @patch("contracts.media_dimensions", return_value=(1920, 1080))
    def test_source_contiguous_context_detail_cut_needs_no_invented_state_change(self, dimensions, duration):
        project = self.project()
        script = self.base()
        script["production"]["enforceSameScreenContinuity"] = True
        framing = self.measured_framing()
        framing.update(presentation="detail")
        framing["beats"][0]["endSec"] = 2
        script["shots"] = [
            {"n": 1, "kind": "clip", "src": "product.mp4", "durSec": 2, "inSec": 1,
             "continuityId": "case", "stateId": "saved"},
            {"n": 2, "kind": "clip", "src": "product.mp4", "durSec": 2, "inSec": 3,
             "continuityId": "case", "stateId": "saved", "framing": framing,
             "presentationCut": True, "transitionReason": "Read the complete saved policy"},
        ]
        self.assertFalse([item for item in validate_script(script, project) if item.severity == "error"])
        reverse_view = copy.deepcopy(script)
        reverse_view["shots"][0]["framing"] = reverse_view["shots"][1].pop("framing")
        self.assertNotIn("PRESENTATION_CUT_INVALID", self.codes(reverse_view, project))
        locked = copy.deepcopy(script)
        locked["production"]["sourceLocks"] = ["product.mp4"]
        self.assertIn("SOURCE_FRAMING_CHANGED", self.codes(locked, project))
        for alter in ("gap", "reverse", "file", "reason", "no-view-change", "implicit"):
            candidate = copy.deepcopy(script)
            right = candidate["shots"][1]
            if alter == "gap":
                right["inSec"] = 4
            elif alter == "reverse":
                right["inSec"] = 1
            elif alter == "file":
                right["src"] = "other.mp4"
            elif alter == "reason":
                right["transitionReason"] = " "
            elif alter == "no-view-change":
                right.pop("framing")
            else:
                right.pop("presentationCut")
            expected = "SAME_SCREEN_CUT" if alter == "implicit" else "PRESENTATION_CUT_INVALID"
            with self.subTest(alter=alter):
                self.assertIn(expected, self.codes(candidate, project))

    @patch("contracts.media_duration", return_value=20)
    @patch("contracts.media_picture_duration", return_value=20)
    @patch("contracts.media_dimensions", return_value=(1920, 1080))
    def test_detail_cut_validates_real_held_source_boundary_and_changed_component(self, dimensions, picture, duration):
        project = self.project()
        script = self.base()
        script["production"]["enforceSameScreenContinuity"] = True
        framing = self.measured_framing()
        framing.update(presentation="detail")
        framing["beats"][0]["endSec"] = 2
        script["shots"] = [{"n": 1, "kind": "clip", "src": "product.mp4", "durSec": 2,
                            "continuityId": "case", "stateId": "saved", "framing": framing,
                            "sourceTimeline": [{"fromSec": 2, "toSec": 2, "durSec": 2, "mode": "hold"}]},
                           {"n": 2, "kind": "clip", "src": "product.mp4", "durSec": 2, "inSec": 2,
                            "continuityId": "case", "stateId": "saved", "framing": copy.deepcopy(framing),
                            "presentationCut": True, "transitionReason": "Read the adjacent complete result"}]
        script["shots"][1]["framing"]["beats"][0]["rect"]["x"] = 65
        self.assertNotIn("PRESENTATION_CUT_INVALID", self.codes(script, project))
        script["shots"][1]["framing"] = copy.deepcopy(framing)
        self.assertIn("PRESENTATION_CUT_INVALID", self.codes(script, project))

    def test_narration_tail_contract_is_enforced(self):
        project = self.project()
        path = os.path.join(project, "audio", "master.wav")
        with wave.open(path, "wb") as audio:
            audio.setnchannels(1)
            audio.setsampwidth(2)
            audio.setframerate(8000)
            audio.writeframes(b"\x00\x00" * 28000)
        script = self.base()
        script["production"]["minNarrationTailSec"] = 0.75
        script["narration"] = {"file": "audio/master.wav"}
        self.assertIn("NARRATION_TAIL_SHORT", self.codes(script, project))

    def test_one_continuous_take_can_carry_two_required_beats(self):
        project = self.project()
        script = self.base()
        script["production"]["requiredStoryBeats"] = ["test", "restraint"]
        script["shots"][0].pop("storyBeat")
        script["shots"][0]["storyBeats"] = ["test", "restraint"]
        self.assertNotIn("STORY_BEAT_MISSING_OR_OUT_OF_ORDER", self.codes(script, project))

    def save_the_cat_script(self):
        groups = [
            (6, SAVE_THE_CAT_BEATS[0:3]),
            (16, SAVE_THE_CAT_BEATS[3:7]),
            (28, SAVE_THE_CAT_BEATS[7:8]),
            (25, SAVE_THE_CAT_BEATS[8:10]),
            (9, SAVE_THE_CAT_BEATS[10:13]),
            (16, SAVE_THE_CAT_BEATS[13:15]),
        ]
        return {
            "production": {"storyFramework": "save-the-cat"},
            "shots": [
                {"n": index, "kind": "title", "durSec": duration, "storyBeats": list(beats)}
                for index, (duration, beats) in enumerate(groups, 1)
            ],
        }

    def test_save_the_cat_accepts_grouped_ordered_beats(self):
        project = self.project()
        findings = validate_script(self.save_the_cat_script(), project)
        self.assertFalse([f for f in findings if f.severity == "error"])
        self.assertNotIn("STORY_BEAT_PLACEMENT", {f.code for f in findings})

    def test_save_the_cat_requires_every_beat(self):
        project = self.project()
        script = self.save_the_cat_script()
        script["shots"][2]["storyBeats"] = []
        self.assertIn("STORY_BEAT_MISSING_OR_OUT_OF_ORDER", self.codes(script, project))

    def test_save_the_cat_rejects_unknown_and_duplicate_beats(self):
        project = self.project()
        script = self.save_the_cat_script()
        script["shots"][0]["storyBeats"].append("setup")
        script["shots"][0]["storyBeats"].append("feature-tour")
        codes = self.codes(script, project)
        self.assertIn("STORY_BEAT_DUPLICATE", codes)
        self.assertIn("STORY_BEAT_UNKNOWN", codes)


if __name__ == "__main__":
    unittest.main()
