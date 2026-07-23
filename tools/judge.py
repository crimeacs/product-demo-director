#!/usr/bin/env python3
"""Gemini video judge — uploads a rendered cut, samples it at a chosen fps, and
WATCHES and LISTENS (VO + music), scoring it against a deliberately HARSH product-demo
rubric. Emits JSON so an improve loop can act on it.

    python tools/judge.py --video projects/my-demo/out/demo.mp4 --fps 4 [--out judge.json]

fps note (per Gemini video-understanding docs): default sampling is 1 fps; raise it to ~3-5 for
fast-cut demos so on-screen text/captions/transitions are read. Max fps is 24. The audio track is
transcribed automatically, so VO clarity and music balance are judged too.

The rubric is intentionally strict: a clean-but-boring, slow, or repetitive demo lands ~30, the
same score a demanding human gives it. Reserve 85+ for punchy, varied, zero-repetition cuts.

Env: GEMINI_API_KEY (or GOOGLE_API_KEY). Model override: GEMINI_JUDGE_MODEL.
"""
import argparse, json, os, re, sys, time

from contracts import sha256_file

RUBRIC = """You are a BRUTAL, impatient viewer scrolling an endless feed, AND a demo-savvy
product-marketing lead. Your DEFAULT is to click away within 2 seconds. The video must EARN every
second it asks for. Judge whether this product demo is GENUINELY GOOD: punchy, varied, surprising,
fast, memorable. Most demos are NOT — the average competent demo is forgettable and deserves a
40-55, never a 90.

START from a baseline of 50 and move from there. Add points only for things that genuinely
impress. Subtract hard for the failure modes below. A clean, competent, but boring / slow /
repetitive demo is a 30.

KILL IT for these — each is common, and each is a real reason a viewer leaves:
- REPETITION. If the same screen / UI / location appears in more than one shot, or the same
  number / claim / word is stated more than once, that is a serious flaw. List every repeat. A
  demo that shows its score three times, or the same terminal/screen twice, is padded and amateur.
- SLOW PACE / PADDING. Assume it is too slow until proven otherwise. Any shot longer than its
  spoken line; any title/stat card held >2s with no new information; any static screen carried by
  only a slow push-in — that is dead weight. If the same message could land in 20s but it runs
  35s+, it is padded. Count the dead seconds.
- BORING SCREENS. Static dashboards, terminals, scorecards, and text cards are LOW-ENERGY by
  default. A slow push-in on a static screen is the BARE MINIMUM, not something to reward. Reward
  ONLY genuinely dynamic, surprising, delightful, or information-dense motion. A screen that just
  sits there is boring, full stop.
- NO SURPRISE. If every beat is predictable, there is no reason to keep watching. A great demo has
  at least one genuinely surprising or satisfying moment.
- WEAK HOOK. If the first 2 seconds don't make you NEED to keep watching, most viewers are gone.

A synthetic / AI voice is acceptable IF well-timed and not monotone — but do not reward it, and
penalize any line that drags or over-explains.

Score each 0-100 from the harsh baseline:
- hook_1s: do the first ~2s make you NEED to keep watching? (most: 30-50)
- pace_rhythm: tight, no dead air, no padded shots? (penalize every padded second)
- non_repetition: 100 = nothing repeats; subtract hard for every repeated screen/number/claim.
- visual_interest: genuinely dynamic / varied / surprising visuals? (static screens + push-in: low)
- motion_design: kinetic captions, clean cuts, motion that adds meaning (not just a zoom).
- vo_performance: clear, well-timed, never dragging or over-explaining.
- sound_design: music + SFX that drive energy and hit the beats.
- clarity_one_thing: ONE crisp, memorable takeaway after one watch.
- proof_credibility: concrete, specific, believable.
- polish: typography, color, finish.
- wow_moment: is there a real wow? (most demos: 0-30 — be stingy.)

CALIBRATION (be strict):
- 85-100: RARE. Punchy, varied, zero repetition, every second earns its place, a real wow — you'd
  stop scrolling and forward it.
- 70-84: good, clearly above average, but with a flaw or two.
- 50-69: competent but generic and forgettable.
- 30-49: boring, repetitive, slow, or padded — you would click away.
- below 30: broken (dead air, monotone, confusing, unreadable).

Be honest and harsh. Find AT LEAST 5 specific weaknesses with mm:ss. Then name the single change
that would most raise the score.

Return STRICT JSON only:
{
  "overall": <int>,
  "scores": {"hook_1s":int,"pace_rhythm":int,"non_repetition":int,"visual_interest":int,"motion_design":int,"vo_performance":int,"sound_design":int,"clarity_one_thing":int,"proof_credibility":int,"polish":int,"wow_moment":int},
  "repeated_elements": ["every screen/number/claim that appears more than once, with mm:ss"],
  "dead_seconds": ["padded/slow/held moments, with mm:ss and why"],
  "biggest_weaknesses": ["at least 5, ranked, with mm:ss"],
  "specific_upgrades": [{"area":"hook|pace|repetition|visual|motion|vo|sound|structure","change":"concrete fix"}],
  "would_keep_watching": <true|false>,
  "one_line_verdict": "the unvarnished truth in one sentence"
}"""

