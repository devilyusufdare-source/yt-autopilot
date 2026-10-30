"""Assemble voice, scene clips, captions, music and a progress bar into the final MP4."""
from __future__ import annotations

import json
import random
import subprocess
import textwrap
from pathlib import Path

import numpy as np
from PIL import Image, ImageDraw, ImageFilter, ImageFont

from .config import ASSETS_DIR, MUSIC_DIR, ROOT, Config
from .tts import SAMPLE_RATE, SceneAudio, Word, read_wav, write_wav


class FFmpegError(subprocess.CalledProcessError):
    """A failed ffmpeg run whose message carries ffmpeg's own last lines. The command line alone says nothing, and the
    Actions log is out of reach, so the reason has to travel in the exception (it ends up in runs/last-failure.txt)."""

    def __str__(self) -> str:
        lines = [ln.strip() for ln in (self.stderr or "").replace("\r", "\n").splitlines()
                 if ln.strip() and not ln.lstrip().startswith(("frame=", "size="))]
        return f"ffmpeg exited with {self.returncode}: " + (" | ".join(lines[-6:]) or "(no error output)")


def _ffmpeg(cmd: list[str]) -> None:
    proc = subprocess.run(cmd, stderr=subprocess.PIPE, text=True, errors="replace")
    if proc.returncode != 0:
        raise FFmpegError(proc.returncode, cmd, stderr=proc.stderr)


def has_picture(path: Path) -> bool:
    """True when the file has a video stream with at least one frame (a clip can come out of ffmpeg without one)."""
    try:
        out = subprocess.run(["ffprobe", "-v", "error", "-select_streams", "v:0", "-count_packets",
                              "-show_entries", "stream=nb_read_packets", "-of", "csv=p=0", str(path)],
                             capture_output=True, text=True, timeout=120).stdout.strip()
    except (subprocess.SubprocessError, OSError):
        return False
    return out.isdigit() and int(out) > 0


def _ff_escape(path: Path) -> str:
    """Escape a path for use inside an ffmpeg filter graph argument."""
    return str(path).replace("\\", "\\\\").replace(":", "\\:").replace("'", "\\'").replace(",", "\\,")


def probe_duration(path: Path) -> float:
    out = subprocess.run(
        ["ffprobe", "-v", "error", "-show_entries", "format=duration", "-of", "json", str(path)],
        check=True, capture_output=True, text=True,
    ).stdout
    return float(json.loads(out)["format"]["duration"])


def assemble_voice(scenes: list[SceneAudio], gap: float, out: Path) -> tuple[list[float], list[list[Word]]]:
    """Concatenate scene audio with `gap` seconds of silence after each scene.

    Returns the visual duration of each scene (audio + gap) and the words with absolute times.
    """
    silence = np.zeros(int(gap * SAMPLE_RATE), dtype=np.int16)
    parts: list[np.ndarray] = []
    durations: list[float] = []
    words: list[list[Word]] = []
    t = 0.0
    for sc in scenes:
        samples, rate = read_wav(sc.wav)
        assert rate == SAMPLE_RATE, f"unexpected sample rate {rate}"
        parts += [samples, silence]
        words.append([Word(w.text, t + w.start, t + w.end) for w in sc.words])
        d = len(samples) / SAMPLE_RATE + gap
        durations.append(d)
        t += d
    write_wav(out, np.concatenate(parts))
    return durations, words


def concat_clips(clips: list[Path], out: Path) -> float:
    lst = out.with_suffix(".txt")
    lst.write_text("".join(f"file '{c.as_posix()}'\n" for c in clips), encoding="utf-8")
    _ffmpeg(["ffmpeg", "-y", "-loglevel", "error", "-f", "concat", "-safe", "0", "-i", str(lst), "-c", "copy", str(out)])
    if not has_picture(out):
        # 30 Oct: a What If render failed twice with "Stream specifier ':v' ... matches no streams": the joined
        # track had no picture. Join again with re-encoding, which rebuilds the stream from every clip that has one.
        good = [c for c in clips if has_picture(c)]
        if not good:
            raise RuntimeError("none of the scene clips has a picture")
        print(f"[render] joined clips had no picture ({len(clips) - len(good)} of {len(clips)} clips without one); re-encoding")
        lst.write_text("".join(f"file '{c.as_posix()}'\n" for c in good), encoding="utf-8")
        _ffmpeg(["ffmpeg", "-y", "-loglevel", "error", "-f", "concat", "-safe", "0", "-i", str(lst), "-an",
                 "-c:v", "libx264", "-preset", "veryfast", "-crf", "18", "-pix_fmt", "yuv420p", str(out)])
    return probe_duration(out)


