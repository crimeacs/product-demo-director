import os
import sys
import unittest


sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "tools"))

from workbench import INTRO_MS, TAIL_MS, duration_ms, render_html  # noqa: E402


class WorkbenchTests(unittest.TestCase):
    def session(self):
        return {
            "title": "Codex · demo",
            "prompt": "Direct <unsafe> footage.",
            "phases": [
                {"mode": "inputs", "durationMs": 2000, "steps": ["BRIEF · product.json"]},
                {"mode": "qa", "durationMs": 3000, "steps": ["60.000 s · runtime"]},
            ],
        }

    def test_duration_is_phase_sum_plus_authored_handles(self):
        self.assertEqual(INTRO_MS + 5000 + TAIL_MS, duration_ms(self.session()))

    def test_session_is_embedded_as_escaped_data(self):
        page = render_html(self.session(), {
            "bg": "#000", "panel": "#111", "ink": "#fff",
            "sub": "#aaa", "accent": "#0f0", "warn": "#fa0",
        })
        self.assertIn("Codex · demo", page)
        self.assertNotIn("<unsafe>", page)
        self.assertIn("\\u003cunsafe>", page)
        self.assertIn("CURATED REPLAY", page)

    def test_preview_attribute_and_theme_are_sanitized(self):
        session = self.session()
        session["phases"][0]["previewSrc"] = 'x" onerror="alert(1)'
        page = render_html(session, {
            "bg": "#000;}</style><script>alert(1)</script>",
            "panel": "#111", "ink": "#fff", "sub": "#aaa",
            "accent": "#0f0", "warn": "#fa0",
        })
        self.assertIn("function escAttr", page)
        self.assertIn("src=\"${escAttr(p.previewSrc)}\"", page)
        self.assertNotIn("#000;}</style>", page)

    def test_final_phase_holds_instead_of_looping(self):
        page = render_html(self.session(), {
            "bg": "#000", "panel": "#111", "ink": "#fff",
            "sub": "#aaa", "accent": "#0f0", "warn": "#fa0",
        })
        self.assertIn("if(i+1<session.phases.length)", page)
        self.assertNotIn("(i+1)%session.phases.length", page)

    def test_phase_can_direct_attention_to_one_workbench_surface(self):
        session = self.session()
        session["phases"][0]["focus"] = "agent"
        page = render_html(session, {
            "bg": "#000", "panel": "#111", "ink": "#fff",
            "sub": "#aaa", "accent": "#0f0", "warn": "#fa0",
        })
        self.assertIn(".main.focus-agent", page)
        self.assertIn("['agent','preview'].includes(p.focus)", page)


if __name__ == "__main__":
    unittest.main()
