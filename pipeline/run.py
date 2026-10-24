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
import math
import os
import shutil
import subprocess
import sys
import time
import traceback
from pathlib import Path

from . import tts as tts_mod
from .captions import build_ass
from .config import (FAILED_DIR, LONGFORM_FAILED_DIR, LONGFORM_QUEUE_DIR, OUTPUT_DIR, PUBLISHED_DIR, QUEUE_DIR,
                     ensure_dirs, load_config)
from .render import assemble_voice, concat_clips, make_thumbnail, pick_music, render_final
from .validate import is_longform, validate_longform, validate_package
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
    """Uploads allowed per rolling 24 h: YouTube's known cap, or a lower `release.videos_per_day` if set."""
    cap = int(load_limits(cfg).get("daily_limit", 0) or 0)
    target = cfg.get("release.videos_per_day")
    if target:
        cap = min(cap, int(target)) if cap > 0 else int(target)
    return cap


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
    failed_dir = LONGFORM_FAILED_DIR if path.parent == LONGFORM_QUEUE_DIR else FAILED_DIR
    failed_dir.mkdir(parents=True, exist_ok=True)
    _save(failed_dir / path.name, pkg)
    path.unlink(missing_ok=True)
    print(f"[run] moved {path.name} to {failed_dir.relative_to(failed_dir.parent.parent)}: {reason}")


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


def package_format(pkg: dict) -> str:
    return str(pkg.get("format") or "fact").lower()


def is_ranking(pkg: dict) -> bool:
    return package_format(pkg) == "ranking"


def preferred_format(cfg) -> str | None:
    """`release.format_mix: {ranking: 3, fact: 1}` → look at the last (3+1) published videos and pick the format
    that is still owed in that window; None when no mix is configured."""
    mix = cfg.get("release.format_mix") or {}
    try:
        mix = {str(k).lower(): int(v) for k, v in dict(mix).items() if int(v) > 0}
    except (TypeError, ValueError, AttributeError):
        return None
    if not mix:
        return None
    window = sum(mix.values())
    # Order by the recorded upload time, not file mtime: on a fresh CI checkout every file has the same mtime.
    recs = []
    for path in PUBLISHED_DIR.glob("*.json"):
        try:
            rec = _load(path)
        except Exception:  # noqa: BLE001
            continue
        if rec.get("kind") == "longform":
            continue
        recs.append((str(rec.get("uploaded_at") or rec.get("publish_at") or ""), path.name, package_format(rec)))
    recs.sort(reverse=True)
    recent = [fmt for _, _, fmt in recs[:window]]
    counts = {f: recent.count(f) for f in mix}
    # the format with the biggest shortfall against its share goes next (ties: the first listed)
    owed = sorted(mix, key=lambda f: (counts[f] - mix[f], list(mix).index(f)))
    return owed[0]


def pick_package(cfg, explicit: Path | None, skip: set[str]) -> tuple[Path, dict] | None:
    if explicit:
        pkg = _load(explicit)
        errs = validate_longform(pkg, cfg) if is_longform(pkg) else validate_package(pkg, cfg)
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
    only = [str(t).lower() for t in (cfg.get("release.only_topics") or [])]
    want = preferred_format(cfg)
    ordered = sorted(candidates, key=lambda c: (c[0], c[1]))
    if want and any(package_format(c[3]) == want for c in ordered):
        ordered = [c for c in ordered if package_format(c[3]) == want] + [c for c in ordered if package_format(c[3]) != want]
    for _, _, path, pkg in ordered:
        if only and str(pkg.get("topic", "")).lower() not in only:
            continue   # temporarily restricted to the topics that still get distribution
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


