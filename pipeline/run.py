"""Scheduled job: take ideas from content/queue (oldest first), make the videos, upload them,
record the results.

    python -m pipeline.run                 # make `release.videos_per_run` videos and upload them
    python -m pipeline.run --count 1       # make/upload just one
    python -m pipeline.run --dry-run       # render one video only, upload nothing, queue untouched
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
import time
import traceback
from pathlib import Path

from . import tts as tts_mod
from .captions import build_ass
from .config import FAILED_DIR, OUTPUT_DIR, PUBLISHED_DIR, QUEUE_DIR, ensure_dirs, load_config
from .render import assemble_voice, concat_clips, make_thumbnail, pick_music, render_final
from .validate import validate_package
from .visuals import Visuals

MAX_ATTEMPTS = 2
MAX_WAIT_MINUTES = 70      # longest a run will wait for a free upload slot before leaving the rest for the next run
SAFETY_MINUTES = 6         # extra margin on YouTube's 24 h window


def recent_upload_times(hours: float = 24.0) -> list[dt.datetime]:
    """UTC times of uploads recorded in content/published within the last `hours`."""
    now = dt.datetime.now(dt.timezone.utc)
    out: list[dt.datetime] = []
    for f in PUBLISHED_DIR.glob("*.json"):
        try:
            t = json.loads(f.read_text(encoding="utf-8")).get("uploaded_at")
            if not t:
                continue
            when = dt.datetime.fromisoformat(t.replace("Z", "+00:00"))
            if when.tzinfo is None:
                when = when.replace(tzinfo=dt.timezone.utc)
            if now - when < dt.timedelta(hours=hours):
                out.append(when)
        except Exception:  # noqa: BLE001
            continue
    return sorted(out)


LIMITS_FILE = PUBLISHED_DIR.parent / "limits.json"
PROBE_EVERY_DAYS = 7


def load_limits(cfg) -> dict:
    data = {"daily_limit": int(cfg.get("release.daily_limit", 0) or 0), "last_probe": None, "history": []}
    if LIMITS_FILE.exists():
        try:
            data.update(json.loads(LIMITS_FILE.read_text(encoding="utf-8")))
        except Exception:  # noqa: BLE001
            pass
    return data


def save_limits(data: dict) -> None:
    LIMITS_FILE.write_text(json.dumps(data, indent=2) + "\n", encoding="utf-8")


def daily_cap(cfg) -> int:
    return int(load_limits(cfg).get("daily_limit", 0) or 0)


def should_probe(cfg) -> bool:
    """Once a week, try one upload beyond the known limit to find out whether YouTube raised it."""
    if not cfg.get("release.probe_limit", True):
        return False
    lim = load_limits(cfg)
    if lim.get("daily_limit", 0) <= 0:
        return False
    last = lim.get("last_probe")
    if not last:
        return True
    try:
        when = dt.datetime.fromisoformat(last.replace("Z", "+00:00"))
    except ValueError:
        return True
    return dt.datetime.now(dt.timezone.utc) - when >= dt.timedelta(days=PROBE_EVERY_DAYS)


def seconds_until_slot(cfg) -> float:
    """0 if an upload may happen now; otherwise seconds to wait until YouTube's 24 h window frees a slot."""
    cap = daily_cap(cfg)
    if cap <= 0:
        return 0.0
    recent = recent_upload_times(24.0)
    if len(recent) < cap:
        return 0.0
    oldest_in_window = recent[len(recent) - cap]
    free_at = oldest_in_window + dt.timedelta(hours=24, minutes=SAFETY_MINUTES)
    return max(0.0, (free_at - dt.datetime.now(dt.timezone.utc)).total_seconds())


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


def _note_attempt(path: Path, pkg: dict, error: str) -> None:
    """Count a failure; after MAX_ATTEMPTS the idea is moved out of the queue so it cannot block it."""
    pkg["_attempts"] = int(pkg.get("_attempts", 0)) + 1
    if pkg["_attempts"] >= MAX_ATTEMPTS:
        _fail(path, pkg, f"failed {pkg['_attempts']}x: {error}")
    else:
        _save(path, pkg)


_STOP = {"the","a","an","of","in","on","and","or","is","are","was","were","to","for","than","that","this","it","its",
         "you","your","can","cant","can't","here's","heres","why","how","what","with","from","has","have","be","will",
         "every","even","only","just","more","not","no","so","if","at","by","as","do","does","did","s"}


def _title_words(title: str) -> set[str]:
    import re
    words = re.findall(r"[a-z0-9']+", title.lower())
    return {w for w in words if w not in _STOP and len(w) > 1}


