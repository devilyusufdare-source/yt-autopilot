"""Upload to YouTube with the Data API v3 (OAuth refresh token from GitHub secrets)."""
from __future__ import annotations

import datetime as dt
import random
import time
from pathlib import Path
from zoneinfo import ZoneInfo

from google.auth.transport.requests import Request
from google.oauth2.credentials import Credentials
from googleapiclient.discovery import build
from googleapiclient.errors import HttpError
from googleapiclient.http import MediaFileUpload

from .config import Config

SCOPES = [
    "https://www.googleapis.com/auth/youtube.upload",
    "https://www.googleapis.com/auth/youtube",
]
RETRIABLE_STATUS = {500, 502, 503, 504}


def youtube_client(cfg: Config):
    creds_dict = cfg.yt_credentials
    if not creds_dict:
        raise RuntimeError("YT_CLIENT_ID / YT_CLIENT_SECRET / YT_REFRESH_TOKEN are not set (see README step 3)")
    creds = Credentials(
        None,
        refresh_token=creds_dict["refresh_token"],
        token_uri="https://oauth2.googleapis.com/token",
        client_id=creds_dict["client_id"],
        client_secret=creds_dict["client_secret"],
        scopes=SCOPES,
    )
    creds.refresh(Request())
    return build("youtube", "v3", credentials=creds, cache_discovery=False)


def publish_slots(count: int, cfg: Config) -> list[str | None]:
    """Publish times (RFC 3339, UTC) for the videos of one run, or None = publish immediately."""
    per_run = int(cfg.get("release.videos_per_run", 1))
    if per_run <= 1 and count <= 1:
        return [None] * count
    interval = int(cfg.get("release.interval_minutes", 60))
    lead = int(cfg.get("release.lead_minutes", 20))
    tz = ZoneInfo(cfg.get("release.timezone", "UTC"))
    earliest = dt.datetime.now(tz) + dt.timedelta(minutes=lead)
    first = earliest.replace(minute=0, second=0, microsecond=0) + dt.timedelta(hours=1)
    return [(first + dt.timedelta(minutes=interval * i)).astimezone(dt.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
            for i in range(count)]


def build_description(pkg: dict, cfg: Config) -> str:
    hashtags = list(pkg.get("hashtags") or [])
    if not any(h.lower() == "#shorts" for h in hashtags):
        hashtags.append("#shorts")
    parts = [pkg["description"].strip(), " ".join(hashtags)]
    footer = (cfg.get("channel.description_footer") or "").strip()
    if footer:
        parts.append(footer)
    sources = pkg.get("sources") or []
    if sources:
        parts.append("Sources:\n" + "\n".join(sources))
    return "\n\n".join(p for p in parts if p)[:4900]


def build_body(pkg: dict, cfg: Config, publish_at: str | None = None) -> dict:
    title = (pkg["title"] + (cfg.get("channel.title_suffix") or "")).strip()[:100]
    lang = cfg.get("channel.language", "en")
    status: dict = {
        "privacyStatus": pkg.get("privacy") or cfg.get("channel.privacy", "public"),
        "selfDeclaredMadeForKids": bool(cfg.get("channel.made_for_kids", False)),
    }
    if publish_at and status["privacyStatus"] == "public":
        status["privacyStatus"] = "private"  # YouTube requires private + publishAt for scheduling
        status["publishAt"] = publish_at
    return {
        "snippet": {
            "title": title,
            "description": build_description(pkg, cfg),
            "tags": pkg["tags"],
            "categoryId": str(pkg.get("category_id") or cfg.get("channel.default_category_id", "27")),
            "defaultLanguage": lang,
            "defaultAudioLanguage": lang,
        },
        "status": status,
    }


def upload_video(youtube, video: Path, body: dict) -> str:
    media = MediaFileUpload(str(video), mimetype="video/mp4", chunksize=8 * 1024 * 1024, resumable=True)
    request = youtube.videos().insert(part="snippet,status", body=body, media_body=media, notifySubscribers=True)
    response, attempt = None, 0
    while response is None:
        try:
            status, response = request.next_chunk()
            if status:
                print(f"[upload] {int(status.progress() * 100)}%")
        except HttpError as e:
            if e.resp.status in RETRIABLE_STATUS and attempt < 6:
                attempt += 1
                wait = (2 ** attempt) + random.random()
                print(f"[upload] HTTP {e.resp.status}, retrying in {wait:.0f}s")
                time.sleep(wait)
                continue
            raise
        except (ConnectionError, TimeoutError, OSError) as e:
            if attempt < 6:
                attempt += 1
                wait = (2 ** attempt) + random.random()
                print(f"[upload] {type(e).__name__}, retrying in {wait:.0f}s")
                time.sleep(wait)
                continue
            raise
    return response["id"]


def set_thumbnail(youtube, video_id: str, image: Path) -> bool:
    """Custom thumbnails need a phone-verified channel; failure is not fatal."""
    try:
        youtube.thumbnails().set(videoId=video_id, media_body=MediaFileUpload(str(image), mimetype="image/jpeg")).execute()
        return True
    except HttpError as e:
        print(f"[upload] thumbnail not set ({e.resp.status}); verify your channel at youtube.com/verify to enable custom thumbnails")
        return False
