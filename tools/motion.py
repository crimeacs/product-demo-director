#!/usr/bin/env python3
"""Motion-graphics films: code-built, style-frame-first, deterministic, motion-blurred.

    python tools/motion.py new projects/my-film            # scaffold film.html, cues.json, motion.json
    python tools/motion.py styleframes projects/my-film f=A1 f=B1  # render styleframes.html frames + sheet
    python tools/motion.py stills projects/my-film 1.2 5.5 # render review stills (fast)
    python tools/motion.py music projects/my-film          # generate music.mp3 from motion.json musicPrompt (ElevenLabs)
    python tools/motion.py sfx projects/my-film            # generate a per-film SFX palette from motion.json sfxPrompts
    python tools/motion.py render projects/my-film         # full render with motion blur -> out/silent.mp4
    python tools/motion.py mix projects/my-film            # music + SFX cue sheet -> out/final.mp4
    python tools/motion.py qa projects/my-film             # loudness / silence / black gates + contact sheet

See docs/MOTION_GRAPHICS.md for the method (style frames first, direction catalogue, craft rules).
motion.json keys: film, music, musicOffsetSec, musicVolume, durationSec, fps, sub, dpr, workers, sfxDir.
"""
import argparse, json, os, shutil, subprocess, sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SFX_DIR = os.path.join(ROOT, "engine", "public", "sfx")
GAIN = {"impact": .85, "pivot_boom": 1.0, "whoosh": .55, "click": .7, "data_tick": .5,
        "success_chime": .8, "confirm_cash": .75, "riser": .6}


def load(project):
    cfg_path = os.path.join(project, "motion.json")
    cfg = json.load(open(cfg_path)) if os.path.exists(cfg_path) else {}
    cfg.setdefault("film", "film.html")
    return cfg


def render(project, cfg, extra):
    out = os.path.join(project, "out", "silent.mp4")
    cmd = ["node", os.path.join(ROOT, "tools", "motion_render.mjs"), "--film", os.path.join(project, cfg["film"]), "--out", out,
           "--fps", str(cfg.get("fps", 60)), "--sub", str(cfg.get("sub", 4)), "--dpr", str(cfg.get("dpr", 1)),
           "--workers", str(cfg.get("workers", 8))] + extra
    subprocess.run(cmd, check=True)
    return out


def build_mix(silent, dur, cfg, cues, project, sfx_dir):
    """Return (ffmpeg input args, filter_complex parts, mix labels). Pure: unit-tested."""
    inputs, parts, labels, n_in = ["-i", silent], [], [], 1   # n_in counts inputs, not argv tokens
    if cfg.get("music"):
        inputs += ["-ss", str(cfg.get("musicOffsetSec", 0)), "-i", os.path.join(project, cfg["music"])]
        parts.append(f"[{n_in}:a]atrim=0:{dur},asetpts=PTS-STARTPTS,afade=t=in:d=0.25,afade=t=out:st={dur-0.8}:d=0.8,"
                     f"volume={cfg.get('musicVolume', .55)}[m]")
        labels.append("[m]")
        n_in += 1
    for i, c in enumerate(cues):
        ms = int(float(c["t"]) * 1000)
        inputs += ["-i", os.path.join(sfx_dir, f"{c['cue']}.mp3")]
        parts.append(f"[{n_in}:a]volume={c.get('gain', GAIN.get(c['cue'], .6))},adelay={ms}|{ms}[s{i}]")
        labels.append(f"[s{i}]")
        n_in += 1
    return inputs, parts, labels


