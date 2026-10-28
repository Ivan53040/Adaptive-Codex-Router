"""Synthesize the intro narration and build exact subtitle timings.

Each cue is synthesized on its own with Kokoro-82M, so cue start/end times come
straight from the audio. Cues with two subtitle lines are split at the quietest
point near the proportional character position (usually the comma pause).

Usage:
    python tts.py --model kokoro.onnx --voices voices.npz --out build/
"""

from __future__ import annotations

import argparse
import json
import wave
from pathlib import Path

import numpy as np
from kokoro_onnx import Kokoro

HERE = Path(__file__).resolve().parent


def find_split(audio: np.ndarray, sr: int, guess: float, window: float = 0.7) -> float:
    """Return the time of the quietest 40 ms region within +/- window of guess."""
    hop = int(sr * 0.01)
    frame = int(sr * 0.04)
    lo = max(0, int((guess - window) * sr))
    hi = min(len(audio) - frame, int((guess + window) * sr))
    if hi <= lo:
        return guess
    best, best_rms = guess, float("inf")
    for start in range(lo, hi, hop):
        rms = float(np.sqrt(np.mean(audio[start : start + frame] ** 2)))
        # Prefer points close to the guess when energy is similar.
        score = rms * (1 + 0.25 * abs(start / sr - guess) / window)
        if score < best_rms:
            best, best_rms = (start + frame / 2) / sr, score
    return best


def fmt_ts(seconds: float, sep: str) -> str:
    ms = int(round(seconds * 1000))
    h, ms = divmod(ms, 3_600_000)
    m, ms = divmod(ms, 60_000)
    s, ms = divmod(ms, 1000)
    return f"{h:02d}:{m:02d}:{s:02d}{sep}{ms:03d}"


def wrap(text: str, width: int = 48) -> str:
    """Keep short lines whole; split long ones into two balanced lines."""
    if len(text) <= width:
        return text
    middle = len(text) / 2
    spaces = [i for i, ch in enumerate(text) if ch == " "]
    cut = min(spaces, key=lambda i: abs(i - middle))
    return text[:cut] + "\n" + text[cut + 1 :]


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--model", required=True)
    parser.add_argument("--voices", required=True)
    parser.add_argument("--script", default=str(HERE / "narration.json"))
    parser.add_argument("--out", required=True)
    args = parser.parse_args()

    script = json.loads(Path(args.script).read_text(encoding="utf-8"))
    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=True)

    kokoro = Kokoro(args.model, args.voices)
    voice, speed = script["voice"], script["speed"]

    sr = None
    clips: list[tuple[float, np.ndarray]] = []
    scenes, subtitles = [], []
    t = script["lead_in"]

    for scene in script["scenes"]:
        cue_rows = []
        for cue in scene["cues"]:
            text = cue.get("say") or " ".join(cue["subs"])
            audio, sr = kokoro.create(text, voice=voice, speed=speed, lang="en-us")
            audio = audio.astype(np.float32)
            dur = len(audio) / sr
            clips.append((t, audio))

            subs = cue["subs"]
            weights = np.array([len(s) for s in subs], dtype=float)
            bounds = [0.0]
            for edge in np.cumsum(weights)[:-1] / weights.sum():
                bounds.append(find_split(audio, sr, edge * dur))
            bounds.append(dur)
            for i, line in enumerate(subs):
                subtitles.append({"start": t + bounds[i], "end": t + bounds[i + 1], "text": line})

            cue_rows.append({"start": round(t, 3), "end": round(t + dur, 3), "text": " ".join(subs)})
            t += dur + script["cue_gap"]
        t += script["scene_gap"] - script["cue_gap"]
        scenes.append({"id": scene["id"], "cues": cue_rows})

    total = t - script["scene_gap"] + script["tail"]

    # Scene windows: visuals arrive slightly before the voice.
    for i, scene in enumerate(scenes):
        scene["start"] = 0.0 if i == 0 else round(scene["cues"][0]["start"] - 0.45, 3)
    for i, scene in enumerate(scenes):
        scene["end"] = scenes[i + 1]["start"] if i + 1 < len(scenes) else round(total, 3)

    # Let each subtitle linger a moment, without overlapping the next one.
    for i, sub in enumerate(subtitles):
        nxt = subtitles[i + 1]["start"] - 0.06 if i + 1 < len(subtitles) else total
        sub["end"] = min(sub["end"] + 0.3, nxt)
        sub["start"], sub["end"] = round(sub["start"], 3), round(sub["end"], 3)

    mix = np.zeros(int(total * sr) + 1, dtype=np.float32)
    for start, audio in clips:
        i = int(start * sr)
        mix[i : i + len(audio)] += audio
    peak = float(np.max(np.abs(mix))) or 1.0
    pcm = (mix / peak * 0.89 * 32767).astype(np.int16)
    with wave.open(str(out / "narration.wav"), "wb") as wav:
        wav.setnchannels(1)
        wav.setsampwidth(2)
        wav.setframerate(sr)
        wav.writeframes(pcm.tobytes())

    timeline = {"duration": round(total, 3), "scenes": scenes, "subtitles": subtitles}
    (out / "timeline.json").write_text(json.dumps(timeline, indent=2), encoding="utf-8")

    srt, vtt = [], ["WEBVTT", ""]
    for n, sub in enumerate(subtitles, 1):
        body = wrap(sub["text"])
        srt += [str(n), f"{fmt_ts(sub['start'], ',')} --> {fmt_ts(sub['end'], ',')}", body, ""]
        vtt += [f"{fmt_ts(sub['start'], '.')} --> {fmt_ts(sub['end'], '.')}", body, ""]
    (out / "subtitles.en.srt").write_text("\n".join(srt), encoding="utf-8")
    (out / "subtitles.en.vtt").write_text("\n".join(vtt), encoding="utf-8")

    print(f"narration: {total:.2f}s, {len(subtitles)} subtitles, {len(scenes)} scenes")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
