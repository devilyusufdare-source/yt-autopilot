"""Validate a content package (content/queue/*.json) before it is rendered.

Usage:  python -m pipeline.validate content/queue/2026-10-15-doorway-effect.json [...]
        python -m pipeline.validate content/longform/queue/2026-10-17-space-facts.json   (long videos too)
Exit code 0 = all valid.
"""
from __future__ import annotations

import json
import re
import sys
from pathlib import Path

from .config import load_config

ID_RE = re.compile(r"^[0-9]{4}-[0-9]{2}-[0-9]{2}-[a-z0-9-]{3,60}$")
HASHTAG_RE = re.compile(r"^#[A-Za-z0-9_]+$")
WORDS_PER_SECOND = 2.6  # typical neural-voice pace at +10% rate


def _tag_char_count(tags: list[str]) -> int:
    """YouTube counts commas, and wraps multi-word tags in quotes, towards the 500-char limit."""
    total = 0
    for i, t in enumerate(tags):
        total += len(t) + (2 if " " in t else 0)
        if i:
            total += 1
    return total


def estimate_seconds(pkg: dict, cfg=None) -> float:
    cfg = cfg or load_config()
    words = sum(len(s["text"].split()) for s in pkg.get("scenes", []))
    cta = pkg.get("cta", cfg.get("cta.text", "")) if cfg.get("cta.spoken", True) else ""
    words += len((cta or "").split())
    gap = float(cfg.get("video.gap_seconds", 0.25))
    return words / WORDS_PER_SECOND + gap * (len(pkg.get("scenes", [])) + 1) + 0.6


def validate_package(pkg: dict, cfg=None) -> list[str]:
    """Return a list of problems (empty list = valid)."""
    cfg = cfg or load_config()
    errs: list[str] = []

    for key in ("id", "topic", "title", "scenes", "description", "tags"):
        if key not in pkg:
            errs.append(f"missing required field '{key}'")
    if errs:
        return errs

    if not isinstance(pkg["id"], str) or not ID_RE.match(pkg["id"]):
        errs.append("id must look like 2026-10-15-some-slug (date + lowercase slug)")

    title = pkg["title"]
    if not isinstance(title, str) or not (10 <= len(title) <= 100):
        errs.append("title must be 10-100 characters")
    elif "<" in title or ">" in title:
        errs.append("title must not contain < or >")

    scenes = pkg["scenes"]
    if not isinstance(scenes, list) or not (3 <= len(scenes) <= 10):
        errs.append("scenes must be a list of 3-10 items")
    else:
        for i, s in enumerate(scenes, 1):
            if not isinstance(s, dict) or "text" not in s or "keywords" not in s:
                errs.append(f"scene {i}: needs 'text' and 'keywords'")
                continue
            if not (4 <= len(s["text"].strip()) <= 220):
                errs.append(f"scene {i}: text must be 4-220 characters")
            if not (2 <= len(s["keywords"].strip()) <= 60):
                errs.append(f"scene {i}: keywords must be 2-60 characters")
            if "<" in s["text"] or ">" in s["text"]:
                errs.append(f"scene {i}: text must not contain < or >")
        if str(pkg.get("format") or "").lower() == "ranking":
            ranked = [s for s in scenes if isinstance(s, dict) and s.get("rank") is not None]
            order = [int(s["rank"]) for s in ranked if str(s.get("rank")).lstrip("-").isdigit()]
            if order != [5, 4, 3, 2, 1]:
                errs.append("ranking: exactly five scenes must carry rank 5,4,3,2,1 in that order (plus a hook scene before them)")
            if not scenes or not isinstance(scenes[0], dict) or scenes[0].get("rank") is not None:
                errs.append("ranking: scene 1 is the hook and must not carry a rank")
            for s in ranked:
                if not str(s.get("label") or "").strip() or len(str(s.get("label"))) > 32:
                    errs.append(f"ranking: rank {s.get('rank')} needs a short 'label' (name + number, under 32 characters)")
            if not str(pkg.get("ranking_by") or "").strip():
                errs.append("ranking: 'ranking_by' (the one metric the list is ranked by) is required")
            if len(pkg.get("sources") or []) < 2:
                errs.append("ranking: at least 2 sources")
        hook_words = len(scenes[0].get("text", "").split()) if scenes and isinstance(scenes[0], dict) else 0
        if hook_words > 18:
            errs.append("scene 1 is the hook: keep it under 18 words")
        total_words = sum(len(s.get("text", "").split()) for s in scenes if isinstance(s, dict))
        if total_words < 40:
            errs.append(f"script too short ({total_words} words); aim for 60-85")
        if total_words > 135:
            errs.append(f"script too long ({total_words} words); aim for 60-85 so the video stays under ~32 seconds")
        est = estimate_seconds(pkg, cfg)
        if est > float(cfg.get("video.max_seconds", 58)):
            errs.append(f"script too long: ~{est:.0f}s estimated, max {cfg.get('video.max_seconds', 58)}s (cut words)")

    desc = pkg["description"]
    if not isinstance(desc, str) or not (20 <= len(desc) <= 3000):
        errs.append("description must be 20-3000 characters")

    tags = pkg["tags"]
    if not isinstance(tags, list) or not (5 <= len(tags) <= 20) or not all(isinstance(t, str) for t in tags):
        errs.append("tags must be a list of 5-20 strings")
    else:
        for t in tags:
            if not (2 <= len(t) <= 30):
                errs.append(f"tag '{t}' must be 2-30 characters")
            if "<" in t or ">" in t:
                errs.append(f"tag '{t}' must not contain < or >")
        if _tag_char_count(tags) > 480:
            errs.append("tags are too long in total (keep under 480 characters including commas)")

    for h in pkg.get("hashtags", []) or []:
        if not HASHTAG_RE.match(h):
            errs.append(f"hashtag '{h}' must look like #Word")
    if len(pkg.get("hashtags", []) or []) > 6:
        errs.append("use at most 6 hashtags")

    for u in pkg.get("sources", []) or []:
        if not isinstance(u, str) or not u.startswith("http"):
            errs.append(f"source '{u}' must be a URL")

    if pkg.get("privacy") not in (None, "public", "unlisted", "private"):
        errs.append("privacy must be public, unlisted or private")

    return errs


