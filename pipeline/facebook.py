"""Cross-post every video to a Facebook Page (Shorts as Reels, long videos as videos).

Needs two GitHub secrets, created once with pipeline/facebook_setup.py on your own computer:
FB_PAGE_ID and FB_PAGE_TOKEN (a permanent Page access token with pages_manage_posts,
pages_read_engagement and publish_video). Without them this module does nothing.
Posting is best-effort: a Facebook failure never fails the YouTube run.
"""
from __future__ import annotations

import datetime as dt
import os
import time
from pathlib import Path

import requests

from .config import Config

GRAPH = "https://graph.facebook.com/v21.0"
GRAPH_VIDEO = "https://graph-video.facebook.com/v21.0"
RUPLOAD = "https://rupload.facebook.com/video-upload/v21.0"
MIN_SCHEDULE_AHEAD = 11 * 60     # Facebook wants scheduled posts at least 10 minutes in the future


def credentials() -> tuple[str, str] | None:
    page_id = (os.environ.get("FB_PAGE_ID") or "").strip()
    token = (os.environ.get("FB_PAGE_TOKEN") or "").strip()
    return (page_id, token) if page_id and token else None


def enabled(cfg: Config) -> bool:
    return bool(cfg.get("facebook.enabled", True)) and credentials() is not None


def _schedule_fields(publish_at: str | None) -> tuple[int | None, bool]:
    """(unix time to schedule for, or None to publish now; whether it is far enough ahead)."""
    if not publish_at:
        return None, True
    try:
        when = dt.datetime.fromisoformat(publish_at.replace("Z", "+00:00"))
    except ValueError:
        return None, True
    secs = int(when.timestamp())
    if secs - time.time() < MIN_SCHEDULE_AHEAD:
        return None, True   # too close: just publish now
    return secs, True


def _err(resp: requests.Response) -> str:
    try:
        e = resp.json().get("error", {})
        return f"HTTP {resp.status_code} {e.get('type', '')} {e.get('code', '')}: {e.get('message', resp.text[:200])}"
    except Exception:  # noqa: BLE001
        return f"HTTP {resp.status_code}: {resp.text[:200]}"


def description_for(pkg: dict, cfg: Config, shorts: bool) -> str:
    hashtags = [h for h in (pkg.get("hashtags") or []) if h.lower() != "#shorts"]
    if shorts and "#reels" not in [h.lower() for h in hashtags]:
        hashtags.append("#reels")
    parts = [pkg["description"].strip()]
    if pkg.get("chapters_text"):
        parts.append(pkg["chapters_text"].strip())
    parts.append(" ".join(hashtags))
    footer = (cfg.get("facebook.footer") or cfg.get("channel.description_footer") or "").strip()
    if footer:
        parts.append(footer)
    sources = pkg.get("sources") or [u for s in pkg.get("segments", []) for u in (s.get("sources") or [])]
    if sources:
        parts.append("Sources:\n" + "\n".join(sources[:12]))
    return "\n\n".join(p for p in parts if p)[:4000]


def post_reel(page_id: str, token: str, video: Path, description: str, publish_at: str | None) -> str:
    """Upload a 9:16 video (3-90 s) as a Reel. Returns the Facebook video id."""
    r = requests.post(f"{GRAPH}/{page_id}/video_reels", data={"upload_phase": "start", "access_token": token}, timeout=60)
    if r.status_code != 200:
        raise RuntimeError(f"reel start failed: {_err(r)}")
    video_id = r.json()["video_id"]
    size = video.stat().st_size
    with open(video, "rb") as f:
        up = requests.post(f"{RUPLOAD}/{video_id}", data=f, timeout=600,
                           headers={"Authorization": f"OAuth {token}", "offset": "0", "file_size": str(size)})
    if up.status_code != 200 or not up.json().get("success", True):
        raise RuntimeError(f"reel upload failed: {_err(up)}")
    when, _ = _schedule_fields(publish_at)
    data = {"upload_phase": "finish", "video_id": video_id, "access_token": token, "description": description,
            "video_state": "SCHEDULED" if when else "PUBLISHED"}
    if when:
        data["scheduled_publish_time"] = str(when)
    fin = requests.post(f"{GRAPH}/{page_id}/video_reels", data=data, timeout=120)
    if fin.status_code != 200:
        raise RuntimeError(f"reel publish failed: {_err(fin)}")
    return video_id


def post_video(page_id: str, token: str, video: Path, title: str, description: str, publish_at: str | None) -> str:
    """Upload a long (16:9) video to the Page in one request (up to 1 GB / 20 min). Returns the video id."""
    when, _ = _schedule_fields(publish_at)
    data = {"access_token": token, "title": title[:255], "description": description}
    if when:
        data["published"] = "false"
        data["scheduled_publish_time"] = str(when)
    with open(video, "rb") as f:
        r = requests.post(f"{GRAPH_VIDEO}/{page_id}/videos", data=data, files={"source": (video.name, f, "video/mp4")}, timeout=1800)
    if r.status_code != 200:
        raise RuntimeError(f"video upload failed: {_err(r)}")
    return r.json()["id"]


def crosspost(pkg: dict, cfg: Config, video: Path, kind: str, publish_at: str | None) -> dict | None:
    """Post one finished video to the Page. Returns {'facebook_id', 'facebook_url'} or None (never raises)."""
    creds = credentials()
    if not creds or not cfg.get("facebook.enabled", True):
        return None
    page_id, token = creds
    shorts = kind != "longform"
    if shorts and not cfg.get("facebook.reels", True):
        return None
    if not shorts and not cfg.get("facebook.long_videos", True):
        return None
    desc = description_for(pkg, cfg, shorts)
    for attempt in range(3):
        try:
            if shorts:
                fid = post_reel(page_id, token, video, desc, publish_at)
            else:
                fid = post_video(page_id, token, video, pkg["title"], desc, publish_at)
            url = f"https://www.facebook.com/reel/{fid}" if shorts else f"https://www.facebook.com/{page_id}/videos/{fid}"
            print(f"[facebook] posted {'reel' if shorts else 'video'} {fid}" + (f" (scheduled for {publish_at})" if publish_at else ""))
            return {"facebook_id": fid, "facebook_url": url}
        except (requests.RequestException, RuntimeError, KeyError, ValueError) as e:
            msg = str(e)
            print(f"[facebook] attempt {attempt + 1} failed: {msg[:300]}")
            if "HTTP 4" in msg and "HTTP 429" not in msg:
                break   # our mistake (permissions, token, format) - retrying will not help
            time.sleep(10 * (attempt + 1))
    return None
