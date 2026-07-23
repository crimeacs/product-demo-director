#!/usr/bin/env python3
"""Voiceover — ElevenLabs (eleven_v3) or Gemini TTS, auto-selected by capability.

Reads <project>/script.json, writes <project>/audio/s<n>.mp3 + manifest.json.
Auto-paced narration maps require ElevenLabs character alignment; Gemini remains
available for per-shot and other non-auto-paced narration.

    python tools/vo.py --project projects/my-demo
    python tools/vo.py --project projects/my-demo --provider gemini

Env:
  ELEVENLABS_API_KEY   enables the ElevenLabs provider
  GEMINI_API_KEY       enables the Gemini TTS provider (or GOOGLE_API_KEY)
  VO_VOICE_ID          ElevenLabs voice id (default: George, a grounded narrative read)
  VO_MODEL             default eleven_v3
  GEMINI_TTS_MODEL     default gemini-2.5-flash-preview-tts
  GEMINI_TTS_VOICE     default Charon (a warm, confident narrator)

Optional per-script knobs (in script.json):
  "voiceId": "..."                         # ElevenLabs voice id
  "voice_settings": { "stability":0.32, "style":0.75, ... }   # ElevenLabs only
  "vo_tts": "[quietly] Spoken line"        # per-shot v3 performance tags; `vo` stays clean
  "narration": {"text":"[building] One continuous performance", "file":"audio/master.mp3"}
  "gemini_voice": "Charon"                  # Gemini prebuilt voice for this project
  "tts_direction": "confidently, warmly"    # spoken-style direction (Gemini only)
  "pronounce": { "Foresyn": "Foreseen" }    # spelling->spoken, applied to the VO audio ONLY
                                            # (on-screen captions keep the real spelling)
"""
import argparse, base64, hashlib, json, os, re, subprocess, tempfile, time, requests

DEFAULT_SETTINGS = {"stability": 0.32, "similarity_boost": 0.85, "style": 0.75, "use_speaker_boost": True}
DEFAULT_DIRECTION = "in a confident, warm product-video narrator voice, energetic but natural"
DEFAULT_ELEVEN_VOICE_ID = "JBFqnCBsd6RMkjVDRZzb"  # George — official premade narrative voice
ALIGNMENT_PROVIDER_ERROR = (
    "auto-paced mapped narration requires ElevenLabs character alignment. "
    "Set ELEVENLABS_API_KEY and use --provider elevenlabs (or leave --provider auto). "
    "Gemini TTS does not return the character timestamps required by pace.py; "
    "it remains available when production.autoPaceNarration is false."
)


def needs_character_alignment(script):
    """Whether this production contract requires provider-aligned narration thoughts."""
    production = script.get("production") if isinstance(script.get("production"), dict) else {}
    narration = script.get("narration") if isinstance(script.get("narration"), dict) else {}
    return bool(production.get("autoPaceNarration") and narration.get("fromMap"))


def select_provider(requested, script, environ=None):
    """Select a configured provider while enforcing the pacing capability contract."""
    environ = os.environ if environ is None else environ
    have_eleven = bool(environ.get("ELEVENLABS_API_KEY") or environ.get("ELEVEN_API_KEY"))
    have_gemini = bool(environ.get("GEMINI_API_KEY") or environ.get("GOOGLE_API_KEY"))
    provider = requested
    if provider == "auto":
        provider = "elevenlabs" if have_eleven else ("gemini" if have_gemini else "")
    if needs_character_alignment(script) and provider != "elevenlabs":
        raise ValueError(ALIGNMENT_PROVIDER_ERROR)
    if provider == "elevenlabs" and not have_eleven:
        raise ValueError("set ELEVENLABS_API_KEY")
    if provider == "gemini" and not have_gemini:
        raise ValueError("set GEMINI_API_KEY")
    if not provider:
        raise ValueError("set ELEVENLABS_API_KEY or GEMINI_API_KEY")
    return provider


