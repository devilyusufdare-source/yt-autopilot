"""Long (16:9, 8-12 minute) videos: a themed list of verified facts, one chapter per fact.

A long-form package lives in content/longform/queue/<id>.json (see content/longform/schema.json):
intro -> 8-12 segments (each: heading, text, keywords, sources) -> outro. The same voice, footage
providers and caption engine as the Shorts are used, with a landscape layout, 2-3 clips per
segment, a chapter pill at the top and YouTube chapter timestamps in the description.
"""
from __future__ import annotations

import os
import subprocess
from pathlib import Path

from PIL import Image

from . import tts as tts_mod
from .captions import build_ass
from .config import Config, with_overrides
from .render import assemble_voice, concat_clips, make_thumbnail, pick_music, render_final
from .visuals import Visuals


def longform_config(cfg: Config) -> Config:
    """The channel config re-targeted at a landscape long video."""
    lf = cfg.get("longform") or {}
    return with_overrides(cfg, {
        "video.width": int(lf.get("width", 1920)),
        "video.height": int(lf.get("height", 1080)),
        "video.max_seconds": int(lf.get("max_seconds", 900)),
        "video.zoom": float(lf.get("zoom", 0.05)),
        "video.crf": int(lf.get("crf", 21)),
        "video.preset": lf.get("preset", "fast"),
        "video.progress_bar": bool(lf.get("progress_bar", False)),
        "video.gap_seconds": float(lf.get("gap_seconds", 0.45)),
        "captions.font_size": int(lf.get("caption_font_size", 66)),
        "captions.words_per_group": int(lf.get("words_per_group", 4)),
        "captions.max_chars_per_line": int(lf.get("max_chars_per_line", 26)),
        "captions.y_percent": float(lf.get("caption_y_percent", 84)),
        "captions.outline_px": int(lf.get("caption_outline_px", 6)),
        "captions.label_scale": float(lf.get("label_scale", 0.6)),
        "thumbnail.enabled": bool(lf.get("thumbnail", True)),
    })


def _keywords(seg: dict) -> list[str]:
    kw = seg.get("keywords") or ""
    if isinstance(kw, list):
        return [str(k).strip() for k in kw if str(k).strip()] or ["abstract background"]
    parts = [k.strip() for k in str(kw).split("|") if k.strip()]
    return parts or [str(kw).strip() or "abstract background"]


def _mmss(t: float) -> str:
    t = int(round(t))
    h, m, s = t // 3600, (t % 3600) // 60, t % 60
    return f"{h}:{m:02d}:{s:02d}" if h else f"{m}:{s:02d}"


def chapters_text(starts: list[float], headings: list[str]) -> str:
    lines = ["Chapters:"]
    for t, name in zip(starts, headings):
        lines.append(f"{_mmss(t)} {name}")
    return "\n".join(lines)


