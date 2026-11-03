"""Pre-upload checks for doctor headshots and voice samples (plan T30).

Headshots: Pillow decode, then OpenCV's bundled Haar cascade. One face, roughly centred, a
reasonable size, 16:9 or 9:16 framing and a short side of at least 1080 px (LiveAvatar's
documented rule). Audio: anything that is not plain PCM WAV goes through ffmpeg to mono 16 kHz
WAV, then stdlib ``wave`` gives duration, RMS and a rough SNR estimate. Every result is a list of
plain-language problems; an empty list means the file passed. Nothing here calls a provider.
"""
from __future__ import annotations

import io
import math
import shutil
import subprocess
import tempfile
import wave
from dataclasses import dataclass, field
from typing import List, Optional, Sequence, Tuple

MIN_SHORT_SIDE = 1080
ASPECTS = (16 / 9, 9 / 16)
ASPECT_TOLERANCE = 0.03
MIN_FACE_FRACTION = 0.12   # face width / image width
MAX_FACE_FRACTION = 0.70
MAX_CENTRE_OFFSET = 0.20   # face centre distance from image centre, as a fraction of each side
MIN_AUDIO_S = 30.0
MAX_AUDIO_S = 15 * 60.0
MIN_RMS_DBFS = -35.0
MIN_SNR_DB = 15.0
FFMPEG_TIMEOUT_S = 120


@dataclass
class ImageReport:
    width: int = 0
    height: int = 0
    faces: int = 0
    problems: List[str] = field(default_factory=list)

    @property
    def ok(self) -> bool:
        return not self.problems


@dataclass
class AudioReport:
    duration_s: float = 0.0
    rms_dbfs: Optional[float] = None
    snr_db: Optional[float] = None
    problems: List[str] = field(default_factory=list)
    speaker_consistency: str = "not checked (heuristic only, never a verification)"

    @property
    def ok(self) -> bool:
        return not self.problems


def detect_faces(gray) -> Sequence[Tuple[int, int, int, int]]:
    import cv2

    cascade = cv2.CascadeClassifier(cv2.data.haarcascades + "haarcascade_frontalface_default.xml")
    min_side = max(40, int(min(gray.shape[:2]) * 0.08))
    return list(cascade.detectMultiScale(gray, scaleFactor=1.1, minNeighbors=6, minSize=(min_side, min_side)))


def assess_frame(width: int, height: int, faces: Sequence[Tuple[int, int, int, int]]) -> List[str]:
    problems: List[str] = []
    if min(width, height) < MIN_SHORT_SIDE:
        problems.append(f"The image is {width}×{height}; the shorter side needs at least {MIN_SHORT_SIDE} px.")
    ratio = width / height if height else 0
    if not any(abs(ratio - a) / a <= ASPECT_TOLERANCE for a in ASPECTS):
        problems.append("Crop the photo to 16:9 (landscape) or 9:16 (portrait).")
    if len(faces) == 0:
        problems.append("No face was found. Use a clear, front-facing photo with good light.")
        return problems
    if len(faces) > 1:
        problems.append(f"{len(faces)} faces were found. The photo must show only the doctor.")
        return problems
    x, y, w, h = faces[0]
    frac = w / width
    if frac < MIN_FACE_FRACTION:
        problems.append("The face is too small. Move closer or crop tighter around head and shoulders.")
    elif frac > MAX_FACE_FRACTION:
        problems.append("The face is too close. Leave some space around head and shoulders.")
    cx, cy = (x + w / 2) / width, (y + h / 2) / height
    if abs(cx - 0.5) > MAX_CENTRE_OFFSET or abs(cy - 0.5) > MAX_CENTRE_OFFSET + 0.1:
        problems.append("Centre the face in the frame.")
    return problems


def check_headshot(data: bytes) -> ImageReport:
    from PIL import Image, ImageOps, UnidentifiedImageError
    import numpy as np

    try:
        img = ImageOps.exif_transpose(Image.open(io.BytesIO(data)))
        img.load()
    except (UnidentifiedImageError, OSError):
        return ImageReport(problems=["This file isn't a readable image. Upload a JPEG or PNG."])
    gray = np.asarray(img.convert("L"))
    faces = detect_faces(gray)
    w, h = img.size
    return ImageReport(width=w, height=h, faces=len(faces), problems=assess_frame(w, h, faces))


