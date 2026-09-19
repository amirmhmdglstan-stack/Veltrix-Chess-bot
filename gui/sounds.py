"""
sounds.py - small original board sounds, synthesized in code (PART 10).

No audio files, no downloads, no third-party material: every sound is a
PCM snippet generated here (short percussive sine-knocks with an
exponential envelope; the chimes are two-note motifs). Playback:

* Windows - winsound (stdlib), WAV bytes from memory
* Linux   - aplay / paplay / ffplay if one happens to be installed
* macOS   - afplay

If no player is available the module silently no-ops: the app never
breaks over sound, and everything remains usable with sound off.
"""
from __future__ import annotations

import array
import io
import math
import shutil
import struct
import subprocess
import sys
import tempfile
import threading
import wave

_SR = 22050


def _env(n, decay=60.0):
    return [math.exp(-decay * i / n) for i in range(n)]


def _tone(freq, ms, decay=60.0, harmonics=(1.0, 0.35, 0.12), gain=0.85):
    n = int(_SR * ms / 1000)
    e = _env(n, decay)
    out = array.array("h")
    for i in range(n):
        t = i / _SR
        v = sum(h * math.sin(2 * math.pi * freq * k * t)
                for k, h in enumerate(harmonics, 1))
        out.append(int(gain * e[i] * v / sum(harmonics) * 32767))
    return out


def _with_space(buf, ms_silence=0):
    if ms_silence:
        buf.extend(array.array("h", b"\x00" * 2 * int(_SR * ms_silence / 1000)))
    return buf


def _pcm_to_wav_bytes(pcm: array.array) -> bytes:
    mem = io.BytesIO()
    with wave.open(mem, "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(_SR)
        w.writeframes(pcm.tobytes())
    return mem.getvalue()


def _knock(freq=620, ms=55, decay=80, gain=0.8):
    """Wooden 'tok' - a heavily damped mid-frequency tone."""
    return _tone(freq, ms, decay=decay, gain=gain,
                 harmonics=(1.0, 0.28, 0.06))


def _build_all():
    """One-shot synth. All events absolutely tiny (<80ms each)."""
    k_low, k_high = 500, 780
    s = {}
    s["move"] = _knock(k_low, 40, 90)
    s["undo"] = _knock(k_low, 30, 120, 0.5)
    s["capture"] = _with_space(_knock(k_low + 190, 35, 70), 10) + _knock(k_low - 120, 50, 90)
    s["castle"] = _with_space(_knock(k_low, 35, 90), 40) + _knock(k_low, 35, 90)
    s["promote"] = _with_space(_knock(k_high, 40, 70), 15) + _knock(int(k_high * 1.5), 60, 60)
    s["check"] = _knock(980, 70, 55, 0.72)
    s["start"] = _with_space(_knock(660, 50, 60, 0.6), 60) + _knock(880, 70, 50, 0.6)
    s["end"] = _with_space(_knock(880, 60, 60, 0.6), 70) + _knock(660, 90, 55, 0.6)
    s["illegal"] = _tone(160, 90, 25, harmonics=(1.0, 0.5), gain=0.5)
    return {k: _pcm_to_wav_bytes(v) for k, v in s.items()}


SOUND_NAMES = ("move", "capture", "check", "castle", "promote",
               "start", "end", "illegal", "undo")


class SoundBoard:
    """Threaded one-shot playback honoring cfg (on/off + volume)."""

    def __init__(self, cfg):
        self.cfg = cfg
        self._sounds = None
        self._lock = threading.Lock()
        self._player = self._detect_player()

    # ------------------------------------------------------------- plumbing
    def _detect_player(self):
        if sys.platform.startswith("win"):
            return "winsound"
        for tool in ("aplay", "paplay", "ffplay", "afplay"):
            if shutil.which(tool):
                return tool
        return None

    @property
    def available(self) -> bool:
        return self._player is not None

    def _synth(self):
        with self._lock:
            if self._sounds is None:
                self._sounds = _build_all()
            return self._sounds

    def _with_volume(self, wav: bytes, volume: int) -> bytes:
        if volume >= 99:
            return wav
        pcm = array.array("h")
        with wave.open(io.BytesIO(wav), "rb") as r:
            pcm.frombytes(r.readframes(r.getnframes()))
        g = max(0.0, min(1.0, volume / 100.0))
        pcm = array.array("h", (int(s * g) for s in pcm))
        return _pcm_to_wav_bytes(pcm)

    # ------------------------------------------------------------- playback
    def play(self, name: str):
        if not getattr(self.cfg, "sound_on", False) or not self.available:
            return False
        if sys.platform.startswith("win"):
            def _w():
                import winsound
                wav = self._with_volume(self._synth()[name],
                                        self.cfg.sound_volume)
                try:
                    winsound.PlaySound(wav, winsound.SND_MEMORY
                                       | winsound.SND_ASYNC)
                except RuntimeError:
                    pass
            threading.Thread(target=_w, daemon=True).start()
            return True

        tool = self._player

        def _x():
            wav = self._with_volume(self._synth()[name], self.cfg.sound_volume)
            try:
                if tool == "afplay" or tool == "ffplay":
                    f = tempfile.NamedTemporaryFile("wb", suffix=".wav",
                                                    delete=False)
                    f.write(wav)
                    f.close()
                    cmd = ([tool, f.name] if tool == "afplay" else
                           [tool, "-nodisp", "-autoexit", "-loglevel", "quiet",
                            f.name])
                    subprocess.Popen(cmd, stdout=subprocess.DEVNULL,
                                     stderr=subprocess.DEVNULL)
                else:
                    p = subprocess.Popen([tool, "-q"], stdin=subprocess.PIPE,
                                         stdout=subprocess.DEVNULL,
                                         stderr=subprocess.DEVNULL)
                    p.communicate(wav, timeout=4)
            except (OSError, subprocess.SubprocessError):
                pass

        threading.Thread(target=_x, daemon=True).start()
        return True
