# Media checks runbook (doctor headshots and voice samples, T30)

Code: `app/services/care/media_checks.py`. Tests: `tests/test_media_checks.py`.
Nothing here calls a provider; it only decides whether a file is worth uploading.

## Dependencies
- `opencv-python-headless==4.11.0.86` (requirements.txt; pulls numpy). Headless build: no GUI libs needed.
  The face model is the bundled `haarcascade_frontalface_default.xml` (`cv2.data.haarcascades`).
- `ffmpeg` from Debian apt in the `Dockerfile`. Only used for non-WAV audio/video (mp3, m4a, mp4, mov).
  Called as an argv list (no shell), `-nostdin`, 120 s timeout, output piped to memory.

## Checks and thresholds (constants at the top of the module)
| Check | Rule |
|---|---|
| Resolution | shorter side ≥ 1080 px (LiveAvatar's documented rule) |
| Framing | 16:9 or 9:16, ±3 % |
| Faces | exactly one; width 12–70 % of the image; centre within 20 % (x) / 30 % (y) |
| Audio length | 30 s – 15 min |
| Loudness | RMS ≥ −35 dBFS |
| Noise | SNR estimate ≥ 15 dB (loud 50 ms frames vs quietest 10 %) — a heuristic |
| Speaker consistency | not checked; always labelled a heuristic, never a verification |

## Verify after a deploy
```
docker compose build -q backend && docker compose up -d --force-recreate backend
docker compose exec -T backend python -c "import cv2,shutil;print(cv2.__version__, shutil.which('ffmpeg'))"
docker compose exec -T backend sh -c 'cd /app && python -m pytest tests/test_media_checks.py -q'
```
In the image the ffmpeg round-trip test runs; on a laptop without ffmpeg it is skipped.

## Troubleshooting
- "Audio can't be checked right now: ffmpeg is not installed" → the image was built without ffmpeg; rebuild.
- "No face was found" on a good photo → usually strong backlight or a turned head; Haar is frontal-only.
- `ImportError: libGL` → the non-headless `opencv-python` got installed; uninstall it, keep headless.
- Do not loosen thresholds to make a specific doctor's file pass; ask for a better file.
