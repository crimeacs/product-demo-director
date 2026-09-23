#!/usr/bin/env python3
"""Forge a bespoke SFX palette and let a model *listen* and keep the best of each.

For every cue it generates N variants with the ElevenLabs sound-generation API, has Gemini
listen and rate each for fit, and installs the top scorer to engine/public/sfx/<cue>.mp3.
The engine wires these as per-beat accents (set "accent": "<cue>" on a shot) plus the pivot
boom + riser and the soft per-cut whoosh. Generated palettes stay local by default; run this
only when the production calls for model-generated sound design.

  python tools/sfx.py                 # regenerate the default palette (3 variants/cue, judged)
  python tools/sfx.py --cues my.json  # custom cues: {"<key>":{"dur":1.1,"role":"...","variants":[...]}}
  python tools/sfx.py --keep          # keep the loudness-normalized raw variants for inspection

Keys: ELEVENLABS_API_KEY (generate), GEMINI_API_KEY / GOOGLE_API_KEY (listen + score).
"""
import argparse, json, os, re, shutil, subprocess, sys, time

HERE = os.path.dirname(os.path.abspath(__file__))
SFX_DIR = os.path.join(HERE, "..", "engine", "public", "sfx")

DEFAULT_CUES = {
  "whoosh":        {"dur": 0.7, "infl": 0.4,  "role": "a smooth, subtle scene-transition whoosh",
                    "variants": ["smooth subtle cinematic whoosh transition, soft filtered air, short, clean",
                                 "gentle airy swoosh transition, premium, understated",
                                 "soft modern UI swipe whoosh, brief, tasteful"]},
  "click":         {"dur": 0.35, "infl": 0.5, "role": "a crisp tactile premium UI click",
                    "variants": ["crisp single soft UI click, premium tactile tap, clean and short",
                                 "satisfying soft mouse click, rounded tactile pop",
                                 "gentle precise click tick, premium interface tap"]},
  "data_tick":     {"dur": 0.9, "infl": 0.45, "role": "a soft subtle data-processing tick under a UI scanning data",
                    "variants": ["soft subtle data ticks, light digital blips and a faint shimmer, gentle",
                                 "quiet modern UI scanning sound, soft rapid clicks, understated",
                                 "delicate data shimmer with tiny ticks, soft, unobtrusive"]},
  "success_chime": {"dur": 1.1, "infl": 0.5,  "role": "a success chime when a check passes",
                    "variants": ["satisfying soft success chime, two gentle ascending bell tones, premium UI",
                                 "warm glassy success ding, bright minimal two-note confirmation",
                                 "positive UI success sparkle chime, soft mallet bells ascending, clean"]},
  "confirm_cash":  {"dur": 1.2, "infl": 0.5,  "role": "a premium positive confirmation for a big number reveal",
                    "variants": ["premium positive confirmation with a soft bright sparkle, tasteful, not cartoonish",
                                 "rich confident confirmation tone with a subtle shimmer up, classy, modern",
                                 "warm affirmative chord with a light sparkle tail, refined not flashy"]},
  "riser":         {"dur": 1.6, "infl": 0.4,  "role": "a short rising tension riser into a reveal",
                    "variants": ["short clean rising riser swell building tension, smooth crescendo",
                                 "gentle upward whoosh riser, airy build into a hit",
                                 "subtle tonal riser sweep building anticipation, modern"]},
  "pivot_boom":    {"dur": 1.6, "infl": 0.45, "role": "a deep cinematic boom on a dramatic reveal",
                    "variants": ["deep cinematic sub-bass impact boom with a soft fading tail, clean low end",
                                 "warm low boom thump with gentle decay, dramatic but tasteful",
                                 "soft powerful impact hit, rounded low-end boom, not harsh"]},
}

def ekey():
    for k in ("ELEVENLABS_API_KEY", "ELEVEN_API_KEY"):
        if os.environ.get(k): return os.environ[k]
def gkey():
    for k in ("GEMINI_API_KEY", "GOOGLE_API_KEY"):
        if os.environ.get(k): return os.environ[k]

def generate(prompt, dur, out, infl):
    import requests
    r = requests.post("https://api.elevenlabs.io/v1/sound-generation",
        headers={"xi-api-key": ekey(), "Content-Type": "application/json", "Accept": "audio/mpeg"},
        json={"text": prompt, "duration_seconds": dur, "prompt_influence": infl,
              "model_id": os.environ.get("SFX_MODEL", "eleven_text_to_sound_v2")}, timeout=180)
    if r.status_code >= 300: return False
    raw = out.replace(".mp3", "_raw.mp3"); open(raw, "wb").write(r.content)
    subprocess.run(["ffmpeg","-y","-i",raw,"-af",f"loudnorm=I=-19:TP=-1.5,afade=t=out:st={max(0.1,dur-0.18):.2f}:d=0.18",out], capture_output=True)
    os.remove(raw); return True

def listen_score(path, role):
    from google import genai
    from google.genai import types
    c = genai.Client(api_key=gkey()); f = c.files.upload(file=path)
    for _ in range(40):
        f = c.files.get(name=f.name)
        if getattr(f.state,"name",str(f.state)) == "ACTIVE": break
        time.sleep(2)
    prompt = (f"You are a senior sound designer for high-end product films. LISTEN to this short sound. "
        f"Intended role: {role}. Rate 0-100 how well it works for that role in a polished, premium, NON-cheesy demo. "
        f"Penalize harsh, cheap/8-bit, cartoonish, distorted, generic-stock, annoying. Reward clean, modern, tasteful, "
        f"satisfying, well-shaped. Return STRICT JSON only: {{\"score\":<int>,\"note\":\"<10 words>\"}}")
    for model in (os.environ.get("SFX_LISTEN_MODEL", "gemini-3.1-pro-preview"), "gemini-3.8-flash"):
        try:
            resp = c.models.generate_content(model=model,
                contents=types.Content(parts=[types.Part(file_data=types.FileData(file_uri=f.uri, mime_type=f.mime_type)), types.Part(text=prompt)]),
                config=types.GenerateContentConfig(response_mime_type="application/json",
                                                   thinking_config=types.ThinkingConfig(thinking_level="high")))
            return json.loads(re.search(r"\{.*\}", resp.text, re.S).group(0))
        except Exception: continue
    return {"score": 0, "note": "judge error"}

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--cues", default=""); ap.add_argument("--keep", action="store_true")
    a = ap.parse_args()
    cues = json.load(open(a.cues)) if a.cues else DEFAULT_CUES
    os.makedirs(SFX_DIR, exist_ok=True)
    tmp = os.path.join(HERE, "..", ".sfx_lab"); os.makedirs(tmp, exist_ok=True)
    for key, c in cues.items():
        best, best_s, allr = None, -1, []
        for i, prompt in enumerate(c["variants"]):
            cand = os.path.join(tmp, f"{key}_{i}.mp3")
            if not generate(prompt, c["dur"], cand, c.get("infl", 0.45)): continue
            r = listen_score(cand, c["role"]); allr.append(r.get("score", 0))
            if r.get("score", 0) > best_s: best, best_s = cand, r.get("score", 0)
        if best:
            shutil.copy(best, os.path.join(SFX_DIR, f"{key}.mp3"))
            print(f"  {key:14s} kept {best_s}  (variants {allr})")
    if not a.keep: shutil.rmtree(tmp, ignore_errors=True)
    print("palette ->", os.path.relpath(SFX_DIR))

if __name__ == "__main__":
    main()
