"""Compile a coherent motion treatment from editorial intent, without changing the story.

This module is pure: no model calls, asset writes, or invented product coordinates.
Authored paths win. Dense product work and human framing stay still unless directed.
"""

from __future__ import annotations

import copy
import math

try:
    from .framing import MAX_CAMERA_SCALE, compile_framing, validate_framing
except ImportError:
    from framing import MAX_CAMERA_SCALE, compile_framing, validate_framing

INTENTS = {"establish", "demonstrate", "focus", "payoff", "resolve"}
TONES = {"precise", "editorial", "energetic"}
EASES = {"smooth", "drive", "settle", "linear"}
TRANSITIONS = {"cut", "xfade", "reveal", "push"}
SOUNDS = {"studio_air", "studio_tick", "studio_resolve", "click", "data_tick", "success_chime",
          "confirm_cash", "pivot_boom", "impact", "riser", "whoosh"}
KINDS = {"clip", "split", "title", "stat", "cta", "score", "strip", "bars"}


def is_number(value):
    try:
        return type(value) in (int, float) and math.isfinite(value)
    except OverflowError:
        return False


def source_rectangle(value):
    """Return a valid source-percent rectangle, allowing only floating-point edge noise."""
    if not isinstance(value, dict) or any(not is_number(value.get(k)) for k in ("x", "y", "width", "height")):
        return None
    if any(value[size] <= 0 or value[pos] < -1e-9 or value[pos] + value[size] > 100 + 1e-9
           for pos, size in (("x", "width"), ("y", "height"))):
        return None
    return {key: float(value[key]) for key in ("x", "y", "width", "height")}


def rectangle_contains(outer, inner):
    return all(outer[pos] - 1e-9 <= inner[pos]
               and inner[pos] + inner[size] <= outer[pos] + outer[size] + 1e-9
               for pos, size in (("x", "width"), ("y", "height")))


def _framing_locks(production):
    """A source identity lock may explicitly allow reframing; only framing locks freeze it."""
    locks = set()
    for lock in production.get("sourceLocks", []) or []:
        if isinstance(lock, str):
            locks.add(lock)
        elif isinstance(lock, dict) and isinstance(lock.get("src"), str) and lock.get("preserveFraming", True):
            locks.add(lock["src"])
    return locks


def _has_legacy_framing(shot):
    return bool(shot.get("zooms")) or any(key in shot for key in ("clickAtSec", "clickX", "clickY")) or any(
        key in shot and shot[key] != neutral for key, neutral in (
            ("scale", 1), ("startScale", 1), ("endScale", 1), ("panX", 0), ("panY", 0),
            ("focusX", 50), ("focusY", 50)))


