#!/usr/bin/env python3
"""Deterministic production contracts for Product Demo Director.

The model judge is useful for taste. It is not allowed to decide whether a source was
cropped, a claim has evidence, a narration master changed, a human boundary moved, or a
delivery exceeded its runtime. Those are source-of-truth checks and live here.

The contract is intentionally additive. Old projects keep rendering. A project opts into
the stronger gate with a top-level ``production`` object and/or the existing
``editorialContract`` / ``finalNarration`` blocks used by long-form demos.
"""

from __future__ import annotations

import hashlib
import json
import math
import os
import re
import shutil
import subprocess
from dataclasses import asdict, dataclass
from typing import Any, Iterable


ALLOWED_KINDS = {"title", "clip", "split", "stat", "cta", "score", "bars", "strip"}
CARD_KINDS = {"title", "stat", "cta", "score", "bars"}

SAVE_THE_CAT_BEATS = (
    "opening-image",
    "theme-stated",
    "setup",
    "catalyst",
    "debate",
    "break-into-two",
    "b-story",
    "fun-and-games",
    "midpoint",
    "bad-guys-close-in",
    "all-is-lost",
    "dark-night-of-the-soul",
    "break-into-three",
    "finale",
    "final-image",
)

STORY_FRAMEWORKS = {"save-the-cat": SAVE_THE_CAT_BEATS}

# Broad structural windows, not frame-level creative mandates. They catch a missing act turn while
# still allowing several inseparable beats to live inside one continuous product take.
SAVE_THE_CAT_WINDOWS = {
    "opening-image": (0.0, 5.0),
    "catalyst": (5.0, 18.0),
    "break-into-two": (15.0, 30.0),
    "fun-and-games": (18.0, 55.0),
    "midpoint": (40.0, 60.0),
    "all-is-lost": (65.0, 82.0),
    "break-into-three": (72.0, 90.0),
    "finale": (78.0, 98.0),
    "final-image": (92.0, 100.0),
}

# Profiles are defaults, not taste mandates. Any value may be overridden in production.
PROFILES: dict[str, dict[str, Any]] = {
    "announcement": {
        "hardMaxSec": 60.0,
        "productBySec": 7.0,
        "maxCardRatio": 0.15,
        "ctaMaxSec": 15.0,
        "singleFocus": True,
        "requireContinuityIds": True,
        "requireNarrationMap": True,
        "requireNarrationMapCoverage": True,
        "narrationCutPolicy": "between-thoughts",
        "minNarrationTailSec": 0.75,
    },
    "yc_60": {
        "hardMaxSec": 90.0,
        "productBySec": 8.0,
        "maxCardRatio": 0.20,
        "ctaMaxSec": 2.5,
    },
    "yc_3m": {
        "hardMaxSec": 180.0,
        "productBySec": 15.0,
        "maxCardRatio": 0.22,
        "ctaMaxSec": 5.0,
    },
    "investor": {
        "hardMaxSec": 180.0,
        "productBySec": 15.0,
        "maxCardRatio": 0.25,
        "ctaMaxSec": 5.0,
    },
    "sales": {
        "hardMaxSec": 300.0,
        "productBySec": 25.0,
        "maxCardRatio": 0.30,
        "ctaMaxSec": 7.0,
    },
}
PROFILE_ALIASES = {
    "launch": "announcement",
    "open-source-launch": "announcement",
    "yc": "yc_60",
    "yc3": "yc_3m",
    "yc-3m": "yc_3m",
}


@dataclass(frozen=True)
class Finding:
    severity: str
    code: str
    message: str
    shot: int | None = None
    path: str | None = None

    def as_dict(self) -> dict[str, Any]:
        return {k: v for k, v in asdict(self).items() if v is not None}


def _finding(severity: str, code: str, message: str, shot: int | None = None,
             path: str | None = None) -> Finding:
    return Finding(severity=severity, code=code, message=message, shot=shot, path=path)


