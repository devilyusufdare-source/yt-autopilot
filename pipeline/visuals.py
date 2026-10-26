"""Background footage for each scene.

Providers, tried in this order for every scene (each needs its key in the environment):
  1. Pixabay videos   (PIXABAY_API_KEY  - free, instant at pixabay.com/api/docs)
  2. Pexels videos    (PEXELS_API_KEY   - free, but new keys are sometimes paused)
  3. Pixabay photos   (PIXABAY_API_KEY  - a vertical photo with a slow push-in)
  4. Animated gradient background in a palette chosen by topic (no key needed)

Downloads are cached in .cache/. Output is always a silent H.264 clip of exactly the scene's
duration at the configured size (1080x1920 by default).
"""
from __future__ import annotations

import hashlib
import json
import os
import random
import re
import subprocess
import time
import urllib.parse
from dataclasses import dataclass
from pathlib import Path

import requests

from .config import CACHE_DIR, Config

PEXELS_SEARCH = "https://api.pexels.com/videos/search"
PIXABAY_VIDEOS = "https://pixabay.com/api/videos/"
PIXABAY_PHOTOS = "https://pixabay.com/api/"
MAX_DOWNLOAD_MB = 80
DRAW_URL = "https://image.pollinations.ai/prompt/"     # free image generation, no key (visuals.style: drawn)
DRAW_STYLE = ("hand-drawn ink illustration on cream paper, fine black linework, light watercolor wash, "
              "scientific field notebook style, single centered subject, lots of empty paper around it, "
              "no text, no letters, no watermark")

# Generic searches to try when the scene's own keywords return nothing.
TOPIC_FALLBACK_QUERIES = {
    "psychology": ["brain", "thinking person", "crowd walking"],
    "human body": ["human body", "heartbeat", "running athlete"],
    "space": ["galaxy", "stars night sky", "planet"],
    "science": ["laboratory", "science experiment", "nature macro"],
    "history": ["ancient ruins", "old map", "castle"],
    "animals": ["wildlife", "ocean animals", "forest"],
    "technology": ["robot arm factory", "rocket launch", "circuit board macro"],
    "games": ["gaming room neon lights", "game controller close up", "pixel art screen"],
    "internet": ["phone scrolling social media", "studio camera recording", "server room blinking lights"],
}
GENERIC_QUERIES = ["abstract background", "dark texture", "clouds timelapse"]

# Words that describe a shot rather than name its subject; ignored when working out what a video is about.
_FOCUS_STOP = set("""close up closeup macro slow motion water sky field river ocean sea forest tree trees mountain mountains night day sun
clouds grass sand rock rocks snow ice underwater flying swimming running walking eating feeding hunting jumping diving sleeping baby young
group herd flock pack large small big dark light the a an of in on and with at to for from its his her their person people man woman
hand hands face head eyes eye body animal animals wildlife nature timelapse aerial view background shot slowmo footage video
close-up detail details scene silhouette sunset sunrise tropical wild""".split())


def footage_focus(scenes: list[dict]) -> list[str]:
    """What a single-subject video is about, from its scenes' footage keywords: the word most scenes share
    ("alligator", "bison"), or the two-word name built around it when that repeats ("leafcutter ants",
    "sea cucumber"). Tried before the generic topic searches, so a scene whose exact search finds nothing
    still shows the right animal instead of random wildlife. [] when nothing repeats."""
    import collections
    toks = [re.findall(r"[a-z][a-z'-]+", str(s.get("keywords", "")).lower()) for s in scenes]
    uni: collections.Counter = collections.Counter(); first: dict[str, int] = {}
    for ws in toks:
        for w in dict.fromkeys(ws):
            if w not in _FOCUS_STOP and len(w) >= 3:
                uni[w] += 1
                first.setdefault(w, len(first))
    if not uni:
        return []
    word, n = max(uni.items(), key=lambda kv: (kv[1], -first[kv[0]]))
    if n < 2:
        return []
    pairs: collections.Counter = collections.Counter()
    for ws in toks:
        for a, b in dict.fromkeys(zip(ws, ws[1:])):
            if word in (a, b) and not (a in _FOCUS_STOP and b in _FOCUS_STOP):
                pairs[f"{a} {b}"] += 1
    best = [p for p, c in pairs.most_common() if c >= 2]
    return [best[0]] if best else [word]


