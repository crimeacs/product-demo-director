#!/usr/bin/env python3
"""Audit declared editorial timing without judging taste or claiming to inspect the picture.

No media, model, or network calls are made. Source beats are authored observations in the source
file's clock; narration cues use the final film's clock. Missing declarations remain unknown.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import os
from pathlib import Path
import tempfile

if __package__:
    from .source_timing import compile_source_timeline, output_times_for_source, source_time_at, validate_source_timing
else:
    from source_timing import compile_source_timeline, output_times_for_source, source_time_at, validate_source_timing


DEFAULT_THRESHOLDS = {
    "firstProofBySec": 15.0,
    "maxEvidenceLagSec": 2.0,
    "maxUnanchoredShotSec": 12.0,
    "maxSetupRatio": 0.30,
    "maxNavigationRatio": 0.25,
}
BEAT_KINDS = {"action", "proof", "navigation"}
SETUP_TAGS = {"setup", "input", "opening-image"}


def narration_cue_shots(cue, shot_numbers):
    """Resolve one cue's assigned picture interval without inventing a mapping."""
    if "shotN" in cue and "shotNs" in cue:
        return [], "Use shotN or shotNs, never both."
    order = {number: index for index, number in enumerate(shot_numbers) if type(number) is int}
    if "shotNs" in cue:
        numbers = cue["shotNs"]
        if (not isinstance(numbers, list) or not numbers
                or any(type(number) is not int or number not in order for number in numbers)):
            return [], "shotNs must be a nonempty array of known integer shot numbers."
        if len(set(numbers)) != len(numbers):
            return [], "shotNs must not repeat a shot."
        positions = [order[number] for number in numbers]
        if positions != list(range(positions[0], positions[0] + len(positions))):
            return [], "shotNs must name consecutive shots in picture order."
        return list(numbers), None
    number = cue.get("shotN")
    if number is None:
        return [], None
    if type(number) is not int or number not in order:
        return [], "Narration cue references an unknown shot."
    return [number], None


def _number(value):
    try:
        return type(value) in (int, float) and math.isfinite(value)
    except OverflowError:
        return False


def _frames(seconds, fps):
    return max(1, math.floor(seconds * fps + 0.5))