LIVE_PROFILES = {"yc_3m", "yc3", "investor", "investor-live-product", "sales"}

LIVE_RUBRIC = """You are reviewing a causal live-product demo for an investor or first-time buyer.
The owner has approved the delivery profile and runtime. Judge whether the film truthfully and
clearly proves one differentiated workflow; do not apply short social-ad assumptions.

The strongest pattern is a visible chain such as input/context → contradiction → hypothesis → test
→ restraint under uncertainty → bounded decision → receipt → learned rule → safe replay → queue
outcome → external handoff. The exact beats vary, but each result must follow a visible cause.

Penalize hard:
- PRESET RESULTS: reasoning, recommendations, or counters are complete before the initiating event.
- PRESENTATION IN PLACE OF PRODUCT: recreated cards/slides substitute for behavior the product should show.
- UNSUPPORTED CLAIMS: narration, counters, economics, customer status, or scale exceed visible evidence.
- FALSE AUTHORITY: low-friction work waits for a generic reviewer, or consequential work silently bypasses one.
- FEATURE-LIST STORY: capabilities accumulate without one unit of work moving causally.
- CAMERA DISCONTINUITY: same-screen crop resets, cursor cropping/teleporting, over-zoomed context, or altered human framing.
- SECOND ENDING: the payoff lands, then familiar screens recap it instead of moving to one fresh close.

Do not penalize a continuous screen merely because it remains on screen while state and evidence advance.
Do not demand a two-second hook when a short human setup creates trust. A long take is good when it proves
causality; a fast cut is bad when it hides it. Restraint such as “this signal alone is not proof” is a
positive proof beat when the product then runs a falsifiable next test.

Score 0-100:
- hook_1s: does the opening earn attention and establish trust for this audience?
- pace_rhythm: does each hold earn comprehension or proof, with inert time removed?
- non_repetition: does each returning state add new evidence or consequence?
- visual_interest: is the evidence legible and progressively revealed without becoming a slide deck?
- motion_design: do camera moves and transitions clarify meaning while protecting context and cursor?
- vo_performance: natural, warm, specific speech with one visible action per step?
- sound_design: clear, balanced, and appropriate rather than theatrically over-produced?
- clarity_one_thing: can a first-time viewer state the product's memorable difference?
- proof_credibility: are actions, counts, receipts, and claims visibly supportable?
- polish: typography, continuity, source framing, color, audio, and final export quality?
- wow_moment: does the differentiated payoff genuinely compound or close the loop?
- product_truth: does this read as a live product with honest boundaries rather than a preset presentation?
- causal_progression: can every important result be traced to a visible initiating action?
- authority_boundary: are agent, human, and external-system responsibilities truthful and clear?

Find at least five timestamped observations. Recommendations must identify whether they require a recut,
recapture, product change, narration change, or claim change. Do not recommend a change outside that layer.

Return STRICT JSON only:
{
  "overall": <int>,
  "scores": {"hook_1s":int,"pace_rhythm":int,"non_repetition":int,"visual_interest":int,"motion_design":int,"vo_performance":int,"sound_design":int,"clarity_one_thing":int,"proof_credibility":int,"polish":int,"wow_moment":int,"product_truth":int,"causal_progression":int,"authority_boundary":int},
  "repeated_elements": ["only repeated states/payoffs with no new information, with mm:ss"],
  "dead_seconds": ["inert moments, with mm:ss and why"],
  "biggest_weaknesses": ["at least 5, ranked, with mm:ss and visible evidence"],
  "specific_upgrades": [{"area":"story|truth|camera|cursor|vo|sound|structure","change_class":"recut|recapture|product_change|narration_change|claim_change","change":"concrete fix"}],
  "would_keep_watching": <true|false>,
  "one_line_verdict": "the unvarnished truth in one sentence"
}"""

