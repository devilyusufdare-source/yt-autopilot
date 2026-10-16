"""Load channel.yml, environment secrets and well-known paths."""
from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import yaml

ROOT = Path(__file__).resolve().parent.parent
CONTENT_DIR = ROOT / "content"
QUEUE_DIR = CONTENT_DIR / "queue"
PUBLISHED_DIR = CONTENT_DIR / "published"
FAILED_DIR = CONTENT_DIR / "failed"
LONGFORM_DIR = CONTENT_DIR / "longform"          # long (16:9, 8-12 min) videos live apart from the Shorts queue
LONGFORM_QUEUE_DIR = LONGFORM_DIR / "queue"
LONGFORM_FAILED_DIR = LONGFORM_DIR / "failed"
STATS_FILE = CONTENT_DIR / "stats.json"
ASSETS_DIR = ROOT / "assets"
MUSIC_DIR = ASSETS_DIR / "music"
OUTPUT_DIR = ROOT / "output"
CACHE_DIR = Path(os.environ.get("YT_CACHE_DIR", ROOT / ".cache"))


def _deep_get(d: dict, path: str, default: Any = None) -> Any:
    cur: Any = d
    for key in path.split("."):
        if not isinstance(cur, dict) or key not in cur:
            return default
        cur = cur[key]
    return cur


@dataclass
class Config:
    raw: dict

    def get(self, path: str, default: Any = None) -> Any:
        return _deep_get(self.raw, path, default)

    # --- secrets (from environment / GitHub secrets) ---
    @property
    def pexels_key(self) -> str | None:
        return os.environ.get("PEXELS_API_KEY") or None

    @property
    def yt_credentials(self) -> dict | None:
        cid = os.environ.get("YT_CLIENT_ID")
        secret = os.environ.get("YT_CLIENT_SECRET")
        refresh = os.environ.get("YT_REFRESH_TOKEN")
        if cid and secret and refresh:
            return {"client_id": cid, "client_secret": secret, "refresh_token": refresh}
        return None

    @property
    def tts_engine(self) -> str:
        return os.environ.get("TTS_ENGINE") or self.get("voice.engine", "auto")

    @property
    def width(self) -> int:
        return int(self.get("video.width", 1080))

    @property
    def height(self) -> int:
        return int(self.get("video.height", 1920))

    @property
    def fps(self) -> int:
        return int(self.get("video.fps", 30))


def with_overrides(cfg: Config, overrides: dict) -> Config:
    """A copy of the config with dotted keys replaced, e.g. {"video.width": 1920}."""
    import copy
    raw = copy.deepcopy(cfg.raw)
    for path, value in overrides.items():
        cur = raw
        keys = path.split(".")
        for k in keys[:-1]:
            if not isinstance(cur.get(k), dict):
                cur[k] = {}
            cur = cur[k]
        cur[keys[-1]] = value
    return Config(raw=raw)


def load_config(path: Path | None = None) -> Config:
    path = path or ROOT / "channel.yml"
    with open(path, "r", encoding="utf-8") as f:
        raw = yaml.safe_load(f) or {}
    return Config(raw=raw)


def ensure_dirs() -> None:
    for d in (QUEUE_DIR, PUBLISHED_DIR, FAILED_DIR, LONGFORM_QUEUE_DIR, LONGFORM_FAILED_DIR, OUTPUT_DIR, CACHE_DIR, MUSIC_DIR):
        d.mkdir(parents=True, exist_ok=True)
