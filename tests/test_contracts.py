import json
import os
import sys
import tempfile
import unittest
import wave

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "tools"))

from contracts import SAVE_THE_CAT_BEATS, validate_script  # noqa: E402


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

    def test_claims_require_verifiable_evidence(self):
        project = self.project()
        script = self.base()
        script["production"]["requireClaimEvidence"] = True
        script["claims"] = [{"id": "seven", "status": "draft", "evidence": "missing.json"}]
        script["shots"][0]["claimIds"] = ["seven"]
        codes = self.codes(script, project)
        self.assertIn("CLAIM_UNVERIFIED", codes)
        self.assertIn("CLAIM_EVIDENCE_MISSING", codes)

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