LENS_RULES = {
    "overall": "Review the integrated film across all rubric axes.",
    "story": "Focus on first-watch comprehension, causal ordering, setup, escalation, payoff, and whether the film ends once.",
    "truth": "Focus on progressive live state, visible evidence, claim support, restraint, autonomy, and the human decision boundary.",
    "visual": "Focus on source framing, same-screen continuity, zoom motivation, cursor safety, UI legibility, transitions, and export polish.",
    "buyer": "Focus on trust, memorable differentiation, operational usefulness, external handoff realism, and what a first-time buyer believes after one watch.",
}


def get_key():
    return os.environ.get("GEMINI_API_KEY") or os.environ.get("GOOGLE_API_KEY")


def _structural(props):
    """Deterministic pace + repetition penalties from the timeline props. Gemini-flash
    won't score these honestly (it calls every cut 'punchy'); the props don't lie.
    Returns (repetition_penalty, other_penalty, notes) so repeats aren't double-charged
    against the model's own repeated_elements list."""
    from collections import Counter
    segs = props.get("segments", []) or []
    if not segs:
        return 0, 0, []
    durs = [float(x.get("durSec", 0)) for x in segs]
    total = sum(durs)
    avg = total / len(segs)
    profile = props.get("profile") or "promo-short"
    live_profile = profile in LIVE_PROFILES
    if live_profile:
        # Continuity is not repetition. Penalize only an explicitly repeated state with no new
        # story beat; a long causal take on one screen is often the strongest proof in the film.
        states = [(x.get("stateId"), x.get("storyBeat")) for x in segs if x.get("stateId")]
        rep = sum(v - 1 for v in Counter(states).values() if v > 1)
        avg_limit = 15.0 if profile != "sales" else 24.0
        runtime_limit = 180.0 if profile != "sales" else 300.0
        card_limit = 9.0
    else:
        srcs = [x.get("src") for x in segs if x.get("kind") == "clip" and x.get("src")]
        rep = sum(v - 1 for v in Counter(srcs).values() if v > 1)
        avg_limit, runtime_limit, card_limit = 3.0, 28.0, 2.6
    held = sum(1 for x in segs if x.get("kind") in ("title", "stat", "cta")
               and float(x.get("durSec", 0)) > card_limit)
    rep_pen, pen, notes = 0, 0, []
    if rep:
        rep_pen = 6 * rep; notes.append(f"{rep} repeated state(s) with no new story information [-{rep_pen}]")
    if avg > avg_limit:
        d = round((avg - avg_limit) * (2 if live_profile else 6)); pen += d
        notes.append(f"slow avg shot {avg:.1f}s for profile {profile} [-{d}]")
    if total > runtime_limit:
        d = round((total - runtime_limit) * (0.5 if live_profile else 0.8)); pen += d
        notes.append(f"runtime {total:.0f}s exceeds profile limit {runtime_limit:.0f}s [-{d}]")
    if held:
        pen += 3 * held; notes.append(f"{held} static card(s) held >{card_limit:.1f}s [-{3*held}]")
    return rep_pen, pen, notes