def pick_music(cfg: Config, seed: str) -> Path | None:
    if not cfg.get("music.enabled", True) or not MUSIC_DIR.exists():
        return None
    files = sorted(p for p in MUSIC_DIR.iterdir() if p.suffix.lower() in (".mp3", ".m4a", ".wav", ".ogg", ".aac"))
    if not files:
        return None
    return random.Random(seed).choice(files)


def render_final(visual: Path, voice: Path, ass: Path, music: Path | None, cfg: Config, out: Path,
                 total: float) -> Path:
    w, h, fps = cfg.width, cfg.height, cfg.fps
    fonts_dir = ROOT / Path(cfg.get("captions.font_file", "assets/fonts/Poppins-ExtraBold.ttf")).parent
    filters = [f"[0:v]subtitles=filename='{_ff_escape(ass)}':fontsdir='{_ff_escape(fonts_dir)}'[v0]"]
    vout = "[v0]"
    if cfg.get("video.progress_bar", True):
        bar_h = max(6, h // 160)
        color = cfg.get("captions.highlight_color", "#FFD400").replace("#", "0x")
        filters.append(f"color=c={color}@0.95:s={w}x{bar_h}:r={fps}:d={total:.3f}[bar]")
        filters.append(f"[v0][bar]overlay=x='-w+w*t/{total:.3f}':y=H-h:shortest=1[v]")
        vout = "[v]"
    lufs = float(cfg.get("voice.loudness_lufs", -16))
    voice_filter = f"[1:a]loudnorm=I={lufs}:TP=-1.5:LRA=11,aresample=48000[va]"
    filters.append(voice_filter)
    inputs = ["-i", str(visual), "-i", str(voice)]
    aout = "[va]"
    if music:
        vol = float(cfg.get("music.volume", 0.10))
        inputs += ["-stream_loop", "-1", "-i", str(music)]
        filters.append(f"[2:a]volume={vol},aresample=48000,afade=t=out:st={max(0.0, total - 1.5):.3f}:d=1.5,"
                       f"atrim=0:{total:.3f}[ma]")
        filters.append("[va][ma]amix=inputs=2:duration=first:normalize=0[a]")
        aout = "[a]"
    cmd = ["ffmpeg", "-y", "-loglevel", "error", "-stats_period", "5", *inputs,
           "-filter_complex", ";".join(filters), "-map", vout, "-map", aout,
           "-c:v", "libx264", "-preset", str(cfg.get("video.preset", "medium")), "-crf", str(cfg.get("video.crf", 20)), "-pix_fmt", "yuv420p",
           "-r", str(fps), "-c:a", "aac", "-b:a", "192k", "-ar", "48000", "-movflags", "+faststart",
           "-t", f"{total:.3f}", str(out)]
    try:
        _ffmpeg(cmd)
    except FFmpegError as e:
        if "nan" not in (e.stderr or "").lower():
            raise
        # 30 Oct: loudnorm's dynamic mode now and then hands the AAC encoder invalid samples ("Input contains (near)
        # NaN/+-Inf", exit 234): What If lost two slots to it. Same loudness target, reached with one fixed gain and a
        # peak limiter instead.
        gain = lufs - measure_lufs(voice)
        print(f"[render] loudnorm produced invalid samples; using a fixed gain of {gain:+.1f} dB instead")
        safe = f"[1:a]volume={gain:.2f}dB,alimiter=limit={10 ** (-1.5 / 20):.4f}:level=false,aresample=48000[va]"
        fc = cmd.index("-filter_complex") + 1
        cmd[fc] = cmd[fc].replace(voice_filter, safe)
        _ffmpeg(cmd)
    return out


def measure_lufs(path: Path) -> float:
    """Integrated loudness (EBU R128) of an audio file; -70 for silence or when it cannot be measured."""
    err = subprocess.run(["ffmpeg", "-hide_banner", "-nostats", "-i", str(path), "-af", "ebur128=framelog=quiet", "-f", "null", "-"],
                         capture_output=True, text=True, errors="replace").stderr
    import re
    found = re.findall(r"I:\s+(-?[\d.]+|-inf) LUFS", err)
    try:
        value = float(found[-1])
    except (IndexError, ValueError):
        return -70.0
    return value if value > -70 else -70.0


# ----------------------------------------------------------------------------- thumbnail
def _font(size: int, cfg: Config) -> ImageFont.FreeTypeFont:
    path = ROOT / cfg.get("captions.font_file", "assets/fonts/Poppins-ExtraBold.ttf")
    try:
        return ImageFont.truetype(str(path), size)
    except OSError:
        return ImageFont.truetype(str(ASSETS_DIR / "fonts" / "Poppins-ExtraBold.ttf"), size)


def _hex(c: str) -> tuple[int, int, int]:
    c = c.lstrip("#")
    return int(c[0:2], 16), int(c[2:4], 16), int(c[4:6], 16)


def make_thumbnail(text: str, label: str, cfg: Config, out: Path, frame: Path | None = None) -> Path:
    w, h = cfg.width, cfg.height
    bg = _hex(cfg.get("thumbnail.background", "#0B1020"))
    accent = _hex(cfg.get("thumbnail.accent", "#FFD400"))
    img = Image.new("RGB", (w, h), bg)
    if frame and frame.exists():
        try:
            f = Image.open(frame).convert("RGB").resize((w, h))
            f = f.filter(ImageFilter.GaussianBlur(6))
            img = Image.blend(f, Image.new("RGB", (w, h), bg), 0.45)
        except Exception:  # noqa: BLE001
            pass
    # Soft radial glow
    glow = Image.new("RGB", (w, h), bg)
    gd = ImageDraw.Draw(glow)
    gd.ellipse((-200, h * 0.25, w + 200, h * 0.95), fill=tuple(min(255, int(c * 1.9 + 25)) for c in bg))
    glow = glow.filter(ImageFilter.GaussianBlur(220))
    img = Image.blend(img, glow, 0.5)

    draw = ImageDraw.Draw(img)
    upper = bool(cfg.get("captions.uppercase", True))
    text = text.upper() if upper else text
    size = 128
    while size > 60:
        font = _font(size, cfg)
        lines = textwrap.wrap(text, width=max(8, int(w * 0.82 / (size * 0.58))))
        if len(lines) <= 5:
            break
        size -= 8
    line_h = int(size * 1.18)
    block_h = line_h * len(lines)
    y = (h - block_h) // 2 - 40
    for li, line in enumerate(lines):
        tw = draw.textlength(line, font=font)
        x = (w - tw) // 2
        # highlight the first line in the accent colour, the rest white
        fill = accent if li == 0 else (255, 255, 255)
        draw.text((x + 6, y + 6), line, font=font, fill=(0, 0, 0))
        draw.text((x, y), line, font=font, fill=fill, stroke_width=6, stroke_fill=(0, 0, 0))
        y += line_h
    # label pill at the top
    lf = _font(44, cfg)
    label = label.upper() if upper else label
    lw = draw.textlength(label, font=lf)
    px, py = (w - lw) // 2 - 36, int(h * 0.11)
    draw.rounded_rectangle((px, py, px + lw + 72, py + 84), radius=42, fill=accent)
    draw.text((px + 36, py + 16), label, font=lf, fill=(0, 0, 0))
    # bottom bar
    draw.rectangle((0, h - 18, w, h), fill=accent)
    img.save(out, "JPEG", quality=88, optimize=True)
    return out
