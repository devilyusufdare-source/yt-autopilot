# yt-autopilot — one YouTube Short a day, hands-off

```
 Claude (scheduled daily)            GitHub Actions (scheduled daily)              YouTube
 ───────────────────────            ──────────────────────────────────            ─────────
 reads channel.yml + stats   ──►    takes the oldest idea in content/queue/
 researches & verifies a fact       voice-over (neural voice, word timings)
 writes title/script/tags           stock footage per scene (Pexels) + captions   ──►  upload with title,
 pushes content/queue/*.json        progress bar, music, thumbnail                    description, tags
                                    records it in content/published/ + stats.json
```

Two independent halves, so one failing never blocks the other:

- **Ideas** — a Claude scheduled task follows `AGENT_TASK.md`: it researches a surprising, *verified*
  fact, writes the script, title, description, tags and hashtags, and keeps 5 ready-to-go ideas
  waiting in `content/queue/`.
- **Factory + uploader** — `.github/workflows/daily.yml` runs every day on GitHub's free runners
  (your computer can be off), renders the oldest idea into a 1080×1920 Short with
  `python -m pipeline.run`, uploads it through the YouTube Data API and commits the result back.

Everything is configurable in **`channel.yml`** (niche, voice, caption style, music, posting time).

---

## One-time setup (about 20 minutes)

### 1. GitHub
Create a free account at github.com if you don't have one, then create a **private** repository and
push this folder to it (or let Claude do it once GitHub is connected in claude.ai → Settings → Connectors).

### 2. Google Cloud — a key that lets the job upload to *your* channel
No billing and no free trial needed — dismiss the "$300 credits" banner.
1. Open https://console.cloud.google.com → top bar **Select a project → NEW PROJECT** (any name,
   e.g. `yt-autopilot`) → Create, then make sure it is selected in the top bar.
2. In the top search box type **YouTube Data API v3** → open it → **Enable**.
3. Search **OAuth consent screen** (it may be called **Google Auth Platform**) → **Get started**:
   app name + your email → Audience **External** → contact email → Finish → **Create**.
4. Left menu **Audience** → under *Test users* **Add users** → your own Gmail → Save.
5. Left menu **Clients** → **Create client** → Application type **Desktop app** → Create →
   **Download JSON**. Save it as `client_secret.json` (it is git-ignored).
