#!/usr/bin/env python3
"""Draft a script.json from a product brief + brand + the footage you captured.

Reads <project>/product.json (what the product is) + <project>/brand.json + a footage manifest
(<project>/assets/footage.json, else an ffprobe scan of assets/*.mp4|*.webm), and asks an LLM to
write a shot list that applies this repo's craft rules (see docs/EDITING.md). ``save-the-cat``
builds a three-act, fifteen-beat product story; several inseparable beats may share one real shot.
The default ``causal-workflow`` format follows a real input through evidence, test, bounded
decision, learning, and outcome. ``launch-film`` creates a single-focus open-source or product
announcement. ``before-after`` retains the legacy short-promo score/bars grammar.

    python tools/script.py --project projects/my-demo                 # -> projects/my-demo/script.json
    python tools/script.py --project projects/my-demo --seconds 15 --dry

It validates the draft against the engine schema (kinds, footage names, one pivot, runtime) and
re-prompts once on failure. The example ships a committed script.json, so this is a convenience,
not a hard requirement. LLM ladder + keys: same as tools/shoot.py (never hardcodes secrets).
"""
import argparse, json, os, re, shutil, subprocess, sys

from contracts import SAVE_THE_CAT_BEATS, validate_script as validate_contract

HERE = os.path.dirname(os.path.abspath(__file__))
ANTHROPIC_MODEL = os.environ.get("PDD_DRAFT_MODEL", "claude-opus-5-5")
ANTHROPIC_EFFORT = os.environ.get("PDD_DRAFT_EFFORT", "high")
GEMINI_MODEL = os.environ.get("PDD_DRAFT_GEMINI_MODEL", "gemini-3.1-pro-preview")
ALLOWED_KINDS = ("title", "clip", "split", "stat", "cta", "score", "bars", "strip")

RULES = """CRAFT RULES (from docs/EDITING.md — follow them):
- Lead with the customer's SHARPEST pain, ideally as an interrogative hook (a question out-pulls a statement).
- Explain WHAT THE PRODUCT IS within the first one or two beats (the viewer may never have seen it).
- Chain beats causally ("because/then", not "and then"); build to the proof.
- Use one visible action per narrated step. A long list of capabilities is not a story.
- Show one full-frame visual subject at a time. Reveal comparisons sequentially with matched cuts;
  never shrink dense product UI into a before/after split unless the requested format explicitly
  opts into that legacy device.
- Keep each complete spoken thought on one visual subject. Plan cuts between ideas, not at round
  second marks inside a sentence.
- Real product state must appear progressively. Never show the finished reasoning or answer before
  the initiating event. Counters alone do not prove completed work; show events, evidence, or receipts.
- Human involvement must match authority: low-friction/reversible work is agent-owned; consequential
  actions are human-owned. Restraint under uncertainty is a proof beat, not a weakness.
- Product screens may use motivated camera focus. Moving footage of real people preserves its source
  framing unless the brief explicitly authorizes a punch-in.
- Captions are optional. When used as subtitles they must match speech; sparse labels may identify a
  real actor/session without restating the narration.
- No AI-tells: no rule-of-three triads, no "seamless/robust/leverage/unlock/elevate", no em-dash
  crutch, no hype. Plain, specific, declarative. Spell numbers as said ("seventy-two").
- Slides may carry sourced traction or market context, never substitute for demonstrable product behavior.
- Story metadata must describe dramatic function in real footage. Never turn a framework into a
  sequence of cards or feature bullets; tension must rise because the situation changes.
"""

