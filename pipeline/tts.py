"""Text-to-speech with word timings.

Engine "edge"    : Microsoft neural voices via the edge-tts package (free, needs internet,
                   gives exact word boundaries).
Engine "offline" : Piper voice run locally with sherpa-onnx (no internet needed after the
                   first ~70 MB model download from GitHub; word timings are estimated).
Engine "auto"    : edge, and if anything fails, offline — so a daily run never dies on TTS.

Every scene is synthesised separately so each scene's exact duration is known.
"""
from __future__ import annotations

import asyncio
import time
import re
import shutil
import subprocess
import tarfile
import urllib.request
import wave
from dataclasses import dataclass, field
from pathlib import Path

import numpy as np

from .config import CACHE_DIR, Config

SAMPLE_RATE = 48000
PIPER_RELEASE = "https://github.com/k2-fsa/sherpa-onnx/releases/download/tts-models/{model}.tar.bz2"


@dataclass
class Word:
    text: str
    start: float
    end: float


@dataclass
class SceneAudio:
    wav: Path
    duration: float
    words: list[Word] = field(default_factory=list)


# ----------------------------------------------------------------------------- helpers
def _ffmpeg_to_wav(src: Path, dst: Path) -> None:
    subprocess.run(
        ["ffmpeg", "-y", "-loglevel", "error", "-i", str(src), "-ac", "1", "-ar", str(SAMPLE_RATE),
         "-c:a", "pcm_s16le", str(dst)],
        check=True,
    )


def read_wav(path: Path) -> tuple[np.ndarray, int]:
    with wave.open(str(path), "rb") as w:
        rate = w.getframerate()
        n = w.getnframes()
        data = np.frombuffer(w.readframes(n), dtype=np.int16)
        if w.getnchannels() > 1:
            data = data.reshape(-1, w.getnchannels()).mean(axis=1).astype(np.int16)
    return data, rate


