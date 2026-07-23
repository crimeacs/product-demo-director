#!/usr/bin/env python3
"""Create a web-safe, loudness-normalized delivery master and a new bound artifact.

The creative render is an intermediate. This step preserves its exact picture frame count while
converting the export to limited-range BT.709/yuv420p, applying measured two-pass EBU R128 audio
normalization, and publishing a finish manifest that retains the build's source provenance.
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
import tempfile
from typing import Any

from contracts import sha256_file


def run(command: list[str], check: bool = True) -> subprocess.CompletedProcess[str]:
    proc = subprocess.run(command, capture_output=True, text=True)
    if check and proc.returncode != 0:
        raise RuntimeError(f"command failed ({proc.returncode}): {' '.join(command)}\n{proc.stderr[-2000:]}")
    return proc


def load_json(path: str) -> dict[str, Any]:
    with open(path) as fh:
        return json.load(fh)


def write_json(path: str, value: Any) -> None:
    os.makedirs(os.path.dirname(os.path.abspath(path)), exist_ok=True)
    fd, temp = tempfile.mkstemp(prefix=f".{os.path.basename(path)}.",
                                dir=os.path.dirname(os.path.abspath(path)))
    try:
        with os.fdopen(fd, "w") as fh:
            json.dump(value, fh, indent=2)
            fh.write("\n")
        os.replace(temp, path)
    finally:
        if os.path.exists(temp):
            os.unlink(temp)


def probe(path: str) -> dict[str, Any]:
    proc = run([
        "ffprobe", "-v", "error", "-count_frames", "-show_entries",
        "format=duration,size,bit_rate:stream=index,codec_type,codec_name,width,height,pix_fmt,"
        "color_range,color_space,color_transfer,color_primaries,r_frame_rate,avg_frame_rate,"
        "nb_frames,nb_read_frames,sample_rate,channels,channel_layout",
        "-of", "json", path,
    ])
    return json.loads(proc.stdout)


def stream(probe_data: dict[str, Any], kind: str) -> dict[str, Any]:
    return next((item for item in probe_data.get("streams", [])
                 if item.get("codec_type") == kind), {})


def frame_count(probe_data: dict[str, Any]) -> int:
    item = stream(probe_data, "video")
    return int(item.get("nb_read_frames") or item.get("nb_frames") or 0)


def fraction(value: Any) -> float:
    text = str(value or "0")
    if "/" in text:
        numerator, denominator = text.split("/", 1)
        return float(numerator) / float(denominator)
    return float(text)


def parse_loudnorm_json(text: str) -> dict[str, float]:
    blocks = re.findall(r"\{\s*\"input_i\".*?\}", text, re.S)
    if not blocks:
        raise ValueError("FFmpeg loudnorm measurement did not return JSON")
    raw = json.loads(blocks[-1])
    mapping = {
        "measured_I": "input_i",
        "measured_TP": "input_tp",
        "measured_LRA": "input_lra",
        "measured_thresh": "input_thresh",
        "offset": "target_offset",
    }
    result = {output: float(raw[source]) for output, source in mapping.items()}
    if not all(math.isfinite(value) for value in result.values()):
        raise ValueError(f"audio cannot be normalized from non-finite measurements: {raw}")
    return result


def loudnorm_measure(path: str, target_i: float, target_lra: float,
                     target_tp: float) -> dict[str, float]:
    proc = run([
        "ffmpeg", "-hide_banner", "-nostats", "-i", path, "-map", "0:a:0", "-af",
        f"loudnorm=I={target_i:g}:LRA={target_lra:g}:TP={target_tp:g}:print_format=json",
        "-vn", "-f", "null", "-",
    ], check=False)
    if proc.returncode != 0:
        raise RuntimeError(f"loudness measurement failed: {proc.stderr[-1600:]}")
    return parse_loudnorm_json(proc.stderr)


def colorspace_filter(video_stream: dict[str, Any]) -> str:
    # Chromium/Remotion H.264 commonly arrives as full-range yuvj420p with an SD matrix label but
    # missing primaries/TRC. Fill only missing input metadata, then perform a real BT.709 transform.
    space = video_stream.get("color_space")
    if space not in {"bt709", "bt470bg", "smpte170m", "smpte240m", "fcc"}:
        space = "bt709"
    primaries = video_stream.get("color_primaries")
    if primaries not in {"bt709", "bt470bg", "smpte170m", "smpte240m", "bt470m"}:
        primaries = "bt709"
    transfer = video_stream.get("color_transfer")
    if transfer not in {"bt709", "bt470bg", "smpte170m", "smpte240m", "bt470m", "iec61966-2-1"}:
        transfer = "bt709"
    color_range = video_stream.get("color_range")
    if color_range not in {"pc", "tv"}:
        color_range = "pc" if str(video_stream.get("pix_fmt", "")).startswith("yuvj") else "tv"
    return (f"colorspace=ispace={space}:iprimaries={primaries}:itrc={transfer}:irange={color_range}:"
            "all=bt709:range=tv:format=yuv420p")


def default_sidecar(input_path: str, kind: str) -> str:
    stem = os.path.splitext(os.path.abspath(input_path))[0]
    preferred = f"{stem}.{kind}.json"
    legacy = os.path.join(os.path.dirname(stem), f"{kind}.json")
    return preferred if os.path.exists(preferred) or not os.path.exists(legacy) else legacy


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input", required=True, help="creative render")
    parser.add_argument("--out", required=True, help="finished delivery MP4")
    parser.add_argument("--artifact", default="", help="input artifact; default stem-specific then legacy")
    parser.add_argument("--props", default="", help="input props; default stem-specific then legacy")
    parser.add_argument("--require-artifact", action="store_true")
    parser.add_argument("--target-lufs", type=float, default=-18.0)
    parser.add_argument("--target-lra", type=float, default=7.0)
    parser.add_argument("--true-peak", type=float, default=-1.5)
    parser.add_argument("--crf", type=int, default=18)
    parser.add_argument("--preset", default="slow")
    parser.add_argument("--audio-bitrate", default="192k")
    parser.add_argument("--no-loudnorm", action="store_true")
    args = parser.parse_args()

    for binary in ("ffmpeg", "ffprobe"):
        if not shutil.which(binary):
            raise SystemExit(f"{binary} is required")
    source = os.path.abspath(args.input)
    output = os.path.abspath(args.out)
    if not os.path.isfile(source):
        raise SystemExit(f"input not found: {source}")
    if source == output:
        raise SystemExit("--out must differ from --input; finishing is a separate provenance step")
    os.makedirs(os.path.dirname(output), exist_ok=True)

    source_probe = probe(source)
    source_video = stream(source_probe, "video")
    source_audio = stream(source_probe, "audio")
    if not source_video or not source_audio:
        raise SystemExit("finish requires one video stream and one audio stream")
    source_frames = frame_count(source_probe)
    if source_frames <= 0:
        raise SystemExit("could not determine input picture frame count")
    source_fps = fraction(source_video.get("avg_frame_rate") or source_video.get("r_frame_rate"))
    if source_fps <= 0:
        raise SystemExit("could not determine input picture frame rate")
    picture_duration = source_frames / source_fps

    artifact_path = os.path.abspath(args.artifact or default_sidecar(source, "artifact"))
    parent = load_json(artifact_path) if os.path.exists(artifact_path) else None
    source_hash = sha256_file(source)
    if parent:
        expected_hash = str((parent.get("output") or {}).get("sha256") or "").lower()
        if expected_hash != source_hash.lower():
            raise SystemExit(f"input artifact hash mismatch: {expected_hash or 'missing'} != {source_hash}")
    elif args.require_artifact:
        raise SystemExit(f"input artifact required but missing: {artifact_path}")
    # A legacy generic artifact in the same directory would otherwise be overwritten by the
    # finished artifact. Promote it to the input stem first so the parent link remains resolvable.
    generic_output_artifact = os.path.join(os.path.dirname(output), "artifact.json")
    if (parent and os.path.realpath(artifact_path) == os.path.realpath(generic_output_artifact)):
        stable_parent = f"{os.path.splitext(source)[0]}.artifact.json"
        write_json(stable_parent, parent)
        artifact_path = stable_parent
    props_path = os.path.abspath(args.props or default_sidecar(source, "props"))
    props = load_json(props_path) if os.path.exists(props_path) else None
    if parent and parent.get("propsSha256"):
        if props is None:
            raise SystemExit(f"input props required by artifact but missing: {props_path}")
        actual_props = hashlib.sha256(json.dumps(
            props, sort_keys=True, separators=(",", ":")).encode()).hexdigest()
        if actual_props.lower() != str(parent["propsSha256"]).lower():
            raise SystemExit("input props hash does not match artifact")

    finish_config = {
        "targetLufs": None if args.no_loudnorm else args.target_lufs,
        "targetLra": None if args.no_loudnorm else args.target_lra,
        "truePeakDbtp": None if args.no_loudnorm else args.true_peak,
        "videoCodec": "libx264", "crf": args.crf, "preset": args.preset,
        "pixelFormat": "yuv420p", "color": "bt709-tv", "audioCodec": "aac",
        "audioBitrate": args.audio_bitrate, "sampleRate": 48000,
        "durationPolicy": "picture-frames",
    }
    identity_blob = json.dumps({"input": source_hash, "config": finish_config},
                               sort_keys=True, separators=(",", ":")).encode()
    finish_id = hashlib.sha256(identity_blob).hexdigest()[:16]

    audio_filter = "aresample=48000"
    measurement = None
    if not args.no_loudnorm:
        measurement = loudnorm_measure(source, args.target_lufs, args.target_lra, args.true_peak)
        audio_filter = (
            f"loudnorm=I={args.target_lufs:g}:LRA={args.target_lra:g}:TP={args.true_peak:g}:"
            f"measured_I={measurement['measured_I']:g}:measured_LRA={measurement['measured_LRA']:g}:"
            f"measured_TP={measurement['measured_TP']:g}:measured_thresh={measurement['measured_thresh']:g}:"
            f"offset={measurement['offset']:g}:linear=true:print_format=summary,aresample=48000"
        )
    # Filters such as loudnorm can add a short audio tail. Bind delivery duration to the exact
    # picture frame count so MP4 container duration cannot drift beyond the authored timeline.
    audio_filter += f",atrim=end={picture_duration:.9f},asetpts=PTS-STARTPTS"

    suffix = os.path.splitext(output)[1] or ".mp4"
    fd, temp_output = tempfile.mkstemp(prefix=f".{os.path.basename(output)}.{finish_id}.",
                                       suffix=suffix, dir=os.path.dirname(output))
    os.close(fd)
    os.unlink(temp_output)  # FFmpeg expects to create the output itself.
    command = [
        "ffmpeg", "-y", "-hide_banner", "-loglevel", "error", "-i", source,
        "-map", "0:v:0", "-map", "0:a:0", "-vf", colorspace_filter(source_video),
        "-af", audio_filter, "-c:v", "libx264", "-crf", str(args.crf),
        "-preset", args.preset, "-pix_fmt", "yuv420p", "-fps_mode", "passthrough",
        "-color_range", "tv", "-colorspace", "bt709", "-color_primaries", "bt709",
        "-color_trc", "bt709", "-c:a", "aac", "-b:a", args.audio_bitrate, "-ar", "48000",
        "-t", f"{picture_duration:.9f}", "-movflags", "+faststart", temp_output,
    ]
    try:
        run(command)
        finished_probe = probe(temp_output)
        finished_frames = frame_count(finished_probe)
        if finished_frames != source_frames:
            raise RuntimeError(f"finish changed picture frames: input={source_frames}, output={finished_frames}")
        os.replace(temp_output, output)
    finally:
        if os.path.exists(temp_output):
            os.unlink(temp_output)

    expected = dict((parent or {}).get("expected") or {})
    expected.update({"frames": source_frames,
                     "fps": float(expected.get("fps") or source_fps),
                     "width": int(source_video.get("width") or 0),
                     "height": int(source_video.get("height") or 0),
                     "videoCodec": "h264", "audioCodec": "aac",
                     "pixelFormat": "yuv420p", "colorSpace": "bt709",
                     "colorTransfer": "bt709", "colorPrimaries": "bt709",
                     "colorRange": "tv", "sampleRate": 48000})
    finished_artifact = {
        "schemaVersion": 2,
        "artifactType": "finished-delivery",
        "buildId": (parent or {}).get("buildId"),
        "finishId": finish_id,
        "project": (parent or {}).get("project"),
        "scriptSha256": (parent or {}).get("scriptSha256"),
        "propsSha256": (parent or {}).get("propsSha256"),
        "parentArtifact": ({"path": artifact_path, "sha256": sha256_file(artifact_path),
                            "outputSha256": source_hash} if parent else None),
        "finishConfig": finish_config,
        "loudnormMeasurement": measurement,
        "expected": expected,
        "observed": finished_probe,
        "output": {"path": output, "sha256": sha256_file(output),
                   "bytes": os.path.getsize(output)},
        "inputs": (parent or {}).get("inputs", []),
    }
    output_base = os.path.splitext(output)[0]
    if props is not None:
        write_json(f"{output_base}.props.json", props)
        write_json(os.path.join(os.path.dirname(output), "props.json"), props)
    source_plan = default_sidecar(source, "build-plan")
    if os.path.exists(source_plan):
        plan = load_json(source_plan)
        write_json(f"{output_base}.build-plan.json", plan)
        write_json(os.path.join(os.path.dirname(output), "build-plan.json"), plan)
    stem_artifact = f"{output_base}.artifact.json"
    write_json(stem_artifact, finished_artifact)
    write_json(os.path.join(os.path.dirname(output), "artifact.json"), finished_artifact)
    print(json.dumps({"status": "pass", "output": output, "artifact": stem_artifact,
                      "finishId": finish_id, "frames": source_frames,
                      "sha256": finished_artifact["output"]["sha256"]}, indent=2))


if __name__ == "__main__":
    main()
