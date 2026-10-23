"""Post the channel's first comment on videos that went public since the last run.

    python -m pipeline.comments        # uses YT_CHANNEL (unset = main channel) and the matching key

Used by the hourly "First comments" workflow so a comment appears within the hour of a video going
public instead of waiting for the channel's next upload run.
"""
from __future__ import annotations

import sys

from .config import load_config
from .run import post_pending_first_comments
from .upload import youtube_client


def main() -> int:
    cfg = load_config()
    if not cfg.get("cta.first_comment_enabled", True):
        print("[comments] first comments are off for this channel")
        return 0
    yt = youtube_client(cfg)
    n, note = post_pending_first_comments(yt, cfg)
    print(f"[comments] posted {n} comment(s)" + (f"; {note}" if note else ""))
    return 0


if __name__ == "__main__":
    sys.exit(main())