def duplicate_of(pkg: dict) -> str | None:
    """Title of an already-published video that this idea repeats, or None."""
    mine = _title_words(pkg.get("title", ""))
    if not mine:
        return None
    for f in PUBLISHED_DIR.glob("*.json"):
        try:
            other = json.loads(f.read_text(encoding="utf-8"))
        except Exception:  # noqa: BLE001
            continue
        if other.get("id") == pkg.get("id"):
            return other.get("title")
        theirs = _title_words(other.get("title", ""))
        if theirs and len(mine & theirs) / min(len(mine), len(theirs)) >= 0.6:
            return other.get("title")
    return None


def pick_package(cfg, explicit: Path | None, skip: set[str]) -> tuple[Path, dict] | None:
    if explicit:
        pkg = _load(explicit)
        errs = validate_package(pkg, cfg)
        if errs:
            raise SystemExit("package is invalid:\n  - " + "\n  - ".join(errs))
        return explicit, pkg
    # Highest "priority" first (default 0), then oldest file name first.
    candidates = []
    for path in sorted(QUEUE_DIR.glob("*.json")):
        if path.name in skip:
            continue
        try:
            pkg = _load(path)
        except Exception as e:  # noqa: BLE001
            _fail(path, {"id": path.stem}, f"not valid JSON: {e}")
            continue
        try:
            prio = int(pkg.get("priority", 0) or 0)
        except (TypeError, ValueError):
            prio = 0
        candidates.append((-prio, path.name, path, pkg))
    for _, _, path, pkg in sorted(candidates, key=lambda c: (c[0], c[1])):
        errs = validate_package(pkg, cfg)
        if errs:
            _fail(path, pkg, "; ".join(errs))
            continue
        dup = duplicate_of(pkg)
        if dup:
            _fail(path, pkg, f"duplicate of an already published video: {dup}")
            continue
        return path, pkg
    return None