def ffmpeg_available() -> bool:
    return shutil.which("ffmpeg") is not None


def to_wav(data: bytes) -> bytes:
    """Any audio or video container → mono 16 kHz 16-bit WAV via ffmpeg (stdin → stdout, no shell)."""
    if not ffmpeg_available():
        raise RuntimeError("ffmpeg is not installed on this server")
    with tempfile.NamedTemporaryFile(suffix=".bin") as src:
        src.write(data)
        src.flush()
        out = subprocess.run(["ffmpeg", "-nostdin", "-hide_banner", "-loglevel", "error", "-i", src.name,
                              "-vn", "-ac", "1", "-ar", "16000", "-sample_fmt", "s16", "-f", "wav", "pipe:1"],
                             capture_output=True, timeout=FFMPEG_TIMEOUT_S, check=False)
    if out.returncode != 0 or not out.stdout:
        raise ValueError("ffmpeg could not decode this file")
    return out.stdout


def _samples(wav_bytes: bytes):
    import numpy as np

    with wave.open(io.BytesIO(wav_bytes)) as w:
        if w.getsampwidth() != 2:
            raise ValueError("expected 16-bit PCM")
        rate, ch = w.getframerate(), w.getnchannels()
        x = np.frombuffer(w.readframes(w.getnframes()), dtype="<i2").astype("float64") / 32768.0
    if ch > 1:
        x = x.reshape(-1, ch).mean(axis=1)
    return x, rate


def _db(v: float) -> float:
    return 20 * math.log10(max(v, 1e-9))


def assess_samples(x, rate: int) -> AudioReport:
    import numpy as np

    rep = AudioReport(duration_s=round(len(x) / rate, 2) if rate else 0.0)
    if rep.duration_s < MIN_AUDIO_S:
        rep.problems.append(f"The recording is {rep.duration_s:.0f} s; at least {MIN_AUDIO_S:.0f} s of speech is needed.")
    if rep.duration_s > MAX_AUDIO_S:
        rep.problems.append(f"The recording is longer than {MAX_AUDIO_S / 60:.0f} minutes. Upload a shorter sample.")
    if len(x) == 0:
        rep.problems.append("The recording is empty.")
        return rep
    rep.rms_dbfs = round(_db(float(np.sqrt(np.mean(x ** 2)))), 1)
    if rep.rms_dbfs < MIN_RMS_DBFS:
        rep.problems.append("The recording is very quiet. Record closer to the microphone.")
    # SNR estimate: loud 50 ms frames (speech) vs the quietest 10 % (room noise). A heuristic, not a measurement.
    n = max(1, int(rate * 0.05))
    frames = x[: len(x) // n * n].reshape(-1, n) if len(x) >= n else x.reshape(1, -1)
    e = np.sort(np.sqrt(np.mean(frames ** 2, axis=1)))
    noise = float(np.mean(e[: max(1, len(e) // 10)]))
    speech = float(np.mean(e[-max(1, len(e) // 2):]))
    rep.snr_db = round(_db(speech) - _db(noise), 1)
    if rep.snr_db < MIN_SNR_DB:
        rep.problems.append("There is a lot of background noise. Record in a quiet room.")
    return rep


def check_audio(data: bytes) -> AudioReport:
    try:
        try:
            x, rate = _samples(data)
        except (wave.Error, EOFError, ValueError):
            x, rate = _samples(to_wav(data))
    except RuntimeError as exc:
        return AudioReport(problems=[f"Audio can't be checked right now: {exc}."])
    except (ValueError, wave.Error, EOFError, subprocess.TimeoutExpired):
        return AudioReport(problems=["This file couldn't be read as audio. Upload WAV, MP3, M4A, MP4 or MOV."])
    return assess_samples(x, rate)
