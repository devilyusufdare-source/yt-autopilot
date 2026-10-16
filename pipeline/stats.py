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
        resp = youtube.videos().list(part="statistics,status,snippet", id=",".join(chunk), maxResults=50).execute()
        for item in resp.get("items", []):
            st = item.get("statistics", {})
            pkg = by_id[item["id"]]
            videos[item["id"]] = {
                "title": item["snippet"]["title"],
                "topic": pkg.get("topic"),
                "style": pkg.get("style", "classic"),
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
    top = sorted(videos.values(), key=lambda v: v["views"], reverse=True)[:10]
    data = {
        "updated_at": dt.datetime.now(dt.timezone.utc).isoformat(timespec="seconds"),
        "total_videos": len(videos),
        "total_views": sum(v["views"] for v in videos.values()),
        "by_topic": summary,
        "by_style": style_summary,
        "top_videos": [{"title": v["title"], "topic": v["topic"], "views": v["views"], "hook": v["hook"]} for v in top],
        "videos": videos,
    }
    STATS_FILE.write_text(json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8")
    return data
