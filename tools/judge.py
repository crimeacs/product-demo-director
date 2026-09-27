#!/usr/bin/env python3
"""Gemini video review — submit the complete cut with audio and an explicit sampling rate.
Existing audience lenses retain their score calibration; the opt-in motion lens returns
timestamped production findings and advisory scores without a shipping gate.

    python tools/judge.py --video projects/my-demo/out/demo.mp4 --fps 4 [--out judge.json]

    python tools/judge.py --video projects/my-demo/out/demo.mp4 --lens motion --fps 24

Sampling accepts 0 < fps <= 24 and never silently clamps. The receipt binds the media bytes,
submitted rate, model and provider usage. Actual provider frame selection remains unverified;
timestamps and observations still need review against the source video.

Env: GEMINI_API_KEY (or GOOGLE_API_KEY). Model override: GEMINI_JUDGE_MODEL.
"""
import argparse, hashlib, json, math, os, re, sys, time
from contextlib import contextmanager
from datetime import datetime, timezone

from contracts import media_duration, sha256_file

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
- SLOW PACE / PADDING. Count time after the spoken point and visible evidence have been understood,
  including cards held without useful reading time or new information. A deliberate hold to read
  a result is earned time; cutting away before the result can be read is a pacing failure. If the
  same understood message could land in 20s but it runs 35s+, identify the padded seconds.
- BORING SCREENS. A static dashboard or text card with no useful evidence progression is weak.
  A slow push-in does not repair it. Reward directing attention to meaningful evidence, a satisfying
  reveal, and legible visual hierarchy. Do not reward perpetual motion or punish a necessary reading hold.
- NO SURPRISE. If every beat is predictable, there is no reason to keep watching. A great demo has
  at least one genuinely surprising or satisfying moment.
- WEAK HOOK. If the first 2 seconds don't make you NEED to keep watching, most viewers are gone.

A synthetic / AI voice is acceptable IF well-timed and not monotone — but do not reward it, and
penalize any line that drags or over-explains.

Score each 0-100 from the harsh baseline:
- hook_1s: do the first ~2s make you NEED to keep watching? (most: 30-50)
- pace_rhythm: tight, no dead air, no padded shots? (penalize every padded second)
- non_repetition: 100 = nothing repeats; subtract hard for every repeated screen/number/claim.
- visual_interest: distinctive composition, hierarchy, and meaningful evidence revealed at the right moment?
- motion_design: motivated camera paths, readable arrivals, intentional cuts, and coherent transitions?
- vo_performance: clear, well-timed, never dragging or over-explaining.
- sound_design: sparse, well-timed cues and intelligible speech; music or silence appropriate to the brief?
- clarity_one_thing: ONE crisp, memorable takeaway after one watch.
- proof_credibility: concrete, specific, believable.
- polish: typography, color, finish.
- wow_moment: is there a real wow? (most demos: 0-30 — be stingy.)

STUDIO CRAFT — apply when a studio treatment is declared or visible:
- Camera: identify the evidence each move helps us see. Check that the target, source context, and
  cursor remain visible, then hold the landing long enough to read it. Penalize aimless drift,
  overshoot, sudden crop resets, and motion continuing while the viewer needs to inspect proof.
- Type and hierarchy: one clear focal point per beat. Check contrast, line breaks, safe margins,
  consistent scale, and the complete final title. A masked line must fully reveal before the cut
  and remain readable at delivery size; an attractive entrance cannot excuse missing words.
- Cuts and masks: transitions must support the change of idea or view. Incoming evidence must
  settle before the next cut; masks cannot hide the initiating action or its result. Flag clipped
  reveals, dark dips, exposed edges, and competing camera/transition movement with timestamps.
- Annotations: boxes and spotlights must stay aligned with the actual source through camera moves.
  Labels must identify what is visible without covering critical controls, inventing product UI,
  or making a stronger claim than the evidence. Decorative tracking that drifts is a defect.
