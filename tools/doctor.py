#!/usr/bin/env python3
"""Check whether Product Demo Director is ready to render."""

from __future__ import annotations

import importlib.util
import os
from pathlib import Path
import shutil
import subprocess
import sys


ROOT = Path(__file__).resolve().parent.parent


def version(command: list[str]) -> str | None:
    try:
        result = subprocess.run(command, capture_output=True, text=True, timeout=10)
    except (OSError, subprocess.TimeoutExpired):
        return None
    if result.returncode:
        return None
    return (result.stdout or result.stderr).splitlines()[0].strip()


def mark(ok: bool, label: str, detail: str, *, required: bool = True) -> bool:
    icon = "OK" if ok else ("FAIL" if required else "NOTE")
    print(f"[{icon:4}] {label:<18} {detail}")
    return ok or not required


def load_dotenv() -> None:
    path = ROOT / ".env"
    if not path.exists():
        return
    for raw in path.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        key, value = key.strip(), value.strip().strip("'\"")
        if key and value:
            os.environ.setdefault(key, value)


def main() -> None:
    load_dotenv()
    checks: list[bool] = []
    checks.append(mark(sys.version_info >= (3, 10), "Python", sys.version.split()[0]))

    for label, command in (
        ("Node.js", ["node", "--version"]),
        ("npm", ["npm", "--version"]),
        ("FFmpeg", ["ffmpeg", "-version"]),
        ("FFprobe", ["ffprobe", "-version"]),
    ):
        found = version(command)
        checks.append(mark(bool(found), label, found or "not found"))

    venv_python = ROOT / ".venv" / ("Scripts/python.exe" if os.name == "nt" else "bin/python")
    checks.append(mark(venv_python.exists(), "Python environment",
                       str(venv_python.relative_to(ROOT)) if venv_python.exists() else "run ./pdd setup"))
    remotion = ROOT / "engine" / "node_modules" / "@remotion" / "cli"
    checks.append(mark(remotion.exists(), "Remotion", "installed" if remotion.exists() else "run ./pdd setup"))

    modules = ["requests", "google.genai", "playwright"]
    if venv_python.exists():
        probe = "import importlib.util,sys;sys.exit(0 if all(importlib.util.find_spec(x) for x in sys.argv[1:]) else 1)"
        result = subprocess.run([str(venv_python), "-c", probe, *modules])
        checks.append(mark(result.returncode == 0, "Python packages",
                           "installed" if result.returncode == 0 else "run ./pdd setup"))
        browser_probe = (
            "from pathlib import Path; from playwright.sync_api import sync_playwright; "
            "p=sync_playwright().start(); path=Path(p.chromium.executable_path); p.stop(); "
            "raise SystemExit(0 if path.exists() else 1)"
        )
        browser = subprocess.run([str(venv_python), "-c", browser_probe],
                                 capture_output=True, text=True)
        mark(browser.returncode == 0, "Capture browser",
             "installed" if browser.returncode == 0 else "optional; run ./pdd setup --with-capture",
             required=False)

    provider = bool(os.getenv("ELEVENLABS_API_KEY") or os.getenv("GEMINI_API_KEY") or os.getenv("GOOGLE_API_KEY"))
    mark(provider, "Narration/music key", "configured" if provider else "add a key to .env", required=False)
    judge = bool(os.getenv("GEMINI_API_KEY") or os.getenv("GOOGLE_API_KEY"))
    mark(judge, "Judge key", "configured" if judge else "optional; add GEMINI_API_KEY", required=False)

    free = shutil.disk_usage(ROOT).free
    free_gib = free / (1024 ** 3)
    checks.append(mark(free_gib >= 1.0, "Free disk", f"{free_gib:.1f} GiB (1 GiB minimum)"))

    print()
    if all(checks):
        print("Ready to direct.")
        return
    print("Workstation needs attention; fix the FAIL items above.")
    raise SystemExit(1)


if __name__ == "__main__":
    main()
