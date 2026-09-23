#!/usr/bin/env python3
"""Record a product's footage — the director plans and shoots it, so you don't pre-record.

Reads <project>/shoot.json (a list of shots) and writes one <project>/assets/<name>.mp4 per shot,
ready for the script drafter + the pipeline. Two kinds of shot:

  - "terminal": render an animated terminal/agent session (term.py) and record it. For CLIs and
    Claude skills with no web UI (e.g. this tool). Drive it with a `transcript` or a real `cmd`.
  - "web": point Chrome at a `url`; if no `steps` are given, the director PLANS the shoot — it
    probes the real page (scroll height, visible CTAs) and an LLM emits scroll/click steps that
    are validated and clamped against that DOM before recording.

    python tools/shoot.py --project projects/my-demo                 # shoot every shot -> assets/<name>.mp4
    python tools/shoot.py --project projects/my-demo --only term_run  # one shot
    python tools/shoot.py --project projects/my-demo --plan-only      # write/validate web plans, no recording
    python tools/shoot.py --url https://app.x.com --goal "show the dashboard, click Run" --out a.mp4

shoot.json:
  { "shots": [
      { "name": "term_run", "kind": "terminal", "speed": 1.7,
        "transcript": [ {"role":"user","text":"..."}, {"role":"tool","text":"Bash(...)"}, ... ] },
      { "name": "dash", "kind": "web", "url": "https://app.example.com",
        "goal": "scroll the report, click Run", "speed": 1.0 }   # steps omitted -> planned
  ] }

LLM ladder (planning only; never hardcodes keys): anthropic SDK if ANTHROPIC_API_KEY set, else the
`claude -p` CLI if present, else google-genai if GEMINI_API_KEY/GOOGLE_API_KEY. A frozen fallback
plan is used if all fail, so a shoot never hard-depends on an LLM.

Requires: playwright (+ chromium), ffmpeg. Raw recordings land in assets/_raw/ (gitignored).
"""
import argparse, json, os, re, shutil, subprocess, sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)  # import sibling tools when run as a script
import capture  # noqa: E402
from events import normalize_events_file, transform_events  # noqa: E402,F401

ANTHROPIC_MODEL = os.environ.get("ANTHROPIC_PLANNER_MODEL", "claude-fable-5-1")
ANTHROPIC_EFFORT = os.environ.get("ANTHROPIC_PLANNER_EFFORT", "high")
GEMINI_MODEL = os.environ.get("PDD_PLANNER_GEMINI_MODEL", "gemini-3.1-pro-preview")

STEPS_SCHEMA = (
    'A JSON array of steps run in order. Allowed step objects:\n'
    '  {"wait": <ms>}\n'
    '  {"scroll_to": <pixels_from_top>, "steps": 24, "pause": 40}\n'
    '  {"click_text": "<visible button text>", "fallback_selector": "<css>", "after": 1400}\n'
    'Rules: open with a {"wait":1000}; alternate scroll + wait so motion is smooth; only click text '
    'that appears in the provided CTAs; end with a {"wait":1500}. 5-9 steps. JSON only, no prose.'
)


# ---------------------------------------------------------------- LLM ladder
def _extract_json(text):
    m = re.search(r"(\{.*\}|\[.*\])", text, re.S)
    if not m:
        raise ValueError("no JSON found")
    return json.loads(m.group(1))


def llm_json(system, user):
    """Return parsed JSON from the first provider that works, or raise."""
    # 1) anthropic SDK (only if a key is set AND the SDK is importable)
    if os.environ.get("ANTHROPIC_API_KEY"):
        try:
            import anthropic
            c = anthropic.Anthropic()
            # Claude Fable 5.1: thinking is always on (adaptive), sampling params are rejected,
            # depth is set with effort; server-side fallbacks rescue a policy decline in-call.
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
            print("  (anthropic SDK planner failed:", e, "- falling through)")
    # 2) the claude CLI (present in Claude Code; uses the configured model, no id needed)
    if shutil.which("claude"):
        try:
            p = subprocess.run(["claude", "-p", f"{system}\n\n{user}", "--output-format", "json"],
                               capture_output=True, text=True, timeout=120)
            data = json.loads(p.stdout)
            return _extract_json(data.get("result", p.stdout) if isinstance(data, dict) else p.stdout)
        except Exception as e:
            print("  (claude CLI planner failed:", e, "- falling through)")
    # 3) google-genai (already a dep; used by judge.py/sfx.py)
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
            print("  (gemini planner failed:", e, "- falling through)")
    raise RuntimeError("no LLM provider available (set ANTHROPIC_API_KEY, install the claude CLI, or set GEMINI_API_KEY)")


