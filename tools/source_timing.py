"""Explicit, chronological source playback maps for directed product footage.

Source times refer to the normalized video file, never the browser's wall clock.
Spans may preserve real time, compress declared navigation, or hold an existing
frame for reading. They cannot skip, reverse, or manufacture a product action.
"""

from __future__ import annotations

import math


EPSILON = 1e-6
DEFAULT_NAVIGATION_RATE = 2.0
MAX_NAVIGATION_RATE = 4.0
MODES = {"realtime", "navigation", "hold"}


def _finite(value):
    try:
        return type(value) in (int, float) and math.isfinite(value)
    except OverflowError:
        return False


def _round_frames(seconds, fps):
    return math.floor(seconds * fps + 0.5)


def _finding(code, message, shot=None):
    result = {"severity": "error", "code": code, "message": message}
    if shot is not None:
        result["shot"] = shot
    return result


def _inspect(shot, fps, max_rate):
    """Return normalized span values plus all independently actionable findings."""
    findings = []
    number = shot.get("n")

    def error(code, message):
        findings.append(_finding(code, message, number))

    raw = shot.get("sourceTimeline")
    if not isinstance(raw, list) or not raw:
        error("SOURCE_TIMELINE_INVALID", "sourceTimeline must contain at least one span")
        return [], findings
    if shot.get("kind", "clip") != "clip":
        error("SOURCE_TIMELINE_INVALID", "sourceTimeline applies only to source clips")
    duration = shot.get("durSec", 2.5)
    if not _finite(duration) or duration <= 0 or not _finite(duration * fps):
        error("SOURCE_TIMELINE_DURATION", "Shot duration and frame count must be finite and positive")
        return [], findings
    if "inSec" in shot and (not _finite(shot["inSec"]) or shot["inSec"] < 0):
        error("SOURCE_TIMELINE_START", "inSec must be a finite nonnegative source time")
    protected = (shot.get("sourceType") == "human" or bool(shot.get("sound"))
                 or (shot.get("actor") == "human" and shot.get("actionRisk") == "consequential"))
    spans, previous_end = [], None
    for index, span in enumerate(raw):
        label = f"sourceTimeline[{index}]"
        if not isinstance(span, dict):
            error("SOURCE_TIMELINE_INVALID", f"{label} must be an object")
            continue
        start, end, span_duration = (span.get(key) for key in ("fromSec", "toSec", "durSec"))
        mode = span.get("mode", "realtime")
        if not isinstance(mode, str) or mode not in MODES:
            error("SOURCE_TIMELINE_INVALID", f"{label}.mode must be realtime, navigation, or hold")
            continue
        if (not _finite(start) or not _finite(end) or start < 0 or end < start
                or not _finite(span_duration) or span_duration <= 0
                or not _finite(span_duration * fps)):
            error("SOURCE_TIMELINE_INVALID", f"{label} needs finite nonnegative source times in order and a positive duration")
            continue
        start, end, span_duration = float(start), float(end), float(span_duration)
        distance = end - start
        if index == 0 and _finite(shot.get("inSec")) and abs(start - shot["inSec"]) > EPSILON:
            error("SOURCE_TIMELINE_START", "First sourceTimeline.fromSec must match inSec")
        if previous_end is not None and abs(start - previous_end) > EPSILON:
            error("SOURCE_TIMELINE_DISCONTINUITY", f"{label} must begin where the previous span ends; source gaps and reversals are forbidden")
        previous_end = end
        if mode == "hold":
            if start != end:
                error("SOURCE_TIMELINE_RATE", f"{label}: a hold must repeat exactly one source frame (fromSec equals toSec)")
        elif distance <= 0:
            error("SOURCE_TIMELINE_RATE", f"{label}: moving spans must advance the source")
        elif mode == "realtime" and abs(distance - span_duration) > 1 / fps + EPSILON:
            error("SOURCE_TIMELINE_RATE", f"{label}: realtime spans must play at 1x within one frame")
        elif mode == "navigation" and distance / span_duration > max_rate + EPSILON:
            error("SOURCE_TIMELINE_RATE", f"{label}: navigation rate cannot exceed {max_rate:g}x")
        if protected and mode != "realtime":
            error("SOURCE_TIMELINE_PROTECTED", "Human footage, native source audio, and consequential human actions require realtime playback")
        spans.append({"fromSec": start, "toSec": end, "durSec": span_duration, "mode": mode})

    if len(spans) == len(raw):
        try:
            total = math.fsum(span["durSec"] for span in spans)
        except OverflowError:
            total = float("inf")
        if not _finite(total) or abs(total - duration) > 1 / fps + EPSILON:
            error("SOURCE_TIMELINE_DURATION", "Source timeline durations must sum to shot durSec within one output frame")
        else:
            cursor, previous_frame = 0.0, 0
            total_frames = _round_frames(duration, fps)
            for index, span in enumerate(spans):
                cursor = math.fsum((cursor, span["durSec"]))
                frame_end = total_frames if index == len(spans) - 1 else _round_frames(cursor, fps)
                if frame_end <= previous_frame:
                    error("SOURCE_TIMELINE_FRAMES", f"sourceTimeline[{index}] has no picture frame after cumulative rounding")
                else:
                    rate = (span["toSec"] - span["fromSec"]) * fps / (frame_end - previous_frame)
                    if span["mode"] == "navigation" and rate > max_rate + EPSILON:
                        error("SOURCE_TIMELINE_RATE", f"sourceTimeline[{index}] exceeds the {max_rate:g}x navigation limit after frame rounding")
                    if protected and abs(rate - 1) > EPSILON:
                        error("SOURCE_TIMELINE_PROTECTED", f"sourceTimeline[{index}] would time-warp protected source after frame rounding; use frame-aligned realtime spans")
                previous_frame = frame_end
    return spans, findings


