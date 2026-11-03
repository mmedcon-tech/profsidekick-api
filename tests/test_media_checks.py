"""T30 media checks: real Pillow/OpenCV/stdlib paths, ffmpeg path when ffmpeg is installed (Docker image)."""
import io
import math
import struct
import wave

import pytest

from app.services.care import media_checks as mc


def _png(w, h, color=(200, 200, 200)):
    from PIL import Image
    buf = io.BytesIO()
    Image.new("RGB", (w, h), color).save(buf, "PNG")
    return buf.getvalue()


def _wav(seconds, amp=0.3, noise=0.0, rate=16000, silent_gaps=True):
    import random
    rnd = random.Random(1)
    buf = io.BytesIO()
    with wave.open(buf, "wb") as w:
        w.setnchannels(1); w.setsampwidth(2); w.setframerate(rate)
        frames = bytearray()
        for i in range(int(seconds * rate)):
            on = not silent_gaps or (i // (rate // 2)) % 2 == 0   # 0.5 s "speech", 0.5 s pause
            v = (amp * math.sin(2 * math.pi * 220 * i / rate) if on else 0.0) + noise * (rnd.random() * 2 - 1)
            frames += struct.pack("<h", max(-32767, min(32767, int(v * 32767))))
        w.writeframes(bytes(frames))
    return buf.getvalue()


def test_cascade_is_bundled():
    import cv2, os
    assert os.path.exists(cv2.data.haarcascades + "haarcascade_frontalface_default.xml")


def test_blank_image_reports_no_face_and_low_resolution():
    rep = mc.check_headshot(_png(640, 480))
    assert not rep.ok and rep.faces == 0
    text = " ".join(rep.problems)
    assert "1080" in text and "16:9" in text and "No face" in text


def test_not_an_image():
    rep = mc.check_headshot(b"not an image")
    assert rep.problems == ["This file isn't a readable image. Upload a JPEG or PNG."]


def test_good_frame_passes():
    assert mc.assess_frame(1080, 1920, [(340, 660, 400, 400)]) == []


@pytest.mark.parametrize("faces,needle", [
    ([(0, 0, 50, 50), (500, 500, 50, 50)], "2 faces"),
    ([(500, 900, 60, 60)], "too small"),
    ([(0, 300, 1000, 1000)], "too close"),
    ([(0, 0, 300, 300)], "Centre"),
])
def test_frame_problems(faces, needle):
    assert any(needle in p for p in mc.assess_frame(1080, 1920, faces))


def test_wrong_aspect_ratio():
    assert any("16:9" in p for p in mc.assess_frame(1500, 1500, [(550, 550, 400, 400)]))


def test_clean_speech_like_wav_passes():
    rep = mc.check_audio(_wav(31, noise=0.001))
    assert rep.ok, rep.problems
    assert 30 < rep.duration_s < 32 and rep.snr_db > 15


def test_short_quiet_noisy_wav_fails():
    rep = mc.check_audio(_wav(5, amp=0.005, noise=0.004, silent_gaps=False))
    text = " ".join(rep.problems)
    assert "at least 30 s" in text and "quiet" in text and "background noise" in text
    assert "heuristic" in rep.speaker_consistency


def test_garbage_audio(monkeypatch):
    monkeypatch.setattr(mc, "ffmpeg_available", lambda: True)
    monkeypatch.setattr(mc, "to_wav", lambda d: (_ for _ in ()).throw(ValueError("bad")))
    assert "couldn't be read" in mc.check_audio(b"xx").problems[0]


def test_missing_ffmpeg_is_explained(monkeypatch):
    monkeypatch.setattr(mc.shutil, "which", lambda name: None)
    assert "ffmpeg is not installed" in mc.check_audio(b"not wav").problems[0]


@pytest.mark.skipif(not mc.ffmpeg_available(), reason="ffmpeg not installed (it is in the Docker image)")
def test_ffmpeg_decodes_mp3_round_trip(tmp_path):
    import subprocess
    src = tmp_path / "a.wav"; src.write_bytes(_wav(31, noise=0.001, rate=44100))
    mp3 = tmp_path / "a.mp3"
    subprocess.run(["ffmpeg", "-nostdin", "-loglevel", "error", "-i", str(src), str(mp3)], check=True)
    rep = mc.check_audio(mp3.read_bytes())
    assert rep.ok, rep.problems
    assert 30 < rep.duration_s < 32.5