def pick_longform(cfg, skip: set[str]) -> tuple[Path, dict] | None:
    """The next valid long-form package (highest priority, then oldest), or None."""
    candidates = []
    for path in sorted(LONGFORM_QUEUE_DIR.glob("*.json")):
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
        errs = validate_longform(pkg, cfg)
        if errs:
            _fail(path, pkg, "; ".join(errs))
            continue
        if (PUBLISHED_DIR / path.name).exists():
            print(f"[run] {path.name} is already published; removing it from the long-form queue")
            path.unlink()
            continue
        return path, pkg
    return None


def longform_due(cfg, claimed: list[str]) -> str | None:
    """The long video's publish time if one should be made now: the next free long-form slot is
    less than `longform.build_hours_ahead` hours away (so exactly one long video per slot)."""
    if not cfg.get("longform.enabled", False) or not cfg.get("release.longform_slots"):
        return None
    slot = release_slot(cfg, claimed, kind="longform")
    if not slot:
        return None
    try:
        when = dt.datetime.fromisoformat(slot.replace("Z", "+00:00"))
    except ValueError:
        return None
    ahead = float(cfg.get("longform.build_hours_ahead", 24))
    if when - dt.datetime.now(dt.timezone.utc) <= dt.timedelta(hours=ahead):
        return slot
    return None


def day_number(cfg, when: dt.datetime | None = None) -> int:
    """Day N of the channel's streak, counted from the first upload. A "day" runs 6 AM to 6 AM in the
    release timezone, so the whole 8 PM-5 AM release window carries one number."""
    from zoneinfo import ZoneInfo
    tz = ZoneInfo(cfg.get("release.timezone", "UTC"))
    shift = dt.timedelta(hours=6)

    def _day(t: dt.datetime) -> dt.date:
        return (t.astimezone(tz) - shift).date()

    first = None
    for f in PUBLISHED_DIR.glob("*.json"):
        try:
            t = json.loads(f.read_text(encoding="utf-8")).get("uploaded_at")
            if t:
                d = _day(dt.datetime.fromisoformat(t.replace("Z", "+00:00")))
                first = d if first is None or d < first else first
        except Exception:  # noqa: BLE001
            continue
    today = _day(when or dt.datetime.now(dt.timezone.utc))
    return 1 if first is None else max(1, (today - first).days + 1)


def first_comment_text(pkg: dict, cfg) -> str:
    """The channel's own first comment: the package's `first_comment`, else the question that ends the description."""
    text = (pkg.get("first_comment") or "").strip()
    if not text:
        lines = [ln.strip() for ln in (pkg.get("description") or "").splitlines() if ln.strip()]
        if lines and lines[-1].endswith("?"):
            text = lines[-1]
    if not text:
        text = cfg.get("cta.first_comment") or "Which fact should we cover next? 👇"
    suffix = (cfg.get("cta.first_comment_suffix") or "").strip()   # e.g. a line pointing at the sister channel
    if suffix and suffix not in text:
        text = f"{text}\n\n{suffix}"
    return text


MAX_FIRST_COMMENTS_PER_RUN = 4   # clears any backlog gently instead of posting 20 comments in a minute
FIRST_COMMENT_ATTEMPTS = 3