def build_longform(pkg: dict, base_cfg: Config, outdir: Path, publish_at: str | None = None) -> dict:
    """Render a long video for `pkg` into outdir. Returns the same keys as run.build_video."""
    cfg = longform_config(base_cfg)
    outdir.mkdir(parents=True, exist_ok=True)
    segments = pkg["segments"]
    scenes = [pkg["intro"].strip()] + [s["text"].strip() for s in segments] + [pkg["outro"].strip()]
    headings = [s["heading"].strip() for s in segments]

    print(f"[longform] voice: {len(scenes)} parts ({sum(len(t.split()) for t in scenes)} words)")
    audio, engine = tts_mod.synthesize(scenes, cfg, outdir / "tts", voice=pkg.get("voice"))
    gap = float(cfg.get("video.gap_seconds", 0.45))
    durations, words = assemble_voice(audio, gap, outdir / "voice.wav")
    total_est = sum(durations)
    max_s = float(cfg.get("video.max_seconds", 900))
    if total_est > max_s + 5:
        raise RuntimeError(f"narration is {total_est / 60:.1f} min, longer than the {max_s / 60:.0f} min limit; shorten the segments")

    providers = [n for n, k in (("pixabay", os.environ.get("PIXABAY_API_KEY")), ("pexels", cfg.pexels_key)) if k]
    print(f"[longform] visuals: {', '.join(providers) if providers else 'no footage key set - animated backgrounds'}")
    vis = Visuals(cfg, outdir / "clips", seed=pkg["id"], topic=pkg.get("theme") or pkg.get("topic", ""))
    clips: list[Path] = []
    idx = 0
    # intro + outro: one clip each; every segment: one clip per keyword (2-3), splitting its time.
    plan: list[tuple[list[str], float]] = [(_keywords({"keywords": pkg.get("intro_keywords") or (segments[0].get("keywords") or "")})[:1], durations[0])]
    for seg, d in zip(segments, durations[1:-1]):
        plan.append((_keywords(seg)[:3], d))
    plan.append((_keywords({"keywords": pkg.get("outro_keywords") or (segments[-1].get("keywords") or "")})[:1], durations[-1]))
    for kws, d in plan:
        share = d / len(kws)
        for kw in kws:
            clips.append(vis.scene_clip(idx, kw, share))
            idx += 1
    vis.save_credits(outdir / "footage_credits.json")
    visual = outdir / "visual.mp4"
    total = concat_clips(clips, visual)

    # Chapter pills: "3/10  •  HEADING" over each segment; the intro pill shows the series name.
    starts: list[float] = []
    t = 0.0
    for d in durations:
        starts.append(t)
        t += d
    labels: list[tuple[float, float, str]] = []
    series = pkg.get("series") or cfg.get("longform.series_label") or cfg.get("channel.name", "")
    labels.append((0.0, starts[1], series))
    for i, (name, s0) in enumerate(zip(headings, starts[1:-1]), 1):
        s1 = starts[i + 1]
        labels.append((s0, s1, f"{i}/{len(headings)}  •  {name}"))
    labels.append((starts[-1], total, series))
    ass = build_ass(words, cfg, outdir / "captions.ass", None, total, labels=labels)

    print("[longform] rendering final video")
    final = render_final(visual, outdir / "voice.wav", ass, pick_music(cfg, pkg["id"]), cfg,
                         outdir / f"{pkg['id']}.mp4", total)

    # Chapters for the description: 0:00 Intro, then one per fact (YouTube needs >= 3, first at 0:00).
    chapter_names = ["Intro"] + [f"{i}. {name}" for i, name in enumerate(headings, 1)]
    pkg["chapters_text"] = chapters_text(starts[:-1], chapter_names)

    thumb = None
    if cfg.get("thumbnail.enabled", True):
        frame = outdir / "frame.jpg"
        subprocess.run(["ffmpeg", "-y", "-loglevel", "error", "-ss", str(min(8.0, max(1.0, durations[0] + 2))), "-i", str(final),
                        "-frames:v", "1", str(frame)], check=False)
        big = make_thumbnail(pkg.get("thumbnail_text") or pkg["title"], pkg.get("thumbnail_label") or f"{len(headings)} FACTS",
                             cfg, outdir / "thumbnail_full.jpg", frame if frame.exists() else None)
        thumb = outdir / "thumbnail.jpg"
        Image.open(big).convert("RGB").resize((1280, 720), Image.LANCZOS).save(thumb, "JPEG", quality=88, optimize=True)

    footage: dict[str, int] = {}
    for c in vis.credits:
        footage[c["provider"]] = footage.get(c["provider"], 0) + 1
    footage["animated-background"] = len(clips) - len(vis.credits)
    return {"video": final, "thumbnail": thumb, "duration": total, "tts_engine": engine,
            "words": sum(len(w) for w in words), "footage": footage, "style": "longform",
            "chapters": pkg["chapters_text"]}
