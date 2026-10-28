"""Generate a quiet ambient music bed for the intro video (numpy only).

A soft pad and bass hold a four-chord loop; a gentle pluck arpeggio joins when
the title appears. Everything is synthesized, so the track is royalty-free.

Usage:
    python music.py --timeline build/timeline.json --out build/music.wav
"""

from __future__ import annotations

import argparse
import json
import wave
from pathlib import Path

import numpy as np

SR = 44100
BPM = 84
BEAT = 60 / BPM
CHORD_BEATS = 8

# Cmaj9, Am9, Fmaj9, G6/9 as MIDI note numbers (pad voicing, bass root).
CHORDS = [
    ([60, 64, 67, 71, 74], 36),
    ([57, 60, 64, 67, 71], 33),
    ([53, 57, 60, 64, 67], 29),
    ([55, 59, 62, 64, 69], 31),
]
ARPEGGIO = [0, 2, 4, 3, 1, 3, 4, 2]


def hz(midi: float) -> float:
    return 440.0 * 2 ** ((midi - 69) / 12)


def pad_voice(freq: float, n: int, rng: np.random.Generator) -> np.ndarray:
    t = np.arange(n) / SR
    out = np.zeros(n)
    for cents, amp in ((-4, 0.5), (0, 1.0), (4, 0.5)):
        f = freq * 2 ** (cents / 1200)
        phase = rng.uniform(0, 2 * np.pi)
        out += amp * (np.sin(2 * np.pi * f * t + phase) + 0.12 * np.sin(4 * np.pi * f * t + phase))
    # Slow tremolo keeps the pad alive without drawing attention.
    out *= 1 + 0.08 * np.sin(2 * np.pi * 0.17 * t + rng.uniform(0, 6))
    return out


def pluck(freq: float, length: float) -> np.ndarray:
    n = int(length * SR)
    t = np.arange(n) / SR
    env = np.exp(-t * 5.5) * np.minimum(1, t / 0.004)
    tone = np.sin(2 * np.pi * freq * t) + 0.3 * np.sin(4 * np.pi * freq * t) * np.exp(-t * 9)
    return tone * env


def reverb(signal: np.ndarray, seconds: float = 2.6, seed: int = 7) -> np.ndarray:
    rng = np.random.default_rng(seed)
    n = int(seconds * SR)
    ir = rng.standard_normal(n) * np.exp(-np.arange(n) / SR * 6.9 / seconds)
    ir[: int(0.012 * SR)] = 0
    size = 1 << int(np.ceil(np.log2(len(signal) + n)))
    wet = np.fft.irfft(np.fft.rfft(signal, size) * np.fft.rfft(ir, size), size)[: len(signal)]
    return wet / (np.max(np.abs(wet)) or 1.0)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--timeline", required=True)
    parser.add_argument("--out", required=True)
    args = parser.parse_args()

    timeline = json.loads(Path(args.timeline).read_text(encoding="utf-8"))
    duration = timeline["duration"]
    arp_start = next(s["start"] for s in timeline["scenes"] if s["id"] == "intro")

    n = int(duration * SR)
    rng = np.random.default_rng(42)
    pad = np.zeros((2, n))
    bass = np.zeros(n)
    arp = np.zeros((2, n))

    chord_len = CHORD_BEATS * BEAT
    fade = 1.4
    k = 0
    start = 0.0
    while start < duration:
        notes, root = CHORDS[k % len(CHORDS)]
        a = int(max(0, start - fade / 2) * SR)
        b = min(n, int((start + chord_len + fade / 2) * SR))
        seg = b - a
        if seg <= 0:
            break
        tt = np.arange(seg) / SR
        span = seg / SR
        env = np.clip(np.minimum(tt / fade, (span - tt) / fade), 0, 1)
        env = 0.5 - 0.5 * np.cos(np.pi * env)  # equal-ish power crossfade
        for i, note in enumerate(notes):
            v = pad_voice(hz(note), seg, rng) * env
            pan = 0.3 + 0.4 * (i / (len(notes) - 1))
            pad[0, a:b] += v * (1 - pan)
            pad[1, a:b] += v * pan
        bt = np.arange(seg) / SR
        bass[a:b] += np.sin(2 * np.pi * hz(root) * bt) * env

        for step in range(CHORD_BEATS * 2):
            at = start + step * BEAT / 2
            if at < arp_start or at > duration - 2.5:
                continue
            note = notes[ARPEGGIO[step % len(ARPEGGIO)]] + 12
            p = pluck(hz(note), 1.6) * (0.75 if step % 2 else 1.0)
            i0 = int(at * SR)
            i1 = min(n, i0 + len(p))
            pan = 0.35 if step % 4 < 2 else 0.65
            arp[0, i0:i1] += p[: i1 - i0] * (1 - pan)
            arp[1, i0:i1] += p[: i1 - i0] * pan
        start += chord_len
        k += 1

    dry = 0.55 * pad / np.max(np.abs(pad)) + 0.35 * arp / (np.max(np.abs(arp)) or 1.0)
    wet = np.stack([reverb(dry[0], seed=7), reverb(dry[1], seed=11)])
    mix = 0.62 * dry + 0.38 * wet
    mix += 0.22 * bass / np.max(np.abs(bass))

    t = np.arange(n) / SR
    master = np.minimum(1, t / 2.0) * np.clip((duration - t) / 3.5, 0, 1)
    mix *= master
    mix /= np.max(np.abs(mix))
    pcm = (mix.T * 0.8 * 32767).astype(np.int16)
    with wave.open(args.out, "wb") as w:
        w.setnchannels(2)
        w.setsampwidth(2)
        w.setframerate(SR)
        w.writeframes(pcm.tobytes())
    print(f"music: {duration:.2f}s -> {args.out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