def calibrate(data, props_path):
    """Final score = harsh-weighted blend of the axes that decide 'not boring', minus the
    model's own detected flaws, minus deterministic structural penalties. The model's raw
    'overall' is kept as overall_model for reference but is NOT trusted."""
    s = data.get("scores", {}) or {}
    def g(k, d=50):   # a sub-score the model failed to emit is treated as mediocre, not good
        try:
            return float(s.get(k, d))
        except Exception:
            return d
    blend = (0.20 * g("non_repetition") + 0.18 * g("pace_rhythm") + 0.16 * g("visual_interest")
             + 0.12 * g("wow_moment") + 0.12 * g("hook_1s") + 0.12 * g("clarity_one_thing")
             + 0.10 * g("motion_design"))
    reps = data.get("repeated_elements", []) or []
    dead = data.get("dead_seconds", []) or []
    if props_path and os.path.exists(props_path):
        with open(props_path) as fh:
            props = json.load(fh)
    else:
        props = None
    if props:
        srep, spen, snotes = _structural(props)
    else:
        srep, spen, snotes = 0, 0, []
        print("WARNING: no props.json — structural pace/repetition scoring SKIPPED (pass --props "
              "or keep props.json next to the video; build.py writes one automatically)", file=sys.stderr)
    # each repeated element is charged ONCE: the larger of the model's list and the structural count
    live_profile = bool(props and props.get("profile") in LIVE_PROFILES)
    if live_profile:
        # Truth cannot be averaged away by visual polish. Product truth, causal progression, and
        # proof carry nearly half the live-demo score; a weak authority boundary caps the result.
        blend = (0.16 * g("product_truth", g("proof_credibility"))
                 + 0.14 * g("causal_progression", g("clarity_one_thing"))
                 + 0.14 * g("proof_credibility")
                 + 0.12 * g("clarity_one_thing")
                 + 0.10 * g("authority_boundary", g("proof_credibility"))
                 + 0.10 * g("pace_rhythm") + 0.07 * g("vo_performance")
                 + 0.06 * g("visual_interest") + 0.05 * g("motion_design")
                 + 0.04 * g("wow_moment") + 0.02 * g("polish"))
    rep_pen = srep if live_profile else max(6 * len(reps), srep)
    overall = round(blend) - rep_pen - 5 * len(dead) - spen
    if live_profile:
        boundary = g("authority_boundary", g("proof_credibility"))
        truth = g("product_truth", g("proof_credibility"))
        if min(boundary, truth) < 50:
            overall = min(overall, 49)
    if not data.get("would_keep_watching", True):
        overall = min(overall, 40)
    data["overall_model"] = data.get("overall")
    data["overall"] = max(5, overall)
    data["structural_penalties"] = snotes
    return data


