#!/usr/bin/env python3
"""UGC talking-head footage for a demo — a real-looking person vouching for the product.

ElevenLabs has no scriptable video API (avatar/lip-sync lives in the ElevenCreative playground),
so this tool does the parts that ARE scriptable and hands you a tight playground runbook for the
one manual step. It reuses the project's voice, so the on-camera creator and the voiceover are the
same person end to end.

  python tools/ugc.py --project examples/funnel --voice     # TTS the creator's lines -> assets/_raw/<name>.mp3
  python tools/ugc.py --project examples/funnel --runbook    # print the exact ElevenCreative steps
  python tools/ugc.py --project examples/funnel --install ugc_hook ~/Downloads/hook.mp4   # normalize a clip -> assets/ugc_hook.mp4 (keeps audio)

Flow: (1) --voice makes the creator's audio. (2) In the ElevenCreative playground, generate the
character image (prompt in ugc.json), pick a lip-sync/avatar model (OmniHuman 1.5), drop in the
matching audio from step 1, generate, and download the MP4. (3) --install normalizes it into
assets/<name>.mp4. (4) Re-run build.py — the script's `sound:true` clip beats play the creator's voice.

ugc.json (in the project): { voiceId, character (image prompt), voice_settings, shots:[{name,text}] }.
Env: ELEVENLABS_API_KEY.
"""
import argparse, json, os, subprocess, sys

HERE = os.path.dirname(os.path.abspath(__file__))
MODEL = os.environ.get("UGC_TTS_MODEL", "eleven_multilingual_v2")


def _key():
    return os.environ.get("ELEVENLABS_API_KEY") or os.environ.get("ELEVEN_API_KEY")


def gen_voice(cfg, raw_dir):
    import requests
    key = _key()
    if not key:
        raise SystemExit("set ELEVENLABS_API_KEY")
    vid = cfg.get("voiceId") or "bIHbv24MWmeRgasZH58o"
    vs = cfg.get("voice_settings", {"stability": 0.4, "similarity_boost": 0.85, "style": 0.45, "use_speaker_boost": True})
    os.makedirs(raw_dir, exist_ok=True)
    out = []
    for sh in cfg["shots"]:
        dest = os.path.join(raw_dir, f"{sh['name']}.mp3")
        r = requests.post(
            f"https://api.elevenlabs.io/v1/text-to-speech/{vid}",
            headers={"xi-api-key": key, "Content-Type": "application/json", "Accept": "audio/mpeg"},
            json={"text": sh["text"], "model_id": MODEL, "voice_settings": vs}, timeout=120)
        if r.status_code >= 300:
            print(f"  {sh['name']}: TTS error {r.status_code}: {r.text[:200]}")
            continue
        open(dest, "wb").write(r.content)
        secs = _dur(dest)
        out.append((sh["name"], dest, secs))
        print(f"  {sh['name']:10s} -> {os.path.relpath(dest)}  ({secs:.1f}s)  «{sh['text'][:60]}»")
    return out


def _dur(path):
    r = subprocess.run(["ffprobe", "-v", "error", "-show_entries", "format=duration",
                        "-of", "default=nk=1:nw=1", path], capture_output=True, text=True)
    try:
        return round(float(r.stdout.strip()), 1)
    except Exception:
        return 0.0


def install(name, src, project):
    """Normalize a downloaded talking-head into <project>/assets/<name>.mp4 (1920x1080/30) — KEEPS audio.
    Fits the FULL frame (no face crop) on a plain white canvas. No creative color grade, no vignette,
    and no blurred side-fill by default; UGC should feel authentic unless the brief asks for a look."""
    assets = os.path.join(project, "assets")
    os.makedirs(assets, exist_ok=True)
    out = os.path.join(assets, f"{name}.mp4")
    fc = "[0:v]scale=-2:1080:force_original_aspect_ratio=decrease,pad=1920:1080:(ow-iw)/2:(oh-ih)/2:color=white,fps=30,setsar=1,format=yuv420p"
    subprocess.run(["ffmpeg", "-y", "-i", src, "-filter_complex", fc, "-c:v", "libx264", "-crf", "18",
                    "-preset", "medium", "-c:a", "aac", "-b:a", "160k", out], capture_output=True)
    print(f"installed -> {os.path.relpath(out)}  ({_dur(out):.1f}s, audio kept)")
    print(f"  set the matching clip beat in script.json to durSec ~{_dur(out):.1f}, \"sound\": true")
    return out


def runbook(cfg, project):
    raw = os.path.join(project, "assets", "_raw")
    print("\n=== ElevenCreative playground runbook (the one manual step) ===\n")
    print("1. Generate the creator image — in ElevenCreative > Image, paste this prompt:\n")
    print("   " + cfg["character"] + "\n")
    print("   Pick the take with the face square to camera, eyes on lens, evenly lit. Download it.\n")
    print("2. Make the talking head — ElevenCreative > Video, model: OmniHuman 1.5 (image + audio).")
    print("   For EACH shot below: upload the image, upload the matching audio, generate, download:\n")
    for sh in cfg["shots"]:
        ap = os.path.join(raw, f"{sh['name']}.mp3")
        tag = "(run --voice first)" if not os.path.exists(ap) else f"({_dur(ap):.1f}s)"
        print(f"   - {sh['name']}: audio = {os.path.relpath(ap)} {tag}")
        print(f"       line: «{sh['text']}»")
    print("\n3. Install each downloaded clip:")
    for sh in cfg["shots"]:
        print(f"   python tools/ugc.py --project {os.path.relpath(project)} --install {sh['name']} <downloaded.mp4>")
    print("\n4. Re-run build.py — the `sound:true` clip beats now play the creator on camera.")
    print(f"\nVoice: {cfg.get('voiceName', cfg.get('voiceId'))}  (use the SAME voice for vo.py so on-camera and voiceover match).\n")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--project", required=True)
    ap.add_argument("--config", default="", help="ugc.json (default <project>/ugc.json)")
    ap.add_argument("--voice", action="store_true", help="TTS the creator's lines -> assets/_raw/")
    ap.add_argument("--runbook", action="store_true", help="print the ElevenCreative playground steps")
    ap.add_argument("--install", nargs=2, metavar=("NAME", "SRC"), help="normalize a downloaded clip -> assets/NAME.mp4")
    a = ap.parse_args()
    proj = os.path.abspath(a.project)
    cfg = json.load(open(a.config or os.path.join(proj, "ugc.json")))

    if a.install:
        install(a.install[0], os.path.expanduser(a.install[1]), proj)
        return
    if a.voice:
        print("generating creator voice (feed these into OmniHuman in the playground):")
        gen_voice(cfg, os.path.join(proj, "assets", "_raw"))
    if a.runbook or not a.voice:
        runbook(cfg, proj)


if __name__ == "__main__":
    main()