def sha256_file(path: str) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as fh:
        for chunk in iter(lambda: fh.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def media_duration(path: str) -> float | None:
    if not shutil.which("ffprobe"):
        return None
    proc = subprocess.run(
        ["ffprobe", "-v", "error", "-show_entries", "format=duration",
         "-of", "default=noprint_wrappers=1:nokey=1", path],
        capture_output=True, text=True,
    )
    if proc.returncode != 0:
        return None
    try:
        return float(proc.stdout.strip())
    except ValueError:
        return None


def timeline(shots: Iterable[dict[str, Any]]) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    cursor = 0.0
    for index, shot in enumerate(shots):
        dur = _number(shot.get("durSec"), 0.0)
        out.append({"index": index, "n": shot.get("n"), "startSec": cursor,
                    "endSec": cursor + max(0.0, dur), "durSec": dur, "shot": shot})
        cursor += max(0.0, dur)
    return out


def _number(value: Any, default: float = 0.0) -> float:
    try:
        n = float(value)
        return n if math.isfinite(n) else default
    except (TypeError, ValueError):
        return default


def _asset_path(project: str, value: str | None) -> str | None:
    if not value:
        return None
    if os.path.isabs(value):
        return value
    direct = os.path.join(project, value)
    if os.path.exists(direct):
        return direct
    return os.path.join(project, "assets", value)


def _profile(production: dict[str, Any], override: str | None) -> tuple[str | None, dict[str, Any]]:
    raw = override or production.get("profile")
    if not raw:
        return None, dict(production)
    name = PROFILE_ALIASES.get(str(raw), str(raw))
    merged = dict(PROFILES.get(name, {}))
    merged.update(production)
    return name, merged


def _source_locks(production: dict[str, Any]) -> dict[str, dict[str, Any]]:
    locks: dict[str, dict[str, Any]] = {}
    for item in production.get("sourceLocks", []) or []:
        if isinstance(item, str):
            locks[item] = {"src": item, "preserveFraming": True}
        elif isinstance(item, dict) and item.get("src"):
            locks[str(item["src"])] = dict(item)
    return locks


def resolve_source_manifests(
    script: dict[str, Any], project: str
) -> tuple[list[tuple[str, str]], list[Finding]]:
    """Resolve optional repo-native capture sources without allowing project escapes."""
    production = script.get("production")
    if not isinstance(production, dict) or "sourceManifests" not in production:
        return [], []
    entries = production.get("sourceManifests")
    if not isinstance(entries, list):
        return [], [_finding(
            "error",
            "SOURCE_MANIFESTS_INVALID",
            "production.sourceManifests must be a list of project-relative file paths",
            path="production.sourceManifests",
        )]

    project_abs = os.path.abspath(project)
    project_real = os.path.realpath(project_abs)
    resolved: list[tuple[str, str]] = []
    findings: list[Finding] = []
    for index, value in enumerate(entries):
        field = f"production.sourceManifests[{index}]"
        if not isinstance(value, str) or not value.strip():
            findings.append(_finding(
                "error",
                "SOURCE_MANIFEST_ENTRY_INVALID",
                "source manifest entries must be non-empty project-relative file paths",
                path=field,
            ))
            continue
        if os.path.isabs(value):
            findings.append(_finding(
                "error",
                "SOURCE_MANIFEST_PATH_ESCAPE",
                f"source manifest must be project-relative: {value}",
                path=field,
            ))
            continue

        absolute = os.path.abspath(os.path.join(project_abs, value))
        real = os.path.realpath(absolute)
        try:
            lexical_inside = os.path.commonpath([project_abs, absolute]) == project_abs
            real_inside = os.path.commonpath([project_real, real]) == project_real
        except ValueError:
            lexical_inside = real_inside = False
        if not lexical_inside or not real_inside:
            findings.append(_finding(
                "error",
                "SOURCE_MANIFEST_PATH_ESCAPE",
                f"source manifest escapes the project: {value}",
                path=field,
            ))
            continue
        if not os.path.exists(absolute):
            findings.append(_finding(
                "error",
                "SOURCE_MANIFEST_MISSING",
                f"source manifest does not exist: {value}",
                path=absolute,
            ))
            continue
        if not os.path.isfile(absolute):
            findings.append(_finding(
                "error",
                "SOURCE_MANIFEST_NOT_FILE",
                f"source manifest is not a file: {value}",
                path=absolute,
            ))
            continue
        name = os.path.relpath(absolute, project_abs).replace(os.sep, "/")
        resolved.append((name, absolute))
    return resolved, findings


def _camera_changes(shot: dict[str, Any]) -> list[str]:
    changed: list[str] = []
    if abs(_number(shot.get("scale"), 1.0) - 1.0) > 1e-6:
        changed.append("scale")
    for key in ("startScale", "endScale"):
        if key in shot and abs(_number(shot.get(key), 1.0) - 1.0) > 1e-6:
            changed.append(key)
    for key in ("panX", "panY"):
        if key in shot and abs(_number(shot.get(key), 0.0)) > 1e-6:
            changed.append(key)
    if shot.get("zooms"):
        changed.append("zooms")
    return changed


def _events_for_shot(project: str, shot: dict[str, Any]) -> tuple[str | None, list[dict[str, Any]]]:
    event_name = shot.get("eventsFile")
    if not event_name and shot.get("src"):
        event_name = os.path.splitext(str(shot["src"]))[0] + ".events.json"
    path = _asset_path(project, event_name)
    if not path or not os.path.exists(path):
        return path, []
    try:
        with open(path) as fh:
            data = json.load(fh)
        if isinstance(data, dict):
            data = data.get("events", [])
        return path, data if isinstance(data, list) else []
    except (OSError, json.JSONDecodeError):
        return path, []


def _cursor_inside_zoom(x: float, y: float, zoom: dict[str, Any], margin: float) -> bool:
    scale = max(1.0, _number(zoom.get("scale"), 1.6))
    cx = min(100.0, max(0.0, _number(zoom.get("focusX"), 50.0)))
    cy = min(100.0, max(0.0, _number(zoom.get("focusY"), 50.0)))
    half = 50.0 / scale
    # The engine clamps focus near edges. Mirror that before checking the rendered viewport.
    cx = min(100.0 - half, max(half, cx))
    cy = min(100.0 - half, max(half, cy))
    inset = margin / scale
    return (cx - half + inset <= x <= cx + half - inset
            and cy - half + inset <= y <= cy + half - inset)


def _validate_cursor(project: str, shot: dict[str, Any], production: dict[str, Any],
                     findings: list[Finding]) -> None:
    required = bool(shot.get("cursorRequired") or production.get("requireCursorEvents"))
    margin = _number(shot.get("cursorSafeMarginPct"),
                     _number(production.get("cursorSafeMarginPct"), 0.0))
    path, events = _events_for_shot(project, shot)
    if required and not events:
        findings.append(_finding("error", "CURSOR_EVENTS_MISSING",
                                 "cursor-safe footage requires a readable interaction sidecar",
                                 shot.get("n"), path))
        return
    if not events or margin <= 0:
        return
    in_sec = _number(shot.get("inSec"), 0.0)
    dur = _number(shot.get("durSec"), 0.0)
    zooms = shot.get("zooms") or []
    for event in events:
        if event.get("type") != "click" or "xPct" not in event or "yPct" not in event:
            continue
        source_t = _number(event.get("t"), -1.0)
        rel_t = source_t - in_sec
        if rel_t < 0 or rel_t > dur:
            continue
        x, y = _number(event.get("xPct"), -1.0), _number(event.get("yPct"), -1.0)
        if not (margin <= x <= 100.0 - margin and margin <= y <= 100.0 - margin):
            findings.append(_finding(
                "error", "CURSOR_RAW_MARGIN",
                f"click at {source_t:.2f}s is outside the {margin:g}% source-frame safe margin",
                shot.get("n"), path,
            ))
        for zoom in zooms:
            start = _number(zoom.get("atSec"), 0.0)
            end = start + _number(zoom.get("durSec"), 0.0)
            if start <= rel_t <= end and not _cursor_inside_zoom(x, y, zoom, margin):
                findings.append(_finding(
                    "error", "CURSOR_ZOOM_CROP",
                    f"click at {source_t:.2f}s falls outside the zoomed viewport safe area",
                    shot.get("n"), path,
                ))


def _claim_evidence_exists(project: str, evidence: Any) -> bool:
    values = evidence if isinstance(evidence, list) else [evidence]
    values = [str(v) for v in values if v]
    if not values:
        return False
    for value in values:
        if re.match(r"^[a-z]+://", value, re.I):
            continue
        path = value if os.path.isabs(value) else os.path.join(project, value)
        if not os.path.exists(path):
            return False
    return True


def _validate_claims(script: dict[str, Any], project: str, production: dict[str, Any],
                     findings: list[Finding]) -> None:
    claims = script.get("claims") or []
    claim_map: dict[str, dict[str, Any]] = {}
    for claim in claims:
        if not isinstance(claim, dict) or not claim.get("id"):
            findings.append(_finding("error", "CLAIM_ID_MISSING", "every claim needs a stable id"))
            continue
        cid = str(claim["id"])
        if cid in claim_map:
            findings.append(_finding("error", "CLAIM_ID_DUPLICATE", f"duplicate claim id: {cid}"))
        claim_map[cid] = claim
        if production.get("requireClaimEvidence"):
            if str(claim.get("status", "")).lower() not in {"verified", "approved"}:
                findings.append(_finding("error", "CLAIM_UNVERIFIED", f"claim {cid} is not verified"))
            if not _claim_evidence_exists(project, claim.get("evidence")):
                findings.append(_finding("error", "CLAIM_EVIDENCE_MISSING",
                                         f"claim {cid} has no resolvable evidence"))
    for shot in script.get("shots", []) or []:
        for cid in shot.get("claimIds", []) or []:
            if str(cid) not in claim_map:
                findings.append(_finding("error", "CLAIM_REFERENCE_UNKNOWN",
                                         f"unknown claim id: {cid}", shot.get("n")))


def _map_narration_text(script: dict[str, Any]) -> str:
    entries = script.get("narrationMap") or []
    return "\n\n".join(
        str(entry.get("text", "") or "").strip()
        for entry in entries
        if isinstance(entry, dict) and str(entry.get("text", "") or "").strip()
    )


def _spoken_text(value: Any) -> str:
    """Normalize authored narration for coverage checks without rewriting spoken words."""
    text = re.sub(r"\[[^\]\n]{1,80}\]\s*", "", str(value or ""))
    return re.sub(r"\s+", " ", text).strip()


def narration_cut_conflicts(entries: Iterable[dict[str, Any]], boundaries: Iterable[float],
                            tolerance: float = 0.05) -> list[dict[str, Any]]:
    """Return picture cuts that land inside a mapped spoken thought."""
    conflicts: list[dict[str, Any]] = []
    for boundary in boundaries:
        cut = _number(boundary, -1.0)
        for index, entry in enumerate(entries):
            start = _number(entry.get("startSec"), -1.0)
            end = _number(entry.get("endSec"), -1.0)
            if start < 0 or end <= start:
                continue
            if start + tolerance < cut < end - tolerance:
                conflicts.append({"cutSec": cut, "cueIndex": index, "entry": entry})
    return conflicts


def _validate_audio_master(script: dict[str, Any], project: str, total: float,
                           production: dict[str, Any], findings: list[Finding],
                           *, allow_pending: bool = False) -> None:
    # ``narration`` is the new engine-mix contract. ``finalNarration`` remains a valid
    # externally-finished master contract and is verified without changing render behavior.
    block = script.get("narration") or script.get("finalNarration")
    if not isinstance(block, dict):
        return
    value = block.get("file") or block.get("edit")
    path = _asset_path(project, value)
    generated_text = str(block.get("text", "") or "").strip()
    if block.get("fromMap"):
        generated_text = _map_narration_text(script)
    if not path or not os.path.exists(path):
        if allow_pending and script.get("narration") and generated_text:
            findings.append(_finding(
                "warning", "NARRATION_PENDING_GENERATION",
                "generated narration is pending; synthesize it and run strict preflight again",
                path=path,
            ))
            return
        findings.append(_finding("error", "NARRATION_MISSING", "narration master is missing", path=path))
        return
    actual = media_duration(path)
    start = _number(block.get("startsAtSec"), 0.0)
    tolerance = _number(block.get("durationToleranceSec"), 0.05)
    if actual is not None and start + actual > total + tolerance:
        findings.append(_finding(
            "error", "NARRATION_OVERRUN",
            f"narration ends at {start + actual:.3f}s after the {total:.3f}s picture; shorten the read or extend the cut",
            path=path,
        ))
    min_tail = _number(production.get("minNarrationTailSec"), 0.0)
    if actual is not None and min_tail > 0:
        tail = total - (start + actual)
        if tail < min_tail - 0.001:
            findings.append(_finding(
                "error", "NARRATION_TAIL_SHORT",
                f"picture leaves {tail:.3f}s after narration; contract requires at least {min_tail:.3f}s",
                path=path,
            ))
    expected_hash = block.get("sha256") or block.get("sourceSha256")
    if expected_hash and sha256_file(path).lower() != str(expected_hash).lower():
        findings.append(_finding("error", "NARRATION_HASH_MISMATCH",
                                 "narration master does not match its locked SHA-256", path=path))
    expected_sec = _number(block.get("expectedDurationSec"), 0.0)
    if expected_sec > 0:
        if actual is None:
            findings.append(_finding("warning", "NARRATION_DURATION_UNCHECKED",
                                     "ffprobe could not verify narration duration", path=path))
        elif abs(actual - expected_sec) > tolerance:
            findings.append(_finding("error", "NARRATION_DURATION_MISMATCH",
                                     f"narration is {actual:.3f}s; expected {expected_sec:.3f}s ± {tolerance:.3f}s",
                                     path=path))
    if script.get("narration") and block.get("mix", True):
        manifest = os.path.join(project, "audio", "manifest.json")
        if os.path.exists(manifest):
            try:
                with open(manifest) as fh:
                    active_vo = json.load(fh)
                if active_vo:
                    findings.append(_finding("error", "NARRATION_DOUBLE_MIX",
                                             "master narration and per-shot VO cannot both be active",
                                             path=manifest))
            except (OSError, json.JSONDecodeError):
                findings.append(_finding("error", "AUDIO_MANIFEST_INVALID",
                                         "audio manifest is not valid JSON", path=manifest))
        if any(s.get("sound") for s in script.get("shots", []) or []) and not block.get("allowSourceAudio"):
            findings.append(_finding("error", "NARRATION_SOURCE_AUDIO_COLLISION",
                                     "master narration requires picture clips to be muted unless allowSourceAudio is explicit"))


def _validate_narration_map(script: dict[str, Any], rows: list[dict[str, Any]], total: float,
                            production: dict[str, Any], findings: list[Finding],
                            *, allow_pending: bool = False) -> None:
    entries = script.get("narrationMap")
    if not entries:
        if production.get("requireNarrationMap"):
            findings.append(_finding(
                "error", "NARRATION_MAP_REQUIRED",
                "this profile requires narrationMap so picture cuts can be locked to complete thoughts",
            ))
        return
    if not isinstance(entries, list):
        findings.append(_finding("error", "NARRATION_MAP_INVALID", "narrationMap must be an array"))
        return
    narration = script.get("narration") if isinstance(script.get("narration"), dict) else {}
    from_map = bool(narration.get("fromMap"))
    pending_timing = False
    previous_end = -1.0
    mapped_shots: list[int] = []
    mapped_text: list[str] = []
    for i, entry in enumerate(entries):
        if not isinstance(entry, dict):
            findings.append(_finding("error", "NARRATION_MAP_ENTRY_INVALID",
                                     f"narrationMap[{i}] must be an object"))
            continue
        text = str(entry.get("text", "") or "").strip()
        if text:
            mapped_text.append(text)
            if production.get("narrationCutPolicy") == "between-thoughts":
                words = _spoken_text(text).split()
                clauses = text.count(",") + text.lower().count(" and ")
                if len(words) >= 32 or (len(words) >= 24 and clauses >= 3):
                    findings.append(_finding(
                        "warning", "NARRATION_THOUGHT_OVERLOADED",
                        f"narrationMap[{i}] carries too many clauses for one visual focus; split the thought",
                        entry.get("shotN"),
                    ))
        elif production.get("requireNarrationMapCoverage") or from_map:
            findings.append(_finding("error", "NARRATION_MAP_TEXT_MISSING",
                                     f"narrationMap[{i}] needs the exact spoken thought"))
        shot_n = entry.get("shotN")
        if shot_n is not None:
            if not isinstance(shot_n, int) or not any(r["shot"].get("n") == shot_n for r in rows):
                findings.append(_finding("error", "NARRATION_MAP_SHOT_INVALID",
                                         f"narrationMap[{i}] references unknown shotN {shot_n!r}"))
            else:
                mapped_shots.append(shot_n)
        elif production.get("autoPaceNarration"):
            findings.append(_finding("error", "NARRATION_MAP_SHOT_MISSING",
                                     f"narrationMap[{i}] needs shotN for automatic pacing"))
        has_range = entry.get("startSec") is not None and entry.get("endSec") is not None
        if not has_range:
            if allow_pending and script.get("narration") and (narration.get("text") or from_map):
                pending_timing = True
                continue
            findings.append(_finding("error", "NARRATION_MAP_RANGE",
                                     f"narrationMap[{i}] has no aligned timing range"))
            continue
        start = _number(entry.get("startSec"), -1.0)
        end = _number(entry.get("endSec"), -1.0)
        if start < 0 or end <= start:
            findings.append(_finding("error", "NARRATION_MAP_RANGE",
                                     f"narrationMap[{i}] has an invalid range"))
        if start < previous_end - 0.001:
            findings.append(_finding("error", "NARRATION_MAP_OVERLAP",
                                     f"narrationMap[{i}] overlaps the prior beat"))
        if not str(entry.get("beat", "")).strip():
            findings.append(_finding("warning", "NARRATION_MAP_BEAT_MISSING",
                                     f"narrationMap[{i}] has no story beat"))
        previous_end = max(previous_end, end)
    if pending_timing:
        findings.append(_finding(
            "warning", "NARRATION_TIMING_PENDING",
            "narration timing will be filled from provider character alignment after synthesis",
        ))
    if previous_end > total + 0.05:
        findings.append(_finding("error", "NARRATION_MAP_OVERRUN",
                                 f"narration map ends at {previous_end:.3f}s after the {total:.3f}s picture"))
    if mapped_shots and mapped_shots != sorted(mapped_shots):
        findings.append(_finding("error", "NARRATION_MAP_SHOT_ORDER",
                                 "narrationMap shotN values must progress in picture order"))
    if production.get("autoPaceNarration"):
        required_shots = [r["shot"].get("n") for r in rows if not r["shot"].get("visualOnly")]
        missing = [n for n in required_shots if n not in mapped_shots]
        if missing:
            findings.append(_finding(
                "error", "NARRATION_MAP_SHOT_COVERAGE",
                "automatic pacing needs a narrated thought for every non-visual shot; missing "
                + ", ".join(str(n) for n in missing),
            ))
    if production.get("requireNarrationMapCoverage") or from_map:
        source = _map_narration_text(script) if from_map else str(narration.get("text", "") or "")
        if _spoken_text(source) != _spoken_text("\n\n".join(mapped_text)):
            findings.append(_finding(
                "error", "NARRATION_MAP_COVERAGE_MISMATCH",
                "narrationMap text must cover the generated master exactly and in order",
            ))
    policy = str(production.get("narrationCutPolicy", "") or "")
    if policy and policy != "between-thoughts":
        findings.append(_finding("error", "NARRATION_CUT_POLICY_UNKNOWN",
                                 f"unknown narrationCutPolicy: {policy}"))
    if policy == "between-thoughts" and not pending_timing:
        boundaries = [row["endSec"] for row in rows[:-1]]
        tolerance = _number(production.get("narrationBoundaryToleranceSec"), 0.05)
        for conflict in narration_cut_conflicts(entries, boundaries, tolerance):
            entry = conflict["entry"]
            preview = _spoken_text(entry.get("text") or entry.get("beat") or "spoken thought")
            if len(preview) > 72:
                preview = preview[:69] + "..."
            findings.append(_finding(
                "error", "NARRATION_THOUGHT_CUT",
                f"picture cuts at {conflict['cutSec']:.3f}s during: {preview}",
                path=f"narrationMap[{conflict['cueIndex']}]",
            ))


def _validate_story(script: dict[str, Any], rows: list[dict[str, Any]], production: dict[str, Any],
                    findings: list[Finding]) -> None:
    framework = str(production.get("storyFramework", "") or "").strip()
    if framework and framework not in STORY_FRAMEWORKS:
        findings.append(_finding("error", "STORY_FRAMEWORK_UNKNOWN",
                                 f"unknown story framework: {framework}"))
    framework_beats = list(STORY_FRAMEWORKS.get(framework, ()))
    required = framework_beats or [str(x) for x in production.get("requiredStoryBeats", []) or []]
    for beat in (production.get("requiredStoryBeats", []) or []):
        if str(beat) not in required:
            required.append(str(beat))
    actual: list[str] = []
    occurrences: list[tuple[str, float, int | None]] = []
    for row in rows:
        shot = row["shot"]
        beats = ([str(shot["storyBeat"])] if shot.get("storyBeat") else [])
        beats.extend(str(beat) for beat in (shot.get("storyBeats") or []) if beat)
        actual.extend(beats)
        for index, beat in enumerate(beats):
            # Spread grouped beats across the shot for placement checks. This preserves one real take
            # while still giving the act turns a meaningful approximate position.
            at = row["startSec"] + row["durSec"] * ((index + 0.5) / max(len(beats), 1))
            occurrences.append((beat, at, shot.get("n")))
    if framework_beats:
        allowed = set(framework_beats)
        for beat in actual:
            if beat not in allowed:
                findings.append(_finding("error", "STORY_BEAT_UNKNOWN",
                                         f"{beat!r} is not a {framework} beat"))
        for beat in framework_beats:
            if actual.count(beat) > 1:
                findings.append(_finding("error", "STORY_BEAT_DUPLICATE",
                                         f"{framework} beat appears more than once: {beat}"))
    cursor = 0
    for beat in required:
        try:
            cursor = actual.index(beat, cursor) + 1
        except ValueError:
            findings.append(_finding("error", "STORY_BEAT_MISSING_OR_OUT_OF_ORDER",
                                     f"required story beat is missing or out of order: {beat}"))
    if framework == "save-the-cat" and rows:
        total = rows[-1]["endSec"]
        first_occurrence = {}
        for beat, at, shot in occurrences:
            first_occurrence.setdefault(beat, (at, shot))
        for beat, (minimum, maximum) in SAVE_THE_CAT_WINDOWS.items():
            if beat not in first_occurrence or total <= 0:
                continue
            at, shot = first_occurrence[beat]
            percent = at / total * 100
            if percent < minimum - 0.01 or percent > maximum + 0.01:
                findings.append(_finding(
                    "warning", "STORY_BEAT_PLACEMENT",
                    f"{beat} lands at {percent:.1f}%; {framework} guidance is {minimum:g}–{maximum:g}%",
                    shot,
                ))
    product_by = _number(production.get("productBySec"), 0.0)
    if product_by > 0:
        product_rows = [r for r in rows if r["shot"].get("sourceType") == "product"]
        if not product_rows:
            findings.append(_finding("warning", "PRODUCT_SOURCE_UNLABELED",
                                     "productBySec is set but no shot declares sourceType=product"))
        elif product_rows[0]["startSec"] > product_by + 0.001:
            findings.append(_finding("error", "PRODUCT_ARRIVES_LATE",
                                     f"product first appears at {product_rows[0]['startSec']:.2f}s; contract requires ≤ {product_by:.2f}s"))
    if production.get("requireLiveProgression"):
        if not any(r["shot"].get("liveState") for r in rows):
            findings.append(_finding("error", "LIVE_PROGRESSION_MISSING",
                                     "at least one product shot must declare liveState=true"))
    actors = {"agent", "human", "system"}
    risks = {"low-friction", "consequential"}
    human = sum(1 for r in rows if r["shot"].get("actor") == "human"
                and r["shot"].get("actionRisk") == "consequential")
    max_human = production.get("maxHumanDecisions")
    if max_human is not None and human > int(max_human):
        findings.append(_finding("error", "TOO_MANY_HUMAN_DECISIONS",
                                 f"{human} consequential human actions exceed the contract maximum {max_human}"))
    exact_human = production.get("exactHumanDecisions")
    if exact_human is not None and human != int(exact_human):
        findings.append(_finding("error", "HUMAN_DECISION_COUNT_MISMATCH",
                                 f"{human} consequential human actions found; contract requires exactly {exact_human}"))
    for row in rows:
        shot = row["shot"]
        actor, risk = shot.get("actor"), shot.get("actionRisk")
        if actor is not None and actor not in actors:
            findings.append(_finding("error", "ACTION_ACTOR_INVALID",
                                     f"actor must be one of {sorted(actors)}", shot.get("n")))
        if risk is not None and risk not in risks:
            findings.append(_finding("error", "ACTION_RISK_INVALID",
                                     f"actionRisk must be one of {sorted(risks)}", shot.get("n")))
        if risk is not None and actor is None:
            findings.append(_finding("error", "ACTION_ACTOR_MISSING",
                                     "an actionRisk declaration also requires actor", shot.get("n")))
        if risk == "low-friction" and actor == "human":
            findings.append(_finding("error", "LOW_FRICTION_HUMAN_GATE",
                                     "low-friction work should execute automatically, not wait for a human",
                                     shot.get("n")))
        if (risk == "consequential" and actor in {"agent", "system"}
                and not production.get("allowAutonomousConsequentialActions")):
            findings.append(_finding("error", "CONSEQUENTIAL_ACTION_NOT_HUMAN",
                                     "consequential action requires a human decision unless autonomy is explicitly authorized",
                                     shot.get("n")))


def _validate_wording(shots: list[dict[str, Any]], production: dict[str, Any],
                      findings: list[Finding]) -> None:
    forbidden = [str(x) for x in production.get("forbiddenPhrases", []) or []]
    for shot in shots:
        text = " ".join(str(shot.get(k, "") or "") for k in ("vo", "caption", "title", "subtitle"))
        lower = text.lower()
        for phrase in forbidden:
            if phrase.lower() in lower:
                findings.append(_finding("error", "FORBIDDEN_PHRASE",
                                         f"forbidden phrase appears: {phrase}", shot.get("n")))
        for sentence in re.split(r"(?<=[.!?])\s+", str(shot.get("vo", "") or "")):
            words = sentence.split()
            clauses = sentence.count(",") + sentence.lower().count(" and ")
            if len(words) >= 42 and clauses >= 4:
                findings.append(_finding("warning", "VO_OVERLOADED_STEP",
                                         "voiceover packs several actions into one sentence; prefer one visible action per step",
                                         shot.get("n")))


def validate_script(script: dict[str, Any], project: str, profile_override: str | None = None,
                    *, allow_pending_narration: bool = False) -> list[Finding]:
    """Return deterministic errors/warnings without mutating the script or project."""
    project = os.path.abspath(project)
    findings: list[Finding] = []
    _, source_manifest_findings = resolve_source_manifests(script, project)
    findings.extend(source_manifest_findings)
    shots = script.get("shots")
    if not isinstance(shots, list) or not shots:
        findings.append(_finding(
            "error", "SHOTS_MISSING", "script must contain a non-empty shots list"
        ))
        return findings
    production_raw = script.get("production") if isinstance(script.get("production"), dict) else {}
    profile_name, production = _profile(production_raw, profile_override)
    if profile_name and profile_name not in PROFILES:
        findings.append(_finding("error", "PROFILE_UNKNOWN", f"unknown production profile: {profile_name}"))
    rows = timeline(shots)
    total = rows[-1]["endSec"] if rows else 0.0

    seen: set[int] = set()
    durations: dict[str, float | None] = {}

    def checked_duration(path: str) -> float | None:
        if path not in durations:
            durations[path] = media_duration(path)
        return durations[path]

    for index, row in enumerate(rows):
        shot = row["shot"]
        n = shot.get("n")
        if not isinstance(n, int):
            findings.append(_finding("error", "SHOT_NUMBER_INVALID", "shot n must be an integer", path=f"shots[{index}]"))
        elif n in seen:
            findings.append(_finding("error", "SHOT_NUMBER_DUPLICATE", f"duplicate shot number {n}", n))
        else:
            seen.add(n)
        kind = shot.get("kind", "clip")
        if kind not in ALLOWED_KINDS:
            findings.append(_finding("error", "SHOT_KIND_INVALID", f"unsupported shot kind: {kind}", n))
        single_focus = bool(production.get("singleFocus") or production.get("singleVisualFocus"))
        if single_focus and kind == "split" and not production.get("allowSplitScreen"):
            findings.append(_finding(
                "error", "SPLIT_SCREEN_FORBIDDEN",
                "singleFocus forbids split-screen; sequence the evidence as full-frame shots",
                n,
            ))
        forbidden_kinds = {str(item) for item in production.get("forbiddenShotKinds", []) or []}
        if kind in forbidden_kinds:
            findings.append(_finding(
                "error", "SHOT_KIND_FORBIDDEN",
                f"production contract forbids shot kind: {kind}", n,
            ))
        if row["durSec"] <= 0:
            findings.append(_finding("error", "SHOT_DURATION_INVALID", "durSec must be positive", n))
        source_keys = (("src",) if kind in {"clip", "strip"}
                       else ("srcL", "srcR") if kind == "split" else ())
        for key in source_keys:
            value = shot.get(key)
            path = _asset_path(project, value)
            if not value or not path or not os.path.exists(path):
                findings.append(_finding("error", "SHOT_ASSET_MISSING", f"missing {key}: {value}", n, path))
                continue
            if kind in {"clip", "split"}:
                actual = checked_duration(path)
                in_key = "inSec" if key == "src" else "inL" if key == "srcL" else "inR"
                needed = _number(shot.get(in_key), 0.0) + row["durSec"]
                if actual is None:
                    findings.append(_finding("warning", "SOURCE_DURATION_UNCHECKED",
                                             f"ffprobe could not verify {key} duration", n, path))
                elif needed > actual + 0.05:
                    findings.append(_finding("error", "SOURCE_RANGE_OVERRUN",
                                             f"{key} needs {needed:.3f}s but source is {actual:.3f}s", n, path))
        source_type = shot.get("sourceType")
        if source_type is not None and source_type not in {"product", "human", "slide", "external", "generated"}:
            findings.append(_finding("error", "SOURCE_TYPE_INVALID",
                                     "sourceType must be product, human, slide, external, or generated", n))
        if (production.get("requireContinuityIds") and kind == "clip"
                and source_type == "product" and not shot.get("continuityId")):
            findings.append(_finding(
                "error", "CONTINUITY_ID_REQUIRED",
                "product clips need continuityId so same-screen crop resets cannot bypass the contract", n,
            ))
        zooms = shot.get("zooms") or []
        previous_end = None
        for zi, zoom in enumerate(zooms):
            start = _number(zoom.get("atSec"), -1.0)
            dur = _number(zoom.get("durSec"), 0.0)
            scale = _number(zoom.get("scale"), 1.6)
            if start < 0 or dur <= 0 or start >= row["durSec"]:
                findings.append(_finding("error", "ZOOM_RANGE_INVALID",
                                         f"zoom {zi} falls outside its shot", n))
            elif start + dur > row["durSec"] + 0.05 and not shot.get("allowZoomTailClip"):
                findings.append(_finding("warning", "ZOOM_TAIL_TRUNCATED",
                                         f"zoom {zi} extends {start + dur - row['durSec']:.2f}s past the shot and will be clipped",
                                         n))
            if scale < 1.0 or scale > _number(production.get("maxZoomScale"), 2.25):
                findings.append(_finding("error", "ZOOM_SCALE_UNSAFE",
                                         f"zoom {zi} scale {scale:g} is outside the safe range", n))
            for axis in ("focusX", "focusY"):
                value = _number(zoom.get(axis), 50.0)
                if value < 0 or value > 100:
                    findings.append(_finding("error", "ZOOM_FOCUS_INVALID",
                                             f"zoom {zi} {axis} must be 0–100", n))
            if previous_end is not None:
                gap = start - previous_end
                max_gap = _number(production.get("maxConnectedZoomGapSec"), 1.5)
                if gap > max_gap and not shot.get("allowZoomReset"):
                    findings.append(_finding("warning", "DISCONNECTED_SAME_SCREEN_ZOOM",
                                             f"zoom resets for {gap:.2f}s on the same screen; connect the move or split on a real state change",
                                             n))
            previous_end = start + dur

        locks = _source_locks(production_raw)
        lock = locks.get(str(shot.get("src")), {})
        preserve = bool(shot.get("preserveFraming") or lock.get("preserveFraming"))
        if (production.get("lockHumanFraming") and source_type == "human"
                and not preserve):
            findings.append(_finding("error", "HUMAN_FRAMING_UNLOCKED",
                                     "human footage must declare preserveFraming under this contract", n))
        if preserve:
            changes = _camera_changes(shot)
            if changes:
                findings.append(_finding("error", "SOURCE_FRAMING_CHANGED",
                                         "source-locked footage cannot use " + ", ".join(changes), n))
            if shot.get("objectFit") == "cover" and not lock.get("allowCover"):
                findings.append(_finding("error", "SOURCE_COVER_CROP",
                                         "source-locked footage must use objectFit=contain", n))
        _validate_cursor(project, shot, production, findings)

    if production.get("enforceSameScreenContinuity"):
        for left, right in zip(rows, rows[1:]):
            a, b = left["shot"], right["shot"]
            aid, bid = a.get("continuityId"), b.get("continuityId")
            same_screen = aid and aid == bid and a.get("kind") == b.get("kind") == "clip"
            real_state_change = (a.get("stateId") is not None and b.get("stateId") is not None
                                 and a.get("stateId") != b.get("stateId"))
            if same_screen and (not b.get("transitionReason") or not real_state_change):
                findings.append(_finding("error", "SAME_SCREEN_CUT",
                                         f"continuityId={aid} is split without both a changed stateId and a declared route, app, or major state change; keep one clip with connected zoom regions",
                                         b.get("n")))
    hard_max = _number(production.get("hardMaxSec"), 0.0)
    if hard_max and total > hard_max + 0.001:
        findings.append(_finding("error", "RUNTIME_OVER_HARD_MAX",
                                 f"runtime {total:.2f}s exceeds the {hard_max:.2f}s hard maximum"))
    card_ratio = sum(r["durSec"] for r in rows if r["shot"].get("kind") in CARD_KINDS) / max(total, 0.001)
    max_card = _number(production.get("maxCardRatio"), 0.0)
    if max_card and card_ratio > max_card + 1e-6:
        findings.append(_finding("error", "PRESENTATION_RATIO_HIGH",
                                 f"cards occupy {card_ratio:.0%} of runtime; contract allows {max_card:.0%}"))
    cta_max = _number(production.get("ctaMaxSec"), 0.0)
    for row in rows:
        if cta_max and row["shot"].get("kind") == "cta" and row["durSec"] > cta_max + 0.001:
            findings.append(_finding("warning", "CTA_TOO_LONG",
                                     f"CTA holds {row['durSec']:.2f}s; profile target is ≤ {cta_max:.2f}s",
                                     row["shot"].get("n")))

    editorial = script.get("editorialContract") if isinstance(script.get("editorialContract"), dict) else {}
    target = _number(editorial.get("targetRuntimeSec"), 0.0)
    runtime_tolerance = max(1e-9, _number(editorial.get("runtimeToleranceSec"), 0.05))
    if target and abs(total - target) > runtime_tolerance:
        findings.append(_finding("error", "EDITORIAL_RUNTIME_MISMATCH",
                                 f"shot runtime is {total:.3f}s; editorial target is {target:.3f}s"))
    cta_rows = [r for r in rows if r["shot"].get("kind") == "cta"]
    expected_cta = _number(editorial.get("ctaStartsAtSec"), -1.0)
    if expected_cta >= 0 and (not cta_rows or abs(cta_rows[-1]["startSec"] - expected_cta) > 0.05):
        actual = cta_rows[-1]["startSec"] if cta_rows else None
        findings.append(_finding("error", "CTA_BOUNDARY_MISMATCH",
                                 f"CTA starts at {actual}; editorial contract says {expected_cta:.3f}s"))

    _validate_audio_master(script, project, total, production, findings,
                           allow_pending=allow_pending_narration)
    _validate_narration_map(script, rows, total, production, findings,
                            allow_pending=allow_pending_narration)
    _validate_claims(script, project, production, findings)
    _validate_story(script, rows, production, findings)
    _validate_wording(shots, production, findings)
    return findings


def summarize(findings: Iterable[Finding]) -> dict[str, Any]:
    items = list(findings)
    return {
        "status": "pass" if not any(f.severity == "error" for f in items) else "fail",
        "errors": sum(1 for f in items if f.severity == "error"),
        "warnings": sum(1 for f in items if f.severity == "warning"),
        "findings": [f.as_dict() for f in items],
    }