def validate_source_timing(script):
    """Validate declared playback maps, without reading files or changing the script.

    production.maxNavigationRate defaults to 2x and may explicitly rise to 4x.
    The production contract separately checks the final source endpoint against
    the probed media duration; this pure module does not guess asset availability.
    """
    if not isinstance(script, dict):
        return [_finding("SOURCE_TIMELINE_INVALID", "Script must be an object")]
    fps = script.get("fps", 30)
    if not _finite(fps) or fps <= 0:
        return [_finding("SOURCE_TIMELINE_INVALID", "fps must be a finite positive number")]
    production = script.get("production") if isinstance(script.get("production"), dict) else {}
    max_rate = production.get("maxNavigationRate", DEFAULT_NAVIGATION_RATE)
    if not _finite(max_rate) or not 1 <= max_rate <= MAX_NAVIGATION_RATE:
        return [_finding("SOURCE_TIMELINE_RATE", "production.maxNavigationRate must be finite and between 1 and 4")]
    shots = script.get("shots", [])
    if not isinstance(shots, list):
        return [_finding("SOURCE_TIMELINE_INVALID", "shots must be an array")]
    findings = []
    for shot in shots:
        if isinstance(shot, dict) and "sourceTimeline" in shot:
            findings.extend(_inspect(shot, float(fps), float(max_rate))[1])
    return findings


def compile_source_timeline(shot, fps):
    """Compile a validated shot into independently addressable output-frame spans.

    Interior boundaries round cumulative time half up; the last span ends at the
    exact canonical shot frame count. Playback rates use those allocated frames,
    preserving both source endpoints instead of accumulating per-span rounding
    drift. Policy validation must run with the script's maxNavigationRate first;
    this compiler enforces the absolute 4x navigation ceiling.
    """
    if not isinstance(shot, dict):
        raise ValueError("SOURCE_TIMELINE_INVALID: Shot must be an object")
    if "sourceTimeline" not in shot:
        return []
    if not _finite(fps) or fps <= 0:
        raise ValueError("SOURCE_TIMELINE_INVALID: fps must be a finite positive number")
    spans, findings = _inspect(shot, float(fps), MAX_NAVIGATION_RATE)
    if findings:
        raise ValueError("; ".join(f"{finding['code']}: {finding['message']}" for finding in findings))
    total_frames = _round_frames(shot.get("durSec", 2.5), fps)
    cursor, frame_start, result = 0.0, 0, []
    for index, span in enumerate(spans):
        cursor = math.fsum((cursor, span["durSec"]))
        frame_end = total_frames if index == len(spans) - 1 else _round_frames(cursor, fps)
        frames = frame_end - frame_start
        hold = span["mode"] == "hold"
        result.append({
            "startFrame": frame_start,
            "frames": frames,
            "sourceStartSec": span["fromSec"],
            "sourceEndSec": span["toSec"],
            "playbackRate": 0.0 if hold else (span["toSec"] - span["fromSec"]) * fps / frames,
            "hold": hold,
        })
        frame_start = frame_end
    return result