- Sound: cues should mark meaningful reveals or actions and leave room for speech. Repeated
  whooshes, a cue on every cut, masking narration, or implying a product confirmation that did not
  occur are defects. Intentional quiet can be the strongest choice.
Judge the resulting communication and finish, never the number of effects or authored keyframes.
Use timestamped observations and name the smallest useful correction. If sparse video sampling or
missing audio prevents an assessment, say what is unverified and which frames/audio need review.
An automated score or clean technical QA does not establish top-studio creative quality.

CALIBRATION (be strict):
- 85-100: RARE. Punchy, varied, zero repetition, every second earns its place, a real wow — you'd
  stop scrolling and forward it.
- 70-84: good, clearly above average, but with a flaw or two.
- 50-69: competent but generic and forgettable.
- 30-49: boring, repetitive, slow, or padded — you would click away.
- below 30: broken (dead air, monotone, confusing, unreadable).

Be honest and specific. Rank observed weaknesses with mm:ss; do not invent defects to meet a quota.
Then name the single change that would most improve the viewing experience.

Return STRICT JSON only:
{
  "overall": <int>,
  "scores": {"hook_1s":int,"pace_rhythm":int,"non_repetition":int,"visual_interest":int,"motion_design":int,"vo_performance":int,"sound_design":int,"clarity_one_thing":int,"proof_credibility":int,"polish":int,"wow_moment":int},
  "repeated_elements": ["every screen/number/claim that appears more than once, with mm:ss"],
  "dead_seconds": ["padded/slow/held moments, with mm:ss and why"],
  "biggest_weaknesses": ["observed weaknesses, ranked, with mm:ss"],
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
- motion_design: do motivated camera moves arrive into readable holds, with coherent cuts and masks that protect context and cursor?
- vo_performance: natural, warm, specific speech with one visible action per step?
- sound_design: sparse cues support real actions and preserve clear speech, with quiet where useful?
- clarity_one_thing: can a first-time viewer state the product's memorable difference?
- proof_credibility: are actions, counts, receipts, and claims visibly supportable?
- polish: typography, continuity, source framing, color, audio, and final export quality?
- wow_moment: does the differentiated payoff genuinely compound or close the loop?
- product_truth: does this read as a live product with honest boundaries rather than a preset presentation?
- causal_progression: can every important result be traced to a visible initiating action?
- authority_boundary: are agent, human, and external-system responsibilities truthful and clear?

STUDIO CRAFT — apply when a studio treatment is declared or visible:
- Camera motion must point to real evidence, preserve source context and cursor, and end in a
  stable reading hold. A continuous shot with clear proof can outperform a busier treatment.
  Penalize aimless drift, overshoot, crop resets, or movement while small UI text must be read.
- Typography must establish one focal point with clear scale, contrast, line breaks, and safe
  margins. Watch the complete title after its entrance: every line must fully reveal and remain
  readable before the next cut. Motion cannot conceal missing or truncated claim text.
- Cuts and reveal masks must preserve the causal chain. Check the outgoing evidence and incoming
  landing, not just a pleasing transition midpoint. Flag clipped reveals, dark dips, exposed edges,
  or camera/transition motion that competes with a product action.
- Annotation rectangles and spotlights must remain anchored to actual source geometry through
  zooms and pans. Labels must neither occlude evidence nor imitate unsupported product behavior.
- Sound cues should punctuate meaningful actions or reveals, sparingly. Penalize repetitive
  whooshes, buried narration, abrupt tails, and cues that falsely imply a product confirmation.
  Silence is valid; adding music or more effects is not inherently an upgrade.
Reward hierarchy, timing, restraint, and comprehension, never effect count or keyframe complexity.
Cite visible/audible evidence at timestamps and the smallest correction needed. When sampling is
too sparse to judge a reveal or landing, request its boundary frames; report unavailable audio as
unverified. A model score or clean machine QA cannot certify top-studio creative quality.

Find timestamped observations; do not invent weaknesses to fill a quota. Recommendations must identify whether they require a recut,
recapture, product change, narration change, or claim change. Do not recommend a change outside that layer.

Return STRICT JSON only:
{
  "overall": <int>,
  "scores": {"hook_1s":int,"pace_rhythm":int,"non_repetition":int,"visual_interest":int,"motion_design":int,"vo_performance":int,"sound_design":int,"clarity_one_thing":int,"proof_credibility":int,"polish":int,"wow_moment":int,"product_truth":int,"causal_progression":int,"authority_boundary":int},
  "repeated_elements": ["only repeated states/payoffs with no new information, with mm:ss"],
  "dead_seconds": ["inert moments, with mm:ss and why"],
  "biggest_weaknesses": ["observed weaknesses, ranked, with mm:ss and visible evidence"],
  "specific_upgrades": [{"area":"story|truth|camera|cursor|vo|sound|structure","change_class":"recut|recapture|product_change|narration_change|claim_change","change":"concrete fix"}],
  "would_keep_watching": <true|false>,
  "one_line_verdict": "the unvarnished truth in one sentence"
}"""

LENS_RULES = {
    "overall": "Review the integrated film across all rubric axes.",
    "story": "Focus on first-watch comprehension, causal ordering, setup, escalation, payoff, and whether the film ends once.",
    "truth": "Focus on progressive live state, visible evidence, claim support, restraint, autonomy, and the human decision boundary.",
    "visual": "Evaluate studio craft as communication: evidence-motivated camera moves with stable reading holds; source framing and cursor safety; typography hierarchy, contrast, delivery-size legibility, and complete line reveals; cuts/masks that preserve causality and finish before the next beat; annotations that stay aligned through camera moves; sparse sound cues that support real actions without masking speech; and export finish. Reward restraint and clarity, never effect count. Cite timestamped defects and the smallest correction; identify uncertain transition boundaries or audio that need closer inspection. Automated QA cannot establish top-studio creative quality.",
    "buyer": "Focus on trust, memorable differentiation, operational usefulness, external handoff realism, and what a first-time buyer believes after one watch.",
    "motion": "Review the complete temporal sequence: motivated attention, camera arrivals, settled reading holds, cut continuity, source playback, typography/masks, and audio timing. Identify the responsible production layer for each observed defect.",
}

MOTION_RUBRIC = """You are a motion director reviewing the supplied complete product-demo video and
its audio in chronological order. Assess what happens between the attractive frames: a contact
sheet or a list of isolated compositions cannot establish motion quality.

First describe the sequence the viewer experiences: setup, action, arrival, reading, consequence,
and how attention transfers into the next shot. Then identify only material defects supported by
visible or audible evidence. Compare the moments before, during, and after each suspected defect.
Do not invent timestamps, claim frame accuracy beyond the sampling interval, or treat a sampling
gap as an observed jump. Mark uncertain observations and unavailable audio as unverified.

Inspect these layers separately:
- camera: is each move motivated, connected to context, and settled before proof must be read?
  Distinguish deliberate reading holds from aimless drift, unnecessary return-to-wide moves,
  hard crop resets, overshoot, and moving a target out of view during an action.
- source_playback: is an action actually visible before its result; do speed changes, frozen
  frames, or source discontinuities break causality? Never propose invented product behavior.
- edit: do cuts preserve the unit of work and transfer attention clearly? Assess the whole
  sequence, including repetitive pacing, an unearned recap, and abrupt changes of visual language.
- transition_mask: check both outgoing and incoming evidence, reveal completion, clipped text,
  exposed edges, dark dips, and competing camera/transition motion.
- typography_annotation: judge complete semantic units, source-anchored labels, readable scale,
  and enough settled reading time. Enlarged fragments, overlap, and soft source pixels are defects.
- audio: assess narration/action alignment, speech masking, cue timing, and abrupt tails only if
  audio is available. Silence and restrained cues are valid production choices.

Distinguish a source-capture limit from an editing or renderer defect. Each correction must name
its layer and change_class: recut, recapture, renderer_change, narration_change, product_change,
or claim_change. Give the smallest concrete correction and the expected viewer benefit. Do not
recommend faster cuts, extra effects, or permanent motion without explaining what they improve.
Returning to an advancing product state is not automatically repetition. A useful settled hold
is not dead air. Do not reward recreated proof merely because its typography is sharp.

Scores are optional guidance for human comparison, never an aesthetic shipping gate or proof of
engagement/studio quality. Empty temporal_findings is valid; never fill a defect quota.
ALL score fields, including overall and every entry in scores, use integer values from 0 to 100.
Do not use a 0-10 scale: write 60 for sixty out of one hundred, not 6. Report each score directly;
do not rescale or silently normalize scores to reconcile their values.
Return STRICT JSON only, using numeric seconds relative to the supplied video's beginning:
{
  "overall": <0-100 integer, advisory>,
  "scores": {"motion_design":int,"temporal_continuity":int,"reading_holds":int,"source_fidelity":int,"polish":int},
  "sequence_summary": "the experienced progression and attention transfer across the whole film",
  "temporal_findings": [{"start_sec":number,"end_sec":number,
    "layer":"camera|source_playback|edit|transition_mask|typography_annotation|audio",
    "severity":"major|minor","confidence":"high|medium|low",
    "observation":"what visibly/audibly happens across this interval",
    "viewer_effect":"why it harms comprehension or finish",
    "correction":{"change_class":"recut|recapture|renderer_change|narration_change|product_change|claim_change","action":"specific correction in the named layer"}}],
  "unverified": ["what sampling, source resolution, or unavailable audio prevents you from judging"],
  "specific_upgrades": [{"area":"production layer","change_class":"correction class","change":"concrete fix"}],
  "would_keep_watching": <true|false>,
  "one_line_verdict": "the strongest production conclusion supported by this viewing"
}"""

MOTION_LAYERS = {"camera", "source_playback", "edit", "transition_mask", "typography_annotation", "audio"}
CHANGE_CLASSES = {"recut", "recapture", "renderer_change", "narration_change", "product_change", "claim_change"}


def validate_sampling(fps, runs):
    if (isinstance(fps, bool) or not isinstance(fps, (int, float))
            or not math.isfinite(fps) or not 0 < fps <= 24):
        raise ValueError("judge fps must be a finite number greater than 0 and at most 24; no silent resampling")
    if isinstance(runs, bool) or not isinstance(runs, int) or runs < 1:
        raise ValueError("judge runs must be a positive integer")


def validate_motion_review(data, duration=None):
    """Reject unusable temporal instructions; do not turn taste into a pass/fail score."""
    validate_review_scores(data)
    if (isinstance(data.get("overall"), bool) or not isinstance(data.get("overall"), (int, float))
            or not math.isfinite(data["overall"]) or not 0 <= data["overall"] <= 100):
        raise ValueError("motion overall must be an advisory score between 0 and 100")
    if not isinstance(data.get("sequence_summary"), str) or not data["sequence_summary"].strip():
        raise ValueError("motion review must describe the complete sequence")
    if not isinstance(data.get("unverified"), list) or any(not isinstance(x, str) for x in data["unverified"]):
        raise ValueError("motion review must report unverified observations as a list")
    findings = data.get("temporal_findings")
    if not isinstance(findings, list):
        raise ValueError("motion review needs a temporal_findings list")
    for finding in findings:
        if not isinstance(finding, dict):
            raise ValueError("motion findings must be objects")
        start, end = finding.get("start_sec"), finding.get("end_sec")
        if (any(isinstance(x, bool) or not isinstance(x, (int, float)) or not math.isfinite(x) for x in (start, end))
                or not 0 <= start <= end or (duration is not None and end > duration + 1e-6)):
            raise ValueError("motion finding timestamps must be ordered and inside the supplied video")
        if (finding.get("layer") not in MOTION_LAYERS or finding.get("severity") not in {"major", "minor"}
                or finding.get("confidence") not in {"high", "medium", "low"}):
            raise ValueError("motion finding layer, severity, or confidence is invalid")
        if any(not isinstance(finding.get(key), str) or not finding[key].strip()
               for key in ("observation", "viewer_effect")):
            raise ValueError("motion findings need observed evidence and a viewer effect")
        correction = finding.get("correction")
        if (not isinstance(correction, dict) or correction.get("change_class") not in CHANGE_CLASSES
                or not isinstance(correction.get("action"), str) or not correction["action"].strip()):
            raise ValueError("motion findings need a layer-specific correction")
    findings.sort(key=lambda finding: (finding["start_sec"], finding["end_sec"]))
    data["overall_model"] = data["overall"]
    data["structural_penalties"] = []
    data["score_policy"] = "advisory motion assessment; no structural score calibration or shipping gate"
    return data


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


def validate_review_scores(data):
    if not isinstance(data, dict) or not isinstance(data.get("scores"), dict) or not data["scores"]:
        raise ValueError("judge response must contain a non-empty scores object")
    s = data["scores"]
    for key, value in s.items():
        if (isinstance(value, bool) or not isinstance(value, (int, float))
                or not math.isfinite(value) or not 0 <= value <= 100):
            raise ValueError(f"judge score {key} must be a finite number between 0 and 100")
    for key in ("repeated_elements", "dead_seconds"):
        if key in data and not isinstance(data[key], list):
            raise ValueError(f"judge {key} must be a list")
    if "would_keep_watching" in data and not isinstance(data["would_keep_watching"], bool):
        raise ValueError("judge would_keep_watching must be a boolean")


def calibrate(data, props_path):
    """Retain legacy profile-aware score calibration for the existing review lenses."""
    validate_review_scores(data)
    s = data["scores"]
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
    data["overall"] = min(100, max(5, overall))
    data["structural_penalties"] = snotes
    return data


@contextmanager
def uploaded_video(client, video):
    """Keep remote review media only for the lifetime of the review, including failed runs."""
    uploaded = client.files.upload(file=video)
    try:
        for _ in range(60):
            current = client.files.get(name=uploaded.name)
            state = getattr(current.state, "name", str(current.state))
            if state == "ACTIVE":
                yield current
                return
            if state == "FAILED":
                raise RuntimeError("file processing FAILED")
            time.sleep(3)
        raise TimeoutError("uploaded video was not ACTIVE after 180 seconds")
    finally:
        try:
            client.files.delete(name=uploaded.name)
        except Exception as exc:
            # Cleanup failures must not replace the useful scoring/processing exception.
            print(f"WARNING: could not delete uploaded review video {uploaded.name}: {exc}", file=sys.stderr)


def _provider_usage(response):
    usage = getattr(response, "usage_metadata", None)
    if usage is None:
        return None
    try:
        if callable(getattr(usage, "model_dump", None)):
            usage = usage.model_dump(mode="json", exclude_none=True)
        elif not isinstance(usage, dict):
            usage = vars(usage)
        # Preserve the provider's field names, including modality token counts.
        return json.loads(json.dumps(usage, allow_nan=False))
    except (TypeError, ValueError):
        return None  # Unavailable metadata is never represented as zero usage.


def _props_hash(path):
    if not path or not os.path.isfile(path):
        return None
    with open(path) as source:
        return hashlib.sha256(json.dumps(json.load(source), sort_keys=True, separators=(",", ":")).encode()).hexdigest()


def judge_video(client, video, context, props, fps, model, runs, lenses=None, *, artifact=None):
    """Upload once, judge `runs` times, return the run whose calibrated overall is the median
    (with all runs' overalls recorded). Median-of-N because same-cut variance is documented
    at ~27 points on a single run."""
    validate_sampling(fps, runs)
    if any(lens not in LENS_RULES for lens in (lenses or ["overall"])):
        raise ValueError("unknown review lens")
    video_hash = sha256_file(video)
    props_hash = _props_hash(props)
    if artifact and (artifact.get("sha256") != video_hash
                     or artifact.get("propsSha256") not in (None, props_hash)):
        raise RuntimeError("artifact changed before review upload")
    duration = media_duration(video)
    receipt = {"schemaVersion": 1, "advisory": True, "provider": "google",
               "modelRequested": model, "requestedFps": fps, "effectiveFps": fps,
               "effectiveFpsMeaning": "video_metadata.fps submitted to the provider",
               "providerObservedFps": None,
               "artifact": {"videoPath": os.path.abspath(video), "sha256": video_hash,
                            "bytes": os.path.getsize(video), "durationSec": duration,
                            "manifestVerified": bool(artifact),
                            "manifestPath": artifact.get("path") if artifact else None,
                            "buildId": artifact.get("buildId") if artifact else None,
                            "propsSha256": props_hash},
               "lensesRequested": list(lenses or ["overall"]), "runsPerLensRequested": runs,
               "reviewerCodeSha256": sha256_file(__file__),
               "startedAt": datetime.now(timezone.utc).isoformat(), "attempts": []}
    try:
        with uploaded_video(client, video) as uploaded:
            if sha256_file(video) != video_hash:
                raise RuntimeError("video changed during review upload")
            result = _judge_uploaded(client, uploaded, context, props, fps, model, runs, lenses,
                                     duration=duration, attempts=receipt["attempts"])
        if sha256_file(video) != video_hash or _props_hash(props) != props_hash:
            raise RuntimeError("video or props changed during review; discard this assessment")
    except Exception as exc:
        receipt["completedAt"] = datetime.now(timezone.utc).isoformat()
        receipt["status"] = "failed"
        exc.review_receipt = receipt
        raise
    receipt["completedAt"] = datetime.now(timezone.utc).isoformat()
    receipt["status"] = result["review_status"]
    result["review_receipt"] = receipt
    return result


def _judge_uploaded(client, f, context, props, fps, model, runs, lenses, *, duration=None, attempts=None):
    from google.genai import types

    profile = None
    if props and os.path.exists(props):
        with open(props) as fh:
            profile = (json.load(fh) or {}).get("profile")
    rubric = LIVE_RUBRIC if profile in LIVE_PROFILES else RUBRIC
    part_video = types.Part(
        file_data=types.FileData(file_uri=f.uri, mime_type=f.mime_type),
        video_metadata=types.VideoMetadata(fps=fps),
    )
    selected = lenses or ["overall"]
    lens_results: dict[str, dict] = {}
    for lens in selected:
        prompt = ((MOTION_RUBRIC if lens == "motion" else rubric) + "\n\nREVIEW LENS: " + LENS_RULES[lens]
                  + f"\n\nVIDEO SUBMISSION: complete video with its audio; requested sampling {fps:g} fps "
                    f"(nominal interval {1 / fps:.6f} seconds). Provider frame selection is not independently verified."
                  + (f" Measured video duration: {duration:.6f} seconds; do not cite times outside it." if duration is not None else
                     " Duration could not be independently probed; mark time coverage uncertain.")
                  + (("\n\nWHAT THIS DEMO IS: " + context) if context else ""))
        results, errors = [], []
        for i in range(runs):
            attempt = {"lens": lens, "run": i + 1, "modelRequested": model,
                       "promptSha256": hashlib.sha256(prompt.encode()).hexdigest(),
                       "modelReturned": None, "responseId": None, "providerUsage": None}
            if attempts is not None:
                attempts.append(attempt)
            try:
                resp = client.models.generate_content(
                    model=model,
                    contents=types.Content(parts=[part_video, types.Part(text=prompt)]),
                    config=_judge_config(types, model),
                )
                attempt["modelReturned"] = getattr(resp, "model_version", None)
                attempt["responseId"] = getattr(resp, "response_id", None)
                attempt["providerUsage"] = _provider_usage(resp)
                attempt["status"] = "invalid_response"
                m = re.search(r"\{.*\}", resp.text, re.S)
                result = json.loads(m.group(0) if m else resp.text)
                results.append(validate_motion_review(result, duration) if lens == "motion" else calibrate(result, props))
                attempt["status"] = "complete"
            except Exception as exc:
                attempt.setdefault("status", "provider_error")
                attempt["error"] = str(exc)
                errors.append(f"{model} lens={lens} run {i + 1}: {exc}")
        if not results:
            raise RuntimeError(errors[-1])
        results.sort(key=lambda item: item["overall"])
        # For an even number of valid runs use the lower middle observation; selecting the
        # upper one systematically inflates scores, especially when a requested run failed.
        median = results[(len(results) - 1) // 2]
        median["runs_overall"] = [item["overall"] for item in results]
        median["runs_requested"] = runs
        median["runs_completed"] = len(results)
        median["review_status"] = "partial" if errors else "complete"
        if errors:
            median["run_errors"] = errors
        median["_lens"] = lens
        median["_model"] = model
        median["_fps"] = fps
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
        "review_status": "partial" if any(item["review_status"] == "partial"
                                            for item in lens_results.values()) else "complete",
        "_model": model,
        "_fps": fps,
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


def verify_artifact(video, artifact_arg="", required=False, props_arg=""):
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
    expected_props = data.get("propsSha256")
    if expected_props:
        props_path = find_props(video, props_arg)
        if not props_path or not os.path.isfile(props_path):
            raise RuntimeError("artifact-bound props are missing; cannot verify review profile or timeline")
        with open(props_path) as fh:
            props = json.load(fh)
        actual_props = hashlib.sha256(json.dumps(
            props, sort_keys=True, separators=(",", ":")).encode()).hexdigest()
        if actual_props.lower() != str(expected_props).lower():
            raise RuntimeError("artifact props hash mismatch; review profile or timeline is stale")
    return {"path": os.path.abspath(path), "buildId": data.get("buildId"), "sha256": actual,
            "propsSha256": expected_props}


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


def _judge_config(types, model):
    """Gemini 3.x: high thinking level at default temperature; older models: temperature 0."""
    if model.startswith("gemini-3"):
        return types.GenerateContentConfig(response_mime_type="application/json",
                                           thinking_config=types.ThinkingConfig(thinking_level="high"))
    return types.GenerateContentConfig(response_mime_type="application/json", temperature=0.0)


HERE = os.path.dirname(os.path.abspath(__file__))
# pinned: a floating alias ("gemini-pro-latest") makes scores drift across sessions.
# Gemini 3.x reasons with thinking_level; Google advises leaving temperature at its default.
DEFAULT_MODEL = "gemini-3.1-pro-preview"


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--video", help="rendered cut to judge")
    ap.add_argument("--context", default="", help="optional one-line note about what the demo is")
    ap.add_argument("--props", default="", help="timeline props.json for deterministic pace/repetition scoring (default: props.json next to the video)")
    ap.add_argument("--fps", type=float, default=4.0,
                    help="submitted video sampling rate, greater than 0 and at most 24; never silently clamped")
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
    try:
        validate_sampling(args.fps, args.runs)
    except ValueError as exc:
        ap.error(str(exc))

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
        artifact = verify_artifact(args.video, args.artifact, args.require_artifact, args.props)
        lenses = ["story", "truth", "visual", "buyer"] if args.all_lenses else [args.lens]
        data = judge_video(client, args.video, args.context, find_props(args.video, args.props),
                           args.fps, args.model, args.runs, lenses=lenses, artifact=artifact)
        data["_artifact"] = artifact
    except Exception as e:
        failure = {"error": str(e)}
        if getattr(e, "review_receipt", None):
            failure["review_receipt"] = e.review_receipt
        print(json.dumps(failure))
        if args.out:
            os.makedirs(os.path.dirname(args.out) or ".", exist_ok=True)
            with open(args.out, "w") as fh:
                json.dump(failure, fh, indent=2)
                fh.write("\n")
        sys.exit(1)
    out = json.dumps(data, indent=2)
    print(out)
    if args.out:
        os.makedirs(os.path.dirname(args.out) or ".", exist_ok=True)
        with open(args.out, "w") as fh:
            fh.write(out + "\n")


if __name__ == "__main__":
    main()