def _words(text: str) -> int:
    return len((text or "").split())


def is_longform(pkg: dict) -> bool:
    return pkg.get("kind") == "longform" or "segments" in pkg


LONGFORM_WORDS_PER_SECOND = 2.85  # measured: Andrew at the natural rate (+0%) in the first long video


def estimate_longform_seconds(pkg: dict, cfg=None) -> float:
    cfg = cfg or load_config()
    words = _words(pkg.get("intro", "")) + _words(pkg.get("outro", "")) + sum(_words(s.get("text", "")) for s in pkg.get("segments", []) if isinstance(s, dict))
    gap = float((cfg.get("longform") or {}).get("gap_seconds", 0.7))
    return words / LONGFORM_WORDS_PER_SECOND + gap * (len(pkg.get("segments", [])) + 2) + 1.0


def validate_longform(pkg: dict, cfg=None) -> list[str]:
    """Rules for content/longform/queue/*.json (a long 16:9 video). Empty list = valid."""
    cfg = cfg or load_config()
    lf = cfg.get("longform") or {}
    errs: list[str] = []
    for key in ("id", "title", "theme", "intro", "segments", "outro", "description", "tags"):
        if key not in pkg:
            errs.append(f"missing required field '{key}'")
    if errs:
        return errs
    if not isinstance(pkg["id"], str) or not ID_RE.match(pkg["id"]):
        errs.append("id must look like 2026-10-17-some-slug (date + lowercase slug)")
    title = pkg["title"]
    if not isinstance(title, str) or not (15 <= len(title) <= 100):
        errs.append("title must be 15-100 characters")
    elif "<" in title or ">" in title:
        errs.append("title must not contain < or >")
    if not (24 <= _words(pkg["intro"]) <= 60):
        errs.append(f"intro must be 24-60 words (is {_words(pkg['intro'])}); it is also the first chapter, which must last 10+ seconds")
    if not (15 <= _words(pkg["outro"]) <= 60):
        errs.append(f"outro must be 15-60 words (is {_words(pkg['outro'])})")
    segs = pkg["segments"]
    lo, hi = int(lf.get("min_segments", 8)), int(lf.get("max_segments", 12))
    if not isinstance(segs, list) or not (lo <= len(segs) <= hi):
        errs.append(f"segments must be a list of {lo}-{hi} facts")
    else:
        total = 0
        for i, sg in enumerate(segs, 1):
            if not isinstance(sg, dict) or not all(k in sg for k in ("heading", "text", "keywords")):
                errs.append(f"segment {i}: needs 'heading', 'text' and 'keywords'")
                continue
            if not (3 <= len(sg["heading"]) <= 60):
                errs.append(f"segment {i}: heading must be 3-60 characters")
            n = _words(sg["text"])
            total += n
            if not (90 <= n <= 175):
                errs.append(f"segment {i}: text must be 90-175 words (is {n}); about 30-60 seconds spoken")
            if "<" in sg["text"] or ">" in sg["text"]:
                errs.append(f"segment {i}: text must not contain < or >")
            kws = sg["keywords"]
            kw_list = kws if isinstance(kws, list) else [k for k in str(kws).split("|")]
            if not (2 <= len(kw_list) <= 3) or not all(2 <= len(str(k).strip()) <= 60 for k in kw_list):
                errs.append(f"segment {i}: keywords must be 2-3 footage searches, each 2-60 characters (a list, or separated by |)")
            srcs = sg.get("sources") or []
            if not srcs or not all(isinstance(u, str) and u.startswith("http") for u in srcs):
                errs.append(f"segment {i}: needs at least one source URL")
        if total and not (1150 <= total <= 1900):
            errs.append(f"segments total {total} words; aim for 1,300-1,600 (9-10 minutes)")
        est = estimate_longform_seconds(pkg, cfg)
        if est > float(lf.get("max_seconds", 900)):
            errs.append(f"too long: ~{est / 60:.1f} min estimated, max {float(lf.get('max_seconds', 900)) / 60:.0f} min")
        if est < 8 * 60 + 20:
            errs.append(f"too short for mid-roll ads: ~{est / 60:.1f} min estimated (needs 8:20+ with margin), aim for 9-10 minutes")
    desc = pkg["description"]
    if not isinstance(desc, str) or not (40 <= len(desc) <= 3000):
        errs.append("description must be 40-3000 characters")
    tags = pkg["tags"]
    if not isinstance(tags, list) or not (5 <= len(tags) <= 25) or not all(isinstance(t, str) for t in tags):
        errs.append("tags must be a list of 5-25 strings")
    elif _tag_char_count(tags) > 480:
        errs.append("tags are too long in total (keep under 480 characters including commas)")
    for h in pkg.get("hashtags", []) or []:
        if not HASHTAG_RE.match(h):
            errs.append(f"hashtag '{h}' must look like #Word")
        if h.lower() == "#shorts":
            errs.append("a long video must not carry #shorts")
    tt = pkg.get("thumbnail_text")
    if tt and not (3 <= len(tt) <= 40):
        errs.append("thumbnail_text must be 3-40 characters (3-5 big words)")
    return errs


def main(argv: list[str]) -> int:
    if not argv:
        print(__doc__)
        return 2
    cfg = load_config()
    bad = 0
    for p in argv:
        path = Path(p)
        try:
            pkg = json.loads(path.read_text(encoding="utf-8"))
        except Exception as e:  # noqa: BLE001
            print(f"✗ {path}: not valid JSON ({e})")
            bad += 1
            continue
        if path.stem != pkg.get("id"):
            print(f"✗ {path}: file name must equal the id ('{pkg.get('id')}')")
            bad += 1
            continue
        long = is_longform(pkg)
        errs = validate_longform(pkg, cfg) if long else validate_package(pkg, cfg)
        if errs:
            bad += 1
            print(f"✗ {path}")
            for e in errs:
                print(f"    - {e}")
        elif long:
            print(f"✓ {path}  (long video, ~{estimate_longform_seconds(pkg, cfg) / 60:.1f} min)")
        else:
            print(f"✓ {path}  (~{estimate_seconds(pkg, cfg):.0f}s)")
    return 1 if bad else 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
