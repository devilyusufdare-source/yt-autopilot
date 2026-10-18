# Running the channel without Claude

Everything that posts videos runs on GitHub by itself (free, public repository). Nothing here needs
a Claude subscription. What Claude did on a schedule was only *writing new ideas*; with 600 ideas in
`content/queue/` there are about two months of videos in stock.

## What keeps running on its own
- **Uploads:** `.github/workflows/daily.yml` runs every 2 hours, makes videos from `content/queue/`
  (highest `priority` first, then oldest), uploads 10 a day and schedules them into the times in
  `channel.yml` → `release.shorts_slots`. It stops only when the queue is empty.
- **Stats:** `content/stats.json` is refreshed after every upload (views, likes, subscribers).

## How to check it is working (2 minutes a day)
1. Open the repository → **Actions**. Green ticks = fine. A red cross = open it, read the last lines.
   GitHub also emails you when a run fails (Settings → Notifications → Actions).
2. YouTube Studio → Content shows the scheduled videos.

## When the queue runs low
`content/queue/` holds one file per idea. To add ideas without Claude's scheduled writer:
- Ask any Claude (the free claude.ai works) to write ideas in the format of `content/schema.json`
  following `AGENT_TASK.md`, then add the files to `content/queue/` on GitHub (**Add file → Create
  new file**, name = the idea's id + `.json`). The next run validates them; bad files go to
  `content/failed/` with the reason inside.
- Or keep the writer running: the "yt-autopilot ideas" scheduled task in Claude writes up to 20 ideas
  a run until the queue holds `queue_target` (channel.yml).

## Common changes (edit channel.yml on GitHub, then every run uses it)
- Release times: `release.shorts_slots`. Daily cap: `release.daily_limit` (10 = YouTube's cap).
- Long videos back on: `longform.enabled: true` (packages in `content/longform/queue/`).
- Pause everything: Actions → Daily video → "…" → **Disable workflow**. Enable again the same way.

## If uploads stop with "could not sign in to YouTube"
The YouTube key expired or was revoked. Re-run step 3 of README.md on your computer
(`python -m pipeline.authorize client_secret.json`) and update the `YT_REFRESH_TOKEN` secret.