# ---------------------------------------------------------------- web planning
def frozen_web_plan(scroll_height):
    sh = max(800, int(scroll_height or 1800))
    return [{"wait": 1000}, {"scroll_to": int(0.45 * sh), "steps": 24, "pause": 42},
            {"wait": 1500}, {"scroll_to": int(0.9 * sh), "steps": 24, "pause": 45}, {"wait": 1500}]


def plan_web(shot):
    url = shot["url"]
    print(f"  probing {url} ...")
    info = capture.probe(url)
    sh = info.get("scrollHeight", 1800)
    cta_texts = {c["text"]: c for c in info.get("ctas", [])}
    goal = shot.get("goal", "give a clear, smooth tour of the product")
    user = (f"GOAL: {goal}\nPAGE: scrollHeight={sh}px, viewport={info.get('viewportH')}px, "
            f"title={info.get('title')!r}\nHEADINGS: {info.get('headings')}\n"
            f"VISIBLE CTAS (only these may be clicked): {[c['text'] for c in info.get('ctas', [])]}\n\n{STEPS_SCHEMA}")
    try:
        steps = llm_json("You are a screen-recording director. Output ONLY a JSON array of capture steps.", user)
        if not isinstance(steps, list):
            raise ValueError("planner did not return a list")
    except Exception as e:
        print("  planner unavailable, using a safe scroll plan:", e)
        return frozen_web_plan(sh), info
    # validate + clamp every step against the real DOM
    clean = []
    for st in steps:
        if not isinstance(st, dict):
            continue
        if "scroll_to" in st:
            st["scroll_to"] = max(0, min(int(st["scroll_to"]), sh))
        if "click_text" in st:
            t = st["click_text"]
            if t not in cta_texts:
                print(f"  dropping click on un-probed CTA: {t!r}")
                continue
            st.setdefault("fallback_selector", cta_texts[t]["selector"])
        clean.append(st)
    return (clean or frozen_web_plan(sh)), info


# ---------------------------------------------------------------- normalize
def normalize(webm, mp4, speed=1.0, trim_lead=0.4, raw_events=None, edited_events=None):
    vf = (f"setpts=PTS/{speed},scale=1920:1080:force_original_aspect_ratio=decrease,"
          f"pad=1920:1080:(ow-iw)/2:(oh-ih)/2,fps=30,format=yuv420p")
    cmd = ["ffmpeg", "-y", "-ss", str(trim_lead), "-i", webm, "-vf", vf,
           "-an", "-c:v", "libx264", "-crf", "18", "-preset", "medium", mp4]
    result = subprocess.run(cmd, capture_output=True, text=True)
    if result.returncode != 0:
        raise RuntimeError(f"ffmpeg normalize failed: {result.stderr[-1200:]}")
    if raw_events and edited_events:
        normalize_events_file(
            raw_events,
            edited_events,
            trim_lead,
            speed,
            source_width=capture.W,
            source_height=capture.H,
        )
    return mp4


# ---------------------------------------------------------------- shot runners
def shoot_terminal(shot, raw_dir, out_mp4, project):
    import term
    name = shot["name"]
    if shot.get("cmd"):
        transcript = term.transcript_from_cmd(shot["cmd"], shot.get("prompt"), shot.get("say"))
    else:
        transcript = shot["transcript"]
    webm = os.path.join(raw_dir, f"{name}.webm")
    term.render_and_capture(transcript, webm, project=project, name=name, title=shot.get("title"))
    normalize(webm, out_mp4, speed=shot.get("speed", 1.7), trim_lead=shot.get("trimLead", 0.4))
    return {"name": name, "kind": "terminal", "out": os.path.relpath(out_mp4, project)}


def shoot_web(shot, raw_dir, out_mp4, project, steps_path, replan=False, plan_only=False):
    name = shot["name"]
    if shot.get("steps"):
        steps, info = shot["steps"], {"scrollHeight": None, "ctas": []}
    elif os.path.exists(steps_path) and not replan:
        steps, info = json.load(open(steps_path)), {"ctas": []}
        print(f"  reusing {os.path.relpath(steps_path, project)}")
    else:
        steps, info = plan_web(shot)
        json.dump(steps, open(steps_path, "w"), indent=2)
        print(f"  planned -> {os.path.relpath(steps_path, project)} ({len(steps)} steps)")
    if plan_only:
        return {"name": name, "kind": "web", "steps": os.path.relpath(steps_path, project), "planOnly": True}
    webm = os.path.join(raw_dir, f"{name}.webm")
    misses = []
    import io, contextlib
    buf = io.StringIO()
    with contextlib.redirect_stdout(buf):
        capture.run(shot["url"], steps, webm, quiet=False)
    for line in buf.getvalue().splitlines():
        if "miss:" in line:
            misses.append(line.strip())
    raw_events = os.path.splitext(webm)[0] + ".events.json"
    edited_events = os.path.splitext(out_mp4)[0] + ".events.json"
    normalize(webm, out_mp4, speed=shot.get("speed", 1.0), trim_lead=shot.get("trimLead", 0.4),
              raw_events=raw_events, edited_events=edited_events)
    return {"name": name, "kind": "web", "out": os.path.relpath(out_mp4, project),
            "events": os.path.relpath(edited_events, project) if os.path.exists(edited_events) else None,
            "steps": os.path.relpath(steps_path, project), "clickMisses": misses}