def build_video(pkg: dict, cfg, outdir: Path, style: str = "classic") -> dict:
    """Render everything for one package into outdir. Returns file paths and details.

    style "classic": word-by-word captions from the first word, spoken call-to-action at the end.
    style "punch":   the whole hook sentence on screen for the first scene, no spoken call-to-action,
                     a small "follow" label in the last second (ends on the punchline so it loops).
    """
    outdir.mkdir(parents=True, exist_ok=True)
    scenes = [s["text"] for s in pkg["scenes"]]
    keywords = [s["keywords"] for s in pkg["scenes"]]
    cta = pkg.get("cta") if "cta" in pkg else cfg.get("cta.text", "")
    if style != "punch" and cfg.get("cta.spoken", True) and cta:
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
    hook_card = pkg["scenes"][0]["text"] if style == "punch" else None
    end_text = (cfg.get("cta.end_text") or "Follow for more") if style == "punch" else None
    ass = build_ass(words, cfg, outdir / "captions.ass", label, total,
                    hook_card=hook_card, hook_end=durations[0], end_text=end_text)

    print("[run] rendering final video")
    final = render_final(visual, outdir / "voice.wav", ass, pick_music(cfg, pkg["id"]), cfg,
                         outdir / f"{pkg['id']}.mp4", total)

    thumb = None
    if cfg.get("thumbnail.enabled", True):
        frame = outdir / "frame.jpg"
        subprocess.run(["ffmpeg", "-y", "-loglevel", "error", "-ss", "1", "-i", str(final), "-frames:v", "1", str(frame)], check=False)
        thumb = make_thumbnail(pkg.get("thumbnail_text") or pkg["scenes"][0]["text"], cfg.get("channel.name", "") or "NEW FACT",
                               cfg, outdir / "thumbnail.jpg", frame if frame.exists() else None)
    footage: dict[str, int] = {}
    for c in vis.credits:
        footage[c["provider"]] = footage.get(c["provider"], 0) + 1
    footage["animated-background"] = len(clips) - len(vis.credits)
    return {"video": final, "thumbnail": thumb, "duration": total, "tts_engine": engine,
            "words": sum(len(w) for w in words), "footage": footage, "style": style}


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--dry-run", action="store_true", help="render only; do not upload or change the queue")
    ap.add_argument("--count", type=int, help="how many videos to make this run (default: release.videos_per_run)")
    ap.add_argument("--package", type=Path, help="render this package first instead of the oldest queued one")
    ap.add_argument("--no-stats", action="store_true", help="skip refreshing content/stats.json")
    ap.add_argument("--now", action="store_true", help="publish immediately instead of scheduling hourly slots")
    args = ap.parse_args(argv)

    ensure_dirs()
    cfg = load_config()
    per_run = int(cfg.get("release.videos_per_run", 1))
    count = args.count or (1 if args.dry_run else per_run)
    cap = daily_cap(cfg)
    probe_index = None
    if args.count is None and not args.dry_run and cap > 0:
        # Catch-up: if YouTube's 24 h window has more room than usual (an earlier run was blocked),
        # make one extra video this run so the day still reaches the daily total.
        free_now = max(0, cap - len(recent_upload_times(24.0)))
        if free_now > per_run:
            count = min(free_now, per_run + 1)
            print(f"[run] {free_now} upload slots free in YouTube's 24 h window -> making {count} videos this run")
        elif free_now == 0 and should_probe(cfg):
            # Weekly probe: the window is full by our count; try ONE extra upload to learn whether
            # YouTube has raised this channel's limit. Refusal costs nothing but a render.
            probe_index = 0
            count = 1
            print(f"[run] weekly limit probe: trying one upload beyond the known limit of {cap}")
    count = max(1, count)

    yt = None
    slots: list[str | None] = [None] * count
    if not args.dry_run:
        from .upload import publish_slots, youtube_client
        try:
            yt = youtube_client(cfg)
        except Exception as e:  # noqa: BLE001
            msg = f"could not sign in to YouTube: {type(e).__name__}: {e}"
            print(f"[run] {msg}")
            _write_summary([], 1, error=msg)
            return 2
        slots = [None] * count if args.now else publish_slots(count, cfg)

    summaries: list[dict] = []
    tried: set[str] = set()
    failures = 0
    limit_hit = False
    for i in range(count):
        picked = pick_package(cfg, args.package if i == 0 else None, tried)
        if not picked:
            if i == 0:
                print("[run] QUEUE EMPTY - nothing to publish. The idea writer needs to run (see AGENT_TASK.md).")
                _write_summary(summaries, failures)
                return 3
            print(f"[run] queue ran out after {i} video(s)")
            break
        path, pkg = picked
        tried.add(path.name)
        if (PUBLISHED_DIR / path.name).exists():
            # Belt and braces: never upload an idea that already has a published record.
            print(f"[run] {path.name} is already published; removing it from the queue")
            if path.parent == QUEUE_DIR:
                path.unlink()
            continue
        if not args.dry_run and probe_index != i:
            wait = seconds_until_slot(cfg)
            if wait > MAX_WAIT_MINUTES * 60:
                print(f"[run] YouTube's daily limit ({cfg.get('release.daily_limit')}) is used up for the next "
                      f"{wait / 60:.0f} min; leaving the remaining ideas for the next run")
                summaries.append({"id": pkg["id"], "title": pkg["title"], "status": "not uploaded: daily limit window full (waits for next run)"})
                limit_hit = True
                break
        print(f"\n[run] ({i + 1}/{count}) {path.name}  title: {pkg['title']}")

        outdir = OUTPUT_DIR / pkg["id"]
        if outdir.exists():
            shutil.rmtree(outdir)
        style = pkg.get("style")
        if style not in ("classic", "punch"):
            if cfg.get("experiment.alternate_styles", False):
                n_pub = len(list(PUBLISHED_DIR.glob("*.json")))
                style = "punch" if (n_pub + i) % 2 == 0 else "classic"
            else:
                style = cfg.get("video.style", "classic")
        print(f"[run] style: {style}")
        try:
            result = build_video(pkg, cfg, outdir, style=style)
        except Exception as e:  # noqa: BLE001
            traceback.print_exc()
            failures += 1
            summaries.append({"id": pkg["id"], "title": pkg["title"], "status": f"render failed: {type(e).__name__}: {e}"[:300]})
            if not args.dry_run and path.parent == QUEUE_DIR:
                _note_attempt(path, pkg, str(e))
            continue

        summary = {"id": pkg["id"], "title": pkg["title"], "duration_seconds": round(result["duration"], 1),
                   "voice": result["tts_engine"], "footage": result["footage"], "style": style}
        print(f"[run] rendered {result['video'].name} ({result['duration']:.1f}s, voice={result['tts_engine']})")
        if args.dry_run:
            summary["status"] = "rendered (dry run)"
            summaries.append(summary)
            continue

        from .upload import build_body, set_thumbnail, upload_video
        wait = 0.0 if probe_index == i else seconds_until_slot(cfg)
        if wait > 0:
            print(f"[run] waiting {wait / 60:.1f} min for a free upload slot (YouTube 24 h limit)")
            time.sleep(min(wait, MAX_WAIT_MINUTES * 60))
        try:
            body = build_body(pkg, cfg, slots[i])
            video_id = upload_video(yt, result["video"], body)
            print(f"[run] uploaded: https://youtube.com/shorts/{video_id}  "
                  f"({'goes public at ' + slots[i] if slots[i] else body['status']['privacyStatus']})")
            if result["thumbnail"]:
                set_thumbnail(yt, video_id, result["thumbnail"])
        except Exception as e:  # noqa: BLE001
            if "uploadLimitExceeded" in str(e) or "exceeded the number of videos" in str(e):
                # YouTube's own per-channel daily cap. Keep the idea untouched and stop for this run.
                note = "YouTube's daily upload limit for this channel is reached; the remaining ideas stay queued for the next run"
                print(f"[run] {note}")
                if probe_index == i:
                    lim = load_limits(cfg)
                    lim["last_probe"] = dt.datetime.now(dt.timezone.utc).isoformat(timespec="seconds")
                    lim.setdefault("history", []).append({"at": lim["last_probe"], "tried": lim["daily_limit"] + 1, "accepted": False})
                    save_limits(lim)
                    print(f"[run] probe result: YouTube still limits this channel to {lim['daily_limit']} uploads per 24 h")
                summaries.append({"id": pkg["id"], "title": pkg["title"], "status": "not uploaded: YouTube daily upload limit reached"})
                limit_hit = True
                break
            traceback.print_exc()
            failures += 1
            summaries.append({"id": pkg["id"], "title": pkg["title"], "status": f"upload failed: {type(e).__name__}: {e}"[:300]})
            if path.parent == QUEUE_DIR:
                _note_attempt(path, pkg, str(e))
            continue

        if probe_index == i:
            lim = load_limits(cfg)
            lim["daily_limit"] = int(lim["daily_limit"]) + 1
            lim["last_probe"] = dt.datetime.now(dt.timezone.utc).isoformat(timespec="seconds")
            lim.setdefault("history", []).append({"at": lim["last_probe"], "tried": lim["daily_limit"], "accepted": True})
            save_limits(lim)
            print(f"[run] probe result: YouTube accepted an extra upload -> daily limit raised to {lim['daily_limit']}")
            summaries.append({"status": f"LIMIT RAISED: YouTube now allows {lim['daily_limit']} uploads per 24 h", "title": pkg["title"]})
        pkg.pop("_attempts", None)
        pkg["youtube_id"] = video_id
        pkg["url"] = f"https://youtube.com/shorts/{video_id}"
        pkg["uploaded_at"] = dt.datetime.now(dt.timezone.utc).isoformat(timespec="seconds")
        pkg["privacy_requested"] = body["status"]["privacyStatus"]
        pkg["publish_at"] = slots[i]
        pkg["tts_engine"] = result["tts_engine"]
        pkg["duration_seconds"] = round(result["duration"], 1)
        pkg["style"] = style
        PUBLISHED_DIR.mkdir(parents=True, exist_ok=True)
        _save(PUBLISHED_DIR / path.name, pkg)
        if path.parent == QUEUE_DIR:
            path.unlink()
        summary.update({"status": "uploaded", "url": pkg["url"], "goes_public_at": slots[i] or "immediately"})
        summaries.append(summary)
        shutil.rmtree(outdir / "clips", ignore_errors=True)  # keep the runner's disk small
        shutil.rmtree(outdir / "tts", ignore_errors=True)

    _write_summary(summaries, failures, note="YouTube daily upload limit reached" if limit_hit else None)
    if yt and not args.no_stats and summaries:
        try:
            from .stats import update_stats
            data = update_stats(yt)
            print(f"[run] stats refreshed: {data['total_videos']} videos, {data['total_views']} views total")
        except Exception as e:  # noqa: BLE001
            print(f"[run] stats refresh failed (non-fatal): {e}")
    done = len([s for s in summaries if s.get("status", "").startswith(("uploaded", "rendered"))])
    print(f"\n[run] finished: {done} video(s) done, {failures} failed")
    if failures:
        return 1
    if limit_hit:
        return 0  # YouTube's cap is not an error; the ideas wait for the next run
    return 0 if done else 3


def _write_summary(summaries: list[dict], failures: int, error: str | None = None, note: str | None = None) -> None:
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    data = {"videos": summaries, "failed": failures}
    if error:
        data["error"] = error
    if note:
        data["note"] = note
    (OUTPUT_DIR / "summary.json").write_text(json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8")


if __name__ == "__main__":
    sys.exit(main())
