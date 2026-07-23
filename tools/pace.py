#!/usr/bin/env python3
"""Move picture cuts into the gaps between timestamp-aligned narration thoughts.

Each narrationMap entry declares the full spoken thought, its aligned start/end time,
and the shot that should carry it. The pacer keeps the authored rhythm when possible,
but clamps every boundary to a safe frame between adjacent thoughts.
"""

from __future__ import annotations

import argparse
import json
import math
import os
import tempfile
from typing import Any


class PaceError(ValueError):
    pass


def _number(value: Any, default: float = 0.0) -> float:
    try:
        number = float(value)
        return number if math.isfinite(number) else default
    except (TypeError, ValueError):
        return default


def _write_json(path: str, value: Any) -> None:
    directory = os.path.dirname(os.path.abspath(path))
    os.makedirs(directory, exist_ok=True)
    fd, temporary = tempfile.mkstemp(prefix=f".{os.path.basename(path)}.", dir=directory)
    try:
        with os.fdopen(fd, "w") as handle:
            json.dump(value, handle, indent=2)
            handle.write("\n")
        os.replace(temporary, path)
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)


def pace_script(script: dict[str, Any]) -> dict[str, Any]:
    shots = script.get("shots")
    cues = script.get("narrationMap")
    if not isinstance(shots, list) or not shots:
        raise PaceError("script needs a non-empty shots array")
    if not isinstance(cues, list) or not cues:
        raise PaceError("script needs a timestamp-aligned narrationMap")
    fps = int(script.get("fps") or 30)
    if fps <= 0:
        raise PaceError("fps must be positive")
    production = script.get("production") if isinstance(script.get("production"), dict) else {}
    editorial = script.get("editorialContract") if isinstance(script.get("editorialContract"), dict) else {}
    target = _number(editorial.get("targetRuntimeSec"), 0.0)
    if target <= 0:
        target = sum(max(0.0, _number(shot.get("durSec"), 0.0)) for shot in shots)
    total_frames = round(target * fps)
    if total_frames <= len(shots):
        raise PaceError("target runtime is too short for the shot count")

    by_shot: dict[int, list[dict[str, Any]]] = {}
    shot_numbers = [shot.get("n") for shot in shots]
    if any(not isinstance(number, int) for number in shot_numbers):
        raise PaceError("every shot needs an integer n")
    for index, cue in enumerate(cues):
        if not isinstance(cue, dict):
            raise PaceError(f"narrationMap[{index}] must be an object")
        shot_n = cue.get("shotN")
        if shot_n not in shot_numbers:
            raise PaceError(f"narrationMap[{index}] references unknown shotN {shot_n!r}")
        start = _number(cue.get("startSec"), -1.0)
        end = _number(cue.get("endSec"), -1.0)
        if start < 0 or end <= start:
            raise PaceError(f"narrationMap[{index}] has no valid aligned range")
        by_shot.setdefault(int(shot_n), []).append(cue)

    unmapped = [int(shot["n"]) for shot in shots
                if not shot.get("visualOnly") and int(shot["n"]) not in by_shot]
    if unmapped:
        raise PaceError("every non-visual shot needs a narration cue; missing "
                        + ", ".join(str(value) for value in unmapped))
    if any(shot.get("visualOnly") for shot in shots):
        raise PaceError("automatic pacing does not yet place visualOnly shots; map a thought to each shot")

    ordered_cues = [cue for shot in shots for cue in by_shot[int(shot["n"])]]
    starts = [_number(cue.get("startSec"), -1.0) for cue in ordered_cues]
    if starts != sorted(starts):
        raise PaceError("narrationMap shot assignments must progress in spoken order")

    authored_boundaries: list[int] = []
    cursor = 0
    for shot in shots[:-1]:
        cursor += max(1, round(_number(shot.get("durSec"), 0.0) * fps))
        authored_boundaries.append(cursor)

    padding = max(0.0, _number(production.get("narrationCutPaddingSec"), 0.04))
    boundaries: list[int] = []
    for index, (left_shot, right_shot) in enumerate(zip(shots, shots[1:])):
        left = by_shot[int(left_shot["n"])]
        right = by_shot[int(right_shot["n"])]
        left_end = max(_number(cue.get("endSec"), -1.0) for cue in left)
        right_start = min(_number(cue.get("startSec"), -1.0) for cue in right)
        lower = math.ceil((left_end + padding) * fps - 1e-9)
        upper = math.floor((right_start - padding) * fps + 1e-9)
        if lower > upper:
            # A frame-exact boundary at the shared sentence edge is still safe. This fallback is
            # deliberately narrow; overlapping speech remains impossible to pace automatically.
            lower = math.ceil(left_end * fps - 1e-9)
            upper = math.floor(right_start * fps + 1e-9)
        if lower > upper:
            raise PaceError(
                f"no frame-safe cut exists between shot {left_shot['n']} ending at "
                f"{left_end:.3f}s and shot {right_shot['n']} starting at {right_start:.3f}s"
            )
        desired = authored_boundaries[index]
        chosen = min(upper, max(lower, desired))
        if boundaries and chosen <= boundaries[-1]:
            raise PaceError(f"shot {right_shot['n']} has no positive frame duration")
        boundaries.append(chosen)

    last_end = max(_number(cue.get("endSec"), -1.0) for cue in by_shot[int(shots[-1]["n"])])
    min_tail = max(0.0, _number(production.get("minNarrationTailSec"), 0.0))
    if last_end + min_tail > total_frames / fps + 1e-9:
        raise PaceError(
            f"narration ends at {last_end:.3f}s and needs {min_tail:.3f}s tail, "
            f"beyond the {total_frames / fps:.3f}s target"
        )

    frame_edges = [0, *boundaries, total_frames]
    rows: list[dict[str, Any]] = []
    for index, shot in enumerate(shots):
        frames = frame_edges[index + 1] - frame_edges[index]
        if frames <= 0:
            raise PaceError(f"shot {shot['n']} has no positive frame duration")
        rows.append({
            "n": int(shot["n"]),
            "startFrame": frame_edges[index],
            "endFrame": frame_edges[index + 1],
            "frames": frames,
            "startSec": frame_edges[index] / fps,
            "endSec": frame_edges[index + 1] / fps,
            "durSec": frames / fps,
        })
    return {"fps": fps, "totalFrames": total_frames, "totalSec": total_frames / fps,
            "paddingSec": padding, "shots": rows}


