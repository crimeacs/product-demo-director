#!/usr/bin/env python3
"""Deterministic final-media QA and proof-sheet generation.

This tool does not grade taste. It proves that the intended artifact decodes, matches its
build manifest, has the expected timing/streams, stays inside audio and black/silence gates,
and produces reviewable evidence for every cut and configured camera/cursor risk interval.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import os
import re
import shutil
import subprocess
import sys
from typing import Any

from contracts import narration_cut_conflicts, sha256_file

NUMBER = r"[+-]?(?:\d+(?:\.\d*)?|\.\d+)(?:[eE][+-]?\d+)?"


def run(command: list[str], check: bool = True) -> subprocess.CompletedProcess[str]:
    proc = subprocess.run(command, capture_output=True, text=True)
    if check and proc.returncode != 0:
        raise RuntimeError(f"command failed ({proc.returncode}): {' '.join(command)}\n{proc.stderr[-2000:]}")
    return proc


def ffprobe(video: str) -> dict[str, Any]:
    proc = run([
        "ffprobe", "-v", "error", "-count_frames",
        "-show_entries",
        "format=duration,size,bit_rate:stream=index,codec_type,codec_name,profile,width,height,"
        "pix_fmt,color_range,color_space,color_transfer,color_primaries,r_frame_rate,avg_frame_rate,"
        "nb_frames,nb_read_frames,sample_rate,channels,channel_layout,start_time,duration",
        "-of", "json", video,
    ])
    return json.loads(proc.stdout)


def parse_black(text: str) -> list[dict[str, float]]:
    out = []
    for match in re.finditer(rf"black_start:({NUMBER})\s+black_end:({NUMBER})\s+black_duration:({NUMBER})", text):
        out.append({"startSec": float(match.group(1)), "endSec": float(match.group(2)),
                    "durationSec": float(match.group(3))})
    return out


def parse_silence(text: str) -> list[dict[str, float]]:
    starts = [float(x) for x in re.findall(rf"silence_start:\s*({NUMBER})", text)]
    ends = [(float(a), float(b)) for a, b in re.findall(
        rf"silence_end:\s*({NUMBER})\s*\|\s*silence_duration:\s*({NUMBER})", text)]
    return [{"startSec": starts[i] if i < len(starts) else max(0.0, end - dur),
             "endSec": end, "durationSec": dur} for i, (end, dur) in enumerate(ends)]


def parse_loudness(text: str) -> dict[str, float | None]:
    summary = text.rsplit("Summary:", 1)[-1]
    def last(pattern: str) -> float | None:
        values = re.findall(pattern, summary)
        return float(values[-1]) if values else None
    return {
        "integratedLufs": last(r"I:\s*(-?[0-9.]+)\s*LUFS"),
        "loudnessRangeLu": last(r"LRA:\s*([0-9.]+)\s*LU"),
        "truePeakDbtp": last(r"Peak:\s*(-?[0-9.]+)\s*dBFS"),
    }


def analyze_media(video: str, black_min: float, silence_db: float,
                  silence_min: float) -> subprocess.CompletedProcess[str]:
    """Decode and measure the exact delivery streams once; any filter/decode error fails QA."""
    return run([
        "ffmpeg", "-hide_banner", "-nostats", "-xerror", "-i", video,
        "-map", "0:v:0", "-map", "0:a:0",
        "-vf", f"blackdetect=d={black_min:g}:pic_th=0.98:pix_th=0.10",
        "-af", f"silencedetect=n={silence_db:g}dB:d={silence_min:g},ebur128=peak=true",
        "-f", "null", "-",
    ], check=False)


def analysis_issues(proc: subprocess.CompletedProcess[str],
                    loudness: dict[str, float | None]) -> list[dict[str, Any]]:
    if proc.returncode != 0:
        return [{"code": "MEDIA_ANALYSIS_FAILED", "severity": "error",
                 "message": f"decode/audio/black analysis failed ({proc.returncode}): {proc.stderr[-1600:]}"}]
    missing = [key for key, value in loudness.items()
               if value is None or not math.isfinite(value)]
    if missing:
        return [{"code": "LOUDNESS_MEASUREMENT_MISSING", "severity": "error",
                 "message": f"could not measure: {', '.join(missing)}"}]
    return []


def audio_coverage_gaps(audio_stream: dict[str, Any], picture_duration: float,
                        fps: float) -> list[dict[str, float]]:
    """silencedetect cannot see silence after an audio stream ends or before it begins."""
    if not audio_stream or audio_stream.get("duration") in (None, "N/A"):
        return []
    start = float(audio_stream.get("start_time") or 0)
    end = start + float(audio_stream["duration"])
    tolerance = container_duration_tolerance(fps)
    gaps = []
    if start > tolerance:
        gaps.append({"startSec": 0.0, "endSec": min(start, picture_duration),
                     "durationSec": min(start, picture_duration)})
    if picture_duration - end > tolerance:
        end = max(0.0, end)
        gaps.append({"startSec": end, "endSec": picture_duration,
                     "durationSec": picture_duration - end})
    return gaps


def loudness_issues(loudness: dict[str, float | None],
                    contract: dict[str, Any]) -> list[dict[str, Any]]:
    issues: list[dict[str, Any]] = []
    try:
        target = float(contract["targetLufs"]) if contract.get("targetLufs") is not None else None
        peak = float(contract["maxTruePeakDbtp"]) if contract.get("maxTruePeakDbtp") is not None else None
        tolerance = float(contract.get("lufsTolerance", 1.0))
        if any(not math.isfinite(value) for value in (target, peak, tolerance) if value is not None) or tolerance < 0:
            raise ValueError("targets must be finite and tolerance non-negative")
    except (ValueError, TypeError) as exc:
        return [{"code": "QA_LOUDNESS_CONFIG_INVALID", "severity": "error", "message": str(exc)}]
    measured_i, measured_peak = loudness.get("integratedLufs"), loudness.get("truePeakDbtp")
    if target is not None and measured_i is not None and abs(measured_i - target) > tolerance:
        issues.append({"code": "LOUDNESS_OUT_OF_RANGE", "severity": "error",
                       "message": f"measured {measured_i} LUFS; target {target} ± {tolerance}"})
    if peak is not None and measured_peak is not None and measured_peak > peak:
        issues.append({"code": "TRUE_PEAK_HIGH", "severity": "error",
                       "message": f"measured {measured_peak} dBTP; maximum {peak}"})
    return issues


def _fraction(value: str | None) -> float | None:
    if not value:
        return None
    try:
        if "/" in value:
            a, b = value.split("/", 1)
            return float(a) / float(b)
        return float(value)
    except (ValueError, ZeroDivisionError):
        return None


def _inside(interval: dict[str, float], allowed: list[dict[str, Any]], tolerance: float = 0.2) -> bool:
    for item in allowed:
        start = float(item.get("startSec", -1)) - tolerance
        end = float(item.get("endSec", -1)) + tolerance
        if interval["startSec"] >= start and interval["endSec"] <= end:
            return True
    return False


def _outside_allowed(intervals: list[dict[str, float]],
                     allowed: list[dict[str, Any]]) -> list[dict[str, float]]:
    return [interval for interval in intervals if not _inside(interval, allowed)]


def canonical_json_sha256(value: Any) -> str:
    payload = json.dumps(value, sort_keys=True, separators=(",", ":")).encode()
    return hashlib.sha256(payload).hexdigest()


def container_duration_tolerance(fps: float) -> float:
    return max(0.10, 3.0 / max(float(fps), 1.0))


def default_sidecar_path(video_dir: str, stem: str, kind: str) -> str:
    preferred = os.path.join(video_dir, f"{stem}.{kind}.json")
    legacy = os.path.join(video_dir, f"{kind}.json")
    if os.path.exists(preferred):
        return preferred
    if os.path.exists(legacy):
        return legacy
    return preferred


def artifact_binding_issues(artifact: dict[str, Any], project: str = "",
                            script_path: str = "", props_path: str = "",
                            props: dict[str, Any] | None = None) -> list[dict[str, Any]]:
    """Bind explicit source inputs to the exact build recorded by artifact.json."""
    issues: list[dict[str, Any]] = []
    if project:
        expected_project = artifact.get("project")
        if not expected_project:
            issues.append({
                "code": "ARTIFACT_PROJECT_MISSING",
                "severity": "error",
                "message": "artifact does not record its source project",
            })
        elif os.path.realpath(str(expected_project)) != os.path.realpath(project):
            issues.append({
                "code": "ARTIFACT_PROJECT_MISMATCH",
                "severity": "error",
                "message": f"artifact project is {expected_project}; QA project is {project}",
            })
        if not script_path or not os.path.exists(script_path):
            issues.append({
                "code": "PROJECT_SCRIPT_MISSING",
                "severity": "error",
                "message": f"project script missing: {script_path}",
            })
        else:
            expected_script = str(artifact.get("scriptSha256") or "").lower()
            actual_script = sha256_file(script_path).lower()
            if not expected_script:
                issues.append({
                    "code": "ARTIFACT_SCRIPT_HASH_MISSING",
                    "severity": "error",
                    "message": "artifact does not record scriptSha256",
                })
            elif expected_script != actual_script:
                issues.append({
                    "code": "SCRIPT_HASH_MISMATCH",
                    "severity": "error",
                    "message": f"artifact expects {expected_script}; script is {actual_script}",
                })
    if props_path:
        if not os.path.exists(props_path):
            issues.append({
                "code": "PROPS_MISSING",
                "severity": "error",
                "message": f"render props missing: {props_path}",
            })
        else:
            expected_props = str(artifact.get("propsSha256") or "").lower()
            actual_props = canonical_json_sha256(props or {}).lower()
            if not expected_props:
                issues.append({
                    "code": "ARTIFACT_PROPS_HASH_MISSING",
                    "severity": "error",
                    "message": "artifact does not record propsSha256",
                })
            elif expected_props != actual_props:
                issues.append({
                    "code": "PROPS_HASH_MISMATCH",
                    "severity": "error",
                    "message": f"artifact expects {expected_props}; props are {actual_props}",
                })
    return issues


def _safe_id(value: str) -> str:
    cleaned = re.sub(r"[^a-zA-Z0-9_-]+", "-", value).strip("-")
    return cleaned or "range"


def _ffmpeg_image(video: str, vf: str, out: str, frames: int = 1) -> None:
    # A successful FFmpeg exit does not imply it emitted a frame (e.g. an empty trim).
    # Clear only the named generated file so a previous run cannot mask missing evidence.
    if os.path.isfile(out):
        os.unlink(out)
    run(["ffmpeg", "-y", "-hide_banner", "-loglevel", "error", "-i", video, "-map", "0:v:0",
         "-vf", vf, "-frames:v", str(frames), out])
    if not os.path.isfile(out) or not os.path.getsize(out):
        raise RuntimeError(f"visual QA produced no image: {out}")


def generate_visuals(video: str, out_dir: str, duration: float, fps: float,
                     props: dict[str, Any], qa_contract: dict[str, Any]) -> dict[str, Any]:
    visuals: dict[str, Any] = {}
    every = max(1.0, float(qa_contract.get("contactEverySec", 5.0)))
    samples = max(1, math.ceil(duration / every))
    rows = math.ceil(samples / 5)
    path = os.path.join(out_dir, "every-5s.png")
    step = max(1, round(every * fps))
    _ffmpeg_image(video, f"select='not(mod(n\\,{step}))',scale=384:216:flags=lanczos,"
                  f"tile=5x{rows}:nb_frames={samples}", path)
    visuals["every5Seconds"] = path

    path = os.path.join(out_dir, "opening.png")
    _ffmpeg_image(video, f"trim=start=0:end=16,setpts=PTS-STARTPTS,"
                  f"select='not(mod(n\\,{max(1, round(fps / 1.5))}))',"
                  "scale=384:216:flags=lanczos,tile=5x5:nb_frames=24", path)
    visuals["opening"] = path

    final_start = max(0.0, duration - 32.0)
    path = os.path.join(out_dir, "ending.png")
    _ffmpeg_image(video, f"trim=start={final_start:.6f},setpts=PTS-STARTPTS,"
                  f"select='not(mod(n\\,{max(1, round(fps * 2))}))',"
                  "scale=384:216:flags=lanczos,tile=5x4:nb_frames=20", path)
    visuals["ending"] = path

    segs = props.get("segments", []) or []
    boundaries: list[int] = []
    cursor = 0
    for seg in segs[:-1]:
        cursor += int(seg.get("durFrames") or round(float(seg.get("durSec", 0)) * fps))
        boundaries.extend([max(0, cursor - 1), cursor])
    if boundaries:
        select = "+".join(f"eq(n\\,{n})" for n in boundaries)
        rows = math.ceil(len(boundaries) / 4)
        path = os.path.join(out_dir, "cut-boundaries.png")
        _ffmpeg_image(video, f"select='{select}',scale=384:216:flags=lanczos,"
                      f"tile=4x{rows}:nb_frames={len(boundaries)}", path)
        visuals["cutBoundaries"] = path

    risk_outputs = []
    risk_ids: set[str] = set()
    for i, item in enumerate(qa_contract.get("criticalRanges", []) or []):
        start = float(item.get("startSec", 0.0))
        end = float(item.get("endSec", start))
        if (not math.isfinite(start) or not math.isfinite(end) or start < 0
                or end <= start or start >= duration or end > duration + 1 / fps):
            raise ValueError(f"critical range {i + 1} is outside the video: {start:g}–{end:g}s")
        end = min(duration, end)
        rid = _safe_id(str(item.get("id") or f"range-{i + 1}"))
        if rid in risk_ids:
            raise ValueError(f"critical range IDs collide after filename sanitization: {rid}")
        risk_ids.add(rid)
        if item.get("everyFrame"):
            start_frame = max(0, round(start * fps))
            end_frame = min(round(duration * fps), round(end * fps))
            count = end_frame - start_frame
            if count <= 0:
                raise ValueError(f"critical range {rid} contains no picture frames")
            pages = math.ceil(count / 15)
            pattern = os.path.join(out_dir, f"critical-{rid}-%02d.png")
            files = [pattern.replace("%02d", f"{n:02d}") for n in range(1, pages + 1)]
            for path in files:
                if os.path.isfile(path):
                    os.unlink(path)
            run(["ffmpeg", "-y", "-hide_banner", "-loglevel", "error", "-i", video,
                 "-map", "0:v:0",
                 "-vf", f"trim=start_frame={start_frame}:end_frame={end_frame},setpts=PTS-STARTPTS,"
                        "scale=384:216:flags=lanczos,tile=5x3:nb_frames=15",
                 "-fps_mode", "passthrough", "-frames:v", str(pages), pattern])
            if any(not os.path.isfile(path) or not os.path.getsize(path) for path in files):
                raise RuntimeError(f"visual QA did not produce every page for critical range {rid}")
            risk_outputs.append({"id": rid, "startSec": start, "endSec": end,
                                 "frames": count, "files": files,
                                 "checks": item.get("checks", [])})
        else:
            rate = min(fps, max(1.0, float(item.get("sampleFps", 5.0))))
            count = max(1, math.ceil((end - start) * rate))
            rows = math.ceil(count / 5)
            path = os.path.join(out_dir, f"critical-{rid}.png")
            _ffmpeg_image(video, f"trim=start={start:.6f}:end={end:.6f},setpts=PTS-STARTPTS,"
                          f"select='not(mod(n\\,{max(1, round(fps / rate))}))',"
                          f"scale=384:216:flags=lanczos,tile=5x{rows}:nb_frames={count}", path)
            risk_outputs.append({"id": rid, "startSec": start, "endSec": end,
                                 "framesSampled": count, "files": [path],
                                 "checks": item.get("checks", [])})
    visuals["criticalRanges"] = risk_outputs
    return visuals


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--video", required=True)
    parser.add_argument("--project", default="", help="project containing script.json")
    parser.add_argument("--props", default="", help="props.json; default beside video")
    parser.add_argument("--artifact", default="", help="artifact.json; default beside video")
    parser.add_argument("--out-dir", default="", help="default: <video-dir>/qa-<video-stem>")
    parser.add_argument("--strict", action="store_true", help="fail on any deterministic delivery issue")
    parser.add_argument("--require-artifact", action="store_true")
    parser.add_argument("--no-visuals", action="store_true")
    parser.add_argument("--force", action="store_true", help="replace generated files in an existing QA directory")
    args = parser.parse_args()

    for binary in ("ffmpeg", "ffprobe"):
        if not shutil.which(binary):
            sys.exit(f"{binary} is required")
    video = os.path.abspath(args.video)
    if not os.path.exists(video):
        sys.exit(f"video not found: {video}")
    video_dir = os.path.dirname(video)
    stem = os.path.splitext(os.path.basename(video))[0]
    out_dir = os.path.abspath(args.out_dir or os.path.join(video_dir, f"qa-{stem}"))
    if os.path.isdir(out_dir) and os.listdir(out_dir) and not args.force:
        sys.exit(f"QA directory is not empty: {out_dir} (pass --force to refresh generated files)")
    os.makedirs(out_dir, exist_ok=True)

    project = os.path.abspath(args.project) if args.project else ""
    script_path = os.path.join(project, "script.json") if project else ""
    script: dict[str, Any] = {}
    if script_path and os.path.exists(script_path):
        with open(script_path) as fh:
            script = json.load(fh)
    props_path = args.props or default_sidecar_path(video_dir, stem, "props")
    if os.path.exists(props_path):
        with open(props_path) as fh:
            props = json.load(fh)
    else:
        props = {}
    production = script.get("production") if isinstance(script.get("production"), dict) else {}
    qa_contract = production.get("qa") or {}

    issues: list[dict[str, Any]] = []
    artifact_path = args.artifact or default_sidecar_path(video_dir, stem, "artifact")
    if os.path.exists(artifact_path):
        with open(artifact_path) as fh:
            artifact = json.load(fh)
    else:
        artifact = None
    digest = sha256_file(video)
    if artifact:
        expected_hash = ((artifact.get("output") or {}).get("sha256") or "").lower()
        if expected_hash != digest.lower():
            issues.append({"code": "ARTIFACT_HASH_MISMATCH", "severity": "error",
                           "message": f"artifact expects {expected_hash}; video is {digest}"})
        issues.extend(artifact_binding_issues(
            artifact,
            project=project if args.project else "",
            script_path=script_path if args.project else "",
            props_path=props_path,
            props=props,
        ))
    elif args.require_artifact:
        issues.append({"code": "ARTIFACT_MISSING", "severity": "error",
                       "message": f"required manifest missing: {artifact_path}"})

    probe = ffprobe(video)
    streams = probe.get("streams", [])
    video_stream = next((s for s in streams if s.get("codec_type") == "video"), {})
    audio_stream = next((s for s in streams if s.get("codec_type") == "audio"), {})
    duration = float((probe.get("format") or {}).get("duration") or 0.0)
    frames = int(video_stream.get("nb_read_frames") or video_stream.get("nb_frames") or 0)
    measured_fps = _fraction(video_stream.get("avg_frame_rate")) or 0.0
    if not video_stream:
        issues.append({"code": "VIDEO_STREAM_MISSING", "severity": "error", "message": "no video stream"})
    if not audio_stream:
        issues.append({"code": "AUDIO_STREAM_MISSING", "severity": "error", "message": "no audio stream"})
    if artifact:
        expected = artifact.get("expected") or {}
        if expected.get("frames") and frames != int(expected["frames"]):
            issues.append({"code": "FRAME_COUNT_MISMATCH", "severity": "error",
                           "message": f"expected {expected['frames']} frames; decoded {frames}"})
        duration_tolerance = container_duration_tolerance(
            float(expected.get("fps") or measured_fps or 30.0)
        )
        if (expected.get("durationSec")
                and abs(duration - float(expected["durationSec"])) > duration_tolerance):
            issues.append({"code": "DURATION_MISMATCH", "severity": "error",
                           "message": f"expected about {expected['durationSec']:.3f}s; "
                                      f"container is {duration:.3f}s "
                                      f"(tolerance {duration_tolerance:.3f}s)"})
        expected_fps = expected.get("fps")
        if expected_fps is not None and abs(measured_fps - float(expected_fps)) > 0.001:
            issues.append({"code": "FPS_MISMATCH", "severity": "error",
                           "message": f"expected {float(expected_fps):g} fps; decoded {measured_fps:g}"})
        media_expectations = {
            "width": (video_stream, "width"),
            "height": (video_stream, "height"),
            "videoCodec": (video_stream, "codec_name"),
            "audioCodec": (audio_stream, "codec_name"),
            "pixelFormat": (video_stream, "pix_fmt"),
            "colorSpace": (video_stream, "color_space"),
            "colorTransfer": (video_stream, "color_transfer"),
            "colorPrimaries": (video_stream, "color_primaries"),
            "colorRange": (video_stream, "color_range"),
            "sampleRate": (audio_stream, "sample_rate"),
            "channels": (audio_stream, "channels"),
        }
        for contract_key, (media_stream, stream_key) in media_expectations.items():
            wanted = expected.get(contract_key)
            if wanted is None:
                continue
            observed_value = media_stream.get(stream_key)
            if str(observed_value).lower() != str(wanted).lower():
                issues.append({"code": f"{contract_key.upper()}_MISMATCH", "severity": "error",
                               "message": f"expected {contract_key}={wanted}; decoded {observed_value}"})

    black_min = float(qa_contract.get("blackMinSec", 0.1))
    silence_db = float(qa_contract.get("silenceNoiseDb", -48.0))
    silence_min = float(qa_contract.get("silenceMinSec", 0.7))
    analysis = analyze_media(video, black_min, silence_db, silence_min)
    loudness = parse_loudness(analysis.stderr)
    issues.extend(analysis_issues(analysis, loudness))
    black = parse_black(analysis.stderr)
    allowed_black = qa_contract.get("allowedBlackRanges", []) or []
    unintended_black = _outside_allowed(black, allowed_black)
    if unintended_black:
        issues.append({"code": "BLACK_INTERVALS", "severity": "error",
                       "message": f"{len(unintended_black)} unintended black interval(s) detected",
                       "intervals": unintended_black})
    silence = parse_silence(analysis.stderr)
    coverage_gaps = audio_coverage_gaps(
        audio_stream, frames / measured_fps if measured_fps and frames else duration,
        measured_fps or 30.0,
    )
    allowed_silence = qa_contract.get("allowedSilenceRanges", []) or []
    unintended = _outside_allowed(silence + coverage_gaps, allowed_silence)
    if unintended:
        issues.append({"code": "UNINTENDED_SILENCE", "severity": "error",
                       "message": f"{len(unintended)} unintended silence interval(s)", "intervals": unintended})
    issues.extend(loudness_issues(loudness, qa_contract))

    narration_continuity: dict[str, Any] = {}
    policy = str(production.get("narrationCutPolicy", "") or "")
    narration_map = script.get("narrationMap") if isinstance(script.get("narrationMap"), list) else []
    if policy == "between-thoughts" and narration_map:
        boundary_seconds: list[float] = []
        frame_cursor = 0
        prop_fps = float(props.get("fps") or measured_fps or 30.0)
        for segment in (props.get("segments") or [])[:-1]:
            frames_in_segment = int(segment.get("durFrames")
                                    or round(float(segment.get("durSec", 0.0)) * prop_fps))
            frame_cursor += frames_in_segment
            boundary_seconds.append(frame_cursor / prop_fps)
        boundary_tolerance = float(production.get("narrationBoundaryToleranceSec", 0.05))
        conflicts = narration_cut_conflicts(narration_map, boundary_seconds, boundary_tolerance)
        for conflict in conflicts:
            entry = conflict["entry"]
            label = str(entry.get("id") or entry.get("beat") or f"cue-{conflict['cueIndex'] + 1}")
            issues.append({
                "code": "NARRATION_THOUGHT_CUT",
                "severity": "error",
                "message": f"picture cut at {conflict['cutSec']:.3f}s lands inside narration cue {label}",
                "cutSec": conflict["cutSec"],
                "cue": label,
            })
        last_cue_end = max((float(entry.get("endSec", 0.0) or 0.0)
                            for entry in narration_map if isinstance(entry, dict)), default=0.0)
        narration_continuity = {
            "policy": policy,
            "cues": len(narration_map),
            "pictureCuts": len(boundary_seconds),
            "thoughtCuts": len(conflicts),
            "lastCueEndSec": last_cue_end,
            "pictureTailAfterLastCueSec": round(duration - last_cue_end, 6),
        }

    visuals = {}
    if not args.no_visuals:
        try:
            visuals = generate_visuals(video, out_dir, duration, measured_fps or 30.0, props, qa_contract)
        except (RuntimeError, ValueError) as exc:
            issues.append({"code": "VISUAL_QA_FAILED", "severity": "error", "message": str(exc)})
    report = {
        "schemaVersion": 1,
        "status": "pass" if not any(i["severity"] == "error" for i in issues) else "fail",
        "video": {"path": video, "sha256": digest, "bytes": os.path.getsize(video)},
        "artifact": ({"path": os.path.abspath(artifact_path), "buildId": artifact.get("buildId")}
                     if artifact else None),
        "media": {"durationSec": duration, "frames": frames, "fps": measured_fps,
                  "video": video_stream, "audio": audio_stream},
        "audio": {**loudness, "silenceThresholdDb": silence_db,
                  "silenceMinSec": silence_min, "detectedSilence": silence,
                  "coverageGaps": coverage_gaps,
                  "unintendedSilence": unintended},
        "narrationContinuity": narration_continuity,
        "blackIntervals": black,
        "unintendedBlackIntervals": unintended_black,
        "fullDecode": "pass" if analysis.returncode == 0 else "fail",
        "issues": issues,
        "visualQa": visuals,
    }
    report_path = os.path.join(out_dir, "qa-report.json")
    with open(report_path, "w") as fh:
        json.dump(report, fh, indent=2)
        fh.write("\n")
    print(json.dumps({"status": report["status"], "report": report_path,
                      "sha256": digest, "durationSec": duration, "frames": frames,
                      "loudness": loudness, "issues": issues}, indent=2))
    if args.strict and report["status"] != "pass":
        sys.exit(1)


if __name__ == "__main__":
    main()
