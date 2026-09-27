#!/usr/bin/env python3
"""Preview or opt a project into the studio motion treatment.

This is an editorial draft, before narration pacing and frame planning. The build
compiler creates the final treatment bound to a rendered artifact.
"""

from __future__ import annotations

import argparse
import copy
import hashlib
import json
import os
from pathlib import Path
import tempfile
from typing import Any

try:
    from .contracts import ALLOWED_KINDS
    from .direction import compile_direction, is_number, validate_direction
except ImportError:
    from contracts import ALLOWED_KINDS
    from direction import compile_direction, is_number, validate_direction


STUDIO_DEFAULTS = {"style": "studio", "tone": "precise", "soundDesign": "sparse"}


def _validate_draft(script: Any) -> None:
    """Check authoring inputs without requiring footage or synthesized narration."""
    if not isinstance(script, dict):
        raise ValueError("SCRIPT_INVALID: script.json must contain an object")
    fps = script.get("fps", 30)
    if type(fps) is not int or fps <= 0:
        raise ValueError("FPS_INVALID: fps must be a positive integer")
    shots = script.get("shots")
    if not isinstance(shots, list) or not shots:
        raise ValueError("SHOTS_MISSING: script needs a non-empty shots array")
    seen: set[int] = set()
    for index, shot in enumerate(shots):
        if not isinstance(shot, dict):
            raise ValueError(f"SHOT_INVALID: shots[{index}] must be an object")
        n = shot.get("n")
        if type(n) is not int or n in seen:
            raise ValueError(f"SHOT_NUMBER_INVALID: shots[{index}] needs a unique integer n")
        seen.add(n)
        kind = shot.get("kind", "clip")
        if not isinstance(kind, str) or kind not in ALLOWED_KINDS:
            raise ValueError(f"SHOT_KIND_INVALID: shot {n} has an unsupported kind")
        duration = shot.get("durSec", 2.5)
        if not is_number(duration) or duration <= 0 or duration * fps < 1:
            raise ValueError(f"SHOT_DURATION_INVALID: shot {n} must last at least one frame")
    production = script.get("production", {})
    if not isinstance(production, dict):
        raise ValueError("PRODUCTION_INVALID: production must be an object")
    locks = production.get("sourceLocks", [])
    if not isinstance(locks, list) or any(
        not isinstance(lock, str) and not (
            isinstance(lock, dict) and isinstance(lock.get("src"), str)
        ) for lock in locks
    ):
        raise ValueError("SOURCE_LOCKS_INVALID: sourceLocks must list source names or objects with src")
    findings = validate_direction(script)
    if findings:
        raise ValueError("; ".join(f"{item['code']}: {item['message']}" for item in findings))


def propose_direction(script: Any, *, source_sha256: str | None = None) -> tuple[dict[str, Any], dict[str, Any]]:
    """Return an independent proposed script and an explicitly unbound draft plan."""
    _validate_draft(script)
    proposed = copy.deepcopy(script)
    creative = {**STUDIO_DEFAULTS, **proposed.get("creativeDirection", {})}
    # Asking to direct opts into studio. Existing tone and sound choices remain
    # intentional; a project that requested silence must not start making sound.
    creative["style"] = "studio"
    proposed["creativeDirection"] = creative
    plan = compile_direction(proposed)
    plan.update({
        "artifactKind": "creative-direction-preview",
        "status": "draft",
        "renderBound": False,
        "note": "Draft before narration pacing and frame planning. Build compiles the final direction bound to the rendered artifact.",
    })
    if source_sha256 is not None:
        plan["sourceScriptSha256"] = source_sha256
    return proposed, plan


def _atomic_write_json(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = json.dumps(value, indent=2, ensure_ascii=False, allow_nan=False) + "\n"
    fd, temporary = tempfile.mkstemp(prefix=f".{path.name}.", suffix=".tmp", dir=path.parent)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            handle.write(payload)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, path)
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)


def direct_project(project: Path | str, *, write: bool = False) -> dict[str, Any]:
    """Dry runs are read-only; writes preserve every field outside creativeDirection."""
    project = Path(project).expanduser().resolve()
    script_path = project / "script.json"
    source = script_path.read_bytes()
    script = json.loads(source)
    proposed, plan = propose_direction(script, source_sha256=hashlib.sha256(source).hexdigest())
    if write:
        # Serialize both before touching the project; reject non-JSON numbers in
        # unrelated fields rather than partially applying an invalid draft.
        json.dumps(proposed, allow_nan=False)
        json.dumps(plan, allow_nan=False)
        # A failed preview write leaves the authored script unchanged. The plan
        # is explicitly a proposal, so it may safely exist before opt-in commits.
        _atomic_write_json(project / "out" / "direction-plan.json", plan)
        _atomic_write_json(script_path, proposed)
    return plan


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--project", required=True, help="project directory containing script.json")
    parser.add_argument("--write", action="store_true", help="enable studio and save out/direction-plan.json; otherwise print only")
    args = parser.parse_args()
    try:
        plan = direct_project(args.project, write=args.write)
    except (OSError, ValueError) as exc:
        parser.exit(1, f"direct: {exc}\n")
    if args.write:
        project = Path(args.project).expanduser().resolve()
        print(f"Studio direction enabled: {project / 'script.json'}")
        print(f"Draft preview (not bound to a render): {project / 'out' / 'direction-plan.json'}")
    else:
        print(json.dumps(plan, indent=2, ensure_ascii=False, allow_nan=False))


if __name__ == "__main__":
    main()
