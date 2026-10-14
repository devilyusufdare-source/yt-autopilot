"""Daily job: take the oldest idea in content/queue, make the video, upload it, record the result.

    python -m pipeline.run                 # full run (render + upload)
    python -m pipeline.run --dry-run       # render only, keep the idea in the queue
    python -m pipeline.run --package content/queue/2026-10-15-doorway-effect.json
"""
from __future__ import annotations

import argparse
import datetime as dt
import json
import os
import shutil
import subprocess
import sys
import traceback
from pathlib import Path

from . import tts as tts_mod
from .captions import build_ass
from .config import FAILED_DIR, OUTPUT_DIR, PUBLISHED_DIR, QUEUE_DIR, ensure_dirs, load_config
from .render import assemble_voice, concat_clips, make_thumbnail, pick_music, render_final
from .validate import validate_package
from .visuals import Visuals

MAX_ATTEMPTS = 2


def _load(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def _save(path: Path, pkg: dict) -> None:
    path.write_text(json.dumps(pkg, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")


def _fail(path: Path, pkg: dict, reason: str) -> None:
    pkg["_error"] = reason
    pkg["_failed_at"] = dt.datetime.now(dt.timezone.utc).isoformat(timespec="seconds")
    FAILED_DIR.mkdir(parents=True, exist_ok=True)
    _save(FAILED_DIR / path.name, pkg)
    path.unlink(missing_ok=True)
    print(f"[run] moved {path.name} to content/failed: {reason}")


def pick_package(cfg, explicit: Path | None) -> tuple[Path, dict] | None:
    if explicit:
        pkg = _load(explicit)
        errs = validate_package(pkg, cfg)
        if errs:
            raise SystemExit("package is invalid:\n  - " + "\n  - ".join(errs))
        return explicit, pkg
    for path in sorted(QUEUE_DIR.glob("*.json")):
        try:
            pkg = _load(path)
        except Exception as e:  # noqa: BLE001
            _fail(path, {"id": path.stem}, f"not valid JSON: {e}")
            continue
        errs = validate_package(pkg, cfg)
        if errs:
            _fail(path, pkg, "; ".join(errs))
            continue
        return path, pkg
    return None


def build_video(pkg: dict, cfg, outdir: Path) -> dict:
    """Render everything for one package into outdir. Returns a dict with file paths and details."""
    outdir.mkdir(parents=True, exist_ok=True)
    scenes = [s["text"] for s in pkg["scenes"]]
    keywords = [s["keywords"] for s in pkg["scenes"]]
    cta = pkg.get("cta") if "cta" in pkg else cfg.get("cta.text", "")
    if cfg.get("cta.spoken", True) and cta:
        scenes.append(cta)
        keywords.append(keywords[-1])

    print(f"[run] voice: {len(scenes)} scenes")
    audio, engine = tts_mod.synthesize(scenes, cfg, outdir / "tts", voice=pkg.get("voice"))
    gap = float(cfg.get("video.gap_seconds", 0.25))
    durations, words = assemble_voice(audio, gap, outdir / "voice.wav")
    total_est = sum(durations)
    max_s = float(cfg.get("video.max_seconds", 58))
    if total_est > max_s + 2:
        raise RuntimeError(f"narration is {total_est:.1f}s, longer than the {max_s:.0f}s limit; shorten the script")

    providers = [n for n, k in (("pixabay", os.environ.get("PIXABAY_API_KEY")), ("pexels", cfg.pexels_key)) if k]
    print(f"[run] visuals: {', '.join(providers) if providers else 'no footage key set - animated backgrounds'}")
    vis = Visuals(cfg, outdir / "clips", seed=pkg["id"], topic=pkg.get("topic", ""))
    clips = [vis.scene_clip(i, kw, d) for i, (kw, d) in enumerate(zip(keywords, durations))]
    vis.save_credits(outdir / "footage_credits.json")
    visual = outdir / "visual.mp4"
    total = concat_clips(clips, visual)

    label = None
    if cfg.get("captions.show_top_label", True):
        label = f"{cfg.get('channel.name', '')}  •  {pkg.get('topic', '')}".strip(" •")
    ass = build_ass(words, cfg, outdir / "captions.ass", label, total)

    print("[run] rendering final video")
    final = render_final(visual, outdir / "voice.wav", ass, pick_music(cfg, pkg["id"]), cfg, outdir / f"{pkg['id']}.mp4", total)

    thumb = None
    if cfg.get("thumbnail.enabled", True):
        frame = outdir / "frame.jpg"
        subprocess.run(["ffmpeg", "-y", "-loglevel", "error", "-ss", "1", "-i", str(final), "-frames:v", "1", str(frame)], check=False)
        thumb = make_thumbnail(pkg.get("thumbnail_text") or pkg["scenes"][0]["text"], cfg.get("channel.name", "") or "NEW FACT",
                               cfg, outdir / "thumbnail.jpg", frame if frame.exists() else None)
    footage = {}
    for c in vis.credits:
        footage[c["provider"]] = footage.get(c["provider"], 0) + 1
    footage["animated-background"] = len(clips) - len(vis.credits)
    return {"video": final, "thumbnail": thumb, "duration": total, "tts_engine": engine,
            "words": sum(len(w) for w in words), "footage": footage}


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--dry-run", action="store_true", help="render only; do not upload or change the queue")
    ap.add_argument("--package", type=Path, help="render this package instead of the oldest queued one")
    ap.add_argument("--no-stats", action="store_true", help="skip refreshing content/stats.json")
    args = ap.parse_args(argv)

    ensure_dirs()
    cfg = load_config()
    picked = pick_package(cfg, args.package)
    if not picked:
        print("[run] QUEUE EMPTY - nothing to publish today. Run the idea generator (see AGENT_TASK.md).")
        return 3
    path, pkg = picked
    print(f"[run] package: {path.name}  title: {pkg['title']}")

    outdir = OUTPUT_DIR / pkg["id"]
    if outdir.exists():
        shutil.rmtree(outdir)
    try:
        result = build_video(pkg, cfg, outdir)
    except Exception as e:  # noqa: BLE001
        traceback.print_exc()
        if not args.dry_run and not args.package:
            pkg["_attempts"] = int(pkg.get("_attempts", 0)) + 1
            if pkg["_attempts"] >= MAX_ATTEMPTS:
                _fail(path, pkg, f"render failed {pkg['_attempts']}x: {e}")
            else:
                _save(path, pkg)
        return 1

    summary = {
        "id": pkg["id"], "title": pkg["title"], "duration_seconds": round(result["duration"], 1),
        "voice": result["tts_engine"], "footage": result["footage"], "video": str(result["video"]),
    }
    print(f"[run] rendered {result['video']} ({result['duration']:.1f}s, voice={result['tts_engine']})")

    if args.dry_run:
        print("[run] dry run: not uploading")
        (OUTPUT_DIR / "summary.json").write_text(json.dumps(summary, indent=2), encoding="utf-8")
        return 0

    from .stats import update_stats
    from .upload import build_body, set_thumbnail, upload_video, youtube_client

    try:
        yt = youtube_client(cfg)
        body = build_body(pkg, cfg)
        video_id = upload_video(yt, result["video"], body)
        print(f"[run] uploaded: https://youtube.com/shorts/{video_id}")
        if result["thumbnail"]:
            set_thumbnail(yt, video_id, result["thumbnail"])
    except Exception as e:  # noqa: BLE001
        traceback.print_exc()
        if not args.package:
            pkg["_attempts"] = int(pkg.get("_attempts", 0)) + 1
            if pkg["_attempts"] >= MAX_ATTEMPTS:
                _fail(path, pkg, f"upload failed {pkg['_attempts']}x: {e}")
            else:
                _save(path, pkg)
        return 1

    pkg.pop("_attempts", None)
    pkg["youtube_id"] = video_id
    pkg["url"] = f"https://youtube.com/shorts/{video_id}"
    pkg["uploaded_at"] = dt.datetime.now(dt.timezone.utc).isoformat(timespec="seconds")
    pkg["privacy_requested"] = body["status"]["privacyStatus"]
    pkg["tts_engine"] = result["tts_engine"]
    pkg["duration_seconds"] = round(result["duration"], 1)
    PUBLISHED_DIR.mkdir(parents=True, exist_ok=True)
    _save(PUBLISHED_DIR / path.name, pkg)
    if path.parent == QUEUE_DIR:
        path.unlink()
    summary.update({"youtube_id": video_id, "url": pkg["url"]})
    (OUTPUT_DIR / "summary.json").write_text(json.dumps(summary, indent=2), encoding="utf-8")

    if not args.no_stats:
        try:
            data = update_stats(yt)
            print(f"[run] stats refreshed: {data['total_videos']} videos, {data['total_views']} views total")
        except Exception as e:  # noqa: BLE001
            print(f"[run] stats refresh failed (non-fatal): {e}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