def apply_plan(script: dict[str, Any], plan: dict[str, Any]) -> None:
    durations = {row["n"]: row["durSec"] for row in plan["shots"]}
    for shot in script["shots"]:
        shot["durSec"] = durations[int(shot["n"])]
    editorial = script.setdefault("editorialContract", {})
    editorial["targetRuntimeSec"] = plan["totalSec"]
    editorial["runtimeToleranceSec"] = 0
    editorial["narrationPaced"] = True
    editorial["narrationPacingFps"] = plan["fps"]


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--project", required=True)
    parser.add_argument("--script", default="", help="default: <project>/script.json")
    parser.add_argument("--write", action="store_true", help="write frame-safe durations into script.json")
    parser.add_argument("--json", action="store_true", help="emit only the machine-readable plan")
    args = parser.parse_args()

    project = os.path.abspath(args.project)
    path = os.path.abspath(args.script or os.path.join(project, "script.json"))
    with open(path) as handle:
        script = json.load(handle)
    try:
        plan = pace_script(script)
    except PaceError as exc:
        raise SystemExit(f"narration pacing failed: {exc}") from exc
    if args.write:
        apply_plan(script, plan)
        _write_json(path, script)
    if args.json:
        print(json.dumps(plan, indent=2))
    else:
        action = "wrote" if args.write else "planned"
        print(f"{action} {len(plan['shots'])} narration-safe shots · "
              f"{plan['totalSec']:.3f}s / {plan['totalFrames']} frames")
        for row in plan["shots"]:
            print(f"  shot {row['n']:>2}: {row['startSec']:>7.3f}–{row['endSec']:<7.3f} "
                  f"({row['frames']}f)")


if __name__ == "__main__":
    main()
