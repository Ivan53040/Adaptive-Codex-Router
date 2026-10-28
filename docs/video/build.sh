#!/usr/bin/env bash
# Rebuild the README intro video from source.
#
#   KOKORO_MODEL=/path/kokoro.onnx KOKORO_VOICES=/path/voices.npz \
#   PYTHON=/path/to/venv/bin/python ./build.sh [build-dir]
#
# Needs ffmpeg, Node.js with Playwright + Chromium, and a Python environment
# with kokoro-onnx installed. Outputs land in ../media/.
set -euo pipefail

HERE="$(cd "$(dirname "$0")" && pwd)"
BUILD="${1:-$HERE/build}"
MEDIA="$HERE/../media"
PY="${PYTHON:-python3}"
NAME="adaptive-codex-router-intro"
mkdir -p "$BUILD" "$MEDIA"

echo "1/5 narration + subtitles"
"$PY" "$HERE/tts.py" --model "$KOKORO_MODEL" --voices "$KOKORO_VOICES" --out "$BUILD"

echo "2/5 music bed"
"$PY" "$HERE/music.py" --timeline "$BUILD/timeline.json" --out "$BUILD/music.wav"

echo "3/5 frames"
node "$HERE/render.cjs" video "$BUILD/timeline.json" "$BUILD/video_silent.mp4" --fps 30 --workers "${WORKERS:-4}"

echo "4/5 mix (music ducks under the voice, then two-pass loudness normalization to -16 LUFS)"
ffmpeg -hide_banner -loglevel error -y -i "$BUILD/narration.wav" -i "$BUILD/music.wav" -filter_complex \
  "[0:a]aresample=48000,pan=stereo|c0=c0|c1=c0,asplit=2[vo][key];\
   [1:a]aresample=48000,volume=0.1[bed];\
   [bed][key]sidechaincompress=threshold=0.02:ratio=4:attack=20:release=500[duck];\
   [vo][duck]amix=inputs=2:normalize=0[a]" -map "[a]" -c:a pcm_s16le "$BUILD/mix.wav"
STATS=$(ffmpeg -hide_banner -i "$BUILD/mix.wav" -af loudnorm=I=-16:TP=-1.5:LRA=11:print_format=json -f null - 2>&1 | sed -n '/^{/,/^}/p')
get() { echo "$STATS" | sed -n "s/.*\"$1\" : \"\([^\"]*\)\".*/\1/p"; }
ffmpeg -hide_banner -loglevel error -y -i "$BUILD/mix.wav" -af \
  "loudnorm=I=-16:TP=-1.5:LRA=11:measured_I=$(get input_i):measured_TP=$(get input_tp):measured_LRA=$(get input_lra):measured_thresh=$(get input_thresh):offset=$(get target_offset):linear=true,aresample=48000" \
  -c:a pcm_s16le "$BUILD/mix_norm.wav"

echo "5/5 compress, mux + thumbnail (two-pass 440 kbps keeps the file under GitHub's 10 MB video upload limit)"
X264=(-c:v libx264 -preset slow -tune animation -b:v 440k -passlogfile "$BUILD/x264" -pix_fmt yuv420p -an)
ffmpeg -hide_banner -loglevel error -y -i "$BUILD/video_silent.mp4" "${X264[@]}" -pass 1 -f null /dev/null
ffmpeg -hide_banner -loglevel error -y -i "$BUILD/video_silent.mp4" "${X264[@]}" -pass 2 "$BUILD/video_small.mp4"
ffmpeg -hide_banner -loglevel error -y -i "$BUILD/video_small.mp4" -i "$BUILD/mix_norm.wav" \
  -map 0:v -map 1:a -c:v copy -c:a aac -b:a 96k -shortest -movflags +faststart \
  -metadata title="Adaptive Codex Router — introduction" -metadata:s:a:0 language=eng \
  "$MEDIA/$NAME.mp4"
cp "$BUILD/subtitles.en.srt" "$MEDIA/$NAME.en.srt"
cp "$BUILD/subtitles.en.vtt" "$MEDIA/$NAME.en.vtt"
DUR=$("$PY" -c "import json,sys;d=json.load(open(sys.argv[1]))['duration'];print(f'{int(d//60)}:{int(d%60):02d}')" "$BUILD/timeline.json")
node "$HERE/render.cjs" poster "$BUILD/timeline.json" "$BUILD/poster.png" "${POSTER_TIME:-22.9}" "$DUR · English voice-over + subtitles"
ffmpeg -hide_banner -loglevel error -y -i "$BUILD/poster.png" -vf scale=1280:720:flags=lanczos "$BUILD/$NAME-poster.png"
echo "done: $MEDIA/$NAME.mp4"