FORMAT_RULES = {
    "launch-film": """FORMAT: PRODUCT ANNOUNCEMENT FILM
Tell one self-contained release story: the old failure, what the product is, how the agent drives it,
the visible production transformation, artifact-bound proof, and one memorable release CTA. Use
Save-the-Cat beats as invisible story metadata, grouped across roughly seven to nine full-frame
sequences. Never show beat names. Never use split-screen. Define the product by eight seconds.
Show Claude Code or Codex acting inside the repo, not merely the finished output. Give each spoken
thought uninterrupted visual runway and use sparse labels instead of duplicate subtitles.""",
    "causal-workflow": """FORMAT: CAUSAL WORKFLOW
Build one connected proof arc from the available footage. Prefer these storyBeat values in order when
the evidence exists: setup, input, contradiction, test, restraint, decision, receipt, learning, outcome,
handoff, close. Use clip shots with sourceType=product and liveState=true when visible state changes.
Declare actor=agent|human|system and actionRisk=low-friction|consequential where an action occurs.
Do not force a before/after pivot, score card, bars card, or captions.""",
    "before-after": """FORMAT: BEFORE / AFTER SHORT PROMO
Use exactly one pivot (flash or chapter AFTER). A real score may use `score`; an iterative history may
use `bars` instead of replaying footage. Keep cards short and captions equal to VO.""",
    "walkthrough": """FORMAT: WALKTHROUGH
Organize a small number of chapters around user goals. Each chapter still needs a visible input, action,
and result. Do not invent a pivot, score, or outcome the footage does not prove.""",
    "save-the-cat": """FORMAT: SAVE THE CAT — THREE ACTS / FIFTEEN BEATS
Use every canonical story beat exactly once and in this order:
opening-image, theme-stated, setup, catalyst, debate, break-into-two, b-story, fun-and-games,
midpoint, bad-guys-close-in, all-is-lost, dark-night-of-the-soul, break-into-three, finale,
final-image.

This is a product story, not a screenplay-themed feature tour. The customer or maker is the hero;
the product changes what becomes possible. Opening-image and final-image must visibly mirror each
other. Theme-stated names the human truth. Catalyst creates a concrete disruption. Debate makes the
old path tempting. Fun-and-games delivers the product promise through real behavior. Midpoint is a
false victory or false defeat that raises the stakes. All-is-lost must be a real failed check,
constraint, or consequence. Break-into-three combines the product capability with the B-story truth.
Finale proves transformation in the product and final-image closes the opening visual.

Use `storyBeats` to group inseparable beats inside one real clip; do not create fifteen title cards.
Aim the major turns near 10%, 20%, 50%, 75%, 80%, and 99% of runtime. Show the product by 20%.""",
}

SCHEMA = """OUTPUT a single JSON object: { "shots": [ ... ] } (no prose). Each shot:
  { "n": <int>, "kind": "title|clip|split|stat|cta|score|bars|strip", "durSec": <float>,
    "vo": "<spoken line; omit on purely visual beats>", "accent": "<sfx key, optional>",
    optional "storyBeat" or "storyBeats":[...], "transition":"cut|xfade" }
Per-kind extra fields:
  clip : "src": <a footage name>, "inSec": <float>, optional "sourceType":"human|product",
         "liveState":true, "actor":"agent|human|system", "actionRisk":"low-friction|consequential",
         "preserveFraming":true, "continuityId":"stable same-screen id", "chapter":"AFTER","flash":true,
         "zooms":[{"atSec":0,"durSec":2,"scale":1.6,"focusX":50,"focusY":50}]
  split: "srcL","srcR": <footage names>, "labelL","labelR": <short>
  score: "score": <int>, "scoreMax": 100, "title": "<what the score means>"
  bars : "title": "<one line, e.g. 'it re-cut until it passed'>"
  title/stat/cta: "title": "<the on-screen line>"
accent keys available: data_tick, click, success_chime, confirm_cash, pivot_boom, impact, riser, whoosh.
Use src values ONLY from the provided footage manifest. Target total runtime ~%d seconds."""


def _extract_json(text):
    m = re.search(r"\{.*\}", text, re.S)
    if not m:
        raise ValueError("no JSON object found")
    return json.loads(m.group(0))