def validate_direction(script):
    findings = []

    def error(code, message, shot=None):
        item = {"severity": "error", "code": code, "message": message}
        if shot is not None:
            item["shot"] = shot
        findings.append(item)

    if not isinstance(script, dict):
        error("DIRECTION_INVALID", "script must be an object")
        return findings
    fps = script.get("fps", 30)
    if not is_number(fps) or fps <= 0:
        error("FPS_INVALID", "fps must be a finite positive number")
    shots = script.get("shots", [])
    if not isinstance(shots, list):
        error("SHOTS_MISSING", "shots must be an array")
        shots = []
    production = script.get("production") if isinstance(script.get("production"), dict) else {}
    source_locks = production.get("sourceLocks", [])
    if source_locks is not None and (not isinstance(source_locks, list) or any(
            not isinstance(lock, (str, dict)) or (isinstance(lock, dict) and (
                not isinstance(lock.get("src"), str) or not lock["src"]
                or ("preserveFraming" in lock and not isinstance(lock["preserveFraming"], bool))))
            for lock in source_locks)):
        error("SOURCE_LOCK_INVALID", "sourceLocks must be source names or objects with a src and optional boolean preserveFraming")
        locks = set()
    else:
        locks = _framing_locks(production)
    max_scale = production.get("maxZoomScale", 2.25)
    if not is_number(max_scale) or max_scale < 1:
        error("CAMERA_SCALE_INVALID", "production.maxZoomScale must be a finite number of at least 1")
        max_scale = 2.25
    max_scale = min(MAX_CAMERA_SCALE, max_scale)
    creative = script.get("creativeDirection", {})
    if not isinstance(creative, dict):
        error("DIRECTION_INVALID", "creativeDirection must be an object")
        creative = {}
    for key, values in (("style", {"studio", "classic"}), ("tone", TONES),
                        ("soundDesign", {"sparse", "silent"})):
        if key in creative and (not isinstance(creative[key], str) or creative[key] not in values):
            error("DIRECTION_INVALID", f"creativeDirection.{key} must be one of {', '.join(sorted(values))}")
    for shot in shots:
        if not isinstance(shot, dict):
            error("SHOT_INVALID", "Every shot must be an object")
            continue
        n, duration = shot.get("n"), shot.get("durSec", 2.5)
        if not is_number(duration) or duration <= 0:
            error("SHOT_DURATION_INVALID", "durSec must be a finite positive number", n)
            continue
        if is_number(fps) and fps > 0 and not is_number(duration * fps):
            error("SHOT_DURATION_INVALID", "Shot frame count must be finite", n)
        kind = shot.get("kind", "clip")
        if not isinstance(kind, str) or kind not in KINDS:
            error("SHOT_KIND_INVALID", "Unknown shot kind", n)
        if creative.get("style") == "studio" and kind in ("score", "bars"):
            score_max = shot.get("scoreMax", 100)
            if not is_number(score_max) or score_max <= 0:
                error("SCORE_MAX_INVALID", "scoreMax must be a finite positive number", n)
                score_max = None
            if kind == "score":
                score = shot.get("score")
                if not is_number(score) or score < 0 or (score_max is not None and score > score_max):
                    error("SCORE_INVALID", "Studio score shots require an explicit finite score between 0 and scoreMax", n)
            else:
                takes = shot.get("takes")
                if not isinstance(takes, list) or not takes or any(
                        not is_number(value) or value < 0 or (score_max is not None and value > score_max)
                        for value in takes):
                    error("TAKES_INVALID", "Studio bars require explicit nonempty takes with finite scores between 0 and scoreMax", n)
            if "passLine" in shot:
                pass_line = shot["passLine"]
                if not is_number(pass_line) or pass_line < 0 or (score_max is not None and pass_line > score_max):
                    error("PASS_LINE_INVALID", "passLine must be finite and between 0 and scoreMax", n)
        direction = shot.get("direction", {})
        if not isinstance(direction, dict):
            error("DIRECTION_INVALID", "shot.direction must be an object", n)
            direction = {}
        if "intent" in direction and (not isinstance(direction["intent"], str) or direction["intent"] not in INTENTS):
            error("DIRECTION_INVALID", "Unknown motion intent", n)
        if "layout" in direction and (not isinstance(direction["layout"], str) or direction["layout"] not in {"fullbleed", "stage"}):
            error("DIRECTION_INVALID", "layout must be fullbleed or stage", n)
        if "align" in direction and (not isinstance(direction["align"], str) or direction["align"] not in {"left", "center"}):
            error("DIRECTION_INVALID", "direction.align must be left or center", n)
        if "energy" in direction and (not is_number(direction["energy"]) or not 0 <= direction["energy"] <= 1):
            error("DIRECTION_INVALID", "energy must be finite and between 0 and 1", n)
        if "focus" in direction:
            focus = direction["focus"]
            if not isinstance(focus, dict) or any(not is_number(focus.get(k)) or not 0 <= focus[k] <= 100 for k in ("x", "y")):
                error("DIRECTION_INVALID", "direction.focus needs source-grounded x and y percentages", n)
        if "transition" in shot and (not isinstance(shot["transition"], str) or shot["transition"] not in TRANSITIONS):
            error("TRANSITION_INVALID", "Unknown transition; use cut, xfade, reveal, or push", n)
        if "transitionSec" in shot and (not is_number(shot["transitionSec"]) or not 0 < shot["transitionSec"] <= 1.2):
            error("TRANSITION_INVALID", "transitionSec must be positive and at most 1.2 seconds", n)
        if "captionFontSize" in shot and (not is_number(shot["captionFontSize"]) or not 16 <= shot["captionFontSize"] <= 160):
            error("CAPTION_SIZE_INVALID", "captionFontSize must be a finite composition-pixel size between 16 and 160", n)
        if "titleLines" in shot:
            lines = shot["titleLines"]
            if not isinstance(lines, list) or not 1 <= len(lines) <= 5 or any(not isinstance(line, str) or not line.strip() for line in lines):
                error("TITLE_LINES_INVALID", "titleLines must contain 1–5 nonempty strings", n)
            elif " ".join(" ".join(lines).split()) != " ".join(str(shot.get("title", "")).split()):
                error("TITLE_TEXT_CHANGED", "titleLines must preserve the complete title in order", n)
        if "emphasis" in shot and (not isinstance(shot["emphasis"], str) or not shot["emphasis"].strip()
                                   or shot["emphasis"] not in str(shot.get("title", ""))):
            error("EMPHASIS_INVALID", "emphasis must quote an exact phrase from the title", n)
        camera = shot.get("camera", [])
        if not isinstance(camera, list):
            error("CAMERA_INVALID", "camera must be an array of keyframes", n)
            camera = []
        if camera and shot.get("zooms"):
            error("CAMERA_CONFLICT", "Use camera keyframes or legacy zooms, never both", n)
        legacy_framing = {"scale", "startScale", "endScale", "focusX", "focusY", "panX", "panY",
                          "clickX", "clickY", "clickAtSec"}.intersection(shot)
        findings.extend(validate_framing(shot))
        if "sourceWindow" in shot:
            window = source_rectangle(shot["sourceWindow"])
            if window is None:
                error("SOURCE_WINDOW_INVALID", "sourceWindow must be a positive source-percent rectangle wholly inside the source", n)
            if kind != "clip":
                error("SOURCE_WINDOW_INVALID", "sourceWindow applies only to source clips", n)
            if shot.get("sourceType") == "human":
                error("SOURCE_WINDOW_HUMAN_FORBIDDEN", "Human footage cannot use a sourceWindow isolation mask", n)
            if shot.get("preserveFraming") or (isinstance(shot.get("src"), str) and shot["src"] in locks):
                error("SOURCE_FRAMING_CHANGED", "Source-locked footage cannot use a sourceWindow isolation mask", n)
            framing = shot.get("framing")
            if shot.get("sourceDetail") or (isinstance(framing, dict) and framing.get("presentation") == "detail"):
                error("SOURCE_WINDOW_CONFLICT", "Detail plates already isolate their complete source region; do not combine with sourceWindow", n)
            if window:
                beats = framing.get("beats", []) if isinstance(framing, dict) else []
                annotations = shot.get("annotations", [])
                targets = [beat.get("rect") for beat in beats if isinstance(beat, dict)] if isinstance(beats, list) else []
                targets.extend(annotations if isinstance(annotations, list) else [])
                if any(source_rectangle(target) and not rectangle_contains(window, source_rectangle(target))
                       for target in targets):
                    error("SOURCE_WINDOW_TARGET_CROP", "sourceWindow must contain every complete framing and annotation target", n)
        if "framing" in shot and (camera or shot.get("zooms") or legacy_framing):
            error("CAMERA_CONFLICT", "Use measured framing or authored camera/legacy framing, never both", n)
        if "framing" in shot and (shot.get("preserveFraming") or (isinstance(shot.get("src"), str) and shot["src"] in locks)):
            error("SOURCE_FRAMING_CHANGED", "Source-locked footage cannot use measured framing", n)
        if camera and legacy_framing:
            error("CAMERA_CONFLICT", "Camera paths cannot also use legacy framing fields: " + ", ".join(sorted(legacy_framing)), n)
        if camera and (shot.get("preserveFraming") or (isinstance(shot.get("src"), str) and shot["src"] in locks)):
            error("SOURCE_FRAMING_CHANGED", "Source-locked footage cannot use an authored camera path", n)
        if camera and kind != "clip":
            error("CAMERA_INVALID", "Camera paths apply to clip shots", n)
        previous = -1.0
        for point in camera:
            if not isinstance(point, dict):
                error("CAMERA_INVALID", "Every camera keyframe must be an object", n)
                continue
            at = point.get("atSec")
            if not is_number(at) or not 0 <= at <= duration or at <= previous:
                error("CAMERA_TIMING_INVALID", "Camera times must increase strictly inside the shot", n)
            else:
                previous = at
            scale = point.get("scale", 1)
            if not is_number(scale) or not 1 <= scale <= max_scale:
                error("CAMERA_SCALE_INVALID", f"Camera scale must be finite and between 1 and {max_scale:g}", n)
            for axis in ("focusX", "focusY"):
                value = point.get(axis, 50)
                if not is_number(value) or not 0 <= value <= 100:
                    error("CAMERA_FOCUS_INVALID", f"{axis} must be a source percentage between 0 and 100", n)
            if not isinstance(point.get("ease", "smooth"), str) or point.get("ease", "smooth") not in EASES:
                error("CAMERA_EASE_INVALID", "Unknown camera easing", n)
        for key in ("annotations", "soundCues"):
            items = shot.get(key, [])
            if not isinstance(items, list):
                error("DIRECTION_INVALID", f"{key} must be an array", n)
                continue
            for item in items:
                if not isinstance(item, dict):
                    error("DIRECTION_INVALID", f"Each {key} entry must be an object", n)
                    continue
                start = item.get("atSec")
                if not is_number(start) or not 0 <= start < duration:
                    error("DIRECTION_TIMING_INVALID", f"{key}.atSec must fall within the shot", n)
                if key == "soundCues":
                    if not isinstance(item.get("sound"), str) or item.get("sound") not in SOUNDS:
                        error("SOUND_CUE_INVALID", "Unknown sound cue", n)
                    volume = item.get("volume", 0.25)
                    if not is_number(volume) or not 0 <= volume <= 1:
                        error("SOUND_CUE_INVALID", "Cue volume must be between 0 and 1", n)
                    continue
                end = item.get("endSec")
                if not is_number(end) or not is_number(start) or not start < end <= duration:
                    error("ANNOTATION_TIMING_INVALID", "Annotation endSec must follow atSec and stay within the shot", n)
                if kind != "clip":
                    error("ANNOTATION_INVALID", "Annotations belong on source clips", n)
                for pos, size in (("x", "width"), ("y", "height")):
                    a, b = item.get(pos), item.get(size)
                    if not is_number(a) or not is_number(b) or a < 0 or b <= 0 or a + b > 100:
                        error("ANNOTATION_BOUNDS_INVALID", "Annotation rectangle must fit within the source frame", n)
                if not isinstance(item.get("kind", "box"), str) or item.get("kind", "box") not in {"box", "spotlight"}:
                    error("ANNOTATION_INVALID", "Annotation kind must be box or spotlight", n)
                if "label" in item and (not isinstance(item["label"], str) or len(item["label"]) > 90):
                    error("ANNOTATION_INVALID", "Annotation label must be a short source-grounded string", n)
    return findings