def write_wav(path: Path, samples: np.ndarray, rate: int = SAMPLE_RATE) -> None:
    with wave.open(str(path), "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(rate)
        w.writeframes(samples.astype(np.int16).tobytes())


def _voiced_span(samples: np.ndarray, rate: int, threshold: float = 0.02) -> tuple[float, float]:
    """Seconds where the audio actually starts and stops (ignores lead-in/trailing silence)."""
    if len(samples) == 0:
        return 0.0, 0.0
    x = np.abs(samples.astype(np.float32)) / 32768.0
    win = max(1, rate // 100)  # 10 ms windows
    env = x[: len(x) // win * win].reshape(-1, win).max(axis=1)
    idx = np.where(env > threshold)[0]
    if len(idx) == 0:
        return 0.0, len(samples) / rate
    return idx[0] * win / rate, min(len(samples) / rate, (idx[-1] + 1) * win / rate)


def estimate_words(text: str, start: float, end: float) -> list[Word]:
    """Spread the words of `text` between start and end, weighted by length and punctuation."""
    tokens = text.split()
    if not tokens:
        return []
    weights = []
    for t in tokens:
        w = len(re.sub(r"[^A-Za-z0-9']", "", t)) + 1.2
        if t[-1] in ".!?":
            w += 2.5
        elif t[-1] in ",;:":
            w += 1.2
        weights.append(w)
    total = sum(weights)
    words, cur = [], start
    for t, w in zip(tokens, weights):
        dur = (end - start) * w / total
        words.append(Word(t, cur, cur + dur))
        cur += dur
    return words


def _finalize(wav: Path, samples: np.ndarray, sr: int, words: list[Word],
              lead: float = 0.10, tail: float = 0.18) -> SceneAudio:
    """Trim long silences at both ends (keeping a natural lead-in/out) and shift word times."""
    v0, v1 = _voiced_span(samples, sr)
    a = max(0, int((v0 - lead) * sr))
    b = min(len(samples), int((v1 + tail) * sr))
    if b <= a:
        a, b = 0, len(samples)
    trimmed = samples[a:b]
    write_wav(wav, trimmed, sr)
    shift = a / sr
    duration = len(trimmed) / sr
    shifted = [Word(w.text, max(0.0, w.start - shift), min(duration, max(0.0, w.end - shift))) for w in words]
    return SceneAudio(wav, duration, shifted)


def _clean_text(text: str) -> str:
    text = text.strip().replace("—", ", ").replace("–", "-").replace("…", "...")
    if text and text[-1] not in ".!?":
        text += "."
    return text


# ----------------------------------------------------------------------------- edge-tts
async def _edge_one(text: str, voice: str, rate: str, mp3: Path) -> list[Word]:
    import edge_tts  # imported lazily so the offline engine works without it

    communicate = edge_tts.Communicate(text, voice, rate=rate)
    words: list[Word] = []
    with open(mp3, "wb") as f:
        async for chunk in communicate.stream():
            if chunk["type"] == "audio":
                f.write(chunk["data"])
            elif chunk["type"] == "WordBoundary":
                s = chunk["offset"] / 1e7
                words.append(Word(chunk["text"], s, s + chunk["duration"] / 1e7))
    return words


def _synth_edge(texts: list[str], cfg: Config, workdir: Path, voice: str | None) -> list[SceneAudio]:
    voice = voice or cfg.get("voice.edge_voice", "en-US-AndrewNeural")
    rate = str(cfg.get("voice.edge_rate", "+10%"))
    out: list[SceneAudio] = []
    for i, text in enumerate(texts):
        mp3 = workdir / f"scene{i:02d}.mp3"
        wav = workdir / f"scene{i:02d}.wav"
        # Microsoft's service fails now and then for a few seconds; retry before giving up on the scene.
        for attempt in range(3):
            try:
                boundaries = asyncio.run(_edge_one(text, voice, rate, mp3))
                if mp3.stat().st_size >= 1000:
                    break
                err = RuntimeError("edge-tts returned no audio")
            except Exception as e:  # noqa: BLE001
                err = e
            if attempt < 2:
                print(f"[tts] edge-tts scene {i} attempt {attempt + 1} failed ({type(err).__name__}: {err}); retrying")
                time.sleep(4 * (attempt + 1))
        else:
            raise err
        _ffmpeg_to_wav(mp3, wav)
        samples, sr = read_wav(wav)
        # Re-attach punctuation from the original text so captions show it.
        tokens = text.split()
        if boundaries and len(boundaries) == len(tokens):
            words = [Word(tok, b.start, b.end) for tok, b in zip(tokens, boundaries)]
        elif boundaries:
            _, v1 = _voiced_span(samples, sr)
            words = estimate_words(text, boundaries[0].start, max(boundaries[-1].end, v1))
        else:
            v0, v1 = _voiced_span(samples, sr)
            words = estimate_words(text, v0, v1)
        out.append(_finalize(wav, samples, sr, words))
    return out


# ----------------------------------------------------------------------------- offline (piper via sherpa-onnx)
def ensure_offline_model(model: str) -> Path:
    model_dir = CACHE_DIR / "tts" / model
    onnx = next(model_dir.glob("*.onnx"), None) if model_dir.exists() else None
    if onnx:
        return model_dir
    model_dir.parent.mkdir(parents=True, exist_ok=True)
    url = PIPER_RELEASE.format(model=model)
    print(f"[tts] downloading offline voice {model} ...")
    tmp = model_dir.parent / f"{model}.tar.bz2"
    with urllib.request.urlopen(url, timeout=120) as r, open(tmp, "wb") as f:
        shutil.copyfileobj(r, f)
    with tarfile.open(tmp, "r:bz2") as tar:
        tar.extractall(model_dir.parent, filter="data")
    tmp.unlink(missing_ok=True)
    if not model_dir.exists():  # archive folder name differs from model name
        extracted = next(p for p in model_dir.parent.iterdir() if p.is_dir() and list(p.glob("*.onnx")))
        extracted.rename(model_dir)
    return model_dir


_OFFLINE_TTS = None


def _offline_tts(model: str):
    global _OFFLINE_TTS
    if _OFFLINE_TTS is not None:
        return _OFFLINE_TTS
    import sherpa_onnx

    d = ensure_offline_model(model)
    onnx = next(d.glob("*.onnx"))
    cfg = sherpa_onnx.OfflineTtsConfig(
        model=sherpa_onnx.OfflineTtsModelConfig(
            vits=sherpa_onnx.OfflineTtsVitsModelConfig(
                model=str(onnx), tokens=str(d / "tokens.txt"), data_dir=str(d / "espeak-ng-data"),
                length_scale=1.0, noise_scale=0.667, noise_scale_w=0.8,
            ),
            num_threads=2, provider="cpu",
        ),
        max_num_sentences=1,
    )
    _OFFLINE_TTS = sherpa_onnx.OfflineTts(cfg)
    return _OFFLINE_TTS


def _synth_offline(texts: list[str], cfg: Config, workdir: Path) -> list[SceneAudio]:
    tts = _offline_tts(cfg.get("voice.offline_voice", "vits-piper-en_US-ryan-medium"))
    speed = float(cfg.get("voice.offline_speed", 1.08))
    out: list[SceneAudio] = []
    for i, text in enumerate(texts):
        raw = workdir / f"scene{i:02d}_raw.wav"
        wav = workdir / f"scene{i:02d}.wav"
        audio = tts.generate(text, sid=0, speed=speed)
        if not getattr(audio, "sample_rate", 0) or len(audio.samples) == 0:
            raise RuntimeError("offline voice returned no audio (check the sherpa-onnx version)")
        samples = (np.clip(np.asarray(audio.samples, dtype=np.float32), -1, 1) * 32767).astype(np.int16)
        write_wav(raw, samples, audio.sample_rate)
        _ffmpeg_to_wav(raw, wav)
        samples48, sr = read_wav(wav)
        v0, v1 = _voiced_span(samples48, sr)
        out.append(_finalize(wav, samples48, sr, estimate_words(text, v0, v1)))
    return out


# ----------------------------------------------------------------------------- public API
def synthesize(texts: list[str], cfg: Config, workdir: Path, voice: str | None = None) -> tuple[list[SceneAudio], str]:
    """Return (scene audio list, engine actually used)."""
    workdir.mkdir(parents=True, exist_ok=True)
    texts = [_clean_text(t) for t in texts]
    engine = cfg.tts_engine
    if engine in ("auto", "edge"):
        try:
            return _synth_edge(texts, cfg, workdir, voice), "edge"
        except Exception as e:  # noqa: BLE001
            if engine == "edge":
                raise
            print(f"[tts] edge-tts failed ({type(e).__name__}: {e}); using offline voice")
    return _synth_offline(texts, cfg, workdir), "offline"
