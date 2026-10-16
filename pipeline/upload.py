"""Upload to YouTube with the Data API v3 (OAuth refresh token from GitHub secrets)."""
from __future__ import annotations

import datetime as dt
import json
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

COMMENT_SCOPE = "https://www.googleapis.com/auth/youtube.force-ssl"   # lets the channel post its own first comment
SCOPES = [
    "https://www.googleapis.com/auth/youtube.upload",
    "https://www.googleapis.com/auth/youtube",
    COMMENT_SCOPE,
]
RETRIABLE_STATUS = {500, 502, 503, 504}


class CommentPermissionError(RuntimeError):
    """The saved YouTube key was created without the comment permission (re-run pipeline.authorize)."""


def youtube_client(cfg: Config):
    creds_dict = cfg.yt_credentials
    if not creds_dict:
        raise RuntimeError("YT_CLIENT_ID / YT_CLIENT_SECRET / YT_REFRESH_TOKEN are not set (see README step 3)")
    # No `scopes` here on purpose: the token keeps whatever permissions it was granted, so a key made
    # before the comment permission existed still uploads fine (it just cannot comment yet).
    creds = Credentials(
        None,
        refresh_token=creds_dict["refresh_token"],
        token_uri="https://oauth2.googleapis.com/token",
        client_id=creds_dict["client_id"],
        client_secret=creds_dict["client_secret"],
    )
    creds.refresh(Request())
    return build("youtube", "v3", credentials=creds, cache_discovery=False)


def can_comment(youtube) -> bool | None:
    """True/False if the token's granted permissions are known, None if unknown."""
    try:
        granted = youtube._http.credentials.granted_scopes  # noqa: SLF001
    except AttributeError:
        return None
    if not granted:
        return None
    return COMMENT_SCOPE in granted


def _parse_hhmm(text: str, default: str) -> dt.time:
    try:
        h, m = str(text or default).split(":")
        return dt.time(int(h), int(m))
    except Exception:  # noqa: BLE001
        h, m = default.split(":")
        return dt.time(int(h), int(m))


def _parse_when(text: str | None) -> dt.datetime | None:
    if not text:
        return None
    try:
        when = dt.datetime.fromisoformat(text.replace("Z", "+00:00"))
    except ValueError:
        return None
    return when if when.tzinfo else when.replace(tzinfo=dt.timezone.utc)


def taken_release_times(published_dir: Path) -> list[dt.datetime]:
    """Publish times already claimed by uploaded videos (UTC), so two never share a slot."""
    out = []
    for f in published_dir.glob("*.json"):
        try:
            pkg = json.loads(f.read_text(encoding="utf-8"))
        except Exception:  # noqa: BLE001
            continue
        if not pkg.get("youtube_id"):
            continue
        when = _parse_when(pkg.get("publish_at")) or _parse_when(pkg.get("uploaded_at"))
        if when:
            out.append(when)
    return out


def publish_slots(count: int, cfg: Config, taken: list[dt.datetime] | None = None,
                  now: dt.datetime | None = None) -> list[str | None]:
    """Publish times (RFC 3339, UTC) for `count` videos, or None = publish immediately.

    With `release.window_start/window_end` set, every video is scheduled into the next free slots
    of the release window (hourly between those times, release timezone), however early in the
    day it was uploaded. Slots already claimed by other uploads (`taken`) are skipped.
    """
    tz = ZoneInfo(cfg.get("release.timezone", "UTC"))
    interval = max(5, int(cfg.get("release.interval_minutes", 60)))
    lead = int(cfg.get("release.lead_minutes", 20))
    now = (now or dt.datetime.now(dt.timezone.utc)).astimezone(tz)
    earliest = now + dt.timedelta(minutes=lead)
    start_txt, end_txt = cfg.get("release.window_start"), cfg.get("release.window_end")
    if not (start_txt and end_txt):
        # Old behaviour: hourly from the next round hour (or immediately for a single video).
        per_run = int(cfg.get("release.videos_per_run", 1))
        if per_run <= 1 and count <= 1:
            return [None] * count
        first = earliest.replace(minute=0, second=0, microsecond=0) + dt.timedelta(hours=1)
        return [(first + dt.timedelta(minutes=interval * i)).astimezone(dt.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
                for i in range(count)]

    start_t, end_t = _parse_hhmm(start_txt, "20:00"), _parse_hhmm(end_txt, "05:00")
    busy = [t.astimezone(tz) for t in (taken or [])]
    half = dt.timedelta(minutes=interval / 2)
    out: list[str | None] = []
    day = earliest.date() - dt.timedelta(days=1)
    for _ in range(10):  # at most ten days ahead
        start = dt.datetime.combine(day, start_t, tzinfo=tz)
        end = dt.datetime.combine(day, end_t, tzinfo=tz)
        if end <= start:
            end += dt.timedelta(days=1)
        slot = start
        while slot <= end and len(out) < count:
            if slot >= earliest and not any(abs(slot - b) < half for b in busy):
                out.append(slot.astimezone(dt.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"))
                busy.append(slot)
            slot += dt.timedelta(minutes=interval)
        if len(out) >= count:
            break
        day += dt.timedelta(days=1)
    return out


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


def post_comment(youtube, video_id: str, text: str) -> str | None:
    """Post a top-level comment as the channel. Returns the comment id, or None if YouTube refused.

    Raises CommentPermissionError when the saved key simply lacks the comment permission.
    """
    try:
        resp = youtube.commentThreads().insert(
            part="snippet",
            body={"snippet": {"videoId": video_id, "topLevelComment": {"snippet": {"textOriginal": text[:9000]}}}},
        ).execute()
        return resp.get("id")
    except HttpError as e:
        reason = ""
        try:
            reason = (e.error_details or [{}])[0].get("reason", "")
        except Exception:  # noqa: BLE001
            pass
        text_err = str(e).lower()
        if e.resp.status in (401, 403) and ("insufficient" in text_err or "scope" in text_err
                                            or reason in ("insufficientPermissions", "forbidden", "authError")):
            raise CommentPermissionError(
                "the YouTube key has no comment permission: run `python -m pipeline.authorize client_secret.json` "
                "again (latest code) and replace the YT_REFRESH_TOKEN secret") from e
        print(f"[comment] not posted on {video_id}: HTTP {e.resp.status} {reason}")
        return None