6. **Branding** (Google requires a home page and privacy policy link before publishing):
   Application home page → `https://github.com/<your-user>/yt-autopilot`, Application privacy
   policy link → `https://github.com/<your-user>/yt-autopilot/blob/main/PRIVACY.md`, Authorised
   domains → add `github.com`. Leave the logo empty (a logo forces Google's review). **Save**.
7. Back on **Audience** → **Publish app** → Confirm. (In *Testing* mode Google expires the token
   after 7 days; publishing stops that. You do **not** need Google's app verification for your own
   channel — the "Google hasn't verified this app" warning in step 3 below is expected.)

### 3. Authorise once, on your own computer
```bash
pip install google-auth-oauthlib
python -m pipeline.authorize client_secret.json
```
A browser window opens → choose the channel's account → "Google hasn't verified this app" →
**Advanced → Go to … (unsafe)** → **Allow**. The script prints three values.

The permissions asked for are upload, manage videos and **comments** (the channel leaves the first
comment under every video once it is public). If you authorised before the comment permission was
added, the job still uploads fine but notes "first comment skipped" - re-run this step with the
latest code and replace the `YT_REFRESH_TOKEN` secret to switch comments on.

### 4. Add the secrets to GitHub
Repository → **Settings → Secrets and variables → Actions → New repository secret**:

| Secret | Value |
|---|---|
| `YT_CLIENT_ID` | printed by step 3 |
| `YT_CLIENT_SECRET` | printed by step 3 |
| `YT_REFRESH_TOKEN` | printed by step 3 |
| `PIXABAY_API_KEY` | free, instant: log in at pixabay.com, open https://pixabay.com/api/docs/ and scroll to the first `key` parameter — your key is printed there |
| `PEXELS_API_KEY` | optional second footage source (pexels.com/api — new keys are sometimes paused; skip if so) |

Without any footage key the videos get animated gradient backgrounds instead of stock footage.

### 5. Test
**Actions → Daily video → Run workflow** → tick **dry_run** → Run. After ~5 minutes open the run,
download the `video-…` artifact and watch the MP4. Happy? Run it again without dry_run: that
uploads the oldest idea in `content/queue/` and from then on the schedule does it daily.

---

## Privacy of uploads
Google's current API documentation says videos uploaded through the API are **not** forced to
private any more, even for unverified projects. If a video still lands as private, check YouTube
Studio → Settings → Upload defaults, and if needed fill in Google's form at
https://support.google.com/youtube/contact/yt_api_form (quota extension / compliance).

Quota: the API allows 100 uploads a day, but **YouTube itself caps each channel** (this one: 10 per 24 h,
seen as `uploadLimitExceeded`). `release.daily_limit` in channel.yml tells the job that cap, and it
waits for a free slot instead of being refused. Raise it when YouTube raises the channel's limit
(Studio → Settings → Channel → Feature eligibility → Advanced features).

Retention (optional, recommended): re-authorize once with analytics access and `content/stats.json`
gains `avg_view_percent` / `avg_view_seconds` per video plus a `retention` summary, so hooks can be
fixed from real numbers. Steps: (1) Google Cloud Console → APIs & Services → Library → enable
**YouTube Analytics API**; (2) on your computer, in the repository folder:
`pip install google-auth-oauthlib` then `python -m pipeline.authorize client_secret.json`
(the OAuth client file from Credentials → your client → Download JSON); (3) sign in with the
channel's Google account and allow everything; (4) paste the printed `YT_REFRESH_TOKEN` over the old
one in GitHub → Settings → Secrets and variables → Actions. Nothing else changes.

Long videos: `content/longform/queue/` holds 8–11 minute, 16:9 list videos (10 facts, one chapter
each; written by the long-form writer task, see `AGENT_LONGFORM.md`). One is made per day for the
`release.longform_slots` time (6:30 AM IST) and uses one of the day's 10 uploads. Test one without
uploading: Actions → Daily video → Run workflow → dry_run ✓, package `content/longform/queue/<file>.json`.

Facebook: with the `FB_PAGE_ID` and `FB_PAGE_TOKEN` secrets set, every Short is also posted to the
Facebook Page as a Reel and every long video as a Page video, scheduled for the same time. Make the
two values once on your own computer: get a short-lived user token in Meta's Graph API Explorer
(permissions pages_show_list, pages_read_engagement, pages_manage_posts, publish_video), then run
`python facebook_setup.py APP_ID APP_SECRET TOKEN` (the file is `pipeline/facebook_setup.py`).

Release window: uploading and going public are separate. The job runs once before each release time and uploads
whenever the 24 h window has room; each video is scheduled (`publishAt`) into the next free hourly
time of its slot list (`release.shorts_slots` / `release.longform_slots`: Shorts every ~2.5 h around
the clock skipping the US-night hours, the long video at 6:30 AM IST = US evening), so Studio shows
uploads as **Scheduled** until their slot.
10 slots a day = the daily limit.

Recovery mode (since 22 Oct 2026): after three days at 10 uploads/day the channel's reach collapsed
(9.3K views/day → 0.7K), so `release.videos_per_day: 4` caps uploads below YouTube's limit and
`release.only_topics: ["animals"]` keeps to the topic that still got shown. Plan: 3 days at 4, then
6 → 8 → 10 as views come back. To end it, delete those two lines and restore the 10-slot list that
is commented out next to `shorts_slots`.

---

## Day to day

| Folder / file | Meaning |
|---|---|
| `content/queue/` | Ideas waiting to be made. Oldest file name first. Delete a file to skip it. |
| `content/published/` | Done. Each file gains `youtube_id`, `url`, `uploaded_at`. |
| `content/failed/` | Rejected by validation or failed twice; the `_error` field says why. |
| `content/stats.json` | Views/likes per video and per topic, refreshed after every upload. The idea task reads it. |
| `output/` (in the Actions artifact) | The rendered MP4, thumbnail and captions of the latest run. |

- **Change how often / when videos go out**: the `cron` lines in `.github/workflows/daily.yml` (UTC; one line per upload per day), or set
  `schedule.schedule_time` in `channel.yml` to upload early and go public at a fixed local time.
- **Change the voice**: `voice.edge_voice` (`en-US-BrianNeural`, `en-GB-RyanNeural`, `en-IN-PrabhatNeural`, …).
  If Microsoft's free voice service is ever unreachable the job automatically uses an offline voice.
- **Add music**: drop royalty-free MP3s into `assets/music/`; one is picked at random, mixed quietly.
- **Captions**: size, colours, words per line and position are under `captions:`.
- **Change the niche**: edit `channel.niche` and `topics`; the idea task adapts on its next run.
  Then clear `content/queue/` so old-niche ideas are not published.
- **Manual idea**: write a JSON file following `content/schema.json`, run
  `python -m pipeline.validate content/queue/<file>.json`, commit.

## Running on your own computer instead of GitHub Actions
Same code, no GitHub needed: install Python 3.11+, ffmpeg and `pip install -r requirements.txt`,
set the four variables from step 4 in the environment (or a `.env` loaded by your shell) and
schedule `python -m pipeline.run` once a day with Task Scheduler (Windows) or `cron` (macOS/Linux).
The computer must be on at that time.

## Troubleshooting
- **"QUEUE EMPTY"** — the idea task has not run; run it (or write a file by hand).
- **`invalid_grant` on upload** — the refresh token expired (app still in Testing mode) or access was
  revoked. Publish the app (step 2.5) and redo step 3.
- **Thumbnail "not set"** — custom thumbnails need a phone-verified channel: youtube.com/verify. Non-fatal.
- **Video looks fine but captions are a default font** — `assets/fonts/Poppins-ExtraBold.ttf` is missing.
- **Keep it original** — YouTube's monetisation rules reject mass-produced, repetitive content. The idea
  task is told to never repeat a fact, to vary topics and to cite sources; keep it that way.
