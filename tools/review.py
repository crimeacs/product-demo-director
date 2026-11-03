#!/usr/bin/env python3
"""Build a private, offline review room for a project's story and delivery evidence."""

from __future__ import annotations

import argparse
from datetime import datetime, timezone
import hashlib
import html
import json
import math
import os
from pathlib import Path
import shutil
import subprocess
import tempfile
from urllib.parse import quote

try:
    from .contracts import sha256_file, validate_script, narration_cue_shots
except ImportError:
    from contracts import sha256_file, validate_script, narration_cue_shots


def read_object(path: Path) -> dict:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ValueError(f"{path.name} must contain a JSON object")
    return value


def finite(value, default=0.0) -> float:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return default
    return number if math.isfinite(number) else default


def relative_url(path: Path, directory: Path) -> str:
    return quote(Path(os.path.relpath(path, directory)).as_posix(), safe="/")


def sidecar(video: Path, kind: str) -> Path:
    specific = video.with_suffix(f".{kind}.json")
    return specific if specific.exists() else video.parent / f"{kind}.json"


def bound_editorial(path: Path | None, artifact: dict, delivery_matches: bool) -> dict:
    """Read advisory evidence only when it belongs to the selected rendered props."""
    unavailable = {"available": False, "reason": "No matching editorial report for this rendered cut."}
    if not path or not path.is_file() or not delivery_matches:
        return unavailable
    try:
        report = read_object(path)
        if (report.get("buildId") != artifact.get("buildId")
                or report.get("propsSha256") != artifact.get("propsSha256")):
            return unavailable
        if (report.get("schemaVersion") != 1 or report.get("advisory") is not True
                or report.get("status") not in ("invalid", "needs-review", "unknown", "clear-declared")
                or not isinstance(report.get("metrics"), dict)
                or not isinstance(report.get("findings"), list)):
            raise ValueError("unsupported editorial report")
        metrics = {}
        for key in ("firstDeclaredProofSec", "setupRatio", "navigationRatio", "anchoredCueCount", "cueCount"):
            value = report["metrics"].get(key)
            if value is not None and (isinstance(value, bool) or not isinstance(value, (int, float))
                                      or not math.isfinite(value) or value < 0):
                raise ValueError("invalid editorial metric")
            metrics[key] = value
        findings = []
        for item in report["findings"]:
            if (not isinstance(item, dict) or item.get("severity") not in ("error", "warning", "info")
                    or not isinstance(item.get("code"), str) or not isinstance(item.get("message"), str)):
                raise ValueError("invalid editorial finding")
            finding = {key: item[key] for key in ("severity", "code", "message")}
            if type(item.get("shot")) is int:
                finding["shot"] = item["shot"]
            findings.append(finding)
        return {"available": True, "status": report["status"], "metrics": metrics, "findings": findings}
    except (OSError, ValueError, OverflowError):
        return {"available": False, "reason": "The matching editorial report could not be read. Rebuild to regenerate it."}


