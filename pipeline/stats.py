"""Refresh view/like counts for every published video into content/stats.json.

The idea generator reads this file to lean into what is working.
"""
from __future__ import annotations

import datetime as dt
import json
from collections import defaultdict

from .config import PUBLISHED_DIR, STATS_FILE


def _published() -> list[dict]:
    out = []
    for p in sorted(PUBLISHED_DIR.glob("*.json")):
        try:
            out.append(json.loads(p.read_text(encoding="utf-8")))
        except Exception:  # noqa: BLE001
            continue
    return [x for x in out if x.get("youtube_id")]


def update_stats(youtube) -> dict:
    pubs = _published()
    by_id = {p["youtube_id"]: p for p in pubs}
    videos: dict[str, dict] = {}
    ids = list(by_id)
    for i in range(0, len(ids), 50):
        chunk = ids[i:i + 50]
        resp = youtube.videos().list(part="statistics,status,snippet,contentDetails", id=",".join(chunk), maxResults=50).execute()
        for item in resp.get("items", []):
            st = item.get("statistics", {})
            status = item.get("status", {})
            cd = item.get("contentDetails", {})
            pkg = by_id[item["id"]]
            videos[item["id"]] = {
                # the switches YouTube uses to limit a video's reach (all should be: public, processed, not for kids)
                "upload_status": status.get("uploadStatus"),
                "rejection_reason": status.get("rejectionReason"),
                "made_for_kids": status.get("madeForKids"),
                "self_declared_made_for_kids": status.get("selfDeclaredMadeForKids"),
                "embeddable": status.get("embeddable"),
                "license": status.get("license"),
                "duration": cd.get("duration"),
                "definition": cd.get("definition"),
                "region_restriction": cd.get("regionRestriction"),
                "content_rating": cd.get("contentRating") or None,
                "category_id": item["snippet"].get("categoryId"),
                "title": item["snippet"]["title"],
                "topic": pkg.get("topic"),
                "style": pkg.get("style", "classic"),
                "voice": pkg.get("voice_used"),
                "hook": (pkg.get("scenes") or [{}])[0].get("text"),
                "published_at": item["snippet"].get("publishedAt"),
                "privacy": item.get("status", {}).get("privacyStatus"),
                "views": int(st.get("viewCount", 0)),
                "likes": int(st.get("likeCount", 0)),
                "comments": int(st.get("commentCount", 0)),
                "url": f"https://youtube.com/shorts/{item['id']}",
            }
    by_topic: dict[str, list[int]] = defaultdict(list)
    for v in videos.values():
        if v["topic"]:
            by_topic[v["topic"]].append(v["views"])
    summary = {
        t: {"videos": len(vs), "avg_views": round(sum(vs) / len(vs)), "best_views": max(vs)}
        for t, vs in by_topic.items()
    }
    by_style: dict[str, list[int]] = defaultdict(list)
    for v in videos.values():
        by_style[v.get("style") or "classic"].append(v["views"])
    style_summary = {k: {"videos": len(vs), "avg_views": round(sum(vs) / len(vs)), "over_1500": sum(1 for x in vs if x >= 1500)}
                     for k, vs in by_style.items()}
    by_voice: dict[str, list[int]] = defaultdict(list)
    for v in videos.values():
        if v.get("voice"):
            by_voice[v["voice"]].append(v["views"])
    voice_summary = {k: {"videos": len(vs), "avg_views": round(sum(vs) / len(vs))} for k, vs in by_voice.items()}
    top = sorted(videos.values(), key=lambda v: v["views"], reverse=True)[:10]
    channel = {}
    try:
        ch = youtube.channels().list(part="statistics,snippet", mine=True).execute().get("items", [])
        if ch:
            cst = ch[0].get("statistics", {})
            channel = {"title": ch[0]["snippet"].get("title"), "subscribers": int(cst.get("subscriberCount", 0)),
                       "channel_views": int(cst.get("viewCount", 0)), "video_count": int(cst.get("videoCount", 0))}
    except Exception as e:  # noqa: BLE001
        print(f"[stats] channel statistics unavailable: {e}")
    diagnosis = {
        "not_public": [v["url"] for v in videos.values() if v.get("privacy") != "public"],
        "made_for_kids": [v["url"] for v in videos.values() if v.get("made_for_kids")],
        "not_processed": [v["url"] for v in videos.values() if v.get("upload_status") not in (None, "processed")],
        "rejected": [v["url"] for v in videos.values() if v.get("rejection_reason")],
        "region_restricted": [v["url"] for v in videos.values() if v.get("region_restriction")],
        "age_restricted": [v["url"] for v in videos.values() if v.get("content_rating")],
        "sd_only": [v["url"] for v in videos.values() if v.get("definition") == "sd"],
    }
    data = {
        "updated_at": dt.datetime.now(dt.timezone.utc).isoformat(timespec="seconds"),
        "channel": channel,
        "diagnosis": diagnosis,
        "total_videos": len(videos),
        "total_views": sum(v["views"] for v in videos.values()),
        "by_topic": summary,
        "by_style": style_summary,
        "by_voice": voice_summary,
        "top_videos": [{"title": v["title"], "topic": v["topic"], "views": v["views"], "hook": v["hook"]} for v in top],
        "videos": videos,
    }
    STATS_FILE.write_text(json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8")
    return data


if __name__ == "__main__":
    # python -m pipeline.stats  -> refresh content/stats.json (read-only YouTube calls)
    from .config import load_config
    from .upload import youtube_client

    d = update_stats(youtube_client(load_config()))
    print(f"[stats] {d['total_videos']} videos, {d['total_views']} views; diagnosis: " +
          ", ".join(f"{k}={len(v)}" for k, v in d["diagnosis"].items()))
