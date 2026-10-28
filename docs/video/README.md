# Intro video source

Everything in the README intro video is generated from the files in this
folder, so it can be edited and rebuilt like code.

| File | Role |
|---|---|
| `narration.json` | The script: scenes, subtitle lines, and pronunciation overrides (`say`) |
| `tts.py` | Synthesizes each line with [Kokoro-82M](https://huggingface.co/hexgrad/Kokoro-82M) (Apache-2.0, voice `af_heart`) and writes `narration.wav`, `timeline.json`, and SRT/VTT subtitles timed from the audio |
| `music.py` | Synthesizes a quiet royalty-free music bed with numpy |
| `stage.html` | The 1920×1080 animated scenes and burned-in subtitles, driven by `timeline.json` |
| `render.cjs` | Seeks the stage frame by frame with Playwright and encodes it with ffmpeg |
| `build.sh` | Runs every step, mixes voice and music, and writes the outputs to `../media/` |
| `dashboard.png` | Dashboard screenshot used in the video, taken from a mock Phase 5 run |

Outputs in [`../media/`](../media):

- `adaptive-codex-router-intro.mp4` — 1080p30, H.264/AAC, English voice-over, burned-in English subtitles, about 9 MB
- `adaptive-codex-router-intro.en.srt` / `.en.vtt` — the same subtitles as separate files

`build.sh` also writes a 1280×720 thumbnail with a play button to the build
folder, for places that need a still image.

GitHub only shows an inline player for videos uploaded through its web editor,
so the README embeds the uploaded copy
(`https://github.com/user-attachments/assets/...`) and links the MP4 in this
repository as a fallback. The MP4 is kept under GitHub's 10 MB upload limit for
free accounts. After rebuilding, drag the new MP4 into the README editor on
github.com and replace the old `user-attachments` URL.

## Rebuild

Requirements: ffmpeg, Node.js with Playwright and Chromium, and Python with
`kokoro-onnx`. The Kokoro model (`kokoro-v1.0` ONNX) and a voices `.npz` file are
not checked in.

```bash
KOKORO_MODEL=/path/to/kokoro.onnx KOKORO_VOICES=/path/to/voices.npz \
PYTHON=/path/to/venv/bin/python ./build.sh /tmp/acr-video
```

To check a layout without rendering the whole video:

```bash
node render.cjs stills /tmp/acr-video/timeline.json /tmp/acr-video/stills 12.6,62.5,94.8
```

The terminal and routing results shown in the video are real
`smart-codex --planner none --dry-run --explain` outputs. The dashboard frame
comes from a mock run and is labelled as such.