def compile_direction(script):
    """Resolve deliberate defaults after narration pacing; never rewrite claims or time."""
    findings = validate_direction(script)
    if findings:
        raise ValueError("; ".join(f"{item['code']}: {item['message']}" for item in findings))
    creative = script.get("creativeDirection") or {}
    style = creative.get("style", "classic")
    tone = creative.get("tone", "precise")
    sound = creative.get("soundDesign", "sparse")
    default_energy = {"precise": 0.35, "editorial": 0.5, "energetic": 0.7}[tone]
    rows, previous = [], None
    production = script.get("production") if isinstance(script.get("production"), dict) else {}
    locks = _framing_locks(production)
    max_scale = min(MAX_CAMERA_SCALE, production.get("maxZoomScale", 2.25))
    fps = float(script.get("fps", 30))
    for shot in script.get("shots", []):
        if not isinstance(shot, dict):
            continue
        kind, duration = shot.get("kind", "clip"), float(shot.get("durSec", 2.5))
        direction = copy.deepcopy(shot.get("direction") or {})
        default_intent = "resolve" if kind == "cta" else "payoff" if kind in {"stat", "score", "bars"} else "demonstrate" if kind == "clip" else "establish"
        intent = direction.setdefault("intent", default_intent)
        locked = bool(shot.get("preserveFraming") or (isinstance(shot.get("src"), str) and shot["src"] in locks))
        human = shot.get("sourceType") == "human"
        layout = "stage" if style == "studio" and kind == "clip" and intent == "establish" and not (locked or human) else "fullbleed"
        direction.setdefault("layout", layout)
        direction.setdefault("energy", default_energy)
        if locked:
            direction["layout"] = "fullbleed"
        if "framing" in shot:
            direction["layout"] = "fullbleed"
        default_transition = "cut"
        if previous:
            if style == "studio":
                if previous.get("kind", "clip") in {"title", "stat"} and kind == "clip":
                    default_transition = "reveal"
            elif not (shot.get("flash") or (kind == previous.get("kind", "clip") == "clip"
                      and shot.get("src") and shot.get("src") == previous.get("src"))):
                default_transition = "xfade"
        transition = shot.get("transition") or default_transition
        default_transition_sec = 0.3 if style == "classic" else 0.55 if tone != "energetic" else 0.4
        transition_sec = min(float(shot.get("transitionSec", default_transition_sec)), max(0.0, duration - 1 / fps))
        camera = copy.deepcopy(shot.get("camera") or [])
        framing_report = None
        if "framing" in shot:
            camera, framing_report = compile_framing(shot, production)
        focus = direction.get("focus")
        # We can direct toward an authored target, but never guess the location of product proof.
        if style == "studio" and not (locked or human) and not camera and "framing" not in shot and not _has_legacy_framing(shot) and kind == "clip" and intent == "focus" and focus:
            last_picture_sec = max(0, math.floor(duration * fps + 0.5) - 1) / fps
            arrival = min(1.25, duration * 0.28, last_picture_sec)
            if arrival > 0 and max_scale > 1:
                camera = [{"atSec": 0, "scale": 1, "focusX": 50, "focusY": 50},
                          {"atSec": arrival, "scale": min(max_scale, round(1.2 + direction["energy"] * 0.35, 3)),
                           "focusX": focus["x"], "focusY": focus["y"], "ease": "smooth"}]
        if locked:
            camera = []
        cues = copy.deepcopy(shot.get("soundCues") or [])
        if sound == "silent":
            cues = []
        elif style == "studio" and "soundCues" not in shot and not shot.get("accent"):
            if transition in {"reveal", "push"} and previous:
                cues = [{"atSec": 0, "sound": "studio_air", "volume": 0.24}]
            elif kind == "cta":
                cues = [{"atSec": min(0.42, duration * 0.2), "sound": "studio_resolve", "volume": 0.17}]
        row = {"n": shot.get("n"), "studio": style == "studio", "direction": direction,
               "camera": camera, "transition": transition, "transitionSec": transition_sec,
               "soundCues": cues}
        if "sourceWindow" in shot:
            row["sourceWindow"] = copy.deepcopy(shot["sourceWindow"])
        if framing_report is not None:
            row["framingReport"] = framing_report
            if "sourceDetail" in framing_report:
                row["sourceDetail"] = copy.deepcopy(framing_report["sourceDetail"])
        rows.append(row)
        previous = shot
    return {"schemaVersion": 1, "style": style, "tone": tone, "soundDesign": sound, "shots": rows}