def llm_json(system, user):
    """Same provider ladder as tools/shoot.py (duplicated so each tool runs standalone)."""
    if os.environ.get("ANTHROPIC_API_KEY"):
        try:
            import anthropic
            c = anthropic.Anthropic()
            # Claude Opus 5.5: thinking is always on (adaptive), sampling params are rejected,
            # depth is set with effort (pinned high; the model defaults to medium); server-side
            # fallbacks rescue a policy decline in-call.
            with c.beta.messages.stream(
                model=ANTHROPIC_MODEL, max_tokens=32000, system=system,
                messages=[{"role": "user", "content": user}],
                output_config={"effort": ANTHROPIC_EFFORT},
                betas=["server-side-fallback-2026-07-01"], fallbacks="default",
            ) as stream:
                r = stream.get_final_message()
            if r.stop_reason == "refusal":
                raise RuntimeError(f"refused ({getattr(r.stop_details, 'category', None)})")
            text = "".join(b.text for b in r.content if b.type == "text")
            return _extract_json(text)
        except Exception as e:
            print("  (anthropic SDK draft failed:", e, "- falling through)")
    if shutil.which("claude"):
        try:
            p = subprocess.run(["claude", "-p", f"{system}\n\n{user}", "--output-format", "json"],
                               capture_output=True, text=True, timeout=180)
            data = json.loads(p.stdout)
            return _extract_json(data.get("result", p.stdout) if isinstance(data, dict) else p.stdout)
        except Exception as e:
            print("  (claude CLI draft failed:", e, "- falling through)")
    if os.environ.get("GEMINI_API_KEY") or os.environ.get("GOOGLE_API_KEY"):
        try:
            from google import genai
            from google.genai import types
            key = os.environ.get("GEMINI_API_KEY") or os.environ.get("GOOGLE_API_KEY")
            cl = genai.Client(api_key=key)
            resp = cl.models.generate_content(
                model=GEMINI_MODEL, contents=f"{system}\n\n{user}",
                config=types.GenerateContentConfig(response_mime_type="application/json",
                                                   thinking_config=types.ThinkingConfig(thinking_level="high")))
            return _extract_json(resp.text)
        except Exception as e:
            print("  (gemini draft failed:", e, "- falling through)")
    raise RuntimeError("no LLM provider available (set ANTHROPIC_API_KEY, install the claude CLI, or set GEMINI_API_KEY)")


def load_footage(project, footage_arg=""):
    path = footage_arg or os.path.join(project, "assets", "footage.json")
    if os.path.exists(path):
        items = json.load(open(path))
        return [{"name": i["name"], "seconds": i.get("seconds"), "contents": i.get("contents", "")} for i in items]
    # fall back to an ffprobe scan
    adir = os.path.join(project, "assets")
    out = []
    if os.path.isdir(adir):
        for f in sorted(os.listdir(adir)):
            if f.lower().endswith((".mp4", ".webm")):
                r = subprocess.run(["ffprobe", "-v", "error", "-show_entries", "format=duration",
                                    "-of", "default=nk=1:nw=1", os.path.join(adir, f)],
                                   capture_output=True, text=True)
                try:
                    secs = round(float(r.stdout.strip()), 1)
                except Exception:
                    secs = None
                out.append({"name": f, "seconds": secs, "contents": ""})
    return out