def audit_editorial(script):
    """Return deterministic, advisory findings; never mutate the script or inspect source pixels."""
    findings = []
    thresholds = dict(DEFAULT_THRESHOLDS)
    metrics = {
        "fps": None, "totalFrames": None, "runtimeSec": None,
        "proofStatus": "unknown", "firstDeclaredProofSec": None,
        "setupSec": None, "setupRatio": None, "setupStatus": "unknown",
        "navigationSec": None, "navigationRatio": None, "navigationStatus": "unknown",
        "navigationEventCount": 0, "sourceBeatCount": 0,
        "cueCount": 0, "anchoredCueCount": 0, "unanchoredCueCount": 0,
        "timedAnchorCount": 0, "longUnanchoredShotCount": 0,
    }
    beat_rows = []

    def finding(severity, code, message, *, shot=None, beat=None, cue=None, path=None):
        row = {"severity": severity, "code": code, "message": message}
        row.update({key: value for key, value in (("shot", shot), ("beatId", beat),
                                                ("cueId", cue), ("path", path)) if value is not None})
        findings.append(row)

    def result():
        status = ("invalid" if any(f["severity"] == "error" for f in findings) else
                  "needs-review" if any(f["severity"] == "warning" for f in findings) else
                  "unknown" if metrics["proofStatus"] == "unknown" or any(
                      f["code"] in {"CUE_ALIGNMENT_UNKNOWN", "CUE_SHOT_UNKNOWN", "NARRATION_ALIGNMENT_UNKNOWN"} for f in findings)
                  else "clear-declared")
        return {"schemaVersion": 1, "advisory": True, "status": status, "thresholds": thresholds,
                "metrics": metrics, "sourceBeats": beat_rows, "findings": findings,
                "basis": "Authored source beats, story tags, source timing, and aligned narration; no visual or retention assessment."}

    if not isinstance(script, dict):
        finding("error", "EDITORIAL_SCRIPT_INVALID", "Script must be an object.")
        return result()
    fps = script.get("fps", 30)
    if not _number(fps) or fps <= 0:
        finding("error", "EDITORIAL_FPS_INVALID", "fps must be a finite positive number.", path="fps")
        return result()
    fps = float(fps)
    metrics["fps"] = fps
    production = script.get("production", {})
    if not isinstance(production, dict):
        finding("error", "EDITORIAL_CONFIG_INVALID", "production must be an object.", path="production")
        production = {}
    config = production.get("editorial", {})
    if not isinstance(config, dict):
        finding("error", "EDITORIAL_CONFIG_INVALID", "production.editorial must be an object.")
        config = {}
    for key, value in config.items():
        path = f"production.editorial.{key}"
        if key not in thresholds:
            finding("error", "EDITORIAL_CONFIG_UNKNOWN", f"Unknown editorial threshold: {key}.", path=path)
        elif value is None:
            thresholds[key] = None  # Explicitly disable an advisory threshold.
        elif not _number(value) or value < 0 or (key.endswith("Ratio") and value > 1):
            finding("error", "EDITORIAL_CONFIG_INVALID", f"{key} must be finite and nonnegative"
                    + (", at most one" if key.endswith("Ratio") else "") + ", or null.", path=path)
        else:
            thresholds[key] = float(value)

    shots = script.get("shots")
    if not isinstance(shots, list) or not shots:
        finding("error", "EDITORIAL_SHOTS_INVALID", "shots must be a nonempty array.")
        return result()
    timeline, by_number, cursor = [], {}, 0
    for index, shot in enumerate(shots):
        path = f"shots[{index}]"
        if not isinstance(shot, dict):
            finding("error", "EDITORIAL_SHOT_INVALID", "Every shot must be an object.", path=path)
            continue
        number, duration = shot.get("n"), shot.get("durSec")
        if type(number) is not int or number in by_number:
            finding("error", "EDITORIAL_SHOT_INVALID", "Shot numbers must be unique integers.", path=path + ".n")
            continue
        if not _number(duration) or duration <= 0 or not math.isfinite(duration * fps):
            finding("error", "EDITORIAL_SHOT_INVALID", "durSec must be finite and positive.", shot=number)
            continue
        count = shot.get("durFrames", _frames(duration, fps))
        if type(count) is not int or count < 1:
            finding("error", "EDITORIAL_SHOT_INVALID", "durFrames must be a positive integer.", shot=number)
            continue
        if shot.get("kind") == "clip" and (not _number(shot.get("inSec", 0)) or shot.get("inSec", 0) < 0):
            finding("error", "EDITORIAL_SOURCE_INVALID", "Clip inSec must be finite and nonnegative.", shot=number)
            continue
        row = {"shot": shot, "mappedShot": {**shot, "durSec": count / fps}, "index": index,
               "n": number, "frames": count, "startFrame": cursor,
               "startSec": cursor / fps, "endSec": (cursor + count) / fps, "durationSec": count / fps}
        timeline.append(row)
        by_number[number] = row
        cursor += count
    if len(timeline) != len(shots):
        return result()  # Partial timelines must never supply misleading event times.
    metrics.update(totalFrames=cursor, runtimeSec=cursor / fps)
    timing_findings = validate_source_timing({**script, "shots": [row["mappedShot"] for row in timeline]})
    findings.extend(timing_findings)
    if timing_findings:
        return result()

    cue_map, cues_by_shot = {}, {number: [] for number in by_number}
    cues = script.get("narrationMap", [])
    if not isinstance(cues, list):
        finding("error", "EDITORIAL_CUES_INVALID", "narrationMap must be an array.")
        cues = []
    duplicate_cues = set()
    for index, cue in enumerate(cues):
        path = f"narrationMap[{index}]"
        if not isinstance(cue, dict):
            finding("error", "EDITORIAL_CUE_INVALID", "Every narration cue must be an object.", path=path)
            continue
        cue_id = cue.get("id")
        numbers, assignment_error = narration_cue_shots(cue, by_number)
        number = numbers[0] if numbers else None
        if cue_id is not None and (not isinstance(cue_id, str) or not cue_id.strip()):
            finding("error", "EDITORIAL_CUE_INVALID", "Cue id must be a nonempty string.", path=path + ".id")
            cue_id = None
        if cue_id in cue_map:
            duplicate_cues.add(cue_id)
            finding("error", "EDITORIAL_CUE_DUPLICATE", "Narration cue ids must be unique.", cue=cue_id, path=path)
        elif cue_id is not None:
            cue_map[cue_id] = cue
        if assignment_error:
            finding("error", "EDITORIAL_CUE_SHOT_INVALID", assignment_error, cue=cue_id, path=path)
            continue
        if not numbers:
            finding("info", "CUE_SHOT_UNKNOWN", "Narration cue has no shot assignment; its picture alignment is unknown.", cue=cue_id, path=path)
            start, end = cue.get("startSec"), cue.get("endSec")
            if not (start is None and end is None) and (not _number(start) or not _number(end) or start < 0 or end <= start):
                finding("error", "EDITORIAL_CUE_RANGE_INVALID", "Narration cue must have a finite ordered timing range.", cue=cue_id, path=path)
            continue
        for member in numbers:
            cues_by_shot[member].append(cue)
        start, end = cue.get("startSec"), cue.get("endSec")
        if start is None and end is None:
            continue  # Unsynthesized drafts are valid, but their evidence lag remains unknown.
        first, last = by_number[numbers[0]], by_number[numbers[-1]]
        if (not _number(start) or not _number(end) or start < 0 or end <= start
                or start < first["startSec"] - 1 / fps or end > last["endSec"] + 1 / fps):
            finding("error", "EDITORIAL_CUE_RANGE_INVALID", "Narration cue must have an ordered range within its assigned picture interval.",
                    shot=number, cue=cue_id, path=path)
    metrics["cueCount"] = sum(isinstance(cue, dict) for cue in cues)

    seen_beats, anchored_cues, setup_frames, navigation_frames = set(), set(), 0, 0
    setup_declared = navigation_declared = False
    for row in timeline:
        shot, number = row["shot"], row["n"]
        tags = shot.get("storyBeats", [])
        tags = tags if isinstance(tags, list) else []
        tags = {tag for tag in [shot.get("storyBeat"), *tags] if isinstance(tag, str)}
        if tags:
            setup_declared = True
        if tags & SETUP_TAGS:
            setup_frames += row["frames"]
        spans = shot.get("sourceTimeline")
        if isinstance(spans, list) and spans:
            for span, compiled in zip(spans, compile_source_timeline(row["mappedShot"], fps)):
                if span.get("mode") == "navigation":
                    navigation_frames += compiled["frames"]
                navigation_declared = True
        elif "navigation" in tags:
            navigation_frames += row["frames"]
            navigation_declared = True
        beats = shot.get("sourceBeats", [])
        if not isinstance(beats, list):
            finding("error", "EDITORIAL_SOURCE_BEATS_INVALID", "sourceBeats must be an array.", shot=number)
            continue
        if beats and shot.get("kind") != "clip":
            finding("error", "EDITORIAL_SOURCE_BEATS_INVALID", "Source beats belong to clip shots.", shot=number)
            continue
        for index, beat in enumerate(beats):
            path = f"shots[{row['index']}].sourceBeats[{index}]"
            if not isinstance(beat, dict):
                finding("error", "EDITORIAL_SOURCE_BEAT_INVALID", "Every source beat must be an object.", shot=number, path=path)
                continue
            beat_id, source_sec, kind = beat.get("id"), beat.get("sourceSec"), beat.get("kind")
            if not isinstance(beat_id, str) or not beat_id.strip() or beat_id in seen_beats:
                finding("error", "EDITORIAL_SOURCE_BEAT_ID_INVALID", "Source beat ids must be nonempty and globally unique.", shot=number, path=path)
                continue
            seen_beats.add(beat_id)
            if not _number(source_sec) or source_sec < 0 or not isinstance(kind, str) or kind not in BEAT_KINDS:
                finding("error", "EDITORIAL_SOURCE_BEAT_INVALID", "Source beats need finite nonnegative sourceSec and kind action, proof, or navigation.",
                        shot=number, beat=beat_id, path=path)
                continue
            lead, hold = beat.get("leadInSec", 0.5), beat.get("readHoldSec", 1.5)
            if any(not _number(value) or value < 0 for value in (lead, hold)):
                finding("error", "EDITORIAL_SOURCE_BEAT_INVALID", "leadInSec and readHoldSec must be finite nonnegative numbers.", shot=number, beat=beat_id)
                continue
            if "label" in beat and not isinstance(beat["label"], str):
                finding("error", "EDITORIAL_SOURCE_BEAT_INVALID", "Source beat label must be a string.", shot=number, beat=beat_id)
                continue
            try:
                # Round event arrivals up: no finding may claim an event is visible before its frame.
                times = output_times_for_source(row["mappedShot"], source_sec, fps=fps)
                frames = sorted({max(0, math.ceil(time * fps - 1e-8)) for time in times
                                 if _number(time) and time >= 0})
                frames = [frame for frame in frames if frame < row["frames"]]
                source_start = source_time_at(row["mappedShot"], 0, fps=fps)
            except (TypeError, ValueError, KeyError, OverflowError) as error:
                finding("error", "EDITORIAL_SOURCE_TIMING_INVALID", f"Cannot map source beat: {error}", shot=number, beat=beat_id)
                continue
            if not frames:
                finding("error", "EDITORIAL_SOURCE_BEAT_OMITTED", "Source beat is outside the selected source ranges or falls after the last picture frame.",
                        shot=number, beat=beat_id)
                continue
            local_frame = frames[0]
            film_frame = row["startFrame"] + local_frame
            available = (row["frames"] - local_frame) / fps
            resolved = {"id": beat_id, "shotN": number, "kind": kind, "sourceSec": source_sec,
                        "frame": film_frame, "startSec": film_frame / fps,
                        "outputLocalSec": local_frame / fps, "leadInAvailableSec": local_frame / fps,
                        "readWindowSec": available, "sourceStartSec": source_start}
            if "label" in beat:
                resolved["label"] = beat["label"]
            beat_rows.append(resolved)
            if kind == "navigation":
                metrics["navigationEventCount"] += 1
            if kind == "action" and local_frame / fps + 1e-8 < lead:
                finding("warning", "INITIATION_LEAD_IN_SHORT", f"Action has {local_frame / fps:.3f}s of visible pre-roll; {lead:g}s was requested. Preserve its initiating context.",
                        shot=number, beat=beat_id)
            if kind == "proof" and available + 1e-8 < hold:
                finding("warning", "PROOF_READ_WINDOW_SHORT", f"Only {available:.3f}s remains after the declared proof; {hold:g}s was requested for reading.",
                        shot=number, beat=beat_id)
            cue_id = beat.get("cueId")
            if cue_id is None:
                continue
            resolved["cueId"] = cue_id
            if (not isinstance(cue_id, str) or not cue_id.strip() or cue_id not in cue_map
                    or cue_id in duplicate_cues):
                finding("error", "SOURCE_BEAT_CUE_INVALID", "cueId must identify exactly one narrationMap entry.", shot=number, beat=beat_id)
                continue
            cue = cue_map[cue_id]
            members, assignment_error = narration_cue_shots(cue, by_number)
            if assignment_error or number not in members:
                finding("error", "SOURCE_BEAT_CUE_SHOT_MISMATCH", "The source beat's shot must belong to the narration cue's picture interval.",
                        shot=number, beat=beat_id, cue=cue_id)
                continue
            anchored_cues.add(cue_id)
            cue_start, cue_end = cue.get("startSec"), cue.get("endSec")
            if not _number(cue_start) or not _number(cue_end) or cue_end <= cue_start:
                finding("info", "CUE_ALIGNMENT_UNKNOWN", "Cue timing is unavailable; evidence-to-narration lag is unknown until synthesis and alignment.",
                        shot=number, beat=beat_id, cue=cue_id)
                continue
            lag = resolved["startSec"] - cue_start
            resolved["cueLagSec"] = lag
            metrics["timedAnchorCount"] += 1
            maximum = thresholds["maxEvidenceLagSec"]
            if maximum is not None and lag > maximum + 1e-8:
                finding("warning", "EVIDENCE_ANCHOR_LATE", f"Declared {kind} arrives {lag:.3f}s after its spoken cue starts; the configured allowance is {maximum:g}s.",
                        shot=number, beat=beat_id, cue=cue_id)

    metrics["sourceBeatCount"] = len(beat_rows)
    proof_times = [beat["startSec"] for beat in beat_rows if beat["kind"] == "proof"]
    if proof_times:
        metrics.update(proofStatus="declared", firstDeclaredProofSec=min(proof_times))
        maximum = thresholds["firstProofBySec"]
        if maximum is not None and min(proof_times) > maximum + 1e-8:
            finding("warning", "FIRST_PROOF_LATE", f"First declared proof arrives at {min(proof_times):.3f}s; the configured target is {maximum:g}s. Inspect the setup and proof order.")
    else:
        finding("info", "PROOF_TIMING_UNKNOWN", "No valid source beat declares visible proof. Time to first proof is unknown, not a pass.")
    for prefix, count, declared in (("setup", setup_frames, setup_declared),
                                    ("navigation", navigation_frames, navigation_declared)):
        if declared:
            ratio = count / cursor
            metrics.update({prefix + "Sec": count / fps, prefix + "Ratio": ratio, prefix + "Status": "declared"})
            maximum = thresholds["max" + prefix.title() + "Ratio"]
            if maximum is not None and ratio > maximum + 1e-8:
                finding("warning", prefix.upper() + "_SHARE_HIGH", f"Declared {prefix} occupies {ratio:.1%} of runtime; the configured review threshold is {maximum:.1%}.")
    metrics["anchoredCueCount"] = len(anchored_cues)
    metrics["unanchoredCueCount"] = max(0, metrics["cueCount"] - len(anchored_cues))
    maximum = thresholds["maxUnanchoredShotSec"]
    for row in timeline:
        missing = [cue for cue in cues_by_shot[row["n"]]
                   if not isinstance(cue.get("id"), str) or cue.get("id") not in anchored_cues]
        if maximum is not None and row["durationSec"] > maximum and missing:
            metrics["longUnanchoredShotCount"] += 1
            finding("warning", "LONG_SHOT_UNANCHORED_CUES", f"This {row['durationSec']:.3f}s shot carries {len(missing)} narration cue(s) without source-beat anchors. Check that each spoken action or finding is visible.", shot=row["n"])
        elif maximum is not None and row["durationSec"] > maximum and row["shot"].get("vo") and not cues_by_shot[row["n"]]:
            finding("info", "NARRATION_ALIGNMENT_UNKNOWN", "Long shot has per-shot voice text but no aligned narration map; cue-to-picture timing is unknown.", shot=row["n"])
    return result()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--project", required=True)
    parser.add_argument("--write", action="store_true", help="save out/editorial-report.json; default only prints JSON")
    args = parser.parse_args()
    project = Path(args.project).resolve()
    script_path = project / "script.json"
    payload = script_path.read_bytes()
    report = audit_editorial(json.loads(payload))
    report["script"] = {"path": str(script_path), "sha256": hashlib.sha256(payload).hexdigest()}
    if args.write:
        output = project / "out" / "editorial-report.json"
        output.parent.mkdir(parents=True, exist_ok=True)
        fd, temporary = tempfile.mkstemp(prefix=".editorial-", suffix=".json", dir=output.parent)
        try:
            with os.fdopen(fd, "w") as handle:
                json.dump(report, handle, indent=2, allow_nan=False)
                handle.write("\n")
            os.replace(temporary, output)
        finally:
            if os.path.exists(temporary):
                os.unlink(temporary)
    print(json.dumps(report, indent=2, allow_nan=False))
    return 2 if report["status"] == "invalid" else 0


if __name__ == "__main__":
    raise SystemExit(main())