def bound_framing(path: Path | None, artifact: dict, delivery_matches: bool) -> dict:
    """Expose declared readability estimates only for the exact selected picture."""
    unavailable = {"available": False, "reason": "Readability is unknown: no matching subject measurements for this rendered cut."}
    if not path or not path.is_file() or not delivery_matches:
        return unavailable
    try:
        plan = read_object(path)
        if (plan.get("buildId") != artifact.get("buildId")
                or plan.get("propsSha256") != artifact.get("propsSha256")):
            return unavailable
        if plan.get("schemaVersion") != 1 or not isinstance(plan.get("shots"), list):
            raise ValueError("unsupported direction plan")

        def number(value, *, nullable=False, minimum=0):
            if nullable and value is None:
                return None
            if (isinstance(value, bool) or not isinstance(value, (int, float))
                    or not math.isfinite(value) or value < minimum):
                raise ValueError("invalid framing measurement")
            return value

        shots, unreported = [], []
        for row in plan["shots"]:
            if not isinstance(row, dict) or type(row.get("n")) is not int:
                raise ValueError("invalid framing shot")
            report = row.get("framingReport")
            if report is None:
                unreported.append(row["n"])
                continue
            if (not isinstance(report, dict) or report.get("schemaVersion") != 1
                    or report.get("advisory") is not True
                    or report.get("status") not in ("needs-review", "unknown", "clear-declared")
                    or not isinstance(report.get("beats"), list) or not report["beats"]
                    or not isinstance(report.get("findings"), list)):
                raise ValueError("unsupported framing report")
            presentation = report.get("presentation", "camera")
            if presentation not in ("camera", "detail"):
                raise ValueError("unsupported framing presentation")
            beats, findings = [], []
            for beat in report["beats"]:
                if (not isinstance(beat, dict) or not isinstance(beat.get("label"), str)
                        or not isinstance(beat.get("camera"), dict)
                        or type(beat.get("subjectVisible")) is not bool or type(beat.get("safeAreaMet")) is not bool):
                    raise ValueError("invalid framing beat")
                start, end = number(beat.get("atSec")), number(beat.get("endSec"))
                if end < start:
                    raise ValueError("invalid framing window")
                # A contained native detail can occupy less than one full-source frame.
                # Its equivalent scale is positive, unlike a camera zoom constrained to >= 1.
                scale = number(beat["camera"].get("scale"), minimum=0 if presentation == "detail" else 1)
                if scale == 0:
                    raise ValueError("invalid framing scale")
                beats.append({"label": beat["label"], "atSec": start, "endSec": end,
                              "projectedTextPx": number(beat.get("projectedTextPx"), nullable=True),
                              "scale": scale,
                              "subjectVisible": beat["subjectVisible"], "safeAreaMet": beat["safeAreaMet"]})
            for item in report["findings"]:
                if (not isinstance(item, dict) or item.get("severity") not in ("warning", "info")
                        or not isinstance(item.get("code"), str) or not isinstance(item.get("message"), str)):
                    raise ValueError("invalid framing finding")
                findings.append({"severity": item["severity"], "code": item["code"],
                                 "message": item["message"], "shot": row["n"]})
            shots.append({"n": row["n"], "status": report["status"],
                          "viewerWidthPx": number(report.get("viewerWidthPx"), minimum=1),
                          "minTextPx": number(report.get("minTextPx"), minimum=1),
                          "beats": beats, "findings": findings})
        return {"available": True, "shots": shots, "unreportedShots": unreported} if shots else unavailable
    except (OSError, ValueError, OverflowError):
        return {"available": False, "reason": "Readability is unknown: the matching direction report could not be read. Rebuild to regenerate it."}


