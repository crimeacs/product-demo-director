#!/usr/bin/env python3
"""Web deliverables from a finished film: fast-start H.264 MP4s at 1080p and 720p, a VP9 WebM, and a poster.

    python tools/web_export.py projects/my-film/out/final.mp4 [--poster-at 24.6] [--out DIR]

Writes <out>/<name>-1080p.mp4, <name>-720p.mp4, <name>-1080p.webm and poster.jpg, and prints an HTML snippet.
The MP4s put the index first (faststart) so a page starts playing before the download finishes; WebM first in
<source> order gives Chrome and Firefox the smaller file, MP4 covers Safari and everything else.
"""
import argparse
import os
import subprocess


def commands(src, out, name, poster_at):
    """The ffmpeg argv for each deliverable. Pure: unit-tested."""
    h264 = ["-c:v", "libx264", "-profile:v", "high", "-preset", "slow", "-pix_fmt", "yuv420p", "-g", "60",
            "-movflags", "+faststart", "-c:a", "aac", "-b:a", "128k", "-ar", "48000"]
    j = lambda f: os.path.join(out, f)  # noqa: E731
    return {
        f"{name}-1080p.mp4": ["ffmpeg", "-v", "error", "-y", "-i", src, "-level", "4.1", "-crf", "22", "-maxrate", "6M",
                              "-bufsize", "12M", *h264, j(f"{name}-1080p.mp4")],
        f"{name}-720p.mp4": ["ffmpeg", "-v", "error", "-y", "-i", src, "-vf", "scale=1280:720:flags=lanczos", "-level", "4.0",
                             "-crf", "23", "-maxrate", "3M", "-bufsize", "6M", *h264, j(f"{name}-720p.mp4")],
        f"{name}-1080p.webm": ["ffmpeg", "-v", "error", "-y", "-i", src, "-c:v", "libvpx-vp9", "-crf", "33", "-b:v", "0",
                               "-row-mt", "1", "-deadline", "good", "-cpu-used", "2", "-pix_fmt", "yuv420p",
                               "-c:a", "libopus", "-b:a", "96k", j(f"{name}-1080p.webm")],
        "poster.jpg": ["ffmpeg", "-v", "error", "-y", "-ss", str(poster_at), "-i", src, "-frames:v", "1", "-q:v", "3", j("poster.jpg")],
    }


def snippet(name):
    return (f'<video controls playsinline preload="metadata" poster="poster.jpg">\n'
            f'  <source src="{name}-1080p.webm" type="video/webm">\n'
            f'  <source src="{name}-1080p.mp4" type="video/mp4">\n</video>')


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("src"); ap.add_argument("--out"); ap.add_argument("--name"); ap.add_argument("--poster-at", type=float, default=1.0)
    a = ap.parse_args()
    out = a.out or os.path.join(os.path.dirname(os.path.abspath(a.src)), "web")
    name = a.name or os.path.splitext(os.path.basename(a.src))[0]
    os.makedirs(out, exist_ok=True)
    for f, cmd in commands(a.src, out, name, a.poster_at).items():
        subprocess.run(cmd, check=True)
        print(f"{f}: {os.path.getsize(os.path.join(out, f)) / 1e6:.1f} MB")
    print("\n" + snippet(name))


if __name__ == "__main__":
    main()