def synth_elevenlabs(spoken, out, script, override=None):
    override = override if isinstance(override, dict) else {}
    key = os.environ.get("ELEVENLABS_API_KEY") or os.environ.get("ELEVEN_API_KEY")
    model = override.get("model") or os.environ.get("VO_MODEL", "eleven_v3")
    voice = (os.environ.get("VO_VOICE_ID") or override.get("voiceId")
             or script.get("voiceId") or DEFAULT_ELEVEN_VOICE_ID)
    settings = override.get("voice_settings") or script.get("voice_settings", DEFAULT_SETTINGS)
    r = requests.post(
        f"https://api.elevenlabs.io/v1/text-to-speech/{voice}?output_format=mp3_44100_128",
        headers={"xi-api-key": key, "Content-Type": "application/json", "Accept": "audio/mpeg"},
        json={"text": spoken, "model_id": model,
              "voice_settings": settings},
        timeout=120,
    )
    if r.status_code >= 300:
        return f"{r.status_code}: {r.text[:160]}"
    with open(out, "wb") as fh:
        fh.write(r.content)
    return None


def synth_elevenlabs_aligned(spoken, out, script, override=None):
    """Synthesize one master and return ElevenLabs character-level alignment."""
    override = override if isinstance(override, dict) else {}
    key = os.environ.get("ELEVENLABS_API_KEY") or os.environ.get("ELEVEN_API_KEY")
    model = override.get("model") or os.environ.get("VO_MODEL", "eleven_v3")
    voice = (os.environ.get("VO_VOICE_ID") or override.get("voiceId")
             or script.get("voiceId") or DEFAULT_ELEVEN_VOICE_ID)
    settings = override.get("voice_settings") or script.get("voice_settings", DEFAULT_SETTINGS)
    response = requests.post(
        f"https://api.elevenlabs.io/v1/text-to-speech/{voice}/with-timestamps?output_format=mp3_44100_128",
        headers={"xi-api-key": key, "Content-Type": "application/json", "Accept": "application/json"},
        json={"text": spoken, "model_id": model, "voice_settings": settings},
        timeout=120,
    )
    if response.status_code >= 300:
        return f"{response.status_code}: {response.text[:160]}", None
    try:
        payload = response.json()
        audio = base64.b64decode(payload["audio_base64"])
        alignment = payload.get("alignment") or payload.get("normalized_alignment")
        if not alignment:
            return "timestamp response contained no character alignment", None
    except (KeyError, ValueError, TypeError) as exc:
        return f"invalid timestamp response: {exc}", None
    with open(out, "wb") as handle:
        handle.write(audio)
    return None, {"alignment": alignment,
                  "normalizedAlignment": payload.get("normalized_alignment")}


def narration_text(script):
    narration = script.get("narration") if isinstance(script.get("narration"), dict) else {}
    if narration.get("fromMap"):
        return "\n\n".join(
            str(entry.get("text", "") or "").strip()
            for entry in script.get("narrationMap", [])
            if isinstance(entry, dict) and str(entry.get("text", "") or "").strip()
        )
    return str(narration.get("text", "") or "").strip()


def apply_character_alignment(script, spoken, alignment):
    """Bind exact authored narrationMap thoughts to provider character timestamps."""
    entries = script.get("narrationMap")
    if not isinstance(entries, list) or not entries:
        return 0
    characters = alignment.get("characters") or []
    starts = alignment.get("character_start_times_seconds") or []
    ends = alignment.get("character_end_times_seconds") or []
    if not characters or not (len(characters) == len(starts) == len(ends)):
        raise ValueError("provider alignment arrays are empty or have different lengths")
    aligned_text = "".join(str(value) for value in characters)
    if aligned_text != spoken:
        raise ValueError("provider character alignment does not match the synthesized text")
    narration = script.get("narration") if isinstance(script.get("narration"), dict) else {}
    offset = float(narration.get("startsAtSec", 0.0) or 0.0)
    cursor = 0
    aligned = 0
    for index, entry in enumerate(entries):
        if not isinstance(entry, dict) or not str(entry.get("text", "") or "").strip():
            continue
        text = str(entry["text"]).strip()
        start_char = aligned_text.find(text, cursor)
        if start_char < 0:
            raise ValueError(f"narrationMap[{index}] text is not present in synthesized order")
        end_char = start_char + len(text)
        entry["startSec"] = round(offset + float(starts[start_char]), 6)
        entry["endSec"] = round(offset + float(ends[end_char - 1]), 6)
        entry["sourceCharStart"] = start_char
        entry["sourceCharEnd"] = end_char
        entry["timingSource"] = "elevenlabs-character-alignment"
        cursor = end_char
        aligned += 1
    return aligned


