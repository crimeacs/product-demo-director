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
        "nb_frames,nb_read_frames,sample_rate,channels,channel_layout",
        "-of", "json", video,
    ])
    return json.loads(proc.stdout)


def parse_black(text: str) -> list[dict[str, float]]:
    out = []
    for match in re.finditer(r"black_start:([0-9.]+)\s+black_end:([0-9.]+)\s+black_duration:([0-9.]+)", text):
        out.append({"startSec": float(match.group(1)), "endSec": float(match.group(2)),
                    "durationSec": float(match.group(3))})
    return out


def parse_silence(text: str) -> list[dict[str, float]]:
    starts = [float(x) for x in re.findall(r"silence_start:\s*([0-9.]+)", text)]
    ends = [(float(a), float(b)) for a, b in re.findall(
        r"silence_end:\s*([0-9.]+)\s*\|\s*silence_duration:\s*([0-9.]+)", text)]
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
    run(["ffmpeg", "-y", "-hide_banner", "-loglevel", "error", "-i", video,
         "-vf", vf, "-frames:v", str(frames), out])


def generate_visuals(video: str, out_dir: str, duration: float, fps: float,
                     props: dict[str, Any], qa_contract: dict[str, Any]) -> dict[str, Any]:
    visuals: dict[str, Any] = {}
    every = max(1.0, float(qa_contract.get("contactEverySec", 5.0)))
    samples = max(1, math.ceil(duration / every))
    rows = math.ceil(samples / 5)
    path = os.path.join(out_dir, "every-5s.png")
    _ffmpeg_image(video, f"fps=1/{every:g},scale=384:216:flags=lanczos,tile=5x{rows}:nb_frames={samples}", path)
    visuals["every5Seconds"] = path

    intro_samples = 24
    path = os.path.join(out_dir, "opening.png")
    _ffmpeg_image(video, "trim=start=0:end=16,setpts=PTS-STARTPTS,fps=3/2,"
                  "scale=384:216:flags=lanczos,tile=5x5:nb_frames=24", path)
    visuals["opening"] = path

    final_start = max(0.0, duration - 32.0)
    path = os.path.join(out_dir, "ending.png")
    _ffmpeg_image(video, f"trim=start={final_start:.6f},setpts=PTS-STARTPTS,fps=1/2,"
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
    for i, item in enumerate(qa_contract.get("criticalRanges", []) or []):
        start = float(item.get("startSec", 0.0))
        end = float(item.get("endSec", start))
        if end <= start:
            continue
        rid = _safe_id(str(item.get("id") or f"range-{i + 1}"))
        if item.get("everyFrame"):
            start_frame = max(0, round(start * fps))
            end_frame = min(round(duration * fps), round(end * fps))
            count = max(1, end_frame - start_frame)
            pages = math.ceil(count / 15)
            pattern = os.path.join(out_dir, f"critical-{rid}-%02d.png")
            run(["ffmpeg", "-y", "-hide_banner", "-loglevel", "error", "-i", video,
                 "-vf", f"trim=start_frame={start_frame}:end_frame={end_frame},setpts=PTS-STARTPTS,"
                        "scale=384:216:flags=lanczos,tile=5x3:nb_frames=15",
                 "-vsync", "0", "-frames:v", str(pages), pattern])
            files = [pattern.replace("%02d", f"{n:02d}") for n in range(1, pages + 1)]
            risk_outputs.append({"id": rid, "startSec": start, "endSec": end,
                                 "frames": count, "files": files,
                                 "checks": item.get("checks", [])})
        else:
            rate = max(1.0, float(item.get("sampleFps", 5.0)))
            count = max(1, math.ceil((end - start) * rate))
            rows = math.ceil(count / 5)
            path = os.path.join(out_dir, f"critical-{rid}.png")
            _ffmpeg_image(video, f"trim=start={start:.6f}:end={end:.6f},setpts=PTS-STARTPTS,"
                          f"fps={rate:g},scale=384:216:flags=lanczos,tile=5x{rows}:nb_frames={count}", path)
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

    decode = run(["ffmpeg", "-v", "error", "-i", video, "-map", "0:v:0", "-map", "0:a:0", "-f", "null", "-"], check=False)
    if decode.returncode != 0:
        issues.append({"code": "DECODE_FAILED", "severity": "error", "message": decode.stderr[-1000:]})
    black_min = float(qa_contract.get("blackMinSec", 0.1))
    black_proc = run(["ffmpeg", "-hide_banner", "-nostats", "-i", video, "-vf",
                      f"blackdetect=d={black_min}:pic_th=0.98:pix_th=0.10", "-an", "-f", "null", "-"], check=False)
    black = parse_black(black_proc.stderr)
    allowed_black = qa_contract.get("allowedBlackRanges", []) or []
    unintended_black = _outside_allowed(black, allowed_black)
    if unintended_black:
        issues.append({"code": "BLACK_INTERVALS", "severity": "error",
                       "message": f"{len(unintended_black)} unintended black interval(s) detected",
                       "intervals": unintended_black})
    silence_db = float(qa_contract.get("silenceNoiseDb", -48.0))
    silence_min = float(qa_contract.get("silenceMinSec", 0.7))
    silence_proc = run(["ffmpeg", "-hide_banner", "-nostats", "-i", video, "-af",
                        f"silencedetect=n={silence_db:g}dB:d={silence_min:g}", "-vn", "-f", "null", "-"], check=False)
    silence = parse_silence(silence_proc.stderr)
    allowed_silence = qa_contract.get("allowedSilenceRanges", []) or []
    unintended = _outside_allowed(silence, allowed_silence)
    if unintended:
        issues.append({"code": "UNINTENDED_SILENCE", "severity": "error",
                       "message": f"{len(unintended)} unintended silence interval(s)", "intervals": unintended})
    loud_proc = run(["ffmpeg", "-hide_banner", "-nostats", "-i", video, "-filter_complex",
                     "ebur128=peak=true", "-f", "null", "-"], check=False)
    loudness = parse_loudness(loud_proc.stderr)
    target_lufs = qa_contract.get("targetLufs")
    if target_lufs is not None and loudness["integratedLufs"] is not None:
        tolerance = float(qa_contract.get("lufsTolerance", 1.0))
        if abs(float(loudness["integratedLufs"]) - float(target_lufs)) > tolerance:
            issues.append({"code": "LOUDNESS_OUT_OF_RANGE", "severity": "error",
                           "message": f"measured {loudness['integratedLufs']} LUFS; target {target_lufs} ± {tolerance}"})
    max_peak = qa_contract.get("maxTruePeakDbtp")
    if max_peak is not None and loudness["truePeakDbtp"] is not None:
        if float(loudness["truePeakDbtp"]) > float(max_peak):
            issues.append({"code": "TRUE_PEAK_HIGH", "severity": "error",
                           "message": f"measured {loudness['truePeakDbtp']} dBTP; maximum {max_peak}"})

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

    visuals = {} if args.no_visuals else generate_visuals(video, out_dir, duration, measured_fps or 30.0,
                                                           props, qa_contract)
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
                  "unintendedSilence": unintended},
        "narrationContinuity": narration_continuity,
        "blackIntervals": black,
        "unintendedBlackIntervals": unintended_black,
        "fullDecode": "pass" if decode.returncode == 0 else "fail",
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