def _words(text: str) -> set[str]:
    """Lower-case words with a trailing plural 's' removed ("ants" -> "ant"), for matching queries to clip tags."""
    return {w[:-1] if len(w) > 3 and w.endswith("s") else w for w in re.findall(r"[a-z]+", text.lower())}


def relevance(c: "Candidate", query: str) -> int | None:
    """How many of the query's subject words (not shot words like 'close up' or 'water') appear in the clip's
    tags or page link. None when the query has no subject words (a deliberately scenic shot) or the provider gave
    no description, so the result cannot be judged."""
    want = {w for w in _words(query) if len(w) >= 3 and w not in _FOCUS_STOP and (w + "s") not in _FOCUS_STOP}
    if not want or not c.text.strip():
        return None
    return len(want & _words(c.text))


# Palettes for the procedural fallback: three colours per topic.
TOPIC_PALETTES = {
    "psychology": ("#2b1055", "#0d0520", "#7597de"),
    "human body": ("#4a0f1f", "#1a0509", "#c03a52"),
    "space": ("#050a1f", "#000000", "#1d3a8a"),
    "science": ("#083344", "#020b10", "#0e9f9f"),
    "history": ("#3d2a0b", "#140d03", "#b07a2a"),
    "animals": ("#0b3d1f", "#031208", "#2a9d5c"),
    "technology": ("#06303a", "#02090c", "#22b8cf"),
    "games": ("#1f3a05", "#0a1202", "#84cc16"),
    "internet": ("#3b0f2e", "#12040e", "#ec4899"),
}
DEFAULT_PALETTE = ("#1b2a4a", "#0b1020", "#243b6b")


@dataclass
class Candidate:
    provider: str          # pixabay-video | pexels-video | pixabay-photo
    uid: str               # provider-unique id, used to avoid repeats within one video
    file_url: str
    width: int
    height: int
    duration: float        # 0 for photos
    page_url: str = ""
    author: str = ""
    kind: str = "video"    # video | image
    text: str = ""         # what the clip shows: Pixabay tags, or the words in a Pexels page link

    @property
    def portrait(self) -> bool:
        return self.height > self.width


def _get_json(url: str, params: dict, headers: dict | None = None) -> dict | None:
    try:
        r = requests.get(url, params=params, headers=headers or {}, timeout=30)
        if r.status_code != 200:
            print(f"[visuals] {url.split('/')[2]} answered {r.status_code} for '{params.get('q') or params.get('query')}'")
            return None
        return r.json()
    except Exception as e:  # noqa: BLE001
        print(f"[visuals] request failed ({url.split('/')[2]}): {e}")
        return None


