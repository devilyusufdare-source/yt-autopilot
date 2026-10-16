"""Find small, active Shorts channels that could buy ready-made Shorts (client prospecting).

    python -m pipeline.prospects "study tips" "english speaking practice" ...
    python -m pipeline.prospects --from-config        # queries from channel.yml -> prospects.queries

Uses the same YouTube key as the uploader (read-only calls: search.list costs 100 quota units
per query, channels.list 1 per 50 channels). Writes content/prospects.md (readable list) and
content/prospects.csv. A prospect is a channel with 1,000-30,000 subscribers that posted at
least 2 Shorts in the last 30 days: big enough to pay, small enough to need help.
"""
from __future__ import annotations

import argparse
import csv
import datetime as dt
import sys
from collections import defaultdict
from pathlib import Path

from .config import CONTENT_DIR, load_config
from .upload import youtube_client

MIN_SUBS = 1_000
MAX_SUBS = 30_000
MIN_RECENT_SHORTS = 2
DAYS_BACK = 30


def search_recent_shorts(youtube, query: str, pages: int = 1) -> dict[str, dict]:
    """channelId -> {title, shorts (count in results), latest (iso)} for recent Shorts matching the query."""
    since = (dt.datetime.now(dt.timezone.utc) - dt.timedelta(days=DAYS_BACK)).strftime("%Y-%m-%dT%H:%M:%SZ")
    found: dict[str, dict] = defaultdict(lambda: {"shorts": 0, "latest": "", "titles": []})
    token = None
    for _ in range(pages):
        resp = youtube.search().list(part="snippet", q=query, type="video", videoDuration="short", order="date",
                                     publishedAfter=since, maxResults=50, relevanceLanguage="en",
                                     safeSearch="strict", pageToken=token).execute()
        for item in resp.get("items", []):
            sn = item["snippet"]
            cid = sn["channelId"]
            d = found[cid]
            d["shorts"] += 1
            d["latest"] = max(d["latest"], sn.get("publishedAt", ""))
            if len(d["titles"]) < 2:
                d["titles"].append(sn.get("title", ""))
        token = resp.get("nextPageToken")
        if not token:
            break
    return found


def channel_details(youtube, ids: list[str]) -> dict[str, dict]:
    out: dict[str, dict] = {}
    for i in range(0, len(ids), 50):
        chunk = ids[i:i + 50]
        resp = youtube.channels().list(part="snippet,statistics", id=",".join(chunk), maxResults=50).execute()
        for ch in resp.get("items", []):
            st = ch.get("statistics", {})
            sn = ch.get("snippet", {})
            out[ch["id"]] = {
                "name": sn.get("title", ""),
                "handle": sn.get("customUrl", ""),
                "country": sn.get("country", ""),
                "subs": int(st.get("subscriberCount", 0)) if not st.get("hiddenSubscriberCount") else 0,
                "videos": int(st.get("videoCount", 0)),
                "views": int(st.get("viewCount", 0)),
            }
    return out


def find_prospects(youtube, queries: list[str]) -> list[dict]:
    hits: dict[str, dict] = {}
    for q in queries:
        print(f"[prospects] searching: {q}")
        for cid, d in search_recent_shorts(youtube, q).items():
            h = hits.setdefault(cid, {"queries": set(), "shorts": 0, "latest": "", "titles": []})
            h["queries"].add(q)
            h["shorts"] += d["shorts"]
            h["latest"] = max(h["latest"], d["latest"])
            h["titles"] = (h["titles"] + d["titles"])[:2]
    details = channel_details(youtube, list(hits))
    rows = []
    for cid, h in hits.items():
        ch = details.get(cid)
        if not ch or not (MIN_SUBS <= ch["subs"] <= MAX_SUBS) or h["shorts"] < MIN_RECENT_SHORTS or ch["videos"] < 10:
            continue
        handle = ch["handle"] or ""
        url = f"https://www.youtube.com/{handle}" if handle.startswith("@") else f"https://www.youtube.com/channel/{cid}"
        avg_views = ch["views"] / max(1, ch["videos"])
        # Score: active (recent Shorts), in the sweet spot (5K-20K subs), views per video below subs x 0.5 = videos underperform = needs help.
        score = h["shorts"] * 2 + (3 if 5_000 <= ch["subs"] <= 20_000 else 1) + (2 if avg_views < ch["subs"] * 0.5 else 0)
        rows.append({
            "score": score, "name": ch["name"], "url": url, "about": url + "/about", "subs": ch["subs"],
            "videos": ch["videos"], "avg_views_per_video": int(avg_views), "recent_shorts": h["shorts"],
            "latest_short": h["latest"][:10], "country": ch["country"], "niche": ", ".join(sorted(h["queries"])),
            "example_titles": " | ".join(h["titles"]),
        })
    rows.sort(key=lambda r: (-r["score"], -r["recent_shorts"], r["subs"]))
    return rows


def write_outputs(rows: list[dict], out_dir: Path) -> tuple[Path, Path]:
    out_dir.mkdir(parents=True, exist_ok=True)
    csv_path = out_dir / "prospects.csv"
    md_path = out_dir / "prospects.md"
    if rows:
        with open(csv_path, "w", newline="", encoding="utf-8") as f:
            w = csv.DictWriter(f, fieldnames=list(rows[0].keys()))
            w.writeheader()
            w.writerows(rows)
    lines = [f"# Prospects ({len(rows)} channels) - {dt.datetime.now(dt.timezone.utc).strftime('%Y-%m-%d %H:%M UTC')}", "",
             "Small, active Shorts channels (1K-30K subscribers, 2+ Shorts in the last 30 days). Higher score = more active and more likely to need help.",
             "Open the About link to find the business email or social links; message 10 a day.", ""]
    lines.append("| # | Channel | Subs | Recent Shorts | Avg views/video | Niche | Country | Links |")
    lines.append("|---|---|---|---|---|---|---|---|")
    for i, r in enumerate(rows, 1):
        lines.append(f"| {i} | {r['name']} | {r['subs']:,} | {r['recent_shorts']} | {r['avg_views_per_video']:,} | {r['niche']} | {r['country']} | [channel]({r['url']}) · [about]({r['about']}) |")
    lines += ["", "## Example titles (to personalise the message)", ""]
    for i, r in enumerate(rows, 1):
        lines.append(f"{i}. **{r['name']}** — {r['example_titles']}")
    md_path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return md_path, csv_path


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("queries", nargs="*", help="search phrases, e.g. 'study tips' 'gym motivation'")
    ap.add_argument("--from-config", action="store_true", help="use prospects.queries from channel.yml")
    args = ap.parse_args(argv)
    cfg = load_config()
    queries = list(args.queries)
    if args.from_config or not queries:
        queries += list(cfg.get("prospects.queries") or [])
    queries = [q for q in dict.fromkeys(q.strip() for q in queries) if q]
    if not queries:
        print("no queries given")
        return 2
    yt = youtube_client(cfg)
    rows = find_prospects(yt, queries)
    md, csv_path = write_outputs(rows, CONTENT_DIR)
    print(f"[prospects] {len(rows)} prospects -> {md.relative_to(CONTENT_DIR.parent)}, {csv_path.relative_to(CONTENT_DIR.parent)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
