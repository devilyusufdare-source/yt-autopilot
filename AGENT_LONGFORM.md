# Daily long-video task (run by Claude on a schedule)

You write the channel's **long videos**: 16:9, 8–11 minutes, a themed list of 8–12 verified facts,
one chapter per fact. Rendering and uploading are automatic (one long video a day, released at
8 PM India time). Your only job is to keep `content/longform/queue/` stocked with
`longform.queue_target` (see channel.yml) excellent, **verified**, ready-to-render packages.

The Shorts have their own writer (AGENT_TASK.md). Do not touch `content/queue/`.

## Steps

1. **Get the repository.** Attach it with `add_repo` (access `push`) and clone it, or `git pull` if
   it is already present. Work on the default branch.
2. **Read the context.**
   - `channel.yml` → `topics`, `longform` settings (queue target, segment counts).
   - `content/longform/schema.json` → the exact file format.
     `content/longform/queue/2026-10-17-space-facts-that-sound-fake.json` (or any file in
     `content/longform/queue/` / a published record with `"kind": "longform"`) is the model for tone,
     length and structure.
   - `content/published/*.json` → every fact already used, in Shorts and long videos. A long video may
     re-use **at most 2** facts that were strong Shorts (rewritten, longer, new angle); everything else
     must be new. Never repeat a long video's theme within 10 days.
   - `content/longform/queue/*.json` → themes already waiting; pick a different one.
   - `content/stats.json` → which topics get views. Prefer winning topics (space, science, animals)
     but rotate: no theme two days in a row.
   - `content/longform/failed/*.json` → read `_error`; do not repeat those mistakes.
3. **Count the queue.** If `content/longform/queue/` already holds `queue_target` or more valid files,
   stop and report "queue full". Otherwise write new packages until it does (usually one).
4. **For every new package:**
   - Choose a theme and a list angle that people search for: "10 Space Facts That Sound Fake",
     "10 Animals That Shouldn't Exist", "10 Things Your Body Does Without Asking",
     "10 Historical Facts Nobody Believes". The number goes in the title.
   - Find 8–12 (10 is ideal) genuinely surprising, specific, TRUE facts for that theme. Use web
     search. Confirm each in at least one reputable source (peer-reviewed paper, university, NASA/ESA,
     museum, major encyclopaedia, major news outlet) and put its URL(s) in that segment's `sources`.
     If you cannot verify it, drop it. No medical or financial advice, nothing about named private
     people, nothing graphic.
   - Order: 2nd-strongest fact first, strongest LAST, and say so in the intro ("we finish with…").
   - Write intro, segments and outro following the **Script rules**; then title, description, tags,
     hashtags, thumbnail_text following the **Metadata rules**.
   - File name = `content/longform/queue/<id>.json`, id = today's date + slug
     (`2026-10-18-animals-that-should-not-exist.json`). Use consecutive future dates when adding several.
5. **Validate**: `python -m pipeline.validate content/longform/queue/<file>.json`
   (needs `pip install -r requirements.txt` once). Fix anything it reports — it checks word counts and
   the 8-minute minimum.
6. **Commit and push**: `git add content/longform/queue && git commit -m "longform: add <title>" && git push`.
7. **Report** in 3–5 lines: which video was added, queue size now, anything odd.

## Script rules (what the voice says)

- **Intro, 24–60 words (10–20 s):** the theme in one line, the promise ("every one is checked, sources
  in the description"), the teaser for the last fact, "Let's go." No "welcome to the channel", no
  "today we will", no asking for likes.
- **Each segment, 120–160 words (40–55 s):**
  1. First sentence = the fact itself, plain words, concrete noun, a number or a comparison where
     possible ("Saturn would float in water." "A day on Venus is longer than its year.").
  2. The proof: a number, who found it, when, how.
  3. Why it happens, in one or two sentences.
  4. One closing line that lands it (a twist, an image, a dry joke). Vary the closings — do not end
     every segment with a question.
  Short sentences. Spoken language, contractions, "you" where natural. Write numbers the way they
  should be spoken ("243 Earth days", "forty-three thousand"). Avoid tongue-twisters and names a
  text-to-speech voice would mangle. No emojis, no quotes inside quotes, no `<` or `>`.
- **Loop between facts:** the last line of a segment can set up the next ("…and that's nothing
  compared to what falls from the sky on Neptune.") — do it 2–3 times per video, not every time.
- **Outro, 15–60 words:** recap three of the facts in a few words, ask ONE question for the comments,
  then "There's a new fact here every evening." Nothing else.
- **`heading`** (3–60 characters): the chapter name shown on screen and in the description. A short
  version of the fact, not a teaser: "It rains diamonds on Neptune", not "You won't believe #4".
- **`keywords`**: 2–3 concrete, visual footage searches per segment, in the order the video should
  show them ("neptune planet blue", "diamonds falling sparkle", "laser laboratory experiment").
  Concrete nouns only — no "amazing", "concept", "science".
- Total: 1,300–1,600 words in the segments (the voice speaks about 2.85 words a second). The
  validator estimates the length; it must come out at 8:20 or more, aim for 9–10 minutes. Under 8
  minutes the video cannot carry mid-roll ads, which is the whole point of the long format.

## Metadata rules

- `title`: 15–100 characters with the number: "10 Space Facts That Sound Fake (But Are 100% Real)".
  Searchable, no ALL CAPS words, no hashtags, no clickbait the video doesn't deliver.
- `description`: 3–5 lines. What the video covers, the strongest fact as a teaser, one question.
  Chapters, hashtags, sources and the footer are appended automatically — do not write them.
- `tags`: 10–20 plain tags: the theme ("space facts"), each big fact ("neutron star", "diamond rain
  neptune"), the format ("facts that sound fake", "10 facts", "mind blowing facts").
- `hashtags`: 3–5 such as `#space #facts #science`. **Never `#shorts`.**
- `thumbnail_text`: 3–5 huge words, the most visual fact: "IT RAINS GLASS", "A STAR THAT SPINS 700 TIMES A SECOND" is too long.
- `thumbnail_label`: optional small pill, default "10 FACTS".
- `priority`: 0 normally; 5–8 if the theme is tied to something trending right now.

## Quality bar

Before saving ask: would a stranger who clicked for fact #1 still be watching at fact #7? Is every
sentence true and sourced? Does the strongest fact come last? Would the list be interesting told at
a dinner table? If any answer is no, rewrite or replace.
