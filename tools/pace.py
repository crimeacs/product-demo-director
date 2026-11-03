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

from contracts import PROFILE_ALIASES, PROFILES


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
    if any(not isinstance(shot, dict) for shot in shots):
        raise PaceError("every shot must be an object")
    fps_value = _number(script.get("fps", 30), -1.0)
    if isinstance(script.get("fps"), bool) or fps_value <= 0 or not fps_value.is_integer():
        raise PaceError("fps must be a positive integer")
    fps = int(fps_value)
    production = script.get("production") if isinstance(script.get("production"), dict) else {}
    profile = str(production.get("profile", ""))
    production = {**PROFILES.get(PROFILE_ALIASES.get(profile, profile), {}), **production}
    editorial = script.get("editorialContract") if isinstance(script.get("editorialContract"), dict) else {}
    target = _number(editorial.get("targetRuntimeSec"), 0.0)
    if target <= 0:
        target = sum(max(0.0, _number(shot.get("durSec"), 0.0)) for shot in shots)
    total_frames = math.floor(target * fps + 0.5)
    if total_frames < len(shots):
        raise PaceError("target runtime is too short for the shot count")

    by_shot: dict[int, list[dict[str, Any]]] = {}
    shot_numbers = [shot.get("n") for shot in shots]
    if any(type(number) is not int for number in shot_numbers):
        raise PaceError("every shot needs an integer n")
    if len(set(shot_numbers)) != len(shot_numbers):
        raise PaceError("shot numbers must be unique")
    for index, cue in enumerate(cues):
        if not isinstance(cue, dict):
            raise PaceError(f"narrationMap[{index}] must be an object")
        shot_n = cue.get("shotN")
        if type(shot_n) is not int or shot_n not in shot_numbers:
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
    ordered_cues = [cue for shot in shots for cue in by_shot.get(int(shot["n"]), [])]
    starts = [_number(cue.get("startSec"), -1.0) for cue in ordered_cues]
    if starts != sorted(starts):
        raise PaceError("narrationMap shot assignments must progress in spoken order")
    if any(_number(left["endSec"]) > _number(right["startSec"]) + 1e-9
           for left, right in zip(ordered_cues, ordered_cues[1:])):
        raise PaceError("narrationMap cues must not overlap")

    authored_boundaries: list[int] = []
    cursor = 0
    for shot in shots[:-1]:
        cursor += max(1, math.floor(_number(shot.get("durSec"), 0.0) * fps + 0.5))
        authored_boundaries.append(cursor)

    padding = max(0.0, _number(production.get("narrationCutPaddingSec"), 0.04))
    # Each cut belongs to a gap between spoken shots. Visual-only shots share that gap,
    # including leading establishing shots and an unvoiced closing card.
    narrated = [index for index, shot in enumerate(shots) if shot["n"] in by_shot]
    windows: list[tuple[int, int]] = []
    for index in range(len(shots) - 1):
        left_index = next((value for value in reversed(narrated) if value <= index), None)
        right_index = next((value for value in narrated if value > index), None)
        left_end = (max(_number(cue["endSec"]) for cue in by_shot[shots[left_index]["n"]])
                    if left_index is not None else 0.0)
        right_start = (min(_number(cue["startSec"]) for cue in by_shot[shots[right_index]["n"]])
                       if right_index is not None else total_frames / fps)
        first_edge = left_index + 1 if left_index is not None else 0
        last_edge = right_index if right_index is not None else len(shots)
        required_span = last_edge - first_edge
        lower = math.ceil((left_end + (padding if left_index is not None else 0)) * fps - 1e-9)
        upper = math.floor((right_start - (padding if right_index is not None else 0)) * fps + 1e-9)
        if upper - lower < required_span:
            # Preserve complete speech when the available gap cannot also carry padding.
            lower = math.ceil(left_end * fps - 1e-9)
            upper = math.floor(right_start * fps + 1e-9)
        if upper - lower < required_span:
            raise PaceError(
                f"no frame-safe cut exists around shot {shots[index]['n']}: "
                f"the {left_end:.3f}–{right_start:.3f}s gap cannot fit the visual shots"
            )
        edge = index + 1
        windows.append((max(edge, lower + edge - first_edge),
                        min(total_frames - (len(shots) - edge), upper - (last_edge - edge))))

    boundaries: list[int] = []
    for index, (lower, upper) in enumerate(windows):
        if boundaries:
            lower = max(lower, boundaries[-1] + 1)
        if lower > upper:
            raise PaceError(f"shot {shots[index]['n']} has no positive frame duration")
        boundaries.append(min(upper, max(lower, authored_boundaries[index])))

    last_end = max(_number(cue.get("endSec"), -1.0) for cue in ordered_cues)
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
        if "sourceTimeline" in shot and frames != math.floor(_number(shot.get("durSec"), 0) * fps + 0.5):
            raise PaceError(
                f"shot {shot['n']} has an authored sourceTimeline and pacing would resize it; "
                "pace narration before mapping the source, then author the map for the final shot duration"
            )
    return {"fps": fps, "totalFrames": total_frames, "totalSec": total_frames / fps,
            "paddingSec": padding, "shots": rows}


def apply_plan(script: dict[str, Any], plan: dict[str, Any]) -> None:
    durations = {row["n"]: row["durSec"] for row in plan["shots"]}
    fps = plan["fps"]
    # Check all mapped shots before mutating any shot; applying an older plan must
    # not silently stretch a protected action or shorten a deliberate reading hold.
    for shot in script["shots"]:
        if "sourceTimeline" in shot and math.floor(_number(shot.get("durSec"), 0) * fps + 0.5) != math.floor(durations[int(shot["n"])] * fps + 0.5):
            raise PaceError(
                f"shot {shot['n']} has an authored sourceTimeline; pace narration before mapping "
                "the source, then regenerate the map for the new shot duration"
            )
    for shot in script["shots"]:
        shot["durSec"] = durations[int(shot["n"])]
    if not isinstance(script.get("editorialContract"), dict):
        script["editorialContract"] = {}
    editorial = script["editorialContract"]
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