def mix(project, cfg):
    silent, out = os.path.join(project, "out", "silent.mp4"), os.path.join(project, "out", "final.mp4")
    dur = float(subprocess.run(["ffprobe", "-v", "error", "-show_entries", "format=duration", "-of", "csv=p=0", silent],
                               capture_output=True, text=True, check=True).stdout.strip())
    cues_path = os.path.join(project, "cues.json")
    cues = json.load(open(cues_path)) if os.path.exists(cues_path) else []
    sfx = cfg.get("sfxDir", SFX_DIR)
    sfx = sfx if os.path.isabs(sfx) else (os.path.join(project, sfx) if cfg.get("sfxDir") else sfx)
    missing = sorted({c["cue"] for c in cues if not os.path.exists(os.path.join(sfx, f"{c['cue']}.mp3"))})
    if missing:
        raise SystemExit(f"missing SFX palette cues {missing} in {sfx}: generate it with `python tools/sfx.py` "
                         "(needs ELEVENLABS_API_KEY) or set motion.json sfxDir")
    if cfg.get("music") and not os.path.exists(os.path.join(project, cfg["music"])):
        raise SystemExit(f"music bed {cfg['music']} not found in {project}: generate it (see the project README) or set music to null")
    inputs, parts, labels = build_mix(silent, dur, cfg, cues, project, sfx)
    if not labels:
        raise SystemExit("nothing to mix: set motion.json music and/or cues.json")
    parts.append("".join(labels) + f"amix=inputs={len(labels)}:normalize=0:duration=longest,atrim=0:{dur},"
                 "loudnorm=I=-14:TP=-1.5:LRA=9,aresample=48000[a]")
    subprocess.run(["ffmpeg", "-loglevel", "error", "-y", *inputs, "-filter_complex", ";".join(parts), "-map", "0:v", "-map", "[a]",
                    "-c:v", "copy", "-c:a", "aac", "-b:a", "256k", "-movflags", "+faststart", "-shortest", out], check=True)
    print("mixed", out)
    return out


def qa(project, cfg):
    f = os.path.join(project, "out", "final.mp4")
    if not os.path.exists(f):
        f = os.path.join(project, "out", "silent.mp4")
    probe = json.loads(subprocess.run(["ffprobe", "-v", "error", "-show_entries", "format=duration:stream=codec_type,width,height,r_frame_rate",
                                       "-of", "json", f], capture_output=True, text=True, check=True).stdout)
    run = lambda af: subprocess.run(["ffmpeg", "-hide_banner", "-i", f, *af, "-f", "null", "-"], capture_output=True, text=True).stderr
    lufs = next((l.split()[1] for l in run(["-af", "ebur128=peak=true"]).splitlines() if l.strip().startswith("I:")), None)
    silences = run(["-af", "silencedetect=n=-48dB:d=0.7"]).count("silence_start")
    blacks = run(["-vf", "blackdetect=d=0.2:pix_th=0.10", "-an"]).count("black_start")
    dur = float(probe["format"]["duration"])
    sheet = os.path.join(project, "out", "contact_sheet.jpg")
    ts = [round(dur * (i + .5) / 12, 2) for i in range(12)]
    tiles = []
    for t in ts:
        p = os.path.join(project, "out", f".qa_{t}.png")
        subprocess.run(["ffmpeg", "-loglevel", "error", "-y", "-ss", str(t), "-i", f, "-frames:v", "1", "-vf", "scale=640:-1", p], check=True)
        tiles.append(p)
    layout = "|".join(f"{'+'.join(['w0']*(i%4)) or 0}_{'+'.join(['h0']*(i//4)) or 0}" for i in range(12))
    subprocess.run(["ffmpeg", "-loglevel", "error", "-y", *sum([["-i", p] for p in tiles], []),
                    "-filter_complex", f"xstack=inputs=12:layout={layout}", sheet], check=True)
    for p in tiles:
        os.remove(p)
    report = {"file": f, "durationSec": dur, "streams": probe["streams"], "integratedLUFS": lufs,
              "silences": silences, "blackIntervals": blacks, "contactSheet": sheet}
    ok = silences == 0 and blacks == 0 and lufs is not None and -16.5 <= float(lufs) <= -12.5
    report["status"] = "pass" if ok else "fail"
    json.dump(report, open(os.path.join(project, "out", "motion_qa.json"), "w"), indent=1)
    print(json.dumps(report, indent=1))
    print("Now LOOK at the contact sheet and the finished file before calling it done.")
    sys.exit(0 if ok else 1)