class Visuals:
    def __init__(self, cfg: Config, workdir: Path, seed: str, topic: str, subject: str = "", focus: list[str] | None = None):
        self.cfg = cfg
        self.subject = (subject or "").strip()   # drawn mode: the thing every picture is about ("brown pelican")
        self.focus = [q for q in (focus or []) if q]   # footage mode: searched before generic topic clips
        self.workdir = workdir
        self.rng = random.Random(seed)
        self.topic = (topic or "").lower()
        self.used: set[str] = set()
        self.workdir.mkdir(parents=True, exist_ok=True)
        self.cache = CACHE_DIR / "footage"
        self.cache.mkdir(parents=True, exist_ok=True)
        self.credits: list[dict] = []
        self.pixabay_key = os.environ.get("PIXABAY_API_KEY") or None
        self.pexels_key = cfg.pexels_key
        self.landscape = cfg.width > cfg.height   # long videos are 16:9; Shorts are portrait
        # Drawn mode: every scene is an illustration generated from its keywords in one fixed style
        # (instead of stock footage), animated with a slow push-in. VISUAL_STYLE=drawn|footage overrides channel.yml.
        self.drawn = (os.environ.get("VISUAL_STYLE") or cfg.get("visuals.style") or "footage").lower() == "drawn"
        self.draw_engine = (os.environ.get("DRAW_ENGINE") or cfg.get("visuals.draw_engine") or "local").lower()
        self.draw_style = cfg.get("visuals.drawn_style") or DRAW_STYLE
        self.draw_fail = 0
        self.draw_errors: list[str] = []
        self.drawings: dict[str, Path | None] = {}   # keywords -> picture (sub-clips of a scene share one drawing)

    # ------------------------------------------------------------------ providers
    def _pixabay_videos(self, query: str) -> list[Candidate]:
        if not self.pixabay_key:
            return []
        data = _get_json(PIXABAY_VIDEOS, {"key": self.pixabay_key, "q": query[:100], "per_page": 20,
                                          "safesearch": "true", "video_type": "film"})
        out: list[Candidate] = []
        for hit in (data or {}).get("hits", []):
            files = hit.get("videos") or {}
            # Prefer the largest rendition that is not absurdly big to download.
            for size in ("large", "medium", "small"):
                f = files.get(size) or {}
                if f.get("url") and f.get("width") and f.get("height") and (f.get("size") or 0) < MAX_DOWNLOAD_MB * 1024 * 1024:
                    out.append(Candidate("pixabay-video", f"pxb{hit['id']}", f["url"], int(f["width"]), int(f["height"]),
                                         float(hit.get("duration", 0)), hit.get("pageURL", ""), hit.get("user", ""),
                                         text=str(hit.get("tags", ""))))
                    break
        return out

    def _pexels_videos(self, query: str) -> list[Candidate]:
        if not self.pexels_key:
            return []
        orientation = "landscape" if self.landscape else "portrait"
        data = _get_json(PEXELS_SEARCH, {"query": query, "orientation": orientation, "size": "medium", "per_page": 15},
                         headers={"Authorization": self.pexels_key})
        out: list[Candidate] = []
        for v in (data or {}).get("videos", []):
            files = [f for f in v.get("video_files", []) if f.get("link") and f.get("width") and f.get("height")]
            if self.landscape:
                fitting = [f for f in files if f["width"] >= f["height"]]
            else:
                fitting = [f for f in files if f["height"] > f["width"]]
            pool = fitting or files
            if not pool:
                continue
            target = 1080 if self.landscape else 1920
            pool.sort(key=lambda f: (abs(f["height"] - target), -f["height"]))
            f = pool[0]
            out.append(Candidate("pexels-video", f"pex{v['id']}", f["link"], int(f["width"]), int(f["height"]),
                                 float(v.get("duration", 0)), v.get("url", ""), (v.get("user") or {}).get("name", ""),
                                 text=" ".join([str(v.get("url", "")).rstrip("/").rsplit("/", 1)[-1], *map(str, v.get("tags") or [])])))
        return out

    def _pixabay_photos(self, query: str) -> list[Candidate]:
        if not self.pixabay_key:
            return []
        data = _get_json(PIXABAY_PHOTOS, {"key": self.pixabay_key, "q": query[:100], "per_page": 20, "safesearch": "true",
                                          "image_type": "photo", "orientation": "horizontal" if self.landscape else "vertical",
                                          "min_height": 720 if self.landscape else 1280})
        out: list[Candidate] = []
        for hit in (data or {}).get("hits", []):
            url = hit.get("largeImageURL")
            if url:
                out.append(Candidate("pixabay-photo", f"pxp{hit['id']}", url, int(hit.get("imageWidth", 0)),
                                     int(hit.get("imageHeight", 0)), 0.0, hit.get("pageURL", ""), hit.get("user", ""), kind="image",
                                     text=str(hit.get("tags", ""))))
        return out

    # ------------------------------------------------------------------ choosing + downloading
    def _pick(self, cands: list[Candidate], min_duration: float, query: str = "", strict: bool = False) -> Candidate | None:
        cands = [c for c in cands if c.uid not in self.used]
        if strict and query:
            # Only clips whose tags/link mention the subject ("alligator teeth close up" must not return a bee close-up);
            # the best-matching ones first. Nothing relevant -> None, so the next search (the video's subject) runs.
            scored = [(relevance(c, query), c) for c in cands]
            if any(r is not None for r, _ in scored):
                best = max((r or 0) for r, _ in scored)
                if best <= 0:
                    return None
                cands = [c for r, c in scored if (r or 0) == best]
        if not cands:
            return None
        # Matching orientation first, then long enough to avoid looping, then top results (most relevant).
        fitting = [c for c in cands if (not c.portrait) == self.landscape]
        pool = fitting or cands
        long_enough = [c for c in pool if c.kind == "image" or c.duration >= min_duration]
        pool = (long_enough or pool)[:8]
        return self.rng.choice(pool)

    def _download(self, c: Candidate) -> Path | None:
        ext = ".jpg" if c.kind == "image" else ".mp4"
        dst = self.cache / f"{c.uid}{ext}"
        if dst.exists() and dst.stat().st_size > 10_000:
            return dst
        try:
            with requests.get(c.file_url, stream=True, timeout=120) as r:
                r.raise_for_status()
                size = 0
                with open(dst, "wb") as f:
                    for chunk in r.iter_content(chunk_size=1 << 16):
                        f.write(chunk)
                        size += len(chunk)
                        if size > MAX_DOWNLOAD_MB * 1024 * 1024:
                            raise RuntimeError("file too large")
            return dst
        except Exception as e:  # noqa: BLE001
            print(f"[visuals] download failed ({c.provider}): {e}")
            dst.unlink(missing_ok=True)
            return None

    @staticmethod
    def _energy(path: Path) -> tuple[float, float]:
        """(motion, brightness) of the first 3 s: mean frame-to-frame difference and mean luma, 0-255."""
        def _mean_yavg(vf: str) -> float:
            try:
                out = subprocess.run(
                    ["ffmpeg", "-v", "error", "-t", "3", "-i", str(path), "-vf", vf, "-f", "null", "-"],
                    capture_output=True, text=True, timeout=60).stderr
            except (subprocess.SubprocessError, OSError):
                return 0.0
            vals = [float(line.split("=")[-1]) for line in out.splitlines() if "signalstats.YAVG=" in line]
            return sum(vals) / len(vals) if vals else 0.0
        motion = _mean_yavg("scale=160:-2,fps=10,tblend=all_mode=difference,signalstats,metadata=print:key=lavfi.signalstats.YAVG:file=/dev/stderr")
        luma = _mean_yavg("scale=160:-2,fps=5,signalstats,metadata=print:key=lavfi.signalstats.YAVG:file=/dev/stderr")
        return motion, luma

    def _find_energetic(self, keywords: str, duration: float) -> tuple[Path, Candidate] | None:
        """For the first scene: download the best few matching videos and keep the one with the most
        visible motion (and not too dark), because the first second decides whether people stay."""
        cands: list[Candidate] = []
        for provider in (self._pixabay_videos, self._pexels_videos):
            cands += provider(keywords)
        cands = [c for c in cands if c.uid not in self.used and c.kind == "video"]
        scored = [(relevance(c, keywords), c) for c in cands]
        if any(r is not None for r, _ in scored):
            best = max((r or 0) for r, _ in scored)
            cands = [c for r, c in scored if (r or 0) == best] if best > 0 else []
        fitting = [c for c in cands if (not c.portrait) == self.landscape]
        pool = (fitting or cands)
        pool = ([c for c in pool if c.duration >= duration] or pool)[:3]
        scored: list[tuple[float, Candidate, Path]] = []
        for c in pool:
            path = self._download(c)
            if not path:
                continue
            motion, luma = self._energy(path)
            score = motion * (1.0 if 35 <= luma <= 215 else 0.5)
            scored.append((score, c, path))
            print(f"[visuals] first clip candidate {c.uid}: motion {motion:.1f}, brightness {luma:.0f}")
        if not scored:
            return None
        score, c, path = max(scored, key=lambda t: t[0])
        self.used.add(c.uid)
        self.credits.append({"query": keywords, "provider": c.provider, "url": c.page_url, "author": c.author})
        return path, c

    def _find_source(self, keywords: str, duration: float, energetic: bool = False) -> tuple[Path, Candidate] | None:
        if not (self.pixabay_key or self.pexels_key):
            return None
        if energetic:
            found = self._find_energetic(keywords, duration)
            if found:
                return found
        # Specific query first across all providers, so a relevant photo beats a generic video.
        queries = ([keywords] + [q for q in self.focus if q.lower() != keywords.lower().strip()]
                   + TOPIC_FALLBACK_QUERIES.get(self.topic, [])[:2] + GENERIC_QUERIES[:1])
        providers = (self._pixabay_videos, self._pexels_videos, self._pixabay_photos)
        strict_queries = {keywords.lower().strip(), *[q.lower() for q in self.focus]}
        for q in queries:
            for provider in providers:
                picked = self._pick(provider(q), duration, query=q, strict=q.lower().strip() in strict_queries)
                if not picked:
                    continue
                path = self._download(picked)
                if path:
                    self.used.add(picked.uid)
                    self.credits.append({"query": q, "provider": picked.provider, "url": picked.page_url, "author": picked.author})
                    return path, picked
        return None

    # ------------------------------------------------------------------ rendering
    def _zoom_filter(self, duration: float, zoom: float | None = None) -> str:
        z = float(self.cfg.get("video.zoom", 0.08)) if zoom is None else zoom
        if z <= 0:
            return ""
        d = max(duration, 0.1)
        return (f",scale=w='trunc(iw*(1+{z}*t/{d:.3f})/2)*2':h='trunc(ih*(1+{z}*t/{d:.3f})/2)*2':eval=frame,"
                f"crop={self.cfg.width}:{self.cfg.height}")

    def _fit_filter(self, duration: float, zoom: float | None = None) -> str:
        w, h, fps = self.cfg.width, self.cfg.height, self.cfg.fps
        return (f"scale={w}:{h}:force_original_aspect_ratio=increase,crop={w}:{h}"
                f"{self._zoom_filter(duration, zoom)},fps={fps},format=yuv420p")

    def _render_video(self, src: Path, duration: float, out: Path) -> None:
        subprocess.run(
            ["ffmpeg", "-y", "-loglevel", "error", "-stream_loop", "-1", "-i", str(src), "-t", f"{duration:.3f}",
             "-an", "-vf", self._fit_filter(duration), "-c:v", "libx264", "-preset", "veryfast", "-crf", "18", str(out)],
            check=True,
        )

    def _render_image(self, src: Path, duration: float, out: Path) -> None:
        zoom = max(float(self.cfg.get("video.zoom", 0.08)), 0.10)  # a still needs visible motion
        subprocess.run(
            ["ffmpeg", "-y", "-loglevel", "error", "-loop", "1", "-framerate", str(self.cfg.fps), "-i", str(src),
             "-t", f"{duration:.3f}", "-vf", self._fit_filter(duration, zoom), "-c:v", "libx264", "-preset", "veryfast",
             "-crf", "18", str(out)],
            check=True,
        )

    def _render_procedural(self, duration: float, out: Path, index: int) -> None:
        w, h, fps = self.cfg.width, self.cfg.height, self.cfg.fps
        c0, c1, c2 = TOPIC_PALETTES.get(self.topic, DEFAULT_PALETTE)
        # A different gradient direction for every scene so cuts are visible.
        corners = [(0, 0, w, h), (w, 0, 0, h), (0, h, w, 0), (w, h, 0, 0), (w // 2, 0, w // 2, h), (0, h // 2, w, h // 2)]
        x0, y0, x1, y1 = corners[index % len(corners)]
        src = (f"gradients=s={w}x{h}:c0={c0}:c1={c1}:c2={c2}:nb_colors=3:speed=0.03:"
               f"duration={duration:.3f}:rate={fps}:x0={x0}:y0={y0}:x1={x1}:y1={y1}")
        vf = "noise=alls=5:allf=t+u,vignette=PI/5,format=yuv420p"
        subprocess.run(
            ["ffmpeg", "-y", "-loglevel", "error", "-f", "lavfi", "-i", src, "-t", f"{duration:.3f}",
             "-vf", vf, "-c:v", "libx264", "-preset", "veryfast", "-crf", "18", str(out)],
            check=True,
        )

    # ------------------------------------------------------------------ drawn mode
    def _drawing(self, keywords: str) -> Path | None:
        """One illustration for these keywords (cached per video and on disk). None if the service fails."""
        if keywords in self.drawings:
            return self.drawings[keywords]
        if self.draw_fail >= 4:            # the service is down for this run: stop asking, use footage
            return None
        subj = self.subject if (self.subject and self.subject.split()[0].lower() not in keywords.lower()) else ""
        prompt = f"{subj + ', ' if subj else ''}{keywords}, {self.draw_style}"
        seed = int(hashlib.sha1((self.rng.random().__repr__() + prompt).encode()).hexdigest()[:6], 16)
        # Smaller than the video (fast to generate, allowed for anonymous use); ffmpeg scales it up and the
        # paper-and-ink style hides the upscaling.
        gw, gh = (1024, 576) if self.landscape else (576, 1024)
        key = hashlib.sha1(f"{prompt}|{seed}|{gw}x{gh}".encode()).hexdigest()[:16]
        dst = self.cache / f"draw-{key}.jpg"
        if not (dst.exists() and dst.stat().st_size > 20_000) and self.draw_engine == "local":
            # On this machine: Stable Diffusion Turbo on the CPU (pipeline/draw.py). No limits, ~15-40 s a picture.
            try:
                from . import draw as drawmod
                if not drawmod.available():
                    raise RuntimeError("diffusers/torch not installed (pip install -r requirements-draw.txt)")
                t0 = time.time()
                drawmod.draw(prompt, dst, width=(1024 if self.landscape else 512), height=(576 if self.landscape else 896), seed=seed)
                print(f"[visuals] drew '{keywords[:40]}' in {time.time() - t0:.0f}s")
            except Exception as e:  # noqa: BLE001
                msg = f"local: {type(e).__name__}: {str(e)[:120]}"
                print(f"[visuals] {msg}")
                self.draw_errors.append(msg)
                self.draw_fail += 1
                self.drawings[keywords] = None
                return None
        if not (dst.exists() and dst.stat().st_size > 20_000):
            ok = False
            for attempt, model in enumerate(("flux", "flux", "turbo")):
                url = (DRAW_URL + urllib.parse.quote(prompt) +
                       f"?width={gw}&height={gh}&seed={seed + attempt}&nologo=true&model={model}&enhance=false&safe=true")
                try:
                    r = requests.get(url, timeout=150)
                    if r.status_code == 200 and r.headers.get("content-type", "").startswith("image") and len(r.content) > 20_000:
                        dst.write_bytes(r.content)
                        ok = True
                        break
                    msg = f"HTTP {r.status_code} {r.headers.get('content-type', '')} {r.text[:80]!r}"
                except requests.RequestException as e:
                    msg = f"{type(e).__name__}: {str(e)[:80]}"
                print(f"[visuals] drawing attempt {attempt + 1} ({model}) failed: {msg}")
                self.draw_errors.append(msg)
                time.sleep(8 + 8 * attempt)
            if not ok:
                self.draw_fail += 1
                self.drawings[keywords] = None
                return None
        self.credits.append({"query": keywords, "provider": "drawing", "url": "", "author": ""})
        self.drawings[keywords] = dst
        return dst

    def _render_drawing(self, src: Path, duration: float, out: Path, index: int) -> None:
        """Ken Burns on an illustration: alternate push-in / pull-back with a gentle drift, paper grain, soft vignette."""
        w, h, fps = self.cfg.width, self.cfg.height, self.cfg.fps
        d = max(duration, 0.1)
        z = max(float(self.cfg.get("video.zoom", 0.08)), 0.10)
        # Always a little larger than the frame (1.02x) so the crop never exceeds the scaled picture, which crashes ffmpeg.
        grow = f"(1.02+{z}*t/{d:.3f})" if index % 2 == 0 else f"(1.02+{z}*(1-t/{d:.3f}))"
        drift = ["(iw-ow)/2", "(iw-ow)/2*(1-0.4*t/%.3f)" % d, "(iw-ow)/2*(1+0.4*t/%.3f)" % d][index % 3]
        vf = (f"scale={w}:{h}:force_original_aspect_ratio=increase,crop={w}:{h},"
              f"scale=w='trunc(iw*{grow}/2)*2':h='trunc(ih*{grow}/2)*2':eval=frame,crop={w}:{h}:x='{drift}':y='(ih-oh)/2',"
              f"noise=alls=4:allf=t,vignette=PI/6,fps={fps},format=yuv420p")
        subprocess.run(
            ["ffmpeg", "-y", "-loglevel", "error", "-loop", "1", "-framerate", str(fps), "-i", str(src), "-t", f"{duration:.3f}",
             "-vf", vf, "-c:v", "libx264", "-preset", "veryfast", "-crf", "18", str(out)],
            check=True,
        )

    def scene_clip(self, index: int, keywords: str, duration: float, energetic: bool = False) -> Path:
        out = self.workdir / f"scene{index:02d}.mp4"
        if self.drawn:
            pic = self._drawing(keywords)
            if pic:
                try:
                    self._render_drawing(pic, duration, out, index)
                    return out
                except subprocess.CalledProcessError as e:
                    print(f"[visuals] ffmpeg failed on a drawing ({e}); using footage for this scene")
            else:
                print("[visuals] no drawing for this scene; using footage")
        found = self._find_source(keywords, duration, energetic=energetic)
        if found:
            src, cand = found
            try:
                if cand.kind == "image":
                    self._render_image(src, duration, out)
                else:
                    self._render_video(src, duration, out)
                return out
            except subprocess.CalledProcessError as e:
                print(f"[visuals] ffmpeg failed on {cand.provider} file ({e}); using procedural background")
        self._render_procedural(duration, out, index)
        return out

    def save_credits(self, path: Path) -> None:
        path.write_text(json.dumps(self.credits, indent=2), encoding="utf-8")
