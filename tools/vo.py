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
  GEMINI_TTS_MODEL     default gemini-3.8-flash-tts
  GEMINI_TTS_VOICE     default Charon (a warm, confident narrator)

Optional per-script knobs (in script.json):
  "voiceId": "..."                         # ElevenLabs voice id
  "voice_settings": { "stability":0.32, "style":0.75, ... }   # ElevenLabs only
  "vo_tts": "[quietly] Spoken line"        # per-shot v3 performance tags; `vo` stays clean
  "narration": {"text":"[building] One continuous performance", "file":"audio/master.mp3"}
  "gemini_voice": "Charon"                  # Gemini prebuilt voice for this project
  "tts_direction": "confidently, warmly"    # spoken-style direction (Gemini only)
  "pronounce": { "ACME": "Ack-me" }         # spelling->spoken, applied to the VO audio ONLY
                                            # (on-screen captions keep the real spelling)
"""
import argparse, base64, hashlib, json, math, os, re, subprocess, tempfile, time, requests

DEFAULT_SETTINGS = {"stability": 0.32, "similarity_boost": 0.85, "style": 0.75, "use_speaker_boost": True}
DEFAULT_DIRECTION = "in a confident, warm product-video narrator voice, energetic but natural"
DEFAULT_ELEVEN_VOICE_ID = "JBFqnCBsd6RMkjVDRZzb"  # George — official premade narrative voice
ALIGNMENT_PROVIDER_ERROR = (
    "auto-paced mapped narration requires ElevenLabs character alignment. "
    "Set ELEVENLABS_API_KEY and use --provider elevenlabs (or leave --provider auto). "
    "Gemini TTS does not return the character timestamps required by pace.py; "
    "it remains available when production.autoPaceNarration is false."
)


def _write_json(path, value):
    """Publish complete metadata without leaving a truncated cache on interruption."""
    directory = os.path.dirname(os.path.abspath(path))
    os.makedirs(directory, exist_ok=True)
    fd, temporary = tempfile.mkstemp(prefix=f".{os.path.basename(path)}.", dir=directory)
    try:
        with os.fdopen(fd, "w") as handle:
            json.dump(value, handle, indent=2, allow_nan=False)
            handle.write("\n")
        os.replace(temporary, path)
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)


def _sha256(path):
    digest = hashlib.sha256()
    with open(path, "rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _audio_duration(path):
    try:
        result = subprocess.run(
            ["ffprobe", "-v", "error", "-show_entries", "format=duration", "-of", "csv=p=0", path],
            capture_output=True, text=True, timeout=30,
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        raise ValueError(f"cannot verify audio with ffprobe: {exc}") from exc
    try:
        duration = float(result.stdout.strip())
    except ValueError:
        duration = 0.0
    if result.returncode or not math.isfinite(duration) or duration <= 0:
        raise ValueError("empty or unreadable audio")
    return duration


def pronounced_text(text, pronunciations):
    """Use the same substitutions for synthesis and cue matching; keep captions authored."""
    for key, value in pronunciations.items():
        text = re.sub(rf"\b{re.escape(key)}\b", lambda _match: str(value), text)
    return text


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


def eleven_extras(script):
    """Optional ElevenLabs request fields from script.narration: a sampling seed for repeatable
    takes, an ISO 639-1 language_code, and apply_text_normalization ("auto" | "on" | "off")."""
    narration = script.get("narration") if isinstance(script.get("narration"), dict) else {}
    extras = {}
    if isinstance(narration.get("seed"), int):
        extras["seed"] = narration["seed"]
    if narration.get("language_code"):
        extras["language_code"] = str(narration["language_code"])
    if narration.get("apply_text_normalization") in ("auto", "on", "off"):
        extras["apply_text_normalization"] = narration["apply_text_normalization"]
    return extras


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
              "voice_settings": settings, **eleven_extras(script)},
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
        json={"text": spoken, "model_id": model, "voice_settings": settings,
              **eleven_extras(script)},
        timeout=120,
    )
    if response.status_code >= 300:
        return f"{response.status_code}: {response.text[:160]}", None
    try:
        payload = response.json()
        audio = base64.b64decode(payload["audio_base64"], validate=True)
        if not audio:
            return "timestamp response contained no audio", None
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
    if not isinstance(alignment, dict):
        raise ValueError("provider alignment must be an object")
    characters = alignment.get("characters") or []
    starts = alignment.get("character_start_times_seconds") or []
    ends = alignment.get("character_end_times_seconds") or []
    if (not all(isinstance(values, list) for values in (characters, starts, ends))
            or not characters or not (len(characters) == len(starts) == len(ends))):
        raise ValueError("provider alignment arrays are empty or have different lengths")
    if any(not isinstance(value, str) or len(value) != 1 for value in characters):
        raise ValueError("provider alignment must contain individual characters")
    try:
        starts = [float(value) for value in starts]
        ends = [float(value) for value in ends]
    except (ValueError, TypeError) as exc:
        raise ValueError("provider alignment timestamps must be finite numbers") from exc
    if any(not math.isfinite(start) or not math.isfinite(end) or start < 0 or end < start
           for start, end in zip(starts, ends)):
        raise ValueError("provider alignment timestamps must have finite, nonnegative ranges")
    if starts != sorted(starts) or ends != sorted(ends):
        raise ValueError("provider alignment timestamps must progress in spoken order")
    aligned_text = "".join(str(value) for value in characters)
    if aligned_text != spoken:
        raise ValueError("provider character alignment does not match the synthesized text")
    narration = script.get("narration") if isinstance(script.get("narration"), dict) else {}
    try:
        offset = float(narration.get("startsAtSec", 0.0) or 0.0)
    except (ValueError, TypeError) as exc:
        raise ValueError("narration.startsAtSec must be a finite, nonnegative number") from exc
    if not math.isfinite(offset) or offset < 0:
        raise ValueError("narration.startsAtSec must be a finite, nonnegative number")
    cursor = 0
    updates = []
    for index, entry in enumerate(entries):
        if not isinstance(entry, dict) or not str(entry.get("text", "") or "").strip():
            continue
        text = pronounced_text(str(entry["text"]).strip(), script.get("pronounce", {}))
        start_char = aligned_text.find(text, cursor)
        if start_char < 0:
            raise ValueError(f"narrationMap[{index}] text is not present in synthesized order")
        end_char = start_char + len(text)
        if ends[end_char - 1] <= starts[start_char]:
            raise ValueError(f"narrationMap[{index}] has no positive spoken duration")
        updates.append((entry, {
            "startSec": round(offset + starts[start_char], 6),
            "endSec": round(offset + ends[end_char - 1], 6),
            "sourceCharStart": start_char,
            "sourceCharEnd": end_char,
            "timingSource": "elevenlabs-character-alignment",
        }))
        cursor = end_char
    # A bad final cue must not leave the earlier cues bound to a failed performance.
    for entry, update in updates:
        entry.update(update)
    return len(updates)


def synth_gemini(spoken, out, script):
    key = os.environ.get("GEMINI_API_KEY") or os.environ.get("GOOGLE_API_KEY")
    model = os.environ.get("GEMINI_TTS_MODEL", "gemini-3.8-flash-tts")
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
        spoken = pronounced_text(master_text, pron)
        eleven_model = narration.get("model") or os.environ.get("VO_MODEL", "eleven_v3")
        eleven_voice = (os.environ.get("VO_VOICE_ID") or narration.get("voiceId")
                         or script.get("voiceId") or DEFAULT_ELEVEN_VOICE_ID)
        gemini_model = os.environ.get("GEMINI_TTS_MODEL", "gemini-3.8-flash-tts")
        gemini_voice = (os.environ.get("GEMINI_TTS_VOICE") or narration.get("voice")
                        or script.get("gemini_voice") or "Charon")
        direction = narration.get("direction") or script.get("tts_direction") or DEFAULT_DIRECTION
        signature_payload = {
            "provider": provider,
            "spoken": spoken,
            "model": eleven_model if provider == "elevenlabs" else gemini_model,
            "voice": eleven_voice if provider == "elevenlabs" else gemini_voice,
            "voice_settings": narration.get("voice_settings") or script.get("voice_settings", DEFAULT_SETTINGS),
            "direction": direction if provider == "gemini" else "",
            "timestampedThoughts": [
                str(entry.get("text", "") or "").strip()
                for entry in script.get("narrationMap", [])
                if isinstance(entry, dict) and str(entry.get("text", "") or "").strip()
            ],
        }
        extras = eleven_extras(script) if provider == "elevenlabs" else {}
        if extras:  # only new knobs change the cache key; existing masters stay valid
            signature_payload["extras"] = extras
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
                if not isinstance(cached, dict):
                    cached = {}
            except (OSError, json.JSONDecodeError):
                cached = {}
        wants_alignment = provider == "elevenlabs" and bool(signature_payload["timestampedThoughts"])
        timing_payload = None
        cache_valid = (cached.get("sig") == signature and cached.get("file") == relative
                       and os.path.isfile(out) and cached.get("sha256") == _sha256(out))
        if cache_valid:
            try:
                dur = _audio_duration(out)
            except ValueError:
                cache_valid = False
            if wants_alignment:
                try:
                    if (cached.get("timingFile") != timing_relative
                            or cached.get("timingSha256") != _sha256(timing_path)):
                        raise ValueError("timing cache changed")
                    with open(timing_path) as fh:
                        timing_payload = json.load(fh)
                    if (timing_payload.get("audioSha256") != cached["sha256"]
                            or timing_payload.get("textSha256") != hashlib.sha256(spoken.encode()).hexdigest()):
                        raise ValueError("timing cache belongs to another performance")
                    apply_character_alignment(script, spoken, timing_payload["alignment"])
                except (OSError, KeyError, TypeError, ValueError, AttributeError):
                    cache_valid = False
                    timing_payload = None
        if cache_valid:
            print(f"VO ({provider} master): cached {dur}s -> {relative}")
        else:
            fd, pending_audio = tempfile.mkstemp(prefix=".master-", suffix=os.path.splitext(out)[1],
                                                  dir=os.path.dirname(out))
            os.close(fd)
            try:
                if wants_alignment:
                    err, timing_payload = synth_elevenlabs_aligned(spoken, pending_audio, script, narration)
                else:
                    err = (synth_elevenlabs(spoken, pending_audio, script, narration) if provider == "elevenlabs"
                           else synth_gemini(spoken, pending_audio,
                                             {**script, "tts_direction": direction, "gemini_voice": gemini_voice}))
                if err:
                    raise ValueError(err)
                dur = _audio_duration(pending_audio)
                if wants_alignment:
                    if not timing_payload:
                        raise ValueError("timestamp payload is missing")
                    apply_character_alignment(script, spoken, timing_payload["alignment"])
                os.replace(pending_audio, out)
            except (ValueError, KeyError, requests.RequestException) as exc:
                raise SystemExit(f"master narration FAILED: {exc}") from exc
            finally:
                if os.path.exists(pending_audio):
                    os.unlink(pending_audio)
        digest = _sha256(out)
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
            _write_json(timing_path, timing_document)
            timing_digest = _sha256(timing_path)
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
        _write_json(master_manifest_path, manifest)

        # A master performance replaces, rather than layers over, old per-shot VO. Preserve the old
        # manifest as a recoverable timestamped file while removing it from the build's active path.
        per_shot_manifest = os.path.join(outdir, "manifest.json")
        if os.path.exists(per_shot_manifest):
            archive = os.path.join(outdir, f"manifest.per-shot-{int(time.time())}.json")
            os.replace(per_shot_manifest, archive)
            print(f"  archived stale per-shot manifest -> {os.path.basename(archive)}")

        narration["file"] = relative
        narration["sha256"] = digest
        narration["expectedDurationSec"] = float(dur)
        narration.setdefault("durationToleranceSec", 0.05)
        if wants_alignment:
            narration["timingFile"] = timing_relative
            narration["timingSha256"] = timing_digest
            narration["timingSource"] = "elevenlabs-character-alignment"
        _write_json(script_path, script)
        print(f"VO ({provider} master): {dur}s -> {relative}")
        return

    # cache: skip lines whose text+voice settings are unchanged (reruns shouldn't re-bill)
    man_path = os.path.join(outdir, "manifest.json")
    old = {}
    if os.path.exists(man_path):
        try:
            with open(man_path) as handle:
                old = {m["n"]: m for m in json.load(handle)}
        except (OSError, ValueError, TypeError, KeyError):
            old = {}
    voice_sig = json.dumps([provider, os.environ.get("VO_MODEL", "eleven_v3"),
                            os.environ.get("GEMINI_TTS_MODEL", "gemini-3.8-flash-tts"),
                            os.environ.get("VO_VOICE_ID", ""), os.environ.get("GEMINI_TTS_VOICE", ""),
                            script.get("voiceId", ""), script.get("gemini_voice", ""),
                            script.get("voice_settings", {}), script.get("tts_direction", "")], sort_keys=True)

    manifest, failed, pending = [], [], []
    for s in script.get("shots", []):
        line = re.sub(r"^\s*\[\d+\]\s*", "", (s.get("vo") or "").strip())  # clean caption/transcript
        performance = re.sub(r"^\s*\[\d+\]\s*", "", (s.get("vo_tts") or line).strip())
        if not line:
            continue
        spoken = pronounced_text(performance, pron)
        n = s["n"]
        out = os.path.join(outdir, f"s{n}.mp3")
        sig = hashlib.sha256((spoken + voice_sig).encode()).hexdigest()[:16]
        if (old.get(n, {}).get("sig") == sig and os.path.isfile(out)
                and old[n].get("sha256") == _sha256(out) and old[n].get("seconds", 0) > 0):
            manifest.append({**old[n], "vo": line})
            print(f"  s{n}: cached {old[n]['seconds']}s  «{line[:60]}»")
            continue
        fd, pending_audio = tempfile.mkstemp(prefix=f".s{n}-", suffix=".mp3", dir=outdir)
        os.close(fd)
        try:
            err = synth(spoken, pending_audio, script)
            if err:
                raise ValueError(err)
            dur = _audio_duration(pending_audio)
        except (ValueError, requests.RequestException) as exc:
            print(f"  s{n} FAILED {exc}")
            failed.append(n)
            os.unlink(pending_audio)
            continue
        manifest.append({"n": n, "file": f"s{n}.mp3", "seconds": float(dur), "vo": line,
                         "sig": sig, "sha256": _sha256(pending_audio)})
        pending.append((pending_audio, out))
        print(f"  s{n}: {dur}s  «{line[:60]}»")

    if failed:
        for temporary, _out in pending:
            os.unlink(temporary)
        raise SystemExit(f"VO FAILED for shots {failed} — a silent shot must never ship")
    for temporary, out in pending:
        os.replace(temporary, out)
    _write_json(man_path, manifest)
    print(f"VO ({provider}): {len(manifest)} lines, {sum(m['seconds'] for m in manifest):.1f}s total")


if __name__ == "__main__":
    main()