def styleframes(project, shots):
    """Render styleframes.html once per query (e.g. f=A1) and tile them into out/styleframes_sheet.jpg."""
    page = os.path.join(project, "styleframes.html")
    if not os.path.exists(page):
        raise SystemExit(f"{page} not found: design 2-3 directions there first (docs/MOTION_GRAPHICS.md)")
    if not shots:
        raise SystemExit("name the frames to render, e.g. f=A1 f=A2 f=B1")
    out = os.path.join(project, "out", "styleframe.mp4")
    subprocess.run(["node", os.path.join(ROOT, "tools", "motion_render.mjs"), "--film", page, "--out", out, "--shots", ",".join(shots)], check=True)
    files = [out.replace(".mp4", "") + "_" + "".join(c if c.isalnum() or c == "_" else "_" for c in q) + ".png" for q in shots]
    cols = min(len(files), 6)
    layout = "|".join(f"{'+'.join(['w0'] * (i % cols)) or 0}_{'+'.join(['h0'] * (i // cols)) or 0}" for i in range(len(files)))
    sheet = os.path.join(project, "out", "styleframes_sheet.jpg")
    if len(files) > 1:
        subprocess.run(["ffmpeg", "-loglevel", "error", "-y", *sum([["-i", f] for f in files], []), "-filter_complex",
                        f"xstack=inputs={len(files)}:layout={layout},scale='min(3600,iw)':-1", sheet], check=True)
        print("sheet", sheet)
    print("Show these to the founder and ask which frames they like and dislike, and why, before animating.")


def _eleven(path, body, out, accept="audio/mpeg", timeout=300):
    """POST to ElevenLabs with a hard wall-clock limit (a socket timeout is not a deadline)."""
    import threading, urllib.request
    key = os.environ.get("ELEVENLABS_API_KEY")
    if not key:
        raise SystemExit("set ELEVENLABS_API_KEY")
    box = {}
    def run():
        try:
            req = urllib.request.Request("https://api.elevenlabs.io" + path, data=json.dumps(body).encode(), method="POST",
                                         headers={"xi-api-key": key, "Content-Type": "application/json", "Accept": accept})
            with urllib.request.urlopen(req, timeout=timeout) as r:
                box["data"] = r.read()
        except Exception as exc:          # noqa: BLE001 - surfaced below
            box["err"] = exc
    th = threading.Thread(target=run, daemon=True); th.start(); th.join(timeout + 30)
    if th.is_alive():
        raise SystemExit(f"ElevenLabs {path} exceeded {timeout}s")
    if "err" in box:
        err = box["err"]; detail = getattr(err, "read", lambda: b"")()[:300]
        raise SystemExit(f"ElevenLabs {path} failed: {err} {detail!r}")
    open(out, "wb").write(box["data"])


def _silent_gaps(path, min_gap=1.2):
    txt = subprocess.run(["ffmpeg", "-hide_banner", "-i", path, "-af", f"silencedetect=noise=-50dB:d={min_gap}", "-f", "null", "-"],
                         capture_output=True, text=True).stderr
    import re
    st = [float(x) for x in re.findall(r"silence_start:\s*(-?[0-9.]+)", txt)]
    en = [float(x) for x in re.findall(r"silence_end:\s*([0-9.]+)", txt)]
    return list(zip(st, en))


def gen_music(project, cfg):
    """Music bed from motion.json musicPrompt (instrumental, prompt mode: music_v2 composition plans can open silent)."""
    prompt, length = cfg.get("musicPrompt"), float(cfg.get("musicLengthSec", 30))
    if not prompt:
        raise SystemExit("set motion.json musicPrompt (describe instrumentation, BPM and a timed structure, no artist names)")
    out = os.path.join(project, cfg.get("music") or "music.mp3")
    _eleven("/v1/music", {"prompt": prompt, "music_length_ms": int(length * 1000), "model_id": "music_v2", "force_instrumental": True}, out)
    gaps = [g for g in _silent_gaps(out) if g[0] < length - 2]
    lead = [g for g in gaps if g[0] <= .05]
    inner = [g for g in gaps if g[0] > .05]
    if inner:
        raise SystemExit(f"music bed has silent gaps {inner}; regenerate or change the prompt")
    if lead:
        print(f"note: the bed opens with {lead[0][1]:.2f}s of near-silence; set motion.json musicOffsetSec >= {lead[0][1]:.2f}")
    print("music", out, "- map its energy (see docs) and set musicOffsetSec so the drop lands on the turn")


