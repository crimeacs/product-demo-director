#!/usr/bin/env python3
"""Generate a music bed sized to the timeline — ElevenLabs Music or Google Lyria 3,
auto-selected by key.

    python tools/music.py --project projects/my-demo   ->  <project>/music.mp3
    python tools/music.py --project projects/my-demo --provider lyria

The mood comes from script.json "music" (a short prompt). Length is taken from a
generated/supplied narration master, then the per-shot VO manifest, else the sum of
shot durations. ElevenLabs renders the exact length (cap 300s); Lyria renders a
~30s clip which is crossfade-looped up to the needed length.

Env: ELEVENLABS_API_KEY and/or GEMINI_API_KEY (or GOOGLE_API_KEY).
     MUSIC_MODEL overrides the ElevenLabs music model (default music_v2).
     LYRIA_MODEL overrides the Lyria model (default lyria-3.5).

Optional script.json "musicSections": [{"name", "styles": [...], "avoid": [...], "untilSec"}]
turns the bed into an ElevenLabs composition plan whose section boundaries land on the edit
(music_v2 enforces section durations exactly). Without it, a single instrumental prompt is used.
"""
import argparse, base64, json, os, re, subprocess, tempfile, requests

DEFAULT_MOOD = ("calm confident minimal corporate underscore, sparse piano, soft low pulse, "
                "steady forward motion, no drums, no risers")
BED_SUFFIX = (" Instrumental only, no vocals, even loudness suitable as a background bed under a voiceover."
              " Keep musical audio active through the requested duration; do not fade out or leave a silent tail.")


def _duration(path):
    return float(subprocess.run(
        ["ffprobe", "-v", "error", "-show_entries", "format=duration", "-of", "csv=p=0", path],
        capture_output=True, text=True,
    ).stdout.strip() or 0)


def _last_trailing_silence(text, duration, tolerance=0.25):
    starts = [float(x) for x in re.findall(r"silence_start:\s*([0-9.]+)", text)]
    ends = [float(x) for x in re.findall(r"silence_end:\s*([0-9.]+)", text)]
    if not starts or not ends or ends[-1] < duration - tolerance:
        return None
    start = starts[-1]
    return start if duration - start >= 0.7 else None


def _silent_gaps(text, max_gap=1.5):
    """Silences longer than max_gap seconds from ffmpeg silencedetect output, as (start, end)."""
    starts = [float(x) for x in re.findall(r"silence_start:\s*(-?[0-9.]+)", text)]
    ends = [float(x) for x in re.findall(r"silence_end:\s*([0-9.]+)", text)]
    return [(max(0.0, a), b) for a, b in zip(starts, ends) if b - max(0.0, a) > max_gap]


def assert_audible_bed(path, requested_seconds, reserve_seconds=2.5):
    """A bed must be audible under the whole picture: fail loudly on any long silent gap inside
    the timeline (the tail reserve is handled by ensure_audible_timeline_tail)."""
    detected = subprocess.run(["ffmpeg", "-hide_banner", "-i", path, "-af",
                               "silencedetect=noise=-50dB:d=1.5", "-f", "null", "-"],
                              capture_output=True, text=True)
    timeline = max(0.0, requested_seconds - reserve_seconds)
    gaps = [(a, b) for a, b in _silent_gaps(detected.stderr) if a < timeline - 0.7]
    if gaps:
        spans = ", ".join(f"{a:.1f}-{b:.1f}s" for a, b in gaps)
        raise SystemExit(f"FAILED music bed is silent inside the timeline ({spans}); "
                         "make the affected musicSections audible (styles, not silence) and rerun")


def ensure_audible_timeline_tail(path, requested_seconds, reserve_seconds=2.5):
    """Repair model-generated beds that stop musically before the picture ends.

    Music generation asks for a small reserve past the authored timeline. Some providers return a
    full-length container whose last 2–4 seconds are silent. When that silence reaches the picture,
    crossfade a stable mid-track passage into the tail; the Remotion timeline still owns the final
    authored fade.
    """
    duration = _duration(path)
    if duration < 6:
        return False
    detected = subprocess.run(
        ["ffmpeg", "-hide_banner", "-nostats", "-i", path, "-af",
         "silencedetect=n=-48dB:d=0.7", "-f", "null", "-"],
        capture_output=True, text=True,
    )
    silence_start = _last_trailing_silence(detected.stderr, duration)
    timeline_end = max(0.0, min(duration, float(requested_seconds)) - reserve_seconds)
    if silence_start is None or silence_start >= timeline_end + 0.5:
        return False

    crossfade = 0.5
    splice_at = max(1.0, min(silence_start - 0.75, timeline_end - 2.5))
    insert_seconds = max(3.0, float(requested_seconds) - splice_at + crossfade)
    latest_sample = max(1.0, splice_at - insert_seconds - 1.0)
    sample_start = min(max(1.0, duration * 0.33), latest_sample)
    sample_end = min(duration, sample_start + insert_seconds)
    if sample_end - sample_start < insert_seconds - 0.1:
        raise SystemExit("music has an early silent tail and no long enough passage to repair it")

    handle = tempfile.NamedTemporaryFile(suffix=".mp3", dir=os.path.dirname(path) or ".", delete=False)
    repaired = handle.name
    handle.close()
    try:
        graph = (
            f"[0:a]atrim=0:{splice_at:.3f},asetpts=PTS-STARTPTS[a];"
            f"[0:a]atrim={sample_start:.3f}:{sample_end:.3f},asetpts=PTS-STARTPTS[b];"
            f"[a][b]acrossfade=d={crossfade}:c1=tri:c2=tri,"
            f"atrim=0:{float(requested_seconds):.3f}[out]"
        )
        subprocess.run([
            "ffmpeg", "-y", "-v", "error", "-i", path, "-filter_complex", graph,
            "-map", "[out]", "-c:a", "libmp3lame", "-b:a", "192k", repaired,
        ], check=True)
        os.replace(repaired, path)
    finally:
        if os.path.exists(repaired):
            os.unlink(repaired)
    return True


