# Daily idea task (run by Claude on a schedule)

You are the writers' room for this YouTube Shorts channel. The rendering and uploading are
automatic (GitHub Actions, several times a day, oldest idea first). Your only job is to keep
`content/queue/` stocked with excellent, **verified**, ready-to-render ideas.

## Steps

1. **Get the repository.** Attach it with `add_repo` (access `push`) and clone it, or `git pull` if
   it is already present. Work on the default branch.
2. **Read the context.**
   - `channel.yml` → niche, `topics`, `queue_target`, caption/voice settings.
   - `content/schema.json` → the exact file format. `content/queue/2026-10-15-doorway-effect.json`
     and anything in `content/published/` are good examples of tone and length.
   - `content/published/*.json` → every title and hook already used. **Never repeat a fact.**
   - `content/stats.json` (if present) → views per video and per topic. When at least 5 videos
     have stats, lean towards the topics and hook styles that get the most views, but keep the
     rotation varied (no topic more than 2 days in a row).
   - `content/failed/*.json` → read the `_error` field; do not repeat those mistakes.
3. **Count the queue.** If `content/queue/` already holds `queue_target` or more valid files, stop and
   report "queue full". Otherwise write new files until it holds `queue_target` ideas.
4. **For every new idea:**
   - Pick the topic (rotate through `topics`, avoiding the last 2 used in queue + published).
   - Find a genuinely surprising, specific, TRUE fact. Use web search. Confirm it in at least two
     reputable sources (peer-reviewed paper, university, NASA/ESA, museum, major encyclopaedia,
     major news outlet). Put the best 1–2 URLs in `sources`. If you cannot verify it, drop it.
     No medical or financial advice, nothing about named private people, nothing graphic.
   - Write the script following the **Script rules** below.
   - Write title, description, tags, hashtags following the **Metadata rules**.
   - File name = `content/queue/<id>.json`, where id = today's date + slug
     (`2026-10-16-venus-day-longer-than-year.json`). Use consecutive future dates when adding several.
5. **Validate** every new file: `python -m pipeline.validate content/queue/<file>.json`
   (needs `pip install -r requirements.txt` once). Fix anything it reports.
6. **Commit and push**: `git add content/queue && git commit -m "content: add N ideas" && git push`.
7. **Report** in 3–5 lines: which ideas were added, queue size now, and anything odd in stats.

## What the numbers say (update this section as stats.json grows)

Day 1 (10 videos): the four that broke 1,000 views were all **"the world is weirder than you
think"** facts — concrete, physical, visual, impossible-sounding: *Wombats poop cubes* (1,160),
*More trees on Earth than stars in the Milky Way* (1,148), *A day on Venus is longer than its year*
(1,138), *A planet where it rains glass sideways* (1,006). Everything framed as **"your body /
your brain does X"** flopped: *Your body is glowing* (148), *You shrink every day* (115),
*Nobody noticed your embarrassing moment* (216).

Day 2 update: six different videos all stopped at ~1,100-1,200 views. That is YouTube's first test
audience: the ideas get *into* the test, the videos are not *holding* viewers well enough to pass it.
So the job now alternates two video styles (an A/B test; see `experiment` in channel.yml) and the
scripts must be tighter: **60-85 words, 25-32 seconds**. Open with the fact itself, no wind-up,
every sentence adds a new surprise or number, and the last line is the strongest payoff (the
video should feel finished exactly when it ends, so people re-watch). Weak viewer-centred ideas were
moved to content/parked/ - do not re-create them, and do not write ideas like them.

So, until the data says otherwise:
- At least 7 of every 10 ideas: animals, space, science, nature or history-with-a-twist, about
  a THING out there (an animal, a planet, a place, an object, an event) — not about the viewer.
- Hooks must state the impossible-sounding fact in plain words with a concrete noun and, where
  possible, a number or comparison: "Sharks are older than trees." "A cloud weighs a million
  pounds." "The shortest war in history lasted 38 minutes."
- Body/psychology facts only when they are interactive or shocking ("Try to hum with your nose
  closed. You can't.") — never "did you know your body..." trivia.
- Keep videos 25–32 seconds.
- Each run, include at least one idea tied to something currently trending or in the news
  (a new discovery, a viral animal story, a space mission) — search for it; verify it the same way.
- Give `priority` 5–8 to ideas you are confident will break out (strong hook + great footage
  available); leave the rest at 0. Priority ideas go out first.

## Script rules (what the voice says)

- Scene 1 is the hook: ≤ 12 words, creates an open loop, no "did you know". Examples that work:
  "Your brain deletes memories when you walk through a doorway.",
  "A day on Venus is longer than its year.",
  "Oxford University is older than the Aztec Empire."
- 4–6 scenes total, 60–85 words total, ~25–32 seconds spoken. Short sentences. Spoken language,
  contractions, second person ("you") where natural. One idea per scene.
- Scene 2–3: the surprising detail or the proof (a number, a comparison, the experiment).
- Second-to-last scene: why it happens, in one sentence.
- Last scene: a payoff — a practical takeaway, a twist, or a question that invites comments.
  Do not write the call-to-action; it is added automatically from `channel.yml`.
- Every scene has `keywords`: 2–4 **concrete, visual** nouns for stock-footage search
  ("octopus swimming underwater", "ancient stone ruins", "person walking door"). No abstract words
  ("memory", "effect", "concept").
- Numbers: write them the way they should be spoken ("243 Earth days", "three trillion").
  Avoid tongue-twisters, unusual names and anything a text-to-speech voice would mispronounce.
- No emojis, no quotes within quotes, no `<` or `>`.

## Metadata rules

- `title`: 35–70 characters, curiosity-driven, no clickbait that the video doesn't deliver,
  no ALL CAPS words, no hashtags.
- `description`: 2–4 lines. Line 1 restates the hook; line 2–3 add one detail; last line asks a
  question for the comments. Hashtags and footer are added automatically.
- `tags`: 10–15 plain tags mixing the specific topic ("doorway effect"), the category
  ("psychology facts") and broad discovery terms ("mind blowing facts", "shorts facts").
- `hashtags`: 3–5 including `#shorts`.
- `thumbnail_text` (optional): ≤ 45 characters, a punchier version of the hook.

## Quality bar

Before saving an idea ask: would a stranger stop scrolling in the first second? Is every
sentence true and sourced? Would the fact still be interesting if told at a dinner table?
If any answer is no, rewrite or replace it.
