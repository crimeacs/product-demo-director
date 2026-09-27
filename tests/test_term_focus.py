"""Faithful opt-in transcript pages; existing terminal mode stays the default."""
import copy
import hashlib
import json
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "tools"))
import term


class TerminalFocusTests(unittest.TestCase):
    def setUp(self):
        self.transcript = [
            {"role": "tool", "text": "curl -X POST https://example.test/api/v1/investigations"},
            {"role": "res", "text": "HTTP 202 Accepted"},
            {"role": "tool", "text": "curl https://example.test/api/v1/investigations/real-id/result"},
            {"role": "res", "text": json.dumps({"findings": 18, "cited": 14, "sources": 35})},
        ]
        self.spec = {"durationSec": 4, "fps": 30, "pages": [
            {"startSec": 0, "endSec": 2, "title": "Open a check.", "requestIndex": 0,
             "responseIndex": 1, "responseAtSec": .5},
            {"startSec": 2, "endSec": 4, "title": "Read the packet.", "kind": "metrics",
             "requestIndex": 2, "responseIndex": 3, "fields": ["findings", "cited", "sources"]},
        ]}

    def test_recorded_routes_status_and_all_selected_values_are_preserved_without_execution(self):
        with patch.object(term.subprocess, "run") as execute:
            plan = term.compile_focus_pages(self.transcript, self.spec)
        execute.assert_not_called()
        self.assertEqual(120, plan["frames"])
        self.assertEqual("POST", plan["pages"][0]["method"])
        self.assertEqual("HTTP 202 Accepted", plan["pages"][0]["response"])
        self.assertEqual("/api/v1/investigations/real-id/result", plan["pages"][1]["path"])
        self.assertEqual([18, 14, 35], [m["value"] for m in plan["pages"][1]["metrics"]])

    def test_legacy_renderer_remains_default(self):
        result = term.render_html(self.transcript)
        self.assertIn('class="term"', result)
        self.assertIn("function follow", result)
        self.assertNotIn("__pddSeek", result)
        self.assertNotIn("Recorded exchange", result)

    def test_focus_html_escapes_titles_and_keeps_provenance_and_complete_values(self):
        self.spec["pages"][0]["title"] = "<b>Recorded</b>"
        result = term.render_focus_html(self.transcript, self.spec)
        self.assertIn("&lt;b&gt;Recorded&lt;/b&gt;", result)
        self.assertIn("Recorded exchange · separate run", result)
        self.assertIn('class="value">35<', result)
        self.assertIn("sources", result)
        self.assertIn("__pddSeek", result)
        self.assertNotIn("fetch(", result)

    def test_metrics_cannot_invent_missing_fields_or_accept_non_numeric_values(self):
        for replacement in ["missing", ["nested"], "findings"]:
            spec = copy.deepcopy(self.spec)
            spec["pages"][1]["fields"] = ["findings", replacement]
            with self.subTest(replacement=replacement), self.assertRaises(ValueError):
                term.compile_focus_pages(self.transcript, spec)
        for value in [True, "18", None, float("inf")]:
            transcript = copy.deepcopy(self.transcript)
            transcript[3]["text"] = json.dumps({"findings": value, "cited": 14, "sources": 35})
            with self.subTest(value=value), self.assertRaises(ValueError):
                term.compile_focus_pages(transcript, self.spec)

    def test_malformed_roles_status_urls_and_response_json_fail_closed(self):
        mutations = [(0, "role", "res"), (0, "text", "echo do-not-execute"),
                     (0, "text", "curl https://a.test https://b.test"),
                     (1, "text", "HTTP 202"), (3, "text", "not json")]
        for index, key, value in mutations:
            transcript = copy.deepcopy(self.transcript)
            transcript[index][key] = value
            with self.subTest(value=value), self.assertRaises(ValueError):
                term.compile_focus_pages(transcript, self.spec)

    def test_noncontiguous_and_fractional_frame_schedules_are_rejected(self):
        for key, value in [("startSec", 2.1), ("startSec", 1.9), ("endSec", 3.99)]:
            spec = copy.deepcopy(self.spec)
            spec["pages"][1][key] = value
            with self.subTest(key=key, value=value), self.assertRaises(ValueError):
                term.compile_focus_pages(self.transcript, spec)
        self.spec["pages"][0]["responseAtSec"] = 2
        with self.assertRaises(ValueError):
            term.compile_focus_pages(self.transcript, self.spec)

    def test_invalid_source_indices_and_nonfinite_duration_are_rejected(self):
        for index in [True, -1, 99, "0"]:
            spec = copy.deepcopy(self.spec)
            spec["pages"][0]["requestIndex"] = index
            with self.subTest(index=index), self.assertRaises(ValueError):
                term.compile_focus_pages(self.transcript, spec)
        self.spec["durationSec"] = float("nan")
        with self.assertRaises(ValueError):
            term.compile_focus_pages(self.transcript, self.spec)

    def test_focus_cli_rejects_command_execution_before_any_command_runs(self):
        with patch.object(sys, "argv", ["term.py", "--focus-spec", "pages.json", "--cmd", "anything"]):
            with patch.object(term, "transcript_from_cmd") as execute, self.assertRaises(SystemExit):
                term.main()
            execute.assert_not_called()

    def recorded(self):
        text = "2 of 5 checks resolved · 1 needs your data · 2 still open"
        transcript = [{"role": "recorded-product", "text": text, "source": {
            "video": {"path": "source.mp4", "sha256": "a" * 64},
            "frame": {"path": "frame.png", "sha256": "b" * 64},
            "timeSec": 7.7, "dimensionsPx": [1920, 1080], "roiPx": [556, 147, 808, 104],
            "textSha256": hashlib.sha256(text.encode()).hexdigest(), "verification": "manual-visual",
        }}]
        spec = {"fps": 30, "durationSec": 4.3, "pages": [{
            "kind": "recorded-text", "recordIndex": 0, "startSec": 0, "endSec": 4.3,
            "title": "What this run settled", "layout": "lines", "splitOn": " · ",
        }]}
        return transcript, spec

    def test_product_excerpt_keeps_all_exact_phrases_and_discloses_typesetting(self):
        transcript, spec = self.recorded()
        plan = term.compile_focus_pages(transcript, spec)
        self.assertEqual(["2 of 5 checks resolved", "1 needs your data", "2 still open"], plan["pages"][0]["blocks"])
        result = term.render_focus_html(transcript, spec)
        self.assertIn("Recorded product · typeset excerpt", result)
        self.assertNotIn("Recorded exchange · separate run", result)
        self.assertIn("of 5 checks resolved", result)
        self.assertIn("needs your data", result)
        self.assertIn("still open", result)
        self.assertEqual(129, plan["frames"])

    def test_changed_text_cannot_reuse_a_verified_transcription_binding(self):
        transcript, spec = self.recorded()
        transcript[0]["text"] = "5 of 5 checks resolved"
        with self.assertRaisesRegex(ValueError, "differs"):
            term.compile_focus_pages(transcript, spec)

    def test_recorded_text_requires_complete_geometry_and_manual_verification(self):
        for key, value in [("verification", "automatic"), ("timeSec", -1),
                           ("roiPx", [1900, 1000, 100, 100]), ("dimensionsPx", None)]:
            transcript, spec = self.recorded()
            transcript[0]["source"][key] = value
            with self.subTest(key=key), self.assertRaises(ValueError):
                term.compile_focus_pages(transcript, spec)

    def test_reflow_cannot_discard_arbitrary_words(self):
        transcript, spec = self.recorded()
        spec["pages"][0]["splitOn"] = "still open"
        with self.assertRaises(ValueError):
            term.compile_focus_pages(transcript, spec)

    def test_recorded_source_hashes_and_project_boundary_are_checked(self):
        from PIL import Image
        transcript, spec = self.recorded()
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "source.mp4").write_bytes(b"test-video-identity")
            Image.new("RGB", (1920, 1080), "white").save(root / "frame.png")
            for name in ("video", "frame"):
                binding = transcript[0]["source"][name]
                binding["sha256"] = hashlib.sha256((root / binding["path"]).read_bytes()).hexdigest()
            plan = term.compile_focus_pages(transcript, spec)
            probe = {"streams": [{"codec_type": "video", "width": 1920, "height": 1080, "duration": "20"}]}
            with patch.object(term.subprocess, "check_output", return_value=json.dumps(probe).encode()):
                term.verify_recorded_sources(plan, root)
                for value in [20, 1000000]:
                    plan["pages"][0]["source"]["timeSec"] = value
                    with self.assertRaisesRegex(ValueError, "inside its video"):
                        term.verify_recorded_sources(plan, root)
                plan["pages"][0]["source"]["timeSec"] = 7.7
                probe["streams"][0]["width"] = 1080
                with patch.object(term.subprocess, "check_output", return_value=json.dumps(probe).encode()):
                    with self.assertRaisesRegex(ValueError, "video dimensions"):
                        term.verify_recorded_sources(plan, root)
            with self.assertRaises(ValueError):
                term.verify_recorded_sources(plan, None)
            (root / "source.mp4").write_bytes(b"different")
            with self.assertRaisesRegex(ValueError, "hash mismatch"):
                term.verify_recorded_sources(plan, root)
            plan["pages"][0]["source"]["video"]["path"] = "../outside.mp4"
            with self.assertRaisesRegex(ValueError, "inside source_root"):
                term.verify_recorded_sources(plan, root)

    def test_implicit_and_compact_curl_methods_are_not_mislabeled(self):
        for command, expected in [
            ("curl -d '{}' https://example.test/create", "POST"),
            ("curl -XPOST https://example.test/create", "POST"),
            ("curl --request=PATCH https://example.test/update", "PATCH"),
            ("curl --head https://example.test/health", "HEAD"),
            ("curl -d '{}' -X GET https://example.test/read", "GET"),
        ]:
            self.transcript[0]["text"] = command
            with self.subTest(command=command):
                self.assertEqual(expected, term.compile_focus_pages(self.transcript, self.spec)["pages"][0]["method"])

    def test_browser_layout_rejects_overflow_without_reducing_readable_type(self):
        from playwright.sync_api import sync_playwright
        from capture import _launch
        with sync_playwright() as playwright:
            browser = _launch(playwright)
            context = browser.new_context(viewport={"width": 1920, "height": 1080})
            context.route("**/*", lambda route: route.abort())
            page = context.new_page()
            def validate(transcript, spec):
                page.set_content(term.render_focus_html(transcript, spec))
                page.evaluate("document.fonts.ready")
                result = term.validate_focus_layout(page, term.compile_focus_pages(transcript, spec))
                page.evaluate("window.__pddSeek", 1)
                self.assertEqual("1", page.locator("#page-0").evaluate("element => element.style.opacity"))
                return result
            validate(self.transcript, self.spec)
            transcript, spec = self.recorded()
            validate(transcript, spec)
            spec["pages"][0]["title"] = "W" * 48
            with self.assertRaisesRegex(ValueError, "layout overflow"):
                validate(transcript, spec)
            for text in ["2 " + "a long complete source phrase " * 20,
                         "2 " + ("complete source words " * 7).strip() + " · 1 needs your data · 2 still open",
                         "200 open checks · 1 needs your data · 2 still open",
                         "2 first row · 1 second row · 2 third row · 3 fourth row"]:
                transcript, spec = self.recorded()
                transcript[0]["text"] = text
                transcript[0]["source"]["textSha256"] = hashlib.sha256(text.encode()).hexdigest()
                with self.subTest(text=text[:30]), self.assertRaisesRegex(ValueError, "layout overflow"):
                    validate(transcript, spec)
            self.transcript[0]["text"] = "curl -X POST https://example.test/" + "long-route/" * 20
            with self.assertRaisesRegex(ValueError, "layout overflow"):
                validate(self.transcript, self.spec)
            context.close()
            browser.close()


if __name__ == "__main__":
    unittest.main()