def target_seconds(args, script):
    total = sum(float(s.get("durSec", 0)) for s in script.get("shots", []))
    narration = script.get("narration") if isinstance(script.get("narration"), dict) else {}
    master = narration.get("file")
    if master:
        path = master if os.path.isabs(str(master)) else os.path.join(args.project, str(master))
        if os.path.exists(path):
            duration = subprocess.run(
                ["ffprobe", "-v", "error", "-show_entries", "format=duration", "-of", "csv=p=0", path],
                capture_output=True, text=True,
            ).stdout.strip()
            if duration:
                total = max(total, float(duration) + float(narration.get("startsAtSec", 0)))
        return total + 2.5
    man = os.path.join(args.project, "audio", "manifest.json")
    if os.path.exists(man):
        total = max(total, sum(m["seconds"] for m in json.load(open(man))))
    return total + 2.5


MUSIC_MODEL = os.environ.get("MUSIC_MODEL", "music_v2")
NO_VOCALS = ["vocals", "singing", "lyrics", "spoken word"]


def composition_plan(script, seconds, model=None):
    """Build an instrumental plan whose section boundaries land on authored cut times.

    music_v2 takes the chunk form (per-chunk styles, durations always enforced);
    music_v1 takes the section form (MusicPrompt with global + local styles)."""
    sections = script.get("musicSections") or []
    if not sections:
        return None
    model = model or MUSIC_MODEL
    total_ms = int(round(seconds * 1000))
    mood = [p.strip() for p in (script.get("music") or DEFAULT_MOOD).split(",") if p.strip()]
    spans, start = [], 0
    for index, sec in enumerate(sections):
        last = index == len(sections) - 1
        end = total_ms if last else int(round(float(sec["untilSec"]) * 1000))
        duration = max(3000, min(120000, end - start))
        spans.append((str(sec.get("name") or f"section {index + 1}")[:100], sec, duration))
        start += duration
    if model == "music_v1":
        return {"positive_global_styles": mood + ["instrumental", "background bed under a voiceover"],
                "negative_global_styles": NO_VOCALS,
                "sections": [{"section_name": name, "positive_local_styles": list(sec.get("styles") or []),
                              "negative_local_styles": list(sec.get("avoid") or []) + NO_VOCALS,
                              "duration_ms": duration, "lines": []} for name, sec, duration in spans]}
    return {"chunks": [{"text": f"[{name}]\n{{instrumental, audible from the first beat}}", "duration_ms": duration,
                        "positive_styles": mood + list(sec.get("styles") or []) + ["instrumental"],
                        "negative_styles": list(sec.get("avoid") or []) + NO_VOCALS + ["silence"],
                        "context_adherence": "high"} for name, sec, duration in spans]}


def timed_prompt(script, seconds, base):
    """Fold musicSections into one prompt with explicit timestamps (prompt-mode fallback)."""
    parts, start = [], 0.0
    for index, sec in enumerate(script.get("musicSections") or []):
        end = seconds if index == len(script["musicSections"]) - 1 else float(sec["untilSec"])
        parts.append(f"{int(start)//60}:{int(start)%60:02d}-{int(end)//60}:{int(end)%60:02d} "
                     f"{sec.get('name', '')}: {', '.join(sec.get('styles') or [])}")
        start = end
    timeline = "; ".join(parts)
    return (base.split(BED_SUFFIX)[0][:300] + ". Structure: " + timeline)[:1900] + BED_SUFFIX


def gen_elevenlabs(prompt, seconds, out, plan=None):
    key = os.environ.get("ELEVENLABS_API_KEY") or os.environ.get("ELEVEN_API_KEY")
    length_ms = min(300000, int(round(seconds * 1000)) or 30000)
    body = ({"composition_plan": plan, "model_id": MUSIC_MODEL} if plan else
            {"prompt": prompt, "music_length_ms": length_ms, "model_id": MUSIC_MODEL,
             "force_instrumental": True})
    r = requests.post(
        "https://api.elevenlabs.io/v1/music",
        headers={"xi-api-key": key, "Content-Type": "application/json"},
        json=body,
        timeout=300,
    )
    if r.status_code >= 300:
        raise SystemExit(f"FAILED {r.status_code}: {r.text[:200]}")
    open(out, "wb").write(r.content)