def synth_gemini(spoken, out, script):
    key = os.environ.get("GEMINI_API_KEY") or os.environ.get("GOOGLE_API_KEY")
    model = os.environ.get("GEMINI_TTS_MODEL", "gemini-2.5-flash-preview-tts")
    voice = os.environ.get("GEMINI_TTS_VOICE") or script.get("gemini_voice") or "Charon"
    direction = script.get("tts_direction", DEFAULT_DIRECTION)
    body = {
        "contents": [{"parts": [{"text": f"Say {direction}: {spoken}"}]}],
        "generationConfig": {
            "responseModalities": ["AUDIO"],
            "speechConfig": {"voiceConfig": {"prebuiltVoiceConfig": {"voiceName": voice}}},
        },
    }
    for attempt in range(3):
        r = requests.post(
            f"https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent?key={key}",
            json=body, timeout=120,
        )
        if r.status_code in (429, 500, 503) and attempt < 2:   # transient only — never retry auth errors
            time.sleep(4 * (attempt + 1)); continue
        break
    if r.status_code >= 300:
        return f"{r.status_code}: {r.text[:160]}"
    try:
        parts = r.json()["candidates"][0]["content"]["parts"]
        data = next(p["inlineData"] for p in parts if "inlineData" in p)
    except (KeyError, IndexError, StopIteration):
        return f"no audio in response: {r.text[:160]}"
    raw = base64.b64decode(data["data"])
    m = re.search(r"rate=(\d+)", data.get("mimeType", ""))
    rate = m.group(1) if m else "24000"
    with tempfile.NamedTemporaryFile(suffix=".pcm", delete=False) as tf:
        tf.write(raw); pcm = tf.name
    try:
        p = subprocess.run(["ffmpeg", "-y", "-v", "error", "-f", "s16le", "-ar", rate, "-ac", "1",
                            "-i", pcm, "-b:a", "160k", out], capture_output=True, text=True)
        if p.returncode != 0:
            return f"ffmpeg: {p.stderr[:160]}"
    finally:
        os.unlink(pcm)
    return None


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--project", required=True)
    ap.add_argument("--provider", choices=["auto", "elevenlabs", "gemini"], default="auto")
    args = ap.parse_args()

    script_path = os.path.join(args.project, "script.json")
    with open(script_path) as fh:
        script = json.load(fh)
    try:
        provider = select_provider(args.provider, script)
    except ValueError as exc:
        raise SystemExit(str(exc)) from exc
    synth = synth_elevenlabs if provider == "elevenlabs" else synth_gemini

    pron = script.get("pronounce", {})
    outdir = os.path.join(args.project, "audio")
    os.makedirs(outdir, exist_ok=True)

    narration = script.get("narration") if isinstance(script.get("narration"), dict) else {}
    master_text = narration_text(script)
    if master_text:
        if any((shot.get("vo") or shot.get("vo_tts")) for shot in script.get("shots", [])):
            raise SystemExit("narration.text is a single master performance; remove per-shot vo/vo_tts to avoid double speech")
        relative = str(narration.get("file") or "audio/master.mp3")
        out = relative if os.path.isabs(relative) else os.path.join(args.project, relative)
        os.makedirs(os.path.dirname(out), exist_ok=True)
        spoken = master_text
        for key, value in pron.items():
            spoken = re.sub(rf"\b{re.escape(key)}\b", value, spoken)
        eleven_model = narration.get("model") or os.environ.get("VO_MODEL", "eleven_v3")
        eleven_voice = (os.environ.get("VO_VOICE_ID") or narration.get("voiceId")
                         or script.get("voiceId") or DEFAULT_ELEVEN_VOICE_ID)
        gemini_model = os.environ.get("GEMINI_TTS_MODEL", "gemini-2.5-flash-preview-tts")
        gemini_voice = (os.environ.get("GEMINI_TTS_VOICE") or narration.get("voice")
                        or script.get("gemini_voice") or "Charon")
        direction = narration.get("direction") or script.get("tts_direction") or DEFAULT_DIRECTION
        signature_payload = {
            "provider": provider,
            "spoken": spoken,
            "model": eleven_model if provider == "elevenlabs" else gemini_model,
            "voice": eleven_voice if provider == "elevenlabs" else gemini_voice,
            "voice_settings": narration.get("voice_settings") or script.get("voice_settings", {}),
            "direction": direction if provider == "gemini" else "",
            "timestampedThoughts": [
                str(entry.get("text", "") or "").strip()
                for entry in script.get("narrationMap", [])
                if isinstance(entry, dict) and str(entry.get("text", "") or "").strip()
            ],
        }
        signature = hashlib.sha256(json.dumps(signature_payload, sort_keys=True).encode()).hexdigest()[:20]
        master_manifest_path = os.path.join(outdir, "master-manifest.json")
        timing_relative = str(narration.get("timingFile") or "audio/master-timing.json")
        timing_path = (timing_relative if os.path.isabs(timing_relative)
                       else os.path.join(args.project, timing_relative))
        cached = {}
        if os.path.exists(master_manifest_path):
            try:
                with open(master_manifest_path) as fh:
                    cached = json.load(fh)
            except (OSError, json.JSONDecodeError):
                cached = {}
        wants_alignment = provider == "elevenlabs" and bool(signature_payload["timestampedThoughts"])
        cache_has_alignment = (not wants_alignment
                               or (cached.get("timingFile") == timing_relative
                                   and os.path.exists(timing_path)))
        timing_payload = None
        if (cached.get("sig") == signature and os.path.exists(out)
                and cached.get("seconds", 0) > 0 and cache_has_alignment):
            dur = str(cached["seconds"])
            if wants_alignment:
                with open(timing_path) as fh:
                    timing_payload = json.load(fh)
                try:
                    apply_character_alignment(script, spoken, timing_payload["alignment"])
                except (KeyError, ValueError) as exc:
                    raise SystemExit(f"cached narration timing FAILED: {exc}") from exc
            print(f"VO ({provider} master): cached {dur}s -> {relative}")
        else:
            if wants_alignment:
                err, timing_payload = synth_elevenlabs_aligned(spoken, out, script, narration)
            else:
                err = (synth_elevenlabs(spoken, out, script, narration) if provider == "elevenlabs"
                       else synth_gemini(spoken, out, {**script, "tts_direction": direction}))
            if err:
                raise SystemExit(f"master narration FAILED: {err}")
            dur = subprocess.run(
                ["ffprobe", "-v", "error", "-show_entries", "format=duration", "-of", "csv=p=0", out],
                capture_output=True, text=True,
            ).stdout.strip()
            if not dur or float(dur) <= 0:
                raise SystemExit("master narration FAILED: empty audio")
        with open(out, "rb") as fh:
            digest = hashlib.sha256(fh.read()).hexdigest()
        timing_digest = ""
        if wants_alignment:
            if not timing_payload:
                raise SystemExit("master narration FAILED: timestamp payload is missing")
            try:
                cue_count = apply_character_alignment(script, spoken, timing_payload["alignment"])
            except (KeyError, ValueError) as exc:
                raise SystemExit(f"master narration timing FAILED: {exc}") from exc
            timing_document = {
                "schemaVersion": 1,
                "provider": "elevenlabs",
                "audioFile": relative,
                "audioSha256": digest,
                "textSha256": hashlib.sha256(spoken.encode()).hexdigest(),
                "alignment": timing_payload["alignment"],
                "normalizedAlignment": timing_payload.get("normalizedAlignment"),
                "cueCount": cue_count,
            }
            os.makedirs(os.path.dirname(timing_path), exist_ok=True)
            with open(timing_path, "w") as fh:
                json.dump(timing_document, fh, indent=2)
                fh.write("\n")
            with open(timing_path, "rb") as fh:
                timing_digest = hashlib.sha256(fh.read()).hexdigest()
        manifest = {
            "provider": provider,
            "file": relative,
            "seconds": float(dur),
            "sha256": digest,
            "voiceId": eleven_voice if provider == "elevenlabs" else gemini_voice,
            "model": eleven_model if provider == "elevenlabs" else gemini_model,
            "sig": signature,
        }
        if wants_alignment:
            manifest.update({"timingFile": timing_relative, "timingSha256": timing_digest})
        with open(master_manifest_path, "w") as fh:
            json.dump(manifest, fh, indent=2)
            fh.write("\n")

        # A master performance replaces, rather than layers over, old per-shot VO. Preserve the old
        # manifest as a recoverable timestamped file while removing it from the build's active path.
        per_shot_manifest = os.path.join(outdir, "manifest.json")
        if os.path.exists(per_shot_manifest):
            archive = os.path.join(outdir, f"manifest.per-shot-{int(time.time())}.json")
            os.replace(per_shot_manifest, archive)
            print(f"  archived stale per-shot manifest -> {os.path.basename(archive)}")

        narration["sha256"] = digest
        narration["expectedDurationSec"] = float(dur)
        narration.setdefault("durationToleranceSec", 0.05)
        if wants_alignment:
            narration["timingFile"] = timing_relative
            narration["timingSha256"] = timing_digest
            narration["timingSource"] = "elevenlabs-character-alignment"
        temp_script = script_path + ".tmp"
        with open(temp_script, "w") as fh:
            json.dump(script, fh, indent=2)
            fh.write("\n")
        os.replace(temp_script, script_path)
        print(f"VO ({provider} master): {dur}s -> {relative}")
        return

    # cache: skip lines whose text+voice settings are unchanged (reruns shouldn't re-bill)
    man_path = os.path.join(outdir, "manifest.json")
    old = {}
    if os.path.exists(man_path):
        try:
            old = {m["n"]: m for m in json.load(open(man_path))}
        except Exception:
            old = {}
    voice_sig = json.dumps([provider, os.environ.get("VO_MODEL", "eleven_v3"),
                            os.environ.get("GEMINI_TTS_MODEL", "gemini-2.5-flash-preview-tts"),
                            os.environ.get("VO_VOICE_ID", ""), os.environ.get("GEMINI_TTS_VOICE", ""),
                            script.get("voiceId", ""), script.get("gemini_voice", ""),
                            script.get("voice_settings", {}), script.get("tts_direction", "")], sort_keys=True)

    manifest, failed = [], []
    for s in script.get("shots", []):
        line = re.sub(r"^\s*\[\d+\]\s*", "", (s.get("vo") or "").strip())  # clean caption/transcript
        performance = re.sub(r"^\s*\[\d+\]\s*", "", (s.get("vo_tts") or line).strip())
        if not line:
            continue
        spoken = performance
        for k, v in pron.items():
            spoken = re.sub(rf"\b{re.escape(k)}\b", v, spoken)
        n = s["n"]
        out = os.path.join(outdir, f"s{n}.mp3")
        sig = hashlib.sha256((spoken + voice_sig).encode()).hexdigest()[:16]
        if old.get(n, {}).get("sig") == sig and os.path.exists(out) and old[n].get("seconds", 0) > 0:
            manifest.append({**old[n], "vo": line})
            print(f"  s{n}: cached {old[n]['seconds']}s  «{line[:60]}»")
            continue
        err = synth(spoken, out, script)
        if err:
            print(f"  s{n} FAILED {err}")
            failed.append(n)
            continue
        dur = subprocess.run(
            ["ffprobe", "-v", "error", "-show_entries", "format=duration", "-of", "csv=p=0", out],
            capture_output=True, text=True,
        ).stdout.strip()
        if not dur or float(dur) <= 0:
            print(f"  s{n} FAILED empty audio")
            failed.append(n)
            continue
        manifest.append({"n": n, "file": f"s{n}.mp3", "seconds": float(dur), "vo": line, "sig": sig})
        print(f"  s{n}: {dur}s  «{line[:60]}»")

    json.dump(manifest, open(man_path, "w"), indent=2)
    print(f"VO ({provider}): {len(manifest)} lines, {sum(m['seconds'] for m in manifest):.1f}s total")
    if failed:
        raise SystemExit(f"VO FAILED for shots {failed} — a silent shot must never ship")


if __name__ == "__main__":
    main()