def collect_review(project: Path, destination: Path, video: Path | None = None) -> dict:
    project = project.resolve()
    script_path = project / "script.json"
    script = read_object(script_path)
    if not isinstance(script.get("shots"), list) or not script["shots"]:
        raise ValueError("script.json needs a non-empty shots array")
    issues = []

    def issue(code, message, severity="error"):
        issues.append({"code": code, "message": message, "severity": severity})

    def optional(path):
        if not path.exists():
            return {}
        try:
            return read_object(path)
        except (OSError, ValueError) as exc:
            issue("REPORT_INVALID", f"{path.name}: {exc}")
            return {}

    def object_field(value, key):
        field = value.get(key)
        if field is not None and not isinstance(field, dict):
            issue("REPORT_INVALID", f"Receipt field {key} must be an object.")
        return field if isinstance(field, dict) else {}

    def array_field(value, key):
        field = value.get(key)
        if field is not None and not isinstance(field, list):
            issue("REPORT_INVALID", f"Receipt field {key} must be an array.")
        return field if isinstance(field, list) else []

    try:
        issues.extend(item.as_dict() for item in validate_script(script, str(project)))
    except (ValueError, TypeError, KeyError, AttributeError, OverflowError) as exc:
        issue("SCRIPT_INVALID", f"The production contract could not be checked: {exc}")

    if video is None:
        video = next((project / "out" / name for name in ("demo-final.mp4", "demo.mp4")
                      if (project / "out" / name).is_file()), None)
    elif not video.is_file():
        raise ValueError(f"Video does not exist: {video}")
    digest = sha256_file(str(video)) if video else None
    artifact_path = sidecar(video, "artifact") if video else None
    artifact = optional(artifact_path) if artifact_path else {}
    plan_path = sidecar(video, "build-plan") if video else project / "out" / "build-plan.json"
    plan = optional(plan_path)
    qa_path = video.parent / f"qa-{video.stem}" / "qa-report.json" if video else None
    qa = optional(qa_path) if qa_path else {}
    script_hash = sha256_file(str(script_path))
    artifact_output = object_field(artifact, "output")
    identity = all(isinstance(artifact.get(key), str) and artifact[key].strip()
                   for key in ("buildId", "propsSha256", "scriptSha256"))
    artifact_matches = bool(artifact and identity and artifact_output.get("sha256") == digest)
    props_matches = False
    script_matches = bool(artifact and artifact.get("scriptSha256") == script_hash)
    if video and not artifact_matches:
        issue("DELIVERY_UNBOUND", "This video has no matching artifact receipt. Render and verify it before delivery.")
    if artifact and not script_matches:
        issue("STORY_CHANGED", "The script has changed since this video was rendered. Rebuild to review the current story.")
    if artifact_matches:
        for source in array_field(artifact, "inputs"):
            if (not isinstance(source, dict) or not isinstance(source.get("path"), str)
                    or not source.get("path") or not isinstance(source.get("sha256"), str)):
                issue("SOURCE_INVALID", "A render input is missing its path or hash.")
                continue
            path = Path(source["path"])
            if not path.is_absolute():
                path = project / path
            if not path.is_file():
                issue("SOURCE_MISSING", f"A bound render input is missing: {source.get('name') or path.name}")
            elif sha256_file(str(path)) != source.get("sha256"):
                issue("SOURCE_CHANGED", f"A render input changed since this cut: {source.get('name') or path.name}")
        props = optional(sidecar(video, "props"))
        props_hash = hashlib.sha256(json.dumps(props, sort_keys=True, separators=(",", ":")).encode()).hexdigest()
        props_matches = bool(props and props_hash == artifact["propsSha256"])
        if not props_matches:
            issue("PROPS_CHANGED", "The rendered props are missing or no longer match the artifact receipt.")
    editorial_path = sidecar(video, "editorial-report") if video else None
    editorial = bound_editorial(editorial_path, artifact, artifact_matches and props_matches)
    direction_path = sidecar(video, "direction-plan") if video else None
    framing = bound_framing(direction_path, artifact, artifact_matches and props_matches)
    # A plan is authoritative only for the current story and the selected delivery.
    plan_matches = bool(plan and object_field(plan, "script").get("sha256") == script_hash
                        and (not video or (artifact_matches and script_matches
                             and plan.get("buildId") == artifact.get("buildId")
                             and plan.get("propsSha256") == artifact.get("propsSha256"))))
    if plan and not plan_matches:
        issue("PLAN_STALE", "Shot timing below is from the current script; the saved build plan is stale.", "warning")
    qa_matches = bool(qa and artifact_matches and script_matches
                      and object_field(qa, "video").get("sha256") == digest
                      and object_field(qa, "artifact").get("buildId") == artifact.get("buildId"))
    if qa and not qa_matches:
        issue("QA_STALE", "The QA receipt does not match this video and script. Run QA again.")
    if video and not qa:
        issue("QA_MISSING", "No QA receipt is available for this delivery.", "warning")
    if qa_matches:
        for finding in array_field(qa, "issues"):
            if isinstance(finding, dict) and finding.get("severity") in ("error", "warning", "info"):
                issues.append(finding)
            else:
                issue("REPORT_INVALID", "The QA receipt contains an invalid finding.")
        if qa.get("status") != "pass" or qa.get("fullDecode") != "pass":
            issue("DELIVERY_QA_FAILED", "Delivery QA has not passed. Resolve its findings before shipping.")

    plan_rows = array_field(plan, "segments") if plan_matches else []
    if plan_matches:
        cursor_check = 0
        valid = finite(plan.get("fps")) > 0 and len(plan_rows) == len(script["shots"])
        for row, shot in zip(plan_rows, script["shots"]):
            if (not isinstance(row, dict) or not isinstance(shot, dict)
                    or row.get("n") != shot.get("n") or type(row.get("frames")) is not int
                    or row["frames"] < 1 or row.get("startFrame", cursor_check) != cursor_check):
                valid = False
                break
            cursor_check += row["frames"]
            if row.get("endFrame", cursor_check) != cursor_check:
                valid = False
        if plan.get("totalFrames", cursor_check) != cursor_check:
            valid = False
        if not valid:
            issue("PLAN_INVALID", "The build plan has inconsistent shot identities or frame boundaries.")
            plan_matches = False
            plan_rows = []
    fps = max(1.0, finite(plan.get("fps") if plan_matches else script.get("fps"), 30.0))
    narration = script.get("narrationMap") if isinstance(script.get("narrationMap"), list) else []
    picture_order = [shot.get("n", index + 1) for index, shot in enumerate(script["shots"]) if isinstance(shot, dict)]
    shots, cursor = [], 0
    for index, raw in enumerate(script["shots"]):
        if not isinstance(raw, dict):
            issue("SHOT_INVALID", f"Shot {index + 1} must be an object.")
            continue
        number = raw.get("n", index + 1)
        row = plan_rows[index] if plan_rows else {}
        frames = max(1, int(finite(row.get("frames"), math.floor(finite(raw.get("durSec"), 2.5) * fps + 0.5))))
        text = " ".join(str(cue.get("text") or "") for cue in narration
                        if isinstance(cue, dict) and number in narration_cue_shots(cue, picture_order)[0]).strip()
        beats = raw.get("storyBeats") or [raw.get("storyBeat") or raw.get("kind", "shot")]
        if not isinstance(beats, list):
            beats = [beats]
        shots.append({"n": number, "kind": raw.get("kind", "shot"),
                      "title": raw.get("caption") or raw.get("title") or raw.get("stateId") or f"Shot {number}",
                      "beat": " / ".join(str(beat).replace("-", " ") for beat in beats),
                      "narration": text or raw.get("vo") or "",
                      "source": raw.get("src") or raw.get("srcL") or "Generated title / graphic",
                      "inSec": finite(raw.get("inSec")),
                      "startSec": cursor / fps, "endSec": (cursor + frames) / fps,
                      "frames": frames, "durationSec": frames / fps,
                      "transition": raw.get("transitionReason") or "",
                      "findings": [item for item in issues if item.get("shot") == number]})
        cursor += frames
    if not shots:
        raise ValueError("script.json contains no valid shots")
    brand = script.get("brand") if isinstance(script.get("brand"), dict) else {}
    product = optional(project / "product.json")
    links = [{"label": "Script", "url": relative_url(script_path, destination.parent)}]
    for label, path in (("Video", video), ("Artifact", artifact_path), ("Build plan", plan_path), ("QA receipt", qa_path)):
        if path and path.is_file():
            links.append({"label": label, "url": relative_url(path, destination.parent)})
    if editorial["available"]:
        links.append({"label": "Editorial report", "url": relative_url(editorial_path, destination.parent)})
    if framing["available"]:
        links.append({"label": "Framing report", "url": relative_url(direction_path, destination.parent)})
    audio = object_field(qa, "audio") if qa_matches else {}
    errors = sum(item.get("severity") == "error" for item in issues)
    warnings = sum(item.get("severity") == "warning" for item in issues)
    verified = bool(qa_matches and qa.get("status") == "pass" and qa.get("fullDecode") == "pass"
                    and not errors and not warnings)
    production = script.get("production") if isinstance(script.get("production"), dict) else {}
    return {"name": product.get("name") or brand.get("name") or project.name,
            "generatedAt": datetime.now(timezone.utc).isoformat(timespec="seconds"),
            "profile": production.get("profile", "custom"),
            "status": "Verified delivery" if verified else "Needs attention" if errors or warnings else "Awaiting QA" if video else "Story preview",
            "verified": verified, "errors": errors, "warnings": warnings,
            "fps": fps, "durationSec": cursor / fps, "totalFrames": cursor,
            "timing": "Rendered frame plan" if plan_matches else "Script estimate",
            "canSeek": bool(video and plan_matches),
            "video": relative_url(video, destination.parent) if video else None,
            "videoPath": str(video) if video else None, "videoSha256": digest,
            "buildId": artifact.get("buildId"), "shots": shots, "issues": issues, "links": links,
            "audio": audio, "editorial": editorial, "framing": framing}