def validate_script(obj, footage_names, seconds, demo_format="causal-workflow"):
    errs = []
    shots = obj.get("shots") if isinstance(obj, dict) else None
    if not shots:
        return ["no shots[]"]
    pivots = 0
    has_proof = False
    total = 0.0
    card_seconds = 0.0
    first_product = None
    has_live_product = False
    actual_beats = []
    for i, sh in enumerate(shots):
        k = sh.get("kind")
        if k not in ALLOWED_KINDS:
            errs.append(f"shot {i}: bad kind {k!r}")
            continue
        if demo_format != "before-after" and k == "split":
            errs.append(f"shot {i}: split-screen is reserved for explicit before-after work; use sequential full-frame shots")
        duration = float(sh.get("durSec", 2.5))
        start = total
        total += duration
        if k in ("title", "stat", "cta", "score", "bars"):
            card_seconds += duration
        if sh.get("sourceType") == "product":
            first_product = start if first_product is None else first_product
            has_live_product = has_live_product or bool(sh.get("liveState"))
        if sh.get("storyBeat"):
            actual_beats.append(str(sh["storyBeat"]))
        grouped = sh.get("storyBeats") or []
        if not isinstance(grouped, list):
            errs.append(f"shot {i}: storyBeats must be an array")
            grouped = []
        actual_beats.extend(str(beat) for beat in grouped if beat)
        if sh.get("flash") or sh.get("chapter") == "AFTER":
            pivots += 1
        if k in ("score", "bars"):
            has_proof = True
        if k == "clip":
            if sh.get("src") not in footage_names:
                errs.append(f"shot {i}: clip src {sh.get('src')!r} not in footage {footage_names}")
        if k == "split":
            for s in (sh.get("srcL"), sh.get("srcR")):
                if s not in footage_names:
                    errs.append(f"shot {i}: split src {s!r} not in footage {footage_names}")
        if k in ("clip", "split", "strip") and sh.get("vo") and "caption" in sh and sh["caption"] not in ("", sh["vo"]):
            errs.append(f"shot {i}: caption must equal vo (or be omitted/empty) on a {k}")
    if pivots > 1:
        errs.append(f"{pivots} pivots (max 1: one shot with flash/chapter AFTER)")
    if demo_format == "before-after" and pivots != 1:
        errs.append(f"before-after format requires exactly one pivot (got {pivots})")
    if demo_format == "before-after" and not has_proof:
        errs.append("no score or bars beat (the proof) — add one")
    if demo_format == "save-the-cat":
        cursor = 0
        for beat in SAVE_THE_CAT_BEATS:
            try:
                cursor = actual_beats.index(beat, cursor) + 1
            except ValueError:
                errs.append(f"Save the Cat beat missing or out of order: {beat}")
        unknown = sorted(set(actual_beats) - set(SAVE_THE_CAT_BEATS))
        if unknown:
            errs.append(f"unknown Save the Cat beats: {', '.join(unknown)}")
        repeated = sorted(beat for beat in SAVE_THE_CAT_BEATS if actual_beats.count(beat) > 1)
        if repeated:
            errs.append(f"Save the Cat beats repeated: {', '.join(repeated)}")
        if card_seconds / max(total, 0.001) > 0.30 + 1e-6:
            errs.append("Save the Cat cards exceed 30% of runtime; carry the story in real footage")
        if first_product is None:
            errs.append("Save the Cat format requires product footage with sourceType=product")
        elif first_product > float(seconds) * 0.20 + 0.001:
            errs.append(f"product first appears at {first_product:.1f}s; show it by 20% of runtime")
        if not has_live_product:
            errs.append("Save the Cat format requires progressive product footage with liveState=true")
    if abs(total - seconds) > 6:
        errs.append(f"runtime {total:.1f}s is far from target {seconds}s (±6 allowed)")
    return errs