def probe_out(mp4):
    r = subprocess.run(["ffprobe", "-v", "error", "-show_entries",
                        "format=duration:stream=width,height,r_frame_rate", "-of", "json", mp4],
                       capture_output=True, text=True)
    try:
        d = json.loads(r.stdout)
        st = next((s for s in d.get("streams", []) if "width" in s), {})
        return {"width": st.get("width"), "height": st.get("height"),
                "durationSec": round(float(d.get("format", {}).get("duration", 0)), 2)}
    except Exception:
        return {}


# ---------------------------------------------------------------- main
def run_project(project, only=None, plan_only=False, force=False, replan=False):
    sj = os.path.join(project, "shoot.json")
    if not os.path.exists(sj):
        raise SystemExit(f"no shoot.json in {project}")
    shots = json.load(open(sj)).get("shots", [])
    assets = os.path.join(project, "assets")
    raw_dir = os.path.join(assets, "_raw")
    os.makedirs(raw_dir, exist_ok=True)
    report = []
    for shot in shots:
        name = shot["name"]
        if only and name != only:
            continue
        out_mp4 = os.path.join(assets, f"{name}.mp4")
        if os.path.exists(out_mp4) and not force and not plan_only:
            print(f"• {name}: exists (use --force to re-shoot)")
            report.append({"name": name, "kind": shot.get("kind"), "out": os.path.relpath(out_mp4, project), "skipped": True})
            continue
        print(f"• {name} ({shot.get('kind')}) ...")
        kind = shot.get("kind", "web")
        if kind == "terminal":
            if plan_only:
                report.append({"name": name, "kind": "terminal", "planOnly": True})
                continue
            rec = shoot_terminal(shot, raw_dir, out_mp4, project)
        elif kind == "web":
            steps_path = os.path.join(assets, f"{name}.steps.json")
            rec = shoot_web(shot, raw_dir, out_mp4, project, steps_path, replan=replan, plan_only=plan_only)
        else:
            print(f"  unknown kind {kind!r}, skipping")
            continue
        if not plan_only:
            rec.update(probe_out(out_mp4))
            print(f"  -> {rec.get('out')}  {rec.get('width')}x{rec.get('height')} {rec.get('durationSec')}s")
        report.append(rec)
    json.dump({"shots": report}, open(os.path.join(assets, "shoot.report.json"), "w"), indent=2)
    print(f"shoot.report.json written ({len([r for r in report if not r.get('skipped')])} shot(s))")
    return report


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--project", default="")
    ap.add_argument("--only", default="")
    ap.add_argument("--plan-only", action="store_true")
    ap.add_argument("--force", action="store_true")
    ap.add_argument("--replan", action="store_true")
    # one-shot web mode
    ap.add_argument("--url", default="")
    ap.add_argument("--goal", default="")
    ap.add_argument("--out", default="")
    a = ap.parse_args()

    if a.url:
        out = a.out or "web.mp4"
        raw_dir = os.path.dirname(os.path.abspath(out)) or "."
        os.makedirs(raw_dir, exist_ok=True)
        shot = {"name": os.path.splitext(os.path.basename(out))[0], "kind": "web", "url": a.url, "goal": a.goal}
        steps_path = os.path.join(raw_dir, shot["name"] + ".steps.json")
        rec = shoot_web(shot, raw_dir, out, raw_dir, steps_path, replan=a.replan, plan_only=a.plan_only)
        if not a.plan_only:
            rec.update(probe_out(out))
        print(json.dumps(rec, indent=2))
        return
    if not a.project:
        raise SystemExit("provide --project <dir> (with shoot.json) or --url <url> --out <file.mp4>")
    run_project(a.project, only=a.only or None, plan_only=a.plan_only, force=a.force, replan=a.replan)


if __name__ == "__main__":
    main()