def gen_sfx(project, cfg):
    """Per-film SFX palette: motion.json sfxPrompts {name: {prompt, seconds}} -> <project>/sfx/<name>.mp3."""
    prompts = cfg.get("sfxPrompts") or {}
    if not prompts:
        raise SystemExit("set motion.json sfxPrompts, e.g. {\"relay\": {\"prompt\": \"soft relay click\", \"seconds\": 0.6}}")
    d = os.path.join(project, "sfx"); os.makedirs(d, exist_ok=True)
    for name, spec in prompts.items():
        raw, out = os.path.join(d, f"{name}_raw.mp3"), os.path.join(d, f"{name}.mp3")
        # provider accepts 0.5-30 s; request at least 0.5 s and trim to the asked length below
        _eleven("/v1/sound-generation", {"text": spec["prompt"], "duration_seconds": min(30.0, max(.5, float(spec.get("seconds", 1.0)))),
                                          "prompt_influence": float(spec.get("influence", .5)), "model_id": "eleven_text_to_sound_v2"}, raw, timeout=180)
        dur = float(spec.get("seconds", 1.0))
        subprocess.run(["ffmpeg", "-loglevel", "error", "-y", "-i", raw, "-t", f"{dur:.3f}", "-af", f"loudnorm=I=-19:TP=-1.5,afade=t=out:st={max(.05, dur-.15):.2f}:d=0.15", out], check=True)
        os.remove(raw); print("sfx", out)
    print("set motion.json sfxDir to \"sfx\" so mix uses this palette")


def new(project):
    os.makedirs(os.path.join(project, "out"), exist_ok=True)
    tpl = os.path.join(ROOT, "motion", "starter.html")
    dst = os.path.join(project, "film.html")
    if os.path.exists(dst):
        raise SystemExit(f"{dst} exists; refusing to overwrite")
    rel = os.path.relpath(os.path.join(ROOT, "motion"), project).replace(os.sep, "/")
    open(dst, "w").write(open(tpl).read().replace("{{MOTION}}", rel))
    json.dump({"film": "film.html", "music": None, "musicOffsetSec": 0, "musicVolume": .55,
               "fps": 60, "sub": 4, "dpr": 1, "workers": 8}, open(os.path.join(project, "motion.json"), "w"), indent=1)
    json.dump([], open(os.path.join(project, "cues.json"), "w"))
    print(f"scaffolded {project}. Next: style frames first (docs/MOTION_GRAPHICS.md), then build scenes in film.html.")


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("cmd", choices=["new", "styleframes", "music", "sfx", "stills", "render", "mix", "qa", "all"])
    ap.add_argument("project")
    ap.add_argument("times", nargs="*")
    a = ap.parse_args()
    if a.cmd == "new":
        return new(a.project)
    cfg = load(a.project)
    if a.cmd == "styleframes":
        return styleframes(a.project, a.times)
    if a.cmd == "music":
        return gen_music(a.project, cfg)
    if a.cmd == "sfx":
        return gen_sfx(a.project, cfg)
    if a.cmd == "stills":
        return render(a.project, cfg, ["--stills", ",".join(a.times or ["1", "5", "10"])])
    if a.cmd in ("render", "all"):
        render(a.project, cfg, [])
    if a.cmd in ("mix", "all"):
        mix(a.project, cfg)
    if a.cmd in ("qa", "all"):
        qa(a.project, cfg)


if __name__ == "__main__":
    main()