def finalize(obj, demo_format, seconds, brand):
    """Apply deterministic defaults before validation so partial model output cannot bypass them."""
    if not isinstance(obj, dict):
        return {"shots": []}
    for i, sh in enumerate(obj.get("shots", []), 1):
        sh["n"] = i
    obj.setdefault("fps", 30)
    obj.setdefault("musicVolume", 0.11)
    obj.setdefault("music", "confident modern tech underscore, crisp pluck synth and warm pad, "
                   "light tight percussion, forward momentum, one short rising riser, then steady, no vocals")
    obj.setdefault("voice_settings", {"stability": 0.32, "similarity_boost": 0.85,
                                      "style": 0.78, "use_speaker_boost": True})
    production = obj.get("production")
    if not isinstance(production, dict):
        production = {}
        obj["production"] = production
    defaults = {}
    if demo_format == "causal-workflow":
        defaults = {
            "profile": "investor",
            "hardMaxSec": max(float(seconds) * 1.15, float(seconds) + 3),
            "maxCardRatio": 0.25,
            "enforceSameScreenContinuity": True,
            "cursorSafeMarginPct": 10,
            "maxHumanDecisions": 1,
        }
    elif demo_format == "save-the-cat":
        defaults = {
            "profile": "investor",
            "storyFramework": "save-the-cat",
            "requiredStoryBeats": list(SAVE_THE_CAT_BEATS),
            "hardMaxSec": max(float(seconds) * 1.05, float(seconds) + 1),
            "productBySec": max(2.0, float(seconds) * 0.20),
            "maxCardRatio": 0.30,
            "requireLiveProgression": True,
            "enforceSameScreenContinuity": True,
            "cursorSafeMarginPct": 10,
        }
    elif demo_format == "launch-film":
        defaults = {
            "profile": "announcement",
            "storyFramework": "save-the-cat",
            "requiredStoryBeats": list(SAVE_THE_CAT_BEATS),
            "hardMaxSec": min(60.0, max(float(seconds), 1.0)),
            "productBySec": min(8.0, max(2.0, float(seconds) * 0.14)),
            "maxCardRatio": 0.15,
            "singleFocus": True,
            "requireContinuityIds": True,
            "requireClaimEvidence": True,
            "enforceSameScreenContinuity": True,
            "cursorSafeMarginPct": 10,
        }
    for key, value in defaults.items():
        production.setdefault(key, value)
    if brand:
        cta = brand.get("cta", {})
        obj["brand"] = {"name": cta.get("name", brand.get("name")),
                        "accent": cta.get("accent"), "url": brand.get("url", "")}
        if brand.get("theme") or brand.get("palette"):
            obj["theme"] = brand.get("theme") or {}
    return obj


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--project", required=True)
    ap.add_argument("--footage", default="")
    ap.add_argument("--out", default="")
    ap.add_argument("--seconds", type=int, default=15)
    ap.add_argument("--format", choices=["auto", "launch-film", "causal-workflow", "before-after", "walkthrough", "save-the-cat"],
                    default="auto")
    ap.add_argument("--dry", action="store_true")
    a = ap.parse_args()

    proj = os.path.abspath(a.project)
    product = json.load(open(os.path.join(proj, "product.json")))
    demo_format = a.format if a.format != "auto" else product.get("demoFormat", "causal-workflow")
    if demo_format not in FORMAT_RULES:
        raise SystemExit(f"unknown demo format: {demo_format}")
    brand_path = os.path.join(proj, "brand.json")
    brand = json.load(open(brand_path)) if os.path.exists(brand_path) else {}
    footage = load_footage(proj, a.footage)
    if not footage:
        raise SystemExit("no footage found — run tools/shoot.py first or add assets/footage.json")
    names = [f["name"] for f in footage]

    system = "You are a senior product-demo director. You output only valid JSON shot lists."
    user = "\n\n".join([
        RULES,
        FORMAT_RULES[demo_format],
        SCHEMA % a.seconds,
        "PRODUCT:\n" + json.dumps(product, indent=2),
        "BRAND:\n" + json.dumps({k: brand.get(k) for k in ("name", "tagline", "url", "tone", "cta") if k in brand}, indent=2),
        "FOOTAGE (use these src names only):\n" + json.dumps(footage, indent=2),
        f"TASK: write the {demo_format} shot list (~{a.seconds}s) for this product using the footage above.",
    ])

    obj = finalize(llm_json(system, user), demo_format, a.seconds, brand)
    errs = validate_script(obj, names, a.seconds, demo_format)
    errs.extend(f"{finding.code}: {finding.message}" for finding in validate_contract(obj, proj)
                if finding.severity == "error")
    if errs:
        print("draft invalid, re-prompting once:\n  - " + "\n  - ".join(errs))
        obj = finalize(llm_json(system, user + "\n\nYour previous attempt had these problems — fix ALL and "
                                  "return STRICT JSON only:\n- " + "\n- ".join(errs)),
                       demo_format, a.seconds, brand)
        errs = validate_script(obj, names, a.seconds, demo_format)
        errs.extend(f"{finding.code}: {finding.message}" for finding in validate_contract(obj, proj)
                    if finding.severity == "error")
        if errs:
            raise SystemExit("draft still invalid:\n  - " + "\n  - ".join(errs))

    out = json.dumps(obj, indent=2)
    if a.dry:
        print(out)
        return
    dest = a.out or os.path.join(proj, "script.json")
    open(dest, "w").write(out + "\n")
    print(f"wrote {dest} ({len(obj['shots'])} shots, ~{sum(float(s.get('durSec',2.5)) for s in obj['shots']):.1f}s)")


if __name__ == "__main__":
    main()