def post_pending_first_comments(youtube, cfg) -> tuple[int, str | None]:
    """Post the first comment on published videos that are public now and have none yet.

    Returns (how many were posted, a note for the run summary or None).
    """
    from .upload import CommentPermissionError, can_comment, post_comment
    if can_comment(youtube) is False:
        return 0, ("first comment skipped: the YouTube key has no comment permission - run "
                   "`python -m pipeline.authorize client_secret.json` again and replace YT_REFRESH_TOKEN")
    now = dt.datetime.now(dt.timezone.utc)
    posted = 0
    for f in sorted(PUBLISHED_DIR.glob("*.json"), reverse=True):   # newest videos first
        if posted >= MAX_FIRST_COMMENTS_PER_RUN:
            break
        try:
            pkg = json.loads(f.read_text(encoding="utf-8"))
        except Exception:  # noqa: BLE001
            continue
        vid = pkg.get("youtube_id")
        if not vid or pkg.get("first_comment_id") or int(pkg.get("first_comment_attempts", 0)) >= FIRST_COMMENT_ATTEMPTS:
            continue
        pub = pkg.get("publish_at") or pkg.get("uploaded_at") or ""
        try:
            when = dt.datetime.fromisoformat(pub.replace("Z", "+00:00"))
        except Exception:  # noqa: BLE001
            continue
        if when > now - dt.timedelta(minutes=2):
            continue  # not public yet; the next run gets it
        try:
            cid = post_comment(youtube, vid, first_comment_text(pkg, cfg))
        except CommentPermissionError as e:
            return posted, f"first comment skipped: {e}"
        if cid:
            pkg["first_comment_id"] = cid
            pkg["first_comment_at"] = now.isoformat(timespec="seconds")
            posted += 1
        else:
            pkg["first_comment_attempts"] = int(pkg.get("first_comment_attempts", 0)) + 1
        _save(f, pkg)
    return posted, None


def try_first_comment_now(youtube, cfg, pkg: dict) -> bool:
    """Right after an upload, try to leave the first comment already (works if YouTube lets the owner
    comment on a scheduled video). If it does not, the regular pass posts it once the video is public."""
    from .upload import CommentPermissionError, can_comment, post_comment
    if can_comment(youtube) is False:
        return False
    try:
        cid = post_comment(youtube, pkg["youtube_id"], first_comment_text(pkg, cfg))
    except CommentPermissionError:
        return False
    if cid:
        pkg["first_comment_id"] = cid
        pkg["first_comment_at"] = dt.datetime.now(dt.timezone.utc).isoformat(timespec="seconds")
        return True
    return False


def release_slot(cfg, extra_taken: list[str], kind: str = "shorts") -> str | None:
    """The next free publish time for this kind of video, skipping slots claimed earlier in this run."""
    from .upload import publish_slots, taken_release_times
    taken = taken_release_times(PUBLISHED_DIR)
    for t in extra_taken:
        try:
            taken.append(dt.datetime.fromisoformat(t.replace("Z", "+00:00")))
        except ValueError:
            pass
    chosen = publish_slots(1, cfg, taken=taken, kind=kind)
    if not chosen:
        return None
    # Never let a finished video wait most of a day for its slot: if the next free time is far away,
    # publish it shortly after the upload instead (the slot list stays the normal rhythm).
    max_wait = float(cfg.get("release.max_wait_hours", 10))
    now = dt.datetime.now(dt.timezone.utc)
    try:
        when = dt.datetime.fromisoformat(chosen[0].replace("Z", "+00:00"))
    except ValueError:
        return chosen[0]
    if kind == "shorts" and when - now > dt.timedelta(hours=max_wait):   # long videos keep their one-a-day slot
        soon = now + dt.timedelta(minutes=int(cfg.get("release.lead_minutes", 20)) + 5)
        soon = soon.replace(second=0, microsecond=0) + dt.timedelta(minutes=(10 - soon.minute % 10) % 10)
        # Never land on (or within 20 min of) a time another video already has: two Shorts going public
        # in the same minute split one test audience (22 Oct: two videos both at 02:30 IST).
        for _ in range(12):
            if not any(abs(soon - t) < dt.timedelta(minutes=20) for t in taken):
                break
            soon += dt.timedelta(minutes=20)
        return soon.strftime("%Y-%m-%dT%H:%M:%SZ")
    return chosen[0]


def topic_look(cfg, pkg: dict):
    """Config re-coloured and re-voiced for this video's topic (see `looks` in channel.yml), plus the voice used."""
    from .config import with_overrides
    topic = (pkg.get("topic") or "").lower()
    looks = cfg.get("looks") or {}
    look = dict(looks.get("default") or {})
    look.update(looks.get(topic) or {})
    over = {}
    if look.get("highlight_color"):
        over["captions.highlight_color"] = look["highlight_color"]
    if look.get("zoom") is not None:
        over["video.zoom"] = float(look["zoom"])
    voice = pkg.get("voice") or look.get("voice") or cfg.get("voice.edge_voice")
    return (with_overrides(cfg, over) if over else cfg), voice


