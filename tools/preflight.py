#!/usr/bin/env python3
"""Run deterministic source, story, camera, truth, and audio checks before render."""

from __future__ import annotations

import argparse
import json
import os
import sys

from contracts import summarize, validate_script


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--project", required=True)
    parser.add_argument("--script", default="", help="default: <project>/script.json")
    parser.add_argument("--profile", default="", help="override production.profile")
    parser.add_argument("--json", action="store_true", help="emit only the machine-readable report")
    parser.add_argument("--out", default="", help="optional report JSON path")
    parser.add_argument("--strict", action="store_true", help="treat warnings as blocking")
    parser.add_argument(
        "--allow-pending-generated-narration",
        action="store_true",
        help="allow narration.text to be synthesized after this structural preflight",
    )
    args = parser.parse_args()

    project = os.path.abspath(args.project)
    script_path = os.path.abspath(args.script or os.path.join(project, "script.json"))
    try:
        with open(script_path) as fh:
            script = json.load(fh)
    except (OSError, json.JSONDecodeError) as exc:
        print(json.dumps({"status": "fail", "errors": 1, "warnings": 0,
                          "findings": [{"severity": "error", "code": "SCRIPT_INVALID",
                                        "message": str(exc), "path": script_path}]}))
        sys.exit(1)

    findings = validate_script(
        script,
        project,
        args.profile or None,
        allow_pending_narration=args.allow_pending_generated_narration,
    )
    report = summarize(findings)
    production = script.get("production") if isinstance(script.get("production"), dict) else {}
    report.update({"project": project, "script": script_path,
                   "profile": args.profile or production.get("profile")})
    rendered = json.dumps(report, indent=2)
    if args.out:
        out = os.path.abspath(args.out)
        os.makedirs(os.path.dirname(out) or ".", exist_ok=True)
        with open(out, "w") as fh:
            fh.write(rendered + "\n")
    if args.json:
        print(rendered)
    else:
        for finding in findings:
            where = f" shot {finding.shot}" if finding.shot is not None else ""
            path = f" [{finding.path}]" if finding.path else ""
            print(f"{finding.severity.upper():7} {finding.code}{where}: {finding.message}{path}")
        print(f"preflight {report['status'].upper()}: {report['errors']} errors, {report['warnings']} warnings")
    blocked = report["errors"] > 0 or (args.strict and report["warnings"] > 0)
    sys.exit(1 if blocked else 0)


if __name__ == "__main__":
    main()
