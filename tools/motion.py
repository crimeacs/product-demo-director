#!/usr/bin/env python3
"""Motion-graphics films: code-built, style-frame-first, deterministic, motion-blurred.

    python tools/motion.py new projects/my-film            # scaffold film.html, cues.json, motion.json
    python tools/motion.py stills projects/my-film 1.2 5.5 # render review stills (fast)
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
    ap.add_argument("cmd", choices=["new", "stills", "render", "mix", "qa", "all"])
    ap.add_argument("project")
    ap.add_argument("times", nargs="*")
    a = ap.parse_args()
    if a.cmd == "new":
        return new(a.project)
    cfg = load(a.project)
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
