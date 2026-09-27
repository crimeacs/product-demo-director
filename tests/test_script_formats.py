import copy
import json
import os
import sys
import tempfile
import unittest
from unittest.mock import patch
from types import SimpleNamespace


sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "tools"))

from contracts import SAVE_THE_CAT_BEATS  # noqa: E402
from script import draft_script, finalize, load_footage, repair_prompt, validate_script  # noqa: E402


class ScriptFormatTests(unittest.TestCase):
    def save_the_cat_draft(self):
        groups = [
            SAVE_THE_CAT_BEATS[0:3],
            SAVE_THE_CAT_BEATS[3:6],
            SAVE_THE_CAT_BEATS[6:9],
            SAVE_THE_CAT_BEATS[9:11],
            SAVE_THE_CAT_BEATS[11:13],
            SAVE_THE_CAT_BEATS[13:15],
        ]
        return {
            "shots": [
                {
                    "n": index,
                    "kind": "clip",
                    "src": "product.mp4",
                    "inSec": (index - 1) * 5,
                    "durSec": 5,
                    "sourceType": "product",
                    "liveState": True,
                    "storyBeats": list(beats),
                }
                for index, beats in enumerate(groups, 1)
            ]
        }

    def test_save_the_cat_draft_accepts_complete_ordered_beats(self):
        errors = validate_script(self.save_the_cat_draft(), {"product.mp4"}, 30, "save-the-cat")
        self.assertEqual([], errors)

    def test_save_the_cat_draft_rejects_a_missing_midpoint(self):
        draft = self.save_the_cat_draft()
        draft["shots"][2]["storyBeats"].remove("midpoint")
        errors = validate_script(draft, {"product.mp4"}, 30, "save-the-cat")
        self.assertTrue(any("midpoint" in error for error in errors))

    def test_save_the_cat_rejects_fifteen_title_cards(self):
        draft = {
            "shots": [
                {"n": index, "kind": "title", "title": beat, "durSec": 2, "storyBeat": beat}
                for index, beat in enumerate(SAVE_THE_CAT_BEATS, 1)
            ]
        }
        errors = validate_script(draft, set(), 30, "save-the-cat")
        self.assertTrue(any("cards exceed" in error for error in errors))

    def test_save_the_cat_rejects_string_story_beats(self):
        draft = self.save_the_cat_draft()
        draft["shots"][0]["storyBeats"] = "opening-image"
        errors = validate_script(draft, {"product.mp4"}, 30, "save-the-cat")
        self.assertTrue(any("must be an array" in error for error in errors))

    def test_finalize_merges_required_defaults_into_partial_production(self):
        draft = self.save_the_cat_draft()
        draft["production"] = {"profile": "sales"}
        finalized = finalize(draft, "save-the-cat", 30, {})
        self.assertEqual("sales", finalized["production"]["profile"])
        self.assertEqual("save-the-cat", finalized["production"]["storyFramework"])
        self.assertTrue(finalized["production"]["requireLiveProgression"])

    def test_launch_film_rejects_split_screen(self):
        draft = self.save_the_cat_draft()
        draft["shots"][0] = {
            "n": 1, "kind": "split", "srcL": "product.mp4", "srcR": "product.mp4",
            "durSec": 5, "storyBeats": list(SAVE_THE_CAT_BEATS[0:3]),
        }
        errors = validate_script(draft, {"product.mp4"}, 30, "launch-film")
        self.assertTrue(any("split-screen" in error for error in errors))

    def test_launch_film_defaults_to_announcement_single_focus(self):
        finalized = finalize(self.save_the_cat_draft(), "launch-film", 60, {})
        production = finalized["production"]
        self.assertEqual(production["profile"], "announcement")
        self.assertTrue(production["singleFocus"])
        self.assertTrue(production["requireContinuityIds"])
        self.assertEqual(production["storyFramework"], "save-the-cat")

    def test_new_drafts_use_studio_defaults_without_overwriting_authored_tone(self):
        draft = self.save_the_cat_draft()
        draft["creativeDirection"] = {"tone": "editorial", "soundDesign": "silent"}
        finalized = finalize(draft, "save-the-cat", 30, {})
        self.assertEqual({"style": "studio", "tone": "editorial", "soundDesign": "silent"},
                         finalized["creativeDirection"])

    def test_classic_style_remains_an_explicit_authoring_choice(self):
        draft = {"creativeDirection": {"style": "classic"}, "shots": []}
        self.assertEqual("classic", finalize(draft, "walkthrough", 30, {})["creativeDirection"]["style"])

    def test_malformed_model_output_returns_findings_instead_of_crashing(self):
        cases = [None, {"shots": "not an array"}, {"shots": [None]},
                 {"shots": [{"kind": "clip", "src": [], "durSec": 5}]},
                 {"shots": [{"kind": "title", "durSec": float("nan")}]},
                 {"shots": [{"kind": "title", "durSec": "5"}]}]
        for draft in cases:
            with self.subTest(draft=draft):
                self.assertTrue(validate_script(finalize(draft, "walkthrough", 5, {}), {"product.mp4"}, 5))

    def test_false_caption_is_an_intentional_subtitle_opt_out(self):
        draft = {"shots": [{"kind": "clip", "src": "product.mp4", "durSec": 5,
                            "vo": "Watch the source arrive.", "caption": False}]}
        self.assertEqual([], validate_script(draft, {"product.mp4"}, 5))

    def test_source_duration_and_framing_metadata_protect_real_footage(self):
        draft = {"shots": [{"kind": "clip", "src": "person.mp4", "inSec": 2,
                            "durSec": 5, "sourceType": "product"}]}
        footage = [{"name": "person.mp4", "seconds": 6, "sourceType": "human", "preserveFraming": True}]
        errors = validate_script(draft, {"person.mp4"}, 5, footage=footage)
        self.assertTrue(any("manifest has 6" in e for e in errors))
        self.assertTrue(any("sourceType must match" in e for e in errors))
        self.assertTrue(any("preserveFraming=true" in e for e in errors))

    def test_studio_camera_and_annotation_errors_use_canonical_validation(self):
        draft = {"shots": [{"kind": "clip", "src": "product.mp4", "durSec": 5,
                            "camera": [{"atSec": 0, "scale": 9}],
                            "annotations": [{"atSec": 2, "endSec": 4, "x": 80, "y": 0,
                                             "width": 30, "height": 20}]}]}
        errors = validate_script(draft, {"product.mp4"}, 5)
        self.assertTrue(any("CAMERA_SCALE_INVALID" in e for e in errors))
        self.assertTrue(any("ANNOTATION_BOUNDS_INVALID" in e for e in errors))

    def test_master_narration_does_not_bypass_reading_time(self):
        draft = {"narration": {"file": "audio/master.mp3", "fromMap": True},
                 "narrationMap": [{"shotN": 1, "text": "This lengthy spoken sentence cannot fit inside one second."}],
                 "shots": [{"n": 1, "kind": "title", "title": "A real result", "durSec": 1}]}
        self.assertTrue(any("mapped narration is too dense" in e for e in validate_script(draft, set(), 1)))

    def test_master_and_per_shot_narration_cannot_coexist_in_a_draft(self):
        draft = {"narration": {"fromMap": True},
                 "shots": [{"kind": "title", "durSec": 5, "vo": "A second voice."}]}
        self.assertTrue(any("never both" in e for e in validate_script(draft, set(), 5)))

    def test_footage_context_keeps_known_geometry_and_source_identity(self):
        item = {"name": "product.mp4", "seconds": 8, "contents": "The receipt appears.",
                "sourceType": "product", "focusRegions": [{"x": 20, "y": 30, "width": 40, "height": 25}],
                "continuityId": "receipt-screen", "source": "original recording"}
        with tempfile.TemporaryDirectory() as project:
            os.mkdir(os.path.join(project, "assets"))
            with open(os.path.join(project, "assets", "footage.json"), "w") as handle:
                json.dump([item], handle)
            self.assertEqual([item], load_footage(project))

    def test_generated_camera_requires_an_observed_source_locator(self):
        draft = {"shots": [{"kind": "clip", "src": "product.mp4", "durSec": 5,
                            "direction": {"intent": "focus", "focus": {"x": 62, "y": 44}}}]}
        footage = [{"name": "product.mp4", "seconds": 5, "contents": "A receipt appears."}]
        errors = validate_script(draft, {"product.mp4"}, 5, footage=footage)
        self.assertTrue(any("omit invented coordinates" in error for error in errors))
        # Manually inspected/authored scripts are validated by the production grammar, not inferred
        # to be grounded or ungrounded based on a manifest unavailable to that caller.
        self.assertEqual([], validate_script(draft, {"product.mp4"}, 5))

    def test_known_source_regions_allow_focus_and_exact_annotations(self):
        draft = {"shots": [{"kind": "clip", "src": "product.mp4", "durSec": 5,
                            "direction": {"intent": "focus", "focus": {"x": 62, "y": 44}},
                            "camera": [{"atSec": 0, "scale": 1, "focusX": 50, "focusY": 50},
                                       {"atSec": 1.2, "scale": 1.4, "focusX": 62, "focusY": 44}],
                            "annotations": [{"atSec": 2, "endSec": 4.5, "x": 42, "y": 32,
                                             "width": 40, "height": 24}]}]}
        footage = [{"name": "product.mp4", "seconds": 5,
                    "focusRegions": [{"x": 42, "y": 32, "width": 40, "height": 24}]}]
        self.assertEqual([], validate_script(draft, {"product.mp4"}, 5, footage=footage))
        draft["shots"][0]["direction"]["focus"] = {"x": 10, "y": 10}
        errors = validate_script(draft, {"product.mp4"}, 5, footage=footage)
        self.assertTrue(any("does not target" in error for error in errors))

    @staticmethod
    def edited_click_payload():
        return {
            "schemaVersion": 2, "timebase": "edited-media-seconds",
            "sourceViewport": {"width": 1920, "height": 1080},
            "events": [{"type": "click", "t": 2.25, "rawT": 4.9, "xPct": 62, "yPct": 44}],
        }

    def test_normalized_click_sidecars_enrich_manifest_without_mutating_authored_metadata(self):
        item = {"name": "product.mp4", "seconds": 8, "contents": "A receipt opens.",
                "events": "assets/product.events.json", "customEvidence": {"approved": True},
                "focusRegions": [{"x": 5, "y": 6, "width": 12, "height": 14, "label": "Header"}]}
        payload = self.edited_click_payload()
        with tempfile.TemporaryDirectory() as project:
            assets = os.path.join(project, "assets")
            os.mkdir(assets)
            manifest_path = os.path.join(assets, "footage.json")
            events_path = os.path.join(assets, "product.events.json")
            for path, data in ((manifest_path, [item]), (events_path, payload)):
                with open(path, "w") as handle:
                    json.dump(data, handle)
            with open(manifest_path, "rb") as handle:
                manifest_before = handle.read()
            with open(events_path, "rb") as handle:
                events_before = handle.read()

            enriched = load_footage(project)[0]
            for key, value in item.items():
                if key != "focusRegions":
                    self.assertEqual(value, enriched[key])
            self.assertEqual(item["focusRegions"], enriched["focusRegions"][:1])
            point = enriched["focusRegions"][1]
            self.assertEqual((62, 44, 2.25), (point["x"], point["y"], point["atSec"]))
            self.assertNotIn("width", point)
            self.assertNotIn("height", point)
            self.assertEqual("edited-media-seconds", point["timebase"])
            self.assertEqual("assets/product.events.json", point["source"])
            self.assertEqual(payload["events"], enriched["observedEvents"]["events"])
            self.assertEqual(payload["sourceViewport"], enriched["observedEvents"]["sourceViewport"])
            with open(manifest_path, "rb") as handle:
                self.assertEqual(manifest_before, handle.read())
            with open(events_path, "rb") as handle:
                self.assertEqual(events_before, handle.read())

    @patch("script.media_dimensions", return_value=(1920, 1080))
    @patch("script.subprocess.run", return_value=SimpleNamespace(stdout="8.0\n"))
    def test_ffprobe_fallback_also_exposes_observed_click_targets(self, probe, dimensions):
        with tempfile.TemporaryDirectory() as project:
            assets = os.path.join(project, "assets")
            os.mkdir(assets)
            with open(os.path.join(assets, "product.mp4"), "wb") as handle:
                handle.write(b"probe fixture")
            with open(os.path.join(assets, "product.events.json"), "w") as handle:
                json.dump(self.edited_click_payload(), handle)
            item = load_footage(project)[0]
            self.assertEqual(8, item["seconds"])
            self.assertEqual(2.25, item["focusRegions"][0]["atSec"])
            self.assertEqual("edited-media-seconds", item["observedEvents"]["timebase"])
            self.assertEqual({"width": 1920, "height": 1080}, item["sourceDisplay"])
            probe.assert_called_once()
            dimensions.assert_called_once()

    def test_raw_or_ambiguous_event_timebases_never_become_focus_targets(self):
        valid = self.edited_click_payload()
        cases = [valid["events"], {"events": valid["events"]},
                 {**valid, "schemaVersion": 1}, {**valid, "timebase": "capture-seconds"}]
        with tempfile.TemporaryDirectory() as project:
            assets = os.path.join(project, "assets")
            os.mkdir(assets)
            with open(os.path.join(assets, "footage.json"), "w") as handle:
                json.dump([{"name": "product.mp4", "seconds": 8}], handle)
            for payload in cases:
                with self.subTest(payload=payload):
                    with open(os.path.join(assets, "product.events.json"), "w") as handle:
                        json.dump(payload, handle)
                    item = load_footage(project)[0]
                    self.assertNotIn("focusRegions", item)
                    self.assertNotIn("observedEvents", item)

    def test_invalid_clicks_and_non_click_events_are_not_locators(self):
        payload = self.edited_click_payload()
        payload["events"] += [
            {"type": "move", "t": 3, "xPct": 1, "yPct": 2},
            {"type": "click", "t": -1, "xPct": 1, "yPct": 2},
            {"type": "click", "t": 30, "xPct": 1, "yPct": 2},
            {"type": "click", "t": 3, "xPct": 101, "yPct": 2},
            {"type": "click", "t": 3, "xPct": 1},
            {"type": "click", "t": 3, "xPct": "10", "yPct": 2},
        ]
        with tempfile.TemporaryDirectory() as project:
            assets = os.path.join(project, "assets")
            os.mkdir(assets)
            with open(os.path.join(assets, "footage.json"), "w") as handle:
                json.dump([{"name": "product.mp4", "seconds": 8}], handle)
            with open(os.path.join(assets, "product.events.json"), "w") as handle:
                json.dump(payload, handle)
            enriched = load_footage(project)[0]
            self.assertEqual(1, len(enriched["focusRegions"]))
            self.assertEqual([payload["events"][0]], enriched["observedEvents"]["events"])

    def test_click_locator_must_fall_inside_selected_source_range(self):
        footage = [{"name": "product.mp4", "seconds": 8,
                    "focusRegions": [{"x": 62, "y": 44, "atSec": 2.25,
                                      "timebase": "edited-media-seconds"}]}]
        draft = {"shots": [{"kind": "clip", "src": "product.mp4", "inSec": 2, "durSec": 3,
                            "direction": {"intent": "focus", "focus": {"x": 62, "y": 44}}}]}
        self.assertEqual([], validate_script(draft, {"product.mp4"}, 3, footage=footage))
        draft["shots"][0]["inSec"] = 3
        errors = validate_script(draft, {"product.mp4"}, 3, footage=footage)
        self.assertTrue(any("selected source range" in error for error in errors))

    def test_annotation_cannot_outlive_its_authored_region_visibility(self):
        footage = [{"name": "product.mp4", "seconds": 8,
                    "focusRegions": [{"x": 42, "y": 32, "width": 40, "height": 24,
                                      "startSec": 2, "endSec": 4}]}]
        shot = {"kind": "clip", "src": "product.mp4", "inSec": 1, "durSec": 5,
                "annotations": [{"atSec": 1.2, "endSec": 2.8, "x": 42, "y": 32,
                                 "width": 40, "height": 24}]}
        self.assertEqual([], validate_script({"shots": [shot]}, {"product.mp4"}, 5, footage=footage))
        shot["annotations"][0]["endSec"] = 4
        errors = validate_script({"shots": [shot]}, {"product.mp4"}, 5, footage=footage)
        self.assertTrue(any("annotation rectangle" in error for error in errors))

    def test_mapped_source_manifest_bounds_allow_holds_and_reject_fast_overrun(self):
        footage = [{"name": "product.mp4", "seconds": 5}]
        shot = {"kind": "clip", "src": "product.mp4", "durSec": 7, "sourceTimeline": [
            {"fromSec": 0, "toSec": 3, "durSec": 3, "mode": "realtime"},
            {"fromSec": 3, "toSec": 3, "durSec": 4, "mode": "hold"},
        ]}
        self.assertEqual([], validate_script({"shots": [shot]}, {"product.mp4"}, 7, footage=footage))
        shot.update(durSec=4, sourceTimeline=[{"fromSec": 0, "toSec": 8, "durSec": 4, "mode": "navigation"}])
        errors = validate_script({"shots": [shot]}, {"product.mp4"}, 4, footage=footage)
        self.assertTrue(any("needs 8.000s but manifest has 5.000s" in error for error in errors))

    def test_mapped_camera_and_annotation_grounding_use_real_source_time(self):
        footage = [{"name": "product.mp4", "seconds": 8,
                    "focusRegions": [{"x": 42, "y": 32, "width": 40, "height": 24,
                                      "startSec": 4, "endSec": 6}]}]
        shot = {"kind": "clip", "src": "product.mp4", "durSec": 4,
                "sourceTimeline": [{"fromSec": 0, "toSec": 8, "durSec": 4, "mode": "navigation"}],
                "camera": [{"atSec": 0, "scale": 1}, {"atSec": 2.5, "scale": 1.5, "focusX": 60, "focusY": 40}],
                "annotations": [{"atSec": 2.2, "endSec": 2.8, "x": 42, "y": 32, "width": 40, "height": 24}]}
        self.assertEqual([], validate_script({"shots": [shot]}, {"product.mp4"}, 4, footage=footage))
        shot["camera"][1]["atSec"] = 1
        errors = validate_script({"shots": [shot]}, {"product.mp4"}, 4, footage=footage)
        self.assertTrue(any("camera target" in error for error in errors))
        shot["camera"][1]["atSec"] = 2.5
        shot["annotations"][0]["endSec"] = 3.5
        errors = validate_script({"shots": [shot]}, {"product.mp4"}, 4, footage=footage)
        self.assertTrue(any("annotation rectangle" in error for error in errors))

    def test_annotation_can_remain_on_a_real_proof_frame_during_reading_hold(self):
        footage = [{"name": "product.mp4", "seconds": 5,
                    "focusRegions": [{"x": 42, "y": 32, "width": 40, "height": 24,
                                      "startSec": 1.9, "endSec": 2.1}]}]
        shot = {"kind": "clip", "src": "product.mp4", "durSec": 5, "sourceTimeline": [
            {"fromSec": 0, "toSec": 2, "durSec": 2, "mode": "realtime"},
            {"fromSec": 2, "toSec": 2, "durSec": 3, "mode": "hold"},
        ], "annotations": [{"atSec": 3, "endSec": 4.5, "x": 42, "y": 32, "width": 40, "height": 24}]}
        self.assertEqual([], validate_script({"shots": [shot]}, {"product.mp4"}, 5, footage=footage))

    def test_planner_cannot_hold_an_undecodable_end_frame(self):
        footage = [{"name": "product.mp4", "seconds": 5}]
        shot = {"kind": "clip", "src": "product.mp4", "durSec": 7,
                "sourceTimeline": [{"fromSec": 5, "toSec": 5, "durSec": 7, "mode": "hold"}]}
        errors = validate_script({"shots": [shot]}, {"product.mp4"}, 7, footage=footage)
        self.assertTrue(any("held proof frame must be strictly before source end" in error for error in errors))

    @staticmethod
    def measured_framing_fixture():
        rect = {"x": 42, "y": 32, "width": 20, "height": 12}
        shot = {"kind": "clip", "src": "product.mp4", "inSec": 1, "durSec": 5,
                "framing": {"sourceWidth": 1920, "sourceHeight": 1080,
                            "beats": [{"atSec": 0, "endSec": 5, "rect": dict(rect), "textHeightPx": 14}]}}
        footage = [{"name": "product.mp4", "seconds": 8,
                    "sourceDisplay": {"width": 1920, "height": 1080},
                    "focusRegions": [{**rect, "startSec": 1, "endSec": 6, "textHeightPx": 14}]}]
        return {"shots": [shot]}, footage

    def test_planner_accepts_measured_rect_glyph_and_display_dimensions_without_mutation(self):
        draft, footage = self.measured_framing_fixture()
        original = copy.deepcopy((draft, footage))
        self.assertEqual([], validate_script(draft, {"product.mp4"}, 5, footage=footage))
        self.assertEqual(original, (draft, footage))

    def test_planner_rejects_invented_rect_dimensions_or_glyph_measurements(self):
        for altered in ("rect", "dimensions", "glyph", "missing-glyph", "missing-dimensions", "missing-region"):
            draft, footage = self.measured_framing_fixture()
            framing = draft["shots"][0]["framing"]
            if altered == "rect":
                framing["beats"][0]["rect"]["x"] = 60
                expected = "framing rectangle"
            elif altered == "dimensions":
                framing["sourceWidth"] = 1680
                expected = "framing dimensions"
            elif altered == "glyph":
                framing["beats"][0]["textHeightPx"] = 22
                expected = "observed glyph measurement"
            elif altered == "missing-glyph":
                del footage[0]["focusRegions"][0]["textHeightPx"]
                expected = "observed glyph measurement"
            elif altered == "missing-dimensions":
                del footage[0]["sourceDisplay"]
                expected = "framing dimensions"
            else:
                del footage[0]["focusRegions"]
                expected = "omit invented coordinates"
            with self.subTest(altered=altered):
                errors = validate_script(draft, {"product.mp4"}, 5, footage=footage)
                self.assertTrue(any(expected in error for error in errors), errors)

    def test_planner_can_leave_glyph_height_unknown_instead_of_inventing_it(self):
        draft, footage = self.measured_framing_fixture()
        del draft["shots"][0]["framing"]["beats"][0]["textHeightPx"]
        del footage[0]["focusRegions"][0]["textHeightPx"]
        self.assertEqual([], validate_script(draft, {"product.mp4"}, 5, footage=footage))

    def test_source_window_requires_an_exact_full_interval_observation(self):
        draft, footage = self.measured_framing_fixture()
        shot = draft['shots'][0]
        shot['sourceWindow'] = shot.pop('framing')['beats'][0]['rect']
        self.assertEqual([], validate_script(draft, {'product.mp4'}, 5, footage=footage))
        for change in ('invented', 'short-lived', 'single-frame'):
            changed, observations = copy.deepcopy((draft, footage))
            if change == 'invented':
                changed['shots'][0]['sourceWindow']['width'] = 25
            elif change == 'short-lived':
                observations[0]['focusRegions'][0]['endSec'] = 3
            else:
                region = observations[0]['focusRegions'][0]
                region.pop('startSec'); region.pop('endSec'); region['atSec'] = 2
            with self.subTest(change=change):
                errors = validate_script(changed, {'product.mp4'}, 5, footage=observations)
                self.assertTrue(any('sourceWindow' in error for error in errors), errors)

    def test_measured_framing_cannot_outlive_observed_region_visibility(self):
        draft, footage = self.measured_framing_fixture()
        footage[0]["focusRegions"][0]["endSec"] = 4
        errors = validate_script(draft, {"product.mp4"}, 5, footage=footage)
        self.assertTrue(any("during the reading window" in error for error in errors), errors)

    def test_single_frame_region_cannot_authorize_framing_across_moving_footage(self):
        draft, footage = self.measured_framing_fixture()
        region = footage[0]["focusRegions"][0]
        region.pop("startSec")
        region.pop("endSec")
        region["atSec"] = 2
        errors = validate_script(draft, {"product.mp4"}, 5, footage=footage)
        self.assertTrue(any("during the reading window" in error for error in errors), errors)

    def test_single_frame_observation_can_authorize_a_real_source_frame_hold(self):
        draft, footage = self.measured_framing_fixture()
        shot = draft["shots"][0]
        shot.update(inSec=2, sourceTimeline=[{"fromSec": 2, "toSec": 2, "durSec": 5, "mode": "hold"}])
        region = footage[0]["focusRegions"][0]
        region.pop("startSec")
        region.pop("endSec")
        region["atSec"] = 2
        self.assertEqual([], validate_script(draft, {"product.mp4"}, 5, footage=footage))

    def test_detail_planner_preserves_observed_component_and_independent_screen_placement(self):
        draft, footage = self.measured_framing_fixture()
        shot = draft["shots"][0]
        shot.update(title="Saved status", eyebrow="Recorded product", caption="Source includes its qualifier")
        shot["framing"].update(presentation="detail",
                               screenRect={"x": 10, "y": 25, "width": 80, "height": 55})
        before = copy.deepcopy((draft, footage))
        self.assertEqual([], validate_script(draft, {"product.mp4"}, 5, footage=footage))
        self.assertEqual(before, (draft, footage))
        # Placement is composition geometry; the source component must still match inspection.
        shot["framing"]["beats"][0]["rect"]["width"] = 35
        errors = validate_script(draft, {"product.mp4"}, 5, footage=footage)
        self.assertTrue(any("framing rectangle" in error for error in errors), errors)

    def test_detail_planner_rejects_expired_observation_and_partial_reading_window(self):
        draft, footage = self.measured_framing_fixture()
        shot = draft["shots"][0]
        shot["framing"]["presentation"] = "detail"
        footage[0]["focusRegions"][0]["endSec"] = 4
        errors = validate_script(draft, {"product.mp4"}, 5, footage=footage)
        self.assertTrue(any("during the reading window" in error for error in errors), errors)
        footage[0]["focusRegions"][0]["endSec"] = 6
        shot["framing"]["beats"][0]["endSec"] = 4
        errors = validate_script(draft, {"product.mp4"}, 5, footage=footage)
        self.assertTrue(any("FRAMING_DETAIL_TIMING_INVALID" in error for error in errors), errors)

    def test_source_beat_grammar_is_checked_before_model_draft_is_accepted(self):
        shot = {"kind": "clip", "src": "product.mp4", "durSec": 5,
                "sourceBeats": [{"id": "proof", "sourceSec": 1, "kind": "proof", "cueId": "result"}]}
        draft = {"shots": [shot], "narrationMap": [
            {"id": "result", "shotN": 1, "text": "A sourced result.", "beat": "evidence"},
        ]}
        # An unsynthesized cue is allowed; its eventual alignment is not fabricated.
        self.assertEqual([], validate_script(draft, {"product.mp4"}, 5))
        self.assertNotIn("n", shot)
        shot["sourceBeats"][0]["cueId"] = "invented"
        self.assertTrue(any("SOURCE_BEAT_CUE_INVALID" in error for error in validate_script(draft, {"product.mp4"}, 5)))
        shot["sourceBeats"][0]["sourceSec"] = 6
        self.assertTrue(any("EDITORIAL_SOURCE_BEAT_OMITTED" in error for error in validate_script(draft, {"product.mp4"}, 5)))

    def test_repair_context_contains_exact_draft_and_actionable_findings(self):
        draft = {"shots": [{"kind": "clip", "src": "evidence.mp4", "durSec": 9}]}
        prompt = repair_prompt("Original brief", draft, ["source ends at 8s"])
        self.assertIn("Original brief", prompt)
        self.assertIn("source ends at 8s", prompt)
        self.assertEqual(draft, json.loads(prompt.split("DRAFT TO REPAIR:\n", 1)[1]))

    @patch("script.validate_contract", return_value=[])
    @patch("script.llm_json")
    def test_repair_keeps_owner_constraints_and_allows_pending_voice(self, llm, contract):
        bad = {"shots": [{"kind": "clip", "src": "product.mp4", "durSec": 8}]}
        good = {"production": {"hardMaxSec": 100},
                "shots": [{"kind": "clip", "src": "product.mp4", "durSec": 5}]}
        llm.side_effect = [bad, good]
        result = draft_script("System", "Brief", "/project", "walkthrough", 5, {},
                              [{"name": "product.mp4", "seconds": 5}], {"hardMaxSec": 5})
        self.assertEqual(5, result["production"]["hardMaxSec"])
        self.assertIn('"durSec": 8', llm.call_args_list[1].args[1])
        self.assertIn("manifest has 5", llm.call_args_list[1].args[1])
        self.assertEqual(1, contract.call_count)
        self.assertTrue(contract.call_args.kwargs["allow_pending_narration"])

    @patch("script.llm_json")
    def test_repairs_are_bounded_and_never_accept_an_invalid_draft(self, llm):
        invalid = {"shots": [{"kind": "clip", "src": "invented.mp4", "durSec": 5}]}
        llm.side_effect = [copy.deepcopy(invalid) for _ in range(3)]
        with self.assertRaisesRegex(ValueError, "after two repairs"):
            draft_script("System", "Brief", "/project", "walkthrough", 5, {},
                         [{"name": "product.mp4", "seconds": 5}])
        self.assertEqual(3, llm.call_count)


if __name__ == "__main__":
    unittest.main()
