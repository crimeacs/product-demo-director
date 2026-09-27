"""Small deterministic editorial accents. No service, sample library, or paid API required."""
from array import array
import math
from pathlib import Path
import random
import sys
import tempfile
import wave
import os

BUILTIN_SOUNDS = {"studio_air", "studio_tick", "studio_resolve"}
SAMPLE_RATE = 48000


def synthesize(name: str) -> bytes:
    if name not in BUILTIN_SOUNDS:
        raise ValueError(f"Unknown built-in sound: {name}")
    duration = {"studio_air": 0.62, "studio_tick": 0.16, "studio_resolve": 1.35}[name]
    rng = random.Random(6143)
    samples = array("h")
    low, high = 0.0, 0.0
    count = round(duration * SAMPLE_RATE)
    for i in range(count):
        t, p = i / SAMPLE_RATE, i / max(1, count - 1)
        noise = rng.uniform(-1, 1)
        low += 0.022 * (noise - low)
        high += 0.21 * (noise - high)
        if name == "studio_air":
            # A soft band of air travels toward the reveal, with no sharp synthetic whistle.
            envelope = math.sin(math.pi * p) ** 2.5
            value = (high - low) * envelope * 0.7
            pan = 0.18 * (2 * p - 1)
        elif name == "studio_tick":
            envelope = (1 - math.exp(-t * 1400)) * math.exp(-t * 65) * (1 - p) ** 2
            value = (math.sin(2 * math.pi * 640 * t) * 0.15 + (high - low) * 0.25) * envelope
            pan = 0
        else:
            # Warm, restrained harmonic punctuation; it is an editorial cue, not product audio.
            attack = min(1.0, t / 0.025)
            envelope = attack * math.exp(-t * 4.5) * math.sin(math.pi * min(1, (1 - p) * 2) / 2) ** 2
            value = sum(math.sin(2 * math.pi * hz * t) * gain
                        for hz, gain in ((196, 0.20), (293.6648, 0.10), (392, 0.07))) * envelope
            pan = 0
        for gain in (math.sqrt((1 - pan) / 2), math.sqrt((1 + pan) / 2)):
            samples.append(round(max(-1, min(1, value * gain)) * 32767))
    if sys.byteorder != "little":
        samples.byteswap()
    return samples.tobytes()


def ensure_sound(name: str, directory: str | Path) -> str:
    """Publish deterministic WAV bytes atomically, replacing stale/corrupt generated cues."""
    directory = Path(directory)
    directory.mkdir(parents=True, exist_ok=True)
    path = directory / f"{name}.wav"
    payload = synthesize(name)
    fd, temp = tempfile.mkstemp(dir=directory, suffix=".wav")
    os.close(fd)
    try:
        with wave.open(temp, "wb") as output:
            output.setnchannels(2)
            output.setsampwidth(2)
            output.setframerate(SAMPLE_RATE)
            output.writeframes(payload)
        if path.exists() and path.read_bytes() == Path(temp).read_bytes():
            return str(path)
        os.replace(temp, path)
    finally:
        Path(temp).unlink(missing_ok=True)
    return str(path)
