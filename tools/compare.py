#!/usr/bin/env python3
"""Order-reversed champion gate for demo revisions.

Deterministic contracts and QA decide whether a candidate is eligible. This tool then compares the
eligible candidate against the current champion in both display orders. A candidate ships only on a
2-0 sweep and, when numeric scores are supplied, an improvement larger than the configured noise
floor. A split is explicitly inconclusive.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
from typing import Any

from judge import verify_artifact


DEFAULT_RUBRIC = """Choose the stronger product demo, not the more decorated edit.
Prioritize, in order:
1. truthful, visible product behavior and claim support;
2. one comprehensible causal story from input through consequence;
3. progressive state that does not look prefilled or preset;
4. correct human/agent authority boundaries and credible restraint;
5. narration-to-picture alignment, legibility, cursor safety, and camera continuity;
6. pace, polish, and a memorable differentiated payoff.
Continuous use of one advancing product screen is coherence, not repetition. Do not reward unsupported
slides, extra zooms, faster cuts, or removed setup merely because they create more motion."""


def load_json(path: str) -> dict[str, Any]:
    with open(path) as fh:
        return json.load(fh)


def duration(path: str) -> float:
    proc = subprocess.run(
        ["ffprobe", "-v", "error", "-show_entries", "format=duration",
         "-of", "default=noprint_wrappers=1:nokey=1", path],
        capture_output=True, text=True,
    )
    if proc.returncode != 0:
        raise RuntimeError(f"ffprobe failed for {path}: {proc.stderr[-800:]}")
    return float(proc.stdout.strip())


def extract(video: str, count: int, out_dir: str, tag: str) -> list[tuple[float, str]]:
    seconds = duration(video)
    frames: list[tuple[float, str]] = []
    for index in range(count):
        # Midpoints cover the whole story without over-weighting either end.
        at = (index + 0.5) * seconds / count
        path = os.path.join(out_dir, f"{tag}-{index:03d}.jpg")
        proc = subprocess.run(
            ["ffmpeg", "-y", "-v", "error", "-ss", f"{at:.6f}", "-i", video,
             "-frames:v", "1", "-vf", "scale=640:-2:flags=lanczos", path],
            capture_output=True, text=True,
        )
        if proc.returncode != 0 or not os.path.exists(path):
            raise RuntimeError(f"frame extraction failed at {at:.3f}s: {proc.stderr[-800:]}")
        frames.append((round(at, 3), path))
    return frames


def ask(first_label: str, first: list[tuple[float, str]], second_label: str,
        second: list[tuple[float, str]], rubric: str) -> dict[str, str]:
    prompt = [
        "You are comparing two cuts of the same product demo. Judge the evidence shown in the frames.",
        "Return exactly one JSON object with keys winner and why. winner must be "
        f"{first_label!r} or {second_label!r}.",
        "Do not infer claims or interactions that are not visible.",
        "",
        f"FILM {first_label}, chronological frames:",
        *[f"- {at:.3f}s: {path}" for at, path in first],
        "",
        f"FILM {second_label}, chronological frames:",
        *[f"- {at:.3f}s: {path}" for at, path in second],
        "",
        "RUBRIC:", rubric,
    ]
    env = {**os.environ, "CLAUDE_CODE_HOOKS_ENABLED": "false"}
    proc = subprocess.run(
        ["claude", "-p", "--allowedTools", "Read", "--output-format", "json", "\n".join(prompt)],
        capture_output=True, text=True, timeout=600, env=env,
    )
    if proc.returncode != 0:
        raise RuntimeError(f"pairwise judge failed: {proc.stderr[-1200:]}")
    outer = json.loads(proc.stdout)
    text = outer.get("result", "") if isinstance(outer, dict) else str(outer)
    match = re.search(r"\{.*\}", text, re.S)
    answer = json.loads(match.group(0) if match else text)
    if answer.get("winner") not in {first_label, second_label}:
        raise RuntimeError(f"invalid pairwise winner: {answer}")
    return {"winner": answer["winner"], "why": str(answer.get("why", ""))}


def gate_decision(winners: list[str], champion_score: float | None = None,
                  candidate_score: float | None = None, noise_floor: float = 2.0) -> tuple[str, str]:
    if winners == ["candidate", "candidate"]:
        if champion_score is not None and candidate_score is not None:
            delta = candidate_score - champion_score
            if delta <= noise_floor:
                return "inconclusive", f"candidate score delta {delta:.2f} is inside the {noise_floor:.2f}-point noise floor"
        return "ship", "candidate swept both display orders"
    if winners == ["champion", "champion"]:
        return "retain-champion", "champion swept both display orders"
    return "inconclusive", "order-reversed votes split"


def require_qa(path: str) -> dict[str, Any]:
    report = load_json(path)
    if report.get("status") != "pass":
        raise RuntimeError(f"candidate deterministic QA did not pass: {path}")
    return report


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--champion", required=True)
    parser.add_argument("--candidate", required=True)
    parser.add_argument("--champion-artifact", default="")
    parser.add_argument("--candidate-artifact", default="")
    parser.add_argument("--candidate-qa", required=True,
                        help="qa-report.json; candidate is ineligible unless status=pass")
    parser.add_argument("--frames", type=int, default=24)
    parser.add_argument("--rubric", default="")
    parser.add_argument("--champion-score", type=float)
    parser.add_argument("--candidate-score", type=float)
    parser.add_argument("--noise-floor", type=float, default=2.0)
    parser.add_argument("--out", default="")
    args = parser.parse_args()

    for binary in ("ffmpeg", "ffprobe", "claude"):
        if not shutil.which(binary):
            raise SystemExit(f"{binary} is required")
    champion = os.path.abspath(args.champion)
    candidate = os.path.abspath(args.candidate)
    champion_artifact = verify_artifact(champion, args.champion_artifact, required=True)
    candidate_artifact = verify_artifact(candidate, args.candidate_artifact, required=True)
    qa = require_qa(args.candidate_qa)
    qa_hash = ((qa.get("video") or {}).get("sha256") or "").lower()
    if qa_hash != candidate_artifact["sha256"].lower():
        raise SystemExit("candidate QA report is bound to a different video hash")
    if args.rubric.endswith(".json"):
        rubric = load_json(args.rubric).get("rubric", "")
    elif args.rubric:
        with open(args.rubric) as fh:
            rubric = fh.read()
    else:
        rubric = DEFAULT_RUBRIC

    count = max(8, min(80, args.frames))
    with tempfile.TemporaryDirectory(prefix="pdd-pairwise-") as temp:
        champ_frames = extract(champion, count, temp, "champion")
        cand_frames = extract(candidate, count, temp, "candidate")
        first = ask("champion", champ_frames, "candidate", cand_frames, rubric)
        second = ask("candidate", cand_frames, "champion", champ_frames, rubric)

    winners = [first["winner"], second["winner"]]
    decision, reason = gate_decision(winners, args.champion_score, args.candidate_score,
                                     max(0.0, args.noise_floor))
    result = {
        "schemaVersion": 1,
        "decision": decision,
        "reason": reason,
        "votes": [
            {"order": "champion-first", **first},
            {"order": "candidate-first", **second},
        ],
        "champion": {"video": champion, "artifact": champion_artifact["path"],
                     "buildId": champion_artifact.get("buildId"),
                     "sha256": champion_artifact["sha256"]},
        "candidate": {"video": candidate, "artifact": candidate_artifact["path"],
                      "buildId": candidate_artifact.get("buildId"),
                      "sha256": candidate_artifact["sha256"]},
        "candidateQa": os.path.abspath(args.candidate_qa),
        "noiseFloor": max(0.0, args.noise_floor),
    }
    output = json.dumps(result, indent=2)
    print(output)
    if args.out:
        os.makedirs(os.path.dirname(os.path.abspath(args.out)), exist_ok=True)
        with open(args.out, "w") as fh:
            fh.write(output + "\n")
    if decision != "ship":
        sys.exit(2)


if __name__ == "__main__":
    main()