def judge_video(client, video, context, props, fps, model, runs, lenses=None):
    """Upload once, judge `runs` times, return the run whose calibrated overall is the median
    (with all runs' overalls recorded). Median-of-N because same-cut variance is documented
    at ~27 points on a single run."""
    from google.genai import types

    f = client.files.upload(file=video)
    for _ in range(60):
        f = client.files.get(name=f.name)
        st = getattr(f.state, "name", str(f.state))
        if st == "ACTIVE":
            break
        if st == "FAILED":
            raise RuntimeError("file processing FAILED")
        time.sleep(3)

    profile = None
    if props and os.path.exists(props):
        with open(props) as fh:
            profile = (json.load(fh) or {}).get("profile")
    rubric = LIVE_RUBRIC if profile in LIVE_PROFILES else RUBRIC
    part_video = types.Part(
        file_data=types.FileData(file_uri=f.uri, mime_type=f.mime_type),
        video_metadata=types.VideoMetadata(fps=min(fps, 24)),
    )
    selected = lenses or ["overall"]
    lens_results: dict[str, dict] = {}
    for lens in selected:
        prompt = (rubric + "\n\nREVIEW LENS: " + LENS_RULES[lens]
                  + (("\n\nWHAT THIS DEMO IS: " + context) if context else ""))
        results, last_err = [], None
        for i in range(runs):
            try:
                resp = client.models.generate_content(
                    model=model,
                    contents=types.Content(parts=[part_video, types.Part(text=prompt)]),
                    config=types.GenerateContentConfig(response_mime_type="application/json", temperature=0.0),
                )
                m = re.search(r"\{.*\}", resp.text, re.S)
                result = json.loads(m.group(0) if m else resp.text)
                results.append(calibrate(result, props))
            except Exception as exc:
                last_err = f"{model} lens={lens} run {i + 1}: {exc}"
        if not results:
            raise RuntimeError(str(last_err))
        results.sort(key=lambda item: item["overall"])
        median = results[len(results) // 2]
        median["runs_overall"] = [item["overall"] for item in results]
        median["_lens"] = lens
        median["_model"] = model
        median["_fps"] = min(fps, 24)
        lens_results[lens] = median
    if len(lens_results) == 1:
        return next(iter(lens_results.values()))
    # Do not average a 92 in visual polish with a 60 in product truth. The weakest independent
    # lens is the review floor and remains visible alongside every complete report.
    floor_name, floor = min(lens_results.items(), key=lambda item: item[1]["overall"])
    return {
        "overall": floor["overall"],
        "lens_floor": floor_name,
        "lenses": lens_results,
        "_model": model,
        "_fps": min(fps, 24),
        "one_line_verdict": f"Independent review floor: {floor_name} ({floor['overall']}).",
    }


def find_props(video, props_arg):
    """--props wins; else look for props.json next to the video (build.py writes one there)."""
    if props_arg:
        return props_arg
    absolute = os.path.abspath(video)
    stem = os.path.splitext(absolute)[0]
    for guess in (f"{stem}.props.json", os.path.join(os.path.dirname(absolute), "props.json")):
        if os.path.exists(guess):
            return guess
    return ""


def verify_artifact(video, artifact_arg="", required=False):
    """Bind judging to build.py's artifact manifest and reject the wrong/stale MP4."""
    absolute = os.path.abspath(video)
    candidates = [artifact_arg] if artifact_arg else [
        f"{os.path.splitext(absolute)[0]}.artifact.json",
        os.path.join(os.path.dirname(absolute), "artifact.json"),
    ]
    path = next((candidate for candidate in candidates if candidate and os.path.exists(candidate)),
                candidates[0])
    if not os.path.exists(path):
        if required:
            raise RuntimeError(f"artifact manifest required but missing: {path}")
        print("WARNING: no artifact.json — judge cannot prove this is the intended build", file=sys.stderr)
        return None
    with open(path) as fh:
        data = json.load(fh)
    expected = ((data.get("output") or {}).get("sha256") or "").lower()
    actual = sha256_file(video).lower()
    if not expected or expected != actual:
        raise RuntimeError(f"artifact hash mismatch: manifest={expected or 'missing'} video={actual}")
    return {"path": os.path.abspath(path), "buildId": data.get("buildId"), "sha256": actual}


def probe_paths(good_path="", bad_path=""):
    """Resolve explicit calibration media without requiring a bundled release video."""
    root = os.path.dirname(HERE)
    bad = os.path.abspath(
        bad_path or os.path.join(root, "examples", "calibration", "known_bad.mp4")
    )
    good = os.path.abspath(good_path) if good_path else ""
    return bad, good


def probe(client, fps, model, *, good_path="", bad_path=""):
    """Sanity-check the judge against a bundled bad cut and an approved local good cut."""
    bad, good = probe_paths(good_path, bad_path)
    if not good:
        print(
            "probe: --probe-good PATH is required; use a reviewed local delivery master",
            file=sys.stderr,
        )
        sys.exit(2)
    for p in (bad, good):
        if not os.path.exists(p):
            print(f"probe: missing {p}", file=sys.stderr)
            sys.exit(1)
    b = judge_video(client, bad, "a product demo", "", fps, model, 1)
    g = judge_video(client, good, "a product demo", "", fps, model, 1)
    ok = b["overall"] <= 50 and g["overall"] > b["overall"]
    print(json.dumps({"probe": "PASS" if ok else "FAIL",
                      "known_bad": b["overall"], "known_good": g["overall"], "model": model}))
    sys.exit(0 if ok else 1)


HERE = os.path.dirname(os.path.abspath(__file__))
# pinned: a floating alias ("gemini-flash-latest") makes scores drift across sessions
DEFAULT_MODEL = "gemini-2.5-flash"


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--video", help="rendered cut to judge")
    ap.add_argument("--context", default="", help="optional one-line note about what the demo is")
    ap.add_argument("--props", default="", help="timeline props.json for deterministic pace/repetition scoring (default: props.json next to the video)")
    ap.add_argument("--fps", type=float, default=4.0)
    ap.add_argument("--model", default=os.environ.get("GEMINI_JUDGE_MODEL", DEFAULT_MODEL))
    ap.add_argument("--runs", type=int, default=3, help="judge N times, report the median run (variance control)")
    ap.add_argument("--lens", choices=sorted(LENS_RULES), default="overall",
                    help="advisory review lens; overall is the integrated default")
    ap.add_argument("--all-lenses", action="store_true",
                    help="run independent story, truth, visual, and buyer reviews; report the weakest lens as the floor")
    ap.add_argument("--probe", action="store_true",
                    help="sanity-check the judge against a known-bad and approved local good cut, then exit")
    ap.add_argument("--probe-good", default="",
                    help="reviewed local delivery master used as the known-good probe reference")
    ap.add_argument("--probe-bad", default="",
                    help="optional bad reference; defaults to examples/calibration/known_bad.mp4")
    ap.add_argument("--artifact", default="", help="artifact.json from build.py (default: beside video)")
    ap.add_argument("--require-artifact", action="store_true", help="refuse to judge an unbound or stale video")
    ap.add_argument("--out", default="")
    args = ap.parse_args()

    key = get_key()
    if not key:
        print(json.dumps({"error": "set GEMINI_API_KEY or GOOGLE_API_KEY"}))
        sys.exit(1)

    from google import genai
    client = genai.Client(api_key=key)

    if args.probe:
        probe(client, args.fps, args.model,
              good_path=args.probe_good, bad_path=args.probe_bad)
    if not args.video:
        sys.exit("--video required (or --probe)")

    try:
        artifact = verify_artifact(args.video, args.artifact, args.require_artifact)
        lenses = ["story", "truth", "visual", "buyer"] if args.all_lenses else [args.lens]
        data = judge_video(client, args.video, args.context, find_props(args.video, args.props),
                           args.fps, args.model, max(1, args.runs), lenses=lenses)
        data["_artifact"] = artifact
    except Exception as e:
        print(json.dumps({"error": str(e)}))
        sys.exit(1)
    out = json.dumps(data, indent=2)
    print(out)
    if args.out:
        os.makedirs(os.path.dirname(args.out) or ".", exist_ok=True)
        with open(args.out, "w") as fh:
            fh.write(out + "\n")


if __name__ == "__main__":
    main()