def gen_lyria(prompt, seconds, out):
    key = os.environ.get("GEMINI_API_KEY") or os.environ.get("GOOGLE_API_KEY")
    model = os.environ.get("LYRIA_MODEL", "lyria-3.5")
    r = requests.post(
        f"https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent?key={key}",
        json={"contents": [{"parts": [{"text": prompt}]}],
              "generationConfig": {"responseModalities": ["AUDIO"]}},
        timeout=300,
    )
    if r.status_code >= 300:
        raise SystemExit(f"FAILED {r.status_code}: {r.text[:200]}")
    try:
        parts = r.json()["candidates"][0]["content"]["parts"]
        data = next(p["inlineData"] for p in parts if "inlineData" in p)
    except (KeyError, IndexError, StopIteration):
        raise SystemExit(f"FAILED no audio in response: {r.text[:200]}")
    with tempfile.NamedTemporaryFile(suffix=".mp3", delete=False) as tf:
        tf.write(base64.b64decode(data["data"])); clip = tf.name
    try:
        dur = float(subprocess.run(
            ["ffprobe", "-v", "error", "-show_entries", "format=duration", "-of", "csv=p=0", clip],
            capture_output=True, text=True).stdout.strip() or 0)
        if dur >= seconds:
            subprocess.run(["ffmpeg", "-y", "-v", "error", "-i", clip, "-t", f"{seconds:.2f}",
                            "-c:a", "libmp3lame", "-b:a", "192k", out], check=True)
        else:
            # crossfade-loop the clip up to length: each pass appends (dur - 2s) more
            loops = clip
            have = dur
            while have < seconds:
                nxt = tempfile.NamedTemporaryFile(suffix=".mp3", delete=False).name
                subprocess.run(["ffmpeg", "-y", "-v", "error", "-i", loops, "-i", clip,
                                "-filter_complex", "acrossfade=d=2:c1=tri:c2=tri",
                                "-c:a", "libmp3lame", "-b:a", "192k", nxt], check=True)
                if loops != clip:
                    os.unlink(loops)
                loops = nxt
                have += dur - 2
            subprocess.run(["ffmpeg", "-y", "-v", "error", "-i", loops, "-t", f"{seconds:.2f}",
                            "-af", f"afade=t=out:st={seconds-1.5:.2f}:d=1.5",
                            "-c:a", "libmp3lame", "-b:a", "192k", out], check=True)
            if loops != clip:
                os.unlink(loops)
    finally:
        os.unlink(clip)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--project", required=True)
    ap.add_argument("--provider", choices=["auto", "elevenlabs", "lyria"], default="auto")
    args = ap.parse_args()

    have_eleven = bool(os.environ.get("ELEVENLABS_API_KEY") or os.environ.get("ELEVEN_API_KEY"))
    have_gemini = bool(os.environ.get("GEMINI_API_KEY") or os.environ.get("GOOGLE_API_KEY"))
    provider = args.provider
    if provider == "auto":
        provider = "elevenlabs" if have_eleven else ("lyria" if have_gemini else "")
    if provider == "elevenlabs" and not have_eleven:
        raise SystemExit("set ELEVENLABS_API_KEY")
    if provider == "lyria" and not have_gemini:
        raise SystemExit("set GEMINI_API_KEY")
    if not provider:
        raise SystemExit("set ELEVENLABS_API_KEY or GEMINI_API_KEY")

    script = json.load(open(os.path.join(args.project, "script.json")))
    prompt = (script.get("music") or DEFAULT_MOOD)[:480] + BED_SUFFIX
    seconds = target_seconds(args, script)
    out = os.path.join(args.project, "music.mp3")
    plan = composition_plan(script, seconds) if provider == "elevenlabs" else None
    if provider == "elevenlabs":
        gen_elevenlabs(prompt, seconds, out, plan)
    else:
        gen_lyria(prompt, seconds, out)
    repaired = ensure_audible_timeline_tail(out, seconds)
    if plan:
        try:
            assert_audible_bed(out, seconds)
        except SystemExit as exc:
            # Observed 2026-09-23: music_v2 chunk plans can open with 10-15 s of digital
            # silence. Retry once as a prompt that narrates the same section timeline.
            print(f"music: composition plan rejected ({exc}); retrying as a timed prompt")
            gen_elevenlabs(timed_prompt(script, seconds, prompt), seconds, out, None)
            repaired = ensure_audible_timeline_tail(out, seconds)
    assert_audible_bed(out, seconds)
    dur = f"{_duration(out):.6f}"
    if repaired:
        print("music: repaired provider's early silent outro with a crossfaded tail")
    print(f"music ({provider}): {os.path.getsize(out)//1024}KB, {dur}s (asked {seconds:.1f}s)")


if __name__ == "__main__":
    main()