def make_thumbnails(data: dict, destination: Path) -> None:
    """Cache small stills by video hash; an unavailable FFmpeg never blocks review."""
    if not data["canSeek"] or not shutil.which("ffmpeg"):
        return
    directory = destination.parent / "review-stills"
    directory.mkdir(exist_ok=True)
    for index, shot in enumerate(data["shots"]):
        when = shot["startSec"] + min(0.8, shot["durationSec"] / 2)
        path = directory / f"{data['videoSha256'][:16]}-{index}-{round(when * data['fps'])}.jpg"
        if not path.exists():
            try:
                result = subprocess.run(["ffmpeg", "-v", "error", "-nostdin", "-y", "-ss", f"{when:.6f}",
                                         "-i", data["videoPath"], "-frames:v", "1", "-vf", "scale=480:-2",
                                         "-q:v", "3", str(path)], capture_output=True, timeout=30)
                if result.returncode or not path.is_file() or not path.stat().st_size:
                    path.unlink(missing_ok=True)
                    continue
            except (OSError, subprocess.TimeoutExpired):
                path.unlink(missing_ok=True)
                continue
        shot["thumbnail"] = relative_url(path, destination.parent)


def write_review(project: Path, destination: Path, video: Path | None = None, thumbnails=True) -> Path:
    destination = destination.resolve()
    # Only the review document is replaced; project media and receipts are read-only.
    if destination.suffix.lower() != ".html":
        raise ValueError("Review output must be an .html file")
    data = collect_review(project, destination, video)
    destination.parent.mkdir(parents=True, exist_ok=True)
    if thumbnails:
        make_thumbnails(data, destination)
    data.pop("videoPath", None)
    template = Path(__file__).with_name("review_template.html").read_text(encoding="utf-8")
    payload = json.dumps(data, ensure_ascii=False, allow_nan=False).replace("<", "\\u003c")
    document = template.replace("__REVIEW_TITLE__", html.escape(str(data["name"]))).replace("__REVIEW_DATA__", payload)
    fd, temporary = tempfile.mkstemp(dir=destination.parent, suffix=".html")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            handle.write(document)
        os.replace(temporary, destination)
    finally:
        Path(temporary).unlink(missing_ok=True)
    return destination


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--project", type=Path, required=True)
    parser.add_argument("--video", type=Path, help="review a specific local cut")
    parser.add_argument("--out", type=Path, help="default: <project>/out/review.html")
    parser.add_argument("--no-thumbnails", action="store_true")
    args = parser.parse_args()
    try:
        output = write_review(args.project, args.out or args.project / "out" / "review.html",
                              args.video, not args.no_thumbnails)
    except (OSError, ValueError) as exc:
        parser.exit(1, f"Cannot create review: {exc}\n")
    print(f"Review: {output}")


if __name__ == "__main__":
    main()