def _mapping(shot, fps=None):
    """Continuous authored map used for semantic audits before frame compilation."""
    if not isinstance(shot, dict):
        raise ValueError("Shot must be an object")
    duration = shot.get("durSec", 2.5)
    if not _finite(duration) or duration <= 0:
        raise ValueError("Shot duration must be finite and positive")
    if fps is not None:
        if not _finite(fps) or fps <= 0 or not _finite(duration * fps):
            raise ValueError("fps and shot frame count must be finite and positive")
        if "sourceTimeline" in shot:
            return [{"fromSec": span["sourceStartSec"], "toSec": span["sourceEndSec"],
                     "durSec": span["frames"] / fps}
                    for span in compile_source_timeline(shot, fps)]
        duration = _round_frames(duration, fps) / fps
        if duration <= 0:
            raise ValueError("Shot must contain at least one output frame")
    if "sourceTimeline" not in shot:
        start = shot.get("inSec", 0)
        if not _finite(start) or start < 0 or not _finite(start + duration):
            raise ValueError("Source start and end must be finite and nonnegative")
        return [{"fromSec": float(start), "toSec": float(start + duration), "durSec": float(duration)}]
    raw = shot["sourceTimeline"]
    if not isinstance(raw, list) or not raw:
        raise ValueError("sourceTimeline must be a nonempty list")
    spans = []
    for span in raw:
        if not isinstance(span, dict):
            raise ValueError("Source span must be an object")
        start, end, length = (span.get(key) for key in ("fromSec", "toSec", "durSec"))
        if (not all(_finite(value) for value in (start, end, length))
                or start < 0 or end < start or length <= 0):
            raise ValueError("Source span needs finite ordered times and a positive duration")
        if spans and abs(start - spans[-1]["toSec"]) > EPSILON:
            raise ValueError("Source timeline must be continuous and chronological")
        spans.append({"fromSec": float(start), "toSec": float(end), "durSec": float(length)})
    return spans


def source_time_at(shot, localSec, *, fps=None):
    """Map output-local seconds to source seconds; hold endpoints outside the shot.

    Pass fps to sample the exact canonical frame allocation used for rendering.
    Without fps, use authored continuous seconds for preliminary planning.
    """
    if not _finite(localSec):
        raise ValueError("Output time must be finite")
    spans = _mapping(shot, fps)
    time = max(0.0, float(localSec))
    for span in spans:
        if time <= span["durSec"]:
            return span["fromSec"] + (span["toSec"] - span["fromSec"]) * time / span["durSec"]
        time -= span["durSec"]
    return spans[-1]["toSec"]


def output_times_for_source(shot, sourceSec, *, fps=None):
    """Return output-local positions for a source time, or [] when outside the trim.

    A held source frame maps to an interval: both its inclusive start and end
    positions are returned. Shared span boundaries are deduplicated. The last
    endpoint may equal shot duration (the exclusive final picture boundary), so
    a caller checking visible proof must reserve its own reading window.
    Pass fps to use the canonical rendered map instead of authored seconds.
    """
    if not _finite(sourceSec):
        raise ValueError("Source time must be finite")
    spans = _mapping(shot, fps)
    cursor, output = 0.0, []
    for span in spans:
        start, end = span["fromSec"], span["toSec"]
        if start - EPSILON <= sourceSec <= end + EPSILON:
            if start == end:
                output.extend((cursor, cursor + span["durSec"]))
            else:
                progress = max(0.0, min(1.0, (sourceSec - start) / (end - start)))
                output.append(cursor + progress * span["durSec"])
        cursor = math.fsum((cursor, span["durSec"]))
    unique = []
    for value in sorted(output):
        if not unique or abs(value - unique[-1]) > EPSILON:
            unique.append(value)
    return unique