def plan_clips(durations: list[float], keywords: list[str], cfg) -> list[tuple[str, float, bool]]:
    """Split each scene into 1-3 clips (target `video.seconds_per_clip`), every clip a whole number of
    frames and never shorter than the voice. Returns [(keywords, seconds, energetic_first_clip), ...]."""
    fps = int(cfg.get("video.fps", 30))
    target = float(cfg.get("video.seconds_per_clip", 2.8))
    max_clips = int(cfg.get("video.max_clips_per_scene", 3))
    plan: list[tuple[str, float, bool]] = []
    for i, (kw, d) in enumerate(zip(keywords, durations)):
        n = max(1, min(max_clips, int(round(d / target))))
        frames = math.ceil(d * fps)
        base, extra = divmod(frames, n)
        for j in range(n):
            part = (base + (1 if j < extra else 0)) / fps
            plan.append((kw, part, i == 0 and j == 0))
    return plan


def build_video(pkg: dict, cfg, outdir: Path, style: str = "classic", publish_at: str | None = None) -> dict:
    """Render everything for one package into outdir. Returns file paths and details.

    style "classic": word-by-word captions from the first word, spoken call-to-action at the end.
    style "punch":   the whole hook sentence on screen for the first scene, no spoken call-to-action,
                     a small "follow" label in the last second (ends on the punchline so it loops).
    """
    outdir.mkdir(parents=True, exist_ok=True)
    cfg, voice = topic_look(cfg, pkg)
    scenes = [s["text"] for s in pkg["scenes"]]
    keywords = [s["keywords"] for s in pkg["scenes"]]
    cta = pkg.get("cta") if "cta" in pkg else cfg.get("cta.text", "")
    if style != "punch" and cfg.get("cta.spoken", True) and cta:
        scenes.append(cta)
        keywords.append(keywords[-1])

    print(f"[run] voice: {len(scenes)} scenes ({voice})")
    audio, engine = tts_mod.synthesize(scenes, cfg, outdir / "tts", voice=voice)
    gap = float(cfg.get("video.gap_seconds", 0.25))
    durations, words = assemble_voice(audio, gap, outdir / "voice.wav")
    total_est = sum(durations)
    max_s = float(cfg.get("video.max_seconds", 58))
    if total_est > max_s + 2:
        raise RuntimeError(f"narration is {total_est:.1f}s, longer than the {max_s:.0f}s limit; shorten the script")

    providers = [n for n, k in (("pixabay", os.environ.get("PIXABAY_API_KEY")), ("pexels", cfg.pexels_key)) if k]
    print(f"[run] visuals: {', '.join(providers) if providers else 'no footage key set - animated backgrounds'}")
    # Drawn mode keeps every picture on the same subject: the package's `subject` if the writer gave one,
    # else the first two words of the hook's footage keywords ("pelican diving").
    subject = (pkg.get("subject") or " ".join(str(pkg["scenes"][0].get("keywords", "")).split()[:2])).strip()
    if is_ranking(pkg):
        subject = ""   # a ranking shows five different animals: every scene's own keywords drive its picture
    vis = Visuals(cfg, outdir / "clips", seed=pkg["id"], topic=pkg.get("topic", ""), subject=subject)
    # Faster cuts: a scene longer than a few seconds is covered by 2-3 different clips of the same
    # search, each a whole number of frames so the picture never drifts from the voice.
    plan = plan_clips(durations, keywords, cfg)
    clips = [vis.scene_clip(k, kw, d, energetic=en) for k, (kw, d, en) in enumerate(plan)]
    vis.save_credits(outdir / "footage_credits.json")
    visual = outdir / "visual.mp4"
    total = concat_clips(clips, visual)

    label = None
    if cfg.get("captions.show_top_label", True):
        if cfg.get("captions.day_counter", True):
            when = None
            if publish_at:
                try:
                    when = dt.datetime.fromisoformat(publish_at.replace("Z", "+00:00"))
                except ValueError:
                    when = None
            label = f"Day {day_number(cfg, when)}  •  {pkg.get('topic', '')}".strip(" •")
        else:
            label = f"{cfg.get('channel.name', '')}  •  {pkg.get('topic', '')}".strip(" •")
        if is_ranking(pkg) and pkg.get("ranking_by"):
            label = f"Ranked by {pkg['ranking_by']}"
    # The first-second promise: the headline (thumbnail_text, 3-7 words) pops in at the top third.
    # "punch" keeps it up for the whole first scene instead of word captions; "classic" shows it for
    # ~1.5 s over the word captions.
    headline = (pkg.get("thumbnail_text") or " ".join(pkg["scenes"][0]["text"].split()[:6])).strip()
    use_card = bool(cfg.get("captions.title_card", True)) and headline
    hook_card = pkg["scenes"][0]["text"] if (style == "punch" and not use_card) else None
    title_end = 0.0
    if use_card:
        title_end = durations[0] if style == "punch" else min(float(cfg.get("captions.title_seconds", 1.5)), durations[0])
    end_text = (cfg.get("cta.end_text") or "Follow for more") if style == "punch" else None
    words_for_captions = words[1:] if (style == "punch" and use_card) else words
    # Ranking videos: a "#5" badge for the whole scene of each rank (scene timings from the voice track).
    ranks: list[tuple[float, float, int, str]] = []
    t_cursor = 0.0
    for k, sc in enumerate(pkg["scenes"]):
        d = durations[k] if k < len(durations) else 0.0
        if isinstance(sc, dict) and sc.get("rank") is not None:
            ranks.append((t_cursor, t_cursor + d, int(sc["rank"]), str(sc.get("label") or "")))
        t_cursor += d
    ass = build_ass(words_for_captions, cfg, outdir / "captions.ass", label, total,
                    hook_card=hook_card, hook_end=durations[0], end_text=end_text,
                    title_card=headline if use_card else None, title_end=title_end, ranks=ranks or None)

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
    footage["animated-background"] = max(0, len(clips) - len(vis.credits))
    footage["look"] = "drawn" if vis.drawn else "footage"
    if vis.draw_errors:
        footage["drawing_errors"] = f"{len(vis.draw_errors)}: " + "; ".join(sorted(set(vis.draw_errors))[:3])[:300]
    return {"video": final, "thumbnail": thumb, "duration": total, "tts_engine": engine, "voice": voice,
            "highlight_color": cfg.get("captions.highlight_color"),
            "words": sum(len(w) for w in words), "footage": footage, "style": style}


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--dry-run", action="store_true", help="render only; do not upload or change the queue")
    ap.add_argument("--count", type=int, help="how many videos to make this run (default: release.videos_per_run)")
    ap.add_argument("--package", type=Path, help="render this package first instead of the oldest queued one")
    ap.add_argument("--no-stats", action="store_true", help="skip refreshing content/stats.json")
    ap.add_argument("--now", action="store_true", help="publish immediately instead of scheduling into the release window")
    args = ap.parse_args(argv)

    ensure_dirs()
    cfg = load_config()
    per_run = int(cfg.get("release.videos_per_run", 1))
    count = args.count or (1 if args.dry_run else per_run)
    cap = daily_cap(cfg)
    probe_index = None
    if args.count is None and not args.dry_run and cap > 0:
        # Catch-up: if YouTube's 24 h window has much more room than usual (two earlier runs were
        # blocked or failed), make one extra video this run so the day still reaches the daily total.
        # One missed run is left alone: with a run before every release time, catching up on a single
        # free place would put two videos in one run and shift the whole rhythm.
        free_now = max(0, cap - len(recent_upload_times(24.0)))
        if free_now >= per_run + 2:
            count = per_run + 1
            print(f"[run] {free_now} upload slots free in YouTube's 24 h window -> making {count} videos this run")
        elif free_now == 0 and should_probe(cfg):
            # Weekly probe: the window is full by our count; try ONE extra upload to learn whether
            # YouTube has raised this channel's limit. Refusal costs nothing but a render.
            probe_index = 0
            count = 1
            print(f"[run] weekly limit probe: trying one upload beyond the known limit of {cap}")
    count = max(1, count)

    yt = None
    notes: list[str] = []
    if not args.dry_run:
        from .upload import youtube_client
        try:
            yt = youtube_client(cfg)
        except Exception as e:  # noqa: BLE001
            msg = f"could not sign in to YouTube: {type(e).__name__}: {e}"
            print(f"[run] {msg}")
            _write_summary([], 1, error=msg)
            return 2
        if cfg.get("cta.first_comment_enabled", True):
            try:
                n, note = post_pending_first_comments(yt, cfg)
                if n:
                    print(f"[run] posted the first comment on {n} video(s)")
                if note:
                    print(f"[run] {note}")
                    notes.append(note)
            except Exception as e:  # noqa: BLE001
                print(f"[run] first-comment pass failed (non-fatal): {e}")

    summaries: list[dict] = []
    tried: set[str] = set()
    failures = 0
    limit_hit = False
    claimed: list[str] = []   # publish times handed out in this run
    for i in range(count):
        kind = "shorts"
        picked = None
        long_slot = None
        if args.package and i == 0:
            picked = pick_package(cfg, args.package, tried)
            if picked and is_longform(picked[1]):
                kind = "longform"
        else:
            if not args.dry_run and not args.now:
                long_slot = longform_due(cfg, claimed)
                if long_slot:
                    picked = pick_longform(cfg, tried)
                    if picked:
                        kind = "longform"
                    else:
                        print("[run] a long video is due but content/longform/queue is empty - making a Short instead")
            if not picked:
                picked = pick_package(cfg, None, tried)
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
        print(f"\n[run] ({i + 1}/{count}) {path.name}  title: {pkg['title']}" + ("  [LONG VIDEO]" if kind == "longform" else ""))

        outdir = OUTPUT_DIR / pkg["id"]
        if outdir.exists():
            shutil.rmtree(outdir)
        if kind == "longform":
            style = "longform"
            slot = None if (args.dry_run or args.now) else (long_slot or release_slot(cfg, claimed, kind="longform"))
        else:
            style = pkg.get("style")
            if style not in ("classic", "punch"):
                if cfg.get("experiment.alternate_styles", False):
                    # Keep the A/B test balanced: this video gets the style with fewer published Shorts so far
                    # (parity on the record count flipped by two per run and froze on one style).
                    counts = {"classic": 0, "punch": 0}
                    for f in PUBLISHED_DIR.glob("*.json"):
                        try:
                            st = json.loads(f.read_text(encoding="utf-8")).get("style")
                        except Exception:  # noqa: BLE001
                            continue
                        if st in counts:
                            counts[st] += 1
                    style = "classic" if counts["classic"] <= counts["punch"] else "punch"
                else:
                    style = cfg.get("video.style", "classic")
            slot = None if (args.dry_run or args.now) else release_slot(cfg, claimed)
        print(f"[run] style: {style}")
        try:
            if kind == "longform":
                from .longform import build_longform
                result = build_longform(pkg, cfg, outdir, publish_at=slot)
            else:
                result = build_video(pkg, cfg, outdir, style=style, publish_at=slot)
        except Exception as e:  # noqa: BLE001
            traceback.print_exc()
            failures += 1
            summaries.append({"id": pkg["id"], "title": pkg["title"], "status": f"render failed: {type(e).__name__}: {e}"[:300]})
            if not args.dry_run and path.parent in (QUEUE_DIR, LONGFORM_QUEUE_DIR):
                _note_attempt(path, pkg, str(e))
            continue

        summary = {"id": pkg["id"], "title": pkg["title"], "duration_seconds": round(result["duration"], 1),
                   "voice": result["tts_engine"], "footage": result["footage"], "style": style, "kind": kind}
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
        if slot and not args.now:
            # Re-pick the slot if the wait pushed us too close to it (publish times must stay in the future).
            try:
                lead = dt.timedelta(minutes=max(5, int(cfg.get("release.lead_minutes", 20)) // 2))
                if dt.datetime.fromisoformat(slot.replace("Z", "+00:00")) < dt.datetime.now(dt.timezone.utc) + lead:
                    slot = release_slot(cfg, claimed, kind=kind)
            except ValueError:
                slot = release_slot(cfg, claimed, kind=kind)
        try:
            body = build_body(pkg, cfg, slot, shorts=(kind != "longform"))
            video_id = upload_video(yt, result["video"], body)
            print(f"[run] uploaded: https://youtube.com/shorts/{video_id}  "
                  f"({'goes public at ' + slot if slot else body['status']['privacyStatus']})")
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
            if path.parent in (QUEUE_DIR, LONGFORM_QUEUE_DIR):
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
        pkg["url"] = f"https://youtube.com/shorts/{video_id}" if kind == "shorts" else f"https://youtu.be/{video_id}"
        pkg["uploaded_at"] = dt.datetime.now(dt.timezone.utc).isoformat(timespec="seconds")
        pkg["privacy_requested"] = body["status"]["privacyStatus"]
        pkg["publish_at"] = slot
        if slot:
            claimed.append(slot)
        pkg["tts_engine"] = result["tts_engine"]
        pkg["voice_used"] = result.get("voice")
        pkg["highlight_color"] = result.get("highlight_color")
        pkg["duration_seconds"] = round(result["duration"], 1)
        pkg["style"] = style
        pkg["kind"] = kind
        try:
            from .facebook import crosspost, enabled as fb_enabled
            if fb_enabled(cfg):
                fb = crosspost(pkg, cfg, result["video"], kind, slot)
                if fb:
                    pkg.update(fb)
                    summary["facebook"] = fb["facebook_url"]
                else:
                    pkg["facebook_failed_at"] = dt.datetime.now(dt.timezone.utc).isoformat(timespec="seconds")
                    summary["facebook"] = "failed (see log)"
        except Exception as e:  # noqa: BLE001
            print(f"[facebook] skipped: {type(e).__name__}: {e}")
        if cfg.get("cta.first_comment_enabled", True):
            try:
                if try_first_comment_now(yt, cfg, pkg):
                    print("[run] first comment posted")
            except Exception as e:  # noqa: BLE001
                print(f"[run] first comment not posted yet ({type(e).__name__}); the next run will do it once the video is public")
        PUBLISHED_DIR.mkdir(parents=True, exist_ok=True)
        _save(PUBLISHED_DIR / path.name, pkg)
        if path.parent in (QUEUE_DIR, LONGFORM_QUEUE_DIR):
            path.unlink()
        summary.update({"status": "uploaded", "url": (pkg["url"] if kind == "shorts" else f"https://youtu.be/{video_id}"),
                        "goes_public_at": slot or "immediately"})
        summaries.append(summary)
        shutil.rmtree(outdir / "clips", ignore_errors=True)  # keep the runner's disk small
        shutil.rmtree(outdir / "tts", ignore_errors=True)

    if limit_hit:
        notes.append("YouTube daily upload limit reached")
    _write_summary(summaries, failures, note="; ".join(notes) if notes else None)
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
