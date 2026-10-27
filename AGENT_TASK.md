# Daily idea task (run by Claude on a schedule)

You are the writers' room for this YouTube Shorts channel. The rendering and uploading are
automatic (GitHub Actions, several times a day, oldest idea first). Your only job is to keep
`content/queue/` stocked with excellent, **verified**, ready-to-render ideas.

## Two channels, two queues (since 23 Oct; channel 1 back to animal facts 24 Oct 10:30)

The repository runs two channels.

**Channel 1 — Mind Unlocked Facts** (`channel.yml`, `content/queue/`) is the **animal-facts channel** again
(decided 24 Oct 10:30 after the numbers: animal single-facts got 250–1,000 views each, space/history got 0–5,
the first rankings 3–18 in their first hours). It posts 10 Shorts a day: **8 animal single-facts, 1 single fact
from any other topic, 1 ranking from any topic** (`release.format_mix: {"fact:animals": 8, "fact:*": 1,
"ranking:*": 1}`, enforced by the picker). The other-topic facts (240+) and rankings (20+) are already stocked,
so **for channel 1 write mostly `"topic": "animals"` packages**: single facts (`"format": "fact"`) until the queue
holds **600 animal fact files**, plus rankings of any topic (`"format": "ranking"`) until it holds **60 ranking
files**. One new voice for the whole channel since 24 Oct (en-US-AvaMultilingualNeural, set in `looks`).

**Channel 2 — What If Factz** (`channels/wild/channel.yml`, `channels/wild/content/queue/`; the folder is still
called `wild`) is the **"what if" channel**: every video is one hypothetical scenario answered with real science
(`"format": "whatif"`). Its `queue_target` is 600 what-if files. It was Wild Unlocked (animals) until 24 Oct; its
old animal ideas were moved into channel 1's queue (`content/queue/`) the same day.

Every run: top up whichever channel is further from its target, alternating so both grow. An idea goes in one
queue only; check both queues, both `content/published/` folders and `channels/wild/content/parked/` before writing.

## Ranking packages (channel 1 — 1 in 10 videos, any topic)

A ranking is the normal schema plus `"format": "ranking"`, `"ranking_by": "<one metric>"`, and `rank` + `label`
on five scenes. Model: `content/queue/2026-10-24-five-fastest-animals-ranked.json`.

- **One measurable metric** (top speed, verified age, size, mass, depth, height, distance, cost, deaths per year,
  decibels, temperature, number sold, years in use…). Never "coolest", "scariest", "best".
- **Spread across the channel's topics**: space ("5 biggest things in the universe"), human body ("5 strongest
  muscles"), science, history ("5 longest-reigning rulers"), animals, technology ("5 fastest machines ever
  built"), games ("5 best-selling games ever"), internet ("5 most-viewed videos ever"). No topic more than 2 rankings
  in a row; no metric repeated within the queue or the published records.
- **Scene 1 = hook**, no rank: name the list and open a gap ("The cheetah doesn't even come close to number one.",
  "Number one was alive before the pyramids.", "Sharks don't make the list."). Under 18 words.
- **Scenes 2–6 = ranks 5, 4, 3, 2, 1 in that order.** Each: "Number five: the pronghorn. Fifty-five miles an
  hour, and it can hold that for miles." — the name, the number, one memorable detail, 12–18 words. The voice
  says "Number five"; the picture shows a "#5" badge and the `label`.
- **`label`**: name + the number, under 32 characters: `"Pronghorn · 55 mph"`, `"Glass sponge · 11,000 years"`.
- **`keywords`**: the item's exact common name plus at most one plain action word ("pronghorn antelope", "cheetah running", "peregrine falcon"). Never a word with a second meaning ("diving" finds sea turtles, "bats dusk" finds sunsets). Every scene searches its own subject; a wrong animal under a #2 badge kills trust.
- **#1 must pay off** the hook; the whole script stays 85–115 words (≤ 55 seconds).
- **Sources**: at least 2, ideally one per surprising number. Numbers must agree across your sources; when
  sources disagree, say "around" / "about" and use the better source's range.
- **Description** ends with a question about the ranking; the full list is appended automatically.
  `first_comment`: ask which they'd put at #1 and what to rank next.
- `thumbnail_text`: "5 FASTEST ANIMALS, RANKED" style, under 30 characters. `priority` 5–8 when #1 is a real
  surprise.

## What-if packages (channel 2)

A what-if is the normal schema plus `"format": "whatif"`. Models: `channels/wild/content/queue/2026-10-24-what-if-*.json`.

- **One scenario per video**, phrased as a question people have actually wondered: the Moon disappears, Earth
  stops spinning, you never sleep, all ice melts, the Sun goes out, mosquitoes go extinct, everyone jumps at once,
  you fall into a black hole, the internet stops for a week, you only drank coffee, humans had wings, money vanished.
- **Real science only.** Every consequence must be grounded in published science (NASA, universities, journals,
  WHO, USGS, major encyclopaedias) with the URLs in `sources` (at least 2). No consequence you cannot source; say
  "about" / "roughly" for estimates. No gore, no named private people, no medical or financial advice.
- **Scene 1 = hook**: the question plus one twist line, under 18 words ("What if the Moon vanished tonight? The
  first thing you'd notice isn't the dark.").
- **Scenes 2–5 = the chain of consequences**, each a concrete physical effect with a number or a time marker
  ("Within a day…", "After a week…", "In a thousand years…"), 12–20 words, in the order they would happen.
- **Scene 6 = the ending**: the biggest consequence, or the twist that reframes the question. 80–115 words total.
- `topic` from the channel's list: space, earth, body, society, technology, animals. Rotate; no topic twice in a row.
- `keywords`: concrete footage for each scene (planet from space, melting glacier, crowd, hospital, frozen sea…).
- `title`: "What If …?" (keep the question form). `thumbnail_text`: "WHAT IF THE MOON VANISHED?" style, under
  34 characters. Description: 2–3 lines, ends with "What should we run through next?". `first_comment`: a
  question that invites their own what-if. `priority` 5–8 for scenarios with a famous question and a surprising answer.


**Never re-tell a published fact under a new title (27 Oct).** The picker now compares the key words of every script with everything already published and rejects an idea that overlaps 20% or more (36 queued ideas were thrown away for this on 27 Oct: the hairy frog, octopus hearts, hornet-cooking bees, the gannet dive...). Before writing, check the *facts* in content/published/ and content/parked/ (scene texts, not just titles); a new animal or a genuinely new fact about it is fine.

## Steps

1. **Get the repository.** Attach it with `add_repo` (access `push`) and clone it, or `git pull` if
   it is already present. Work on the default branch.
2. **Read the context.**
   - `channel.yml` → niche, `topics`, `queue_target`, caption/voice settings.
   - `content/schema.json` → the exact file format. `content/queue/2026-10-15-doorway-effect.json`
     and anything in `content/published/` are good examples of tone and length.
   - `content/published/*.json` → every title and hook already used. **Never repeat a fact.**
     Records with `"kind": "longform"` are long videos: their `segments[].heading` are facts too —
     do not write a Short about a fact that is a segment in a published or queued
     (`content/longform/queue/`) long video.
   - `content/stats.json` (if present) → views per video and per topic. When at least 5 videos
     have stats, lean towards the topics and hook styles that get the most views, but keep the
     rotation varied (no topic more than 2 days in a row).
   - `content/failed/*.json` → read the `_error` field; do not repeat those mistakes.
   - `content/sold/*.json` → ideas moved into a product that is sold (Fact Vault); treat them as used
     (never re-create them or anything like them).
3. **Count the queues.** Channel 1 is full when `content/queue/` holds 600 or more files with
   `"topic": "animals"` and `"format": "fact"` (or missing format) AND 60 or more files with
   `"format": "ranking"` (any topic). Channel 2 is full when `channels/wild/content/queue/`
   holds its `queue_target` (600) what-if files. If both are full, stop and report "queues full". Otherwise
   write for the channel further from its target, alternating so both grow.
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

Day 4 update (36 videos, 23K views): the ceiling is still ~1,100-1,600. What separates the top from
the bottom is now clear:
- **Every video over 1,000 has a violent or extreme PHYSICAL event with a number, that the first
  clip can SHOW**: lightning 5x hotter than the Sun (1,628), stomach acid eats a razor blade (1,311),
  a shrimp smashes aquarium glass (1,194), it rains glass sideways (1,246), a cloud weighs a million
  pounds (1,236) - or an animal with a superpower: crows remember your face (1,415), a shark lives
  400 years (1,216), wombats poop cubes (1,210), the immortal jellyfish (1,067), animals survive open
  space (1,231).
- **Everything abstract, geographic or "older/taller than" without a dramatic picture flopped**:
  Jupiter doesn't orbit the Sun (14), the Sahara feeds the Amazon (4), the shortest war (12), sharks
  older than trees (188), Oxford older than the Aztecs (352), a volcano taller than Everest (149),
  "your car could drive to space in an hour" (202). Body trivia flopped again (glowing 246, taller in
  the morning 222, hum with your nose 328) unless it is visceral (stomach acid).
- Rules from this: (1) the hook names a physical event or extreme number you can see - a strike,
  a bite, a crash, a punch, something eaten, frozen, crushed, surviving the impossible; (2) scene 1
  `keywords` must be the single most dramatic footage that exists for the fact (a lightning strike,
  not "sky"; a mantis shrimp strike, not "shrimp"); (3) at least 4 of every 10 ideas are animals
  with a superpower; (4) no history-of-institutions, no geography processes, no orbital mechanics,
  no "did you know your body" trivia, no "try this" interactive facts; (5) every title carries the
  number or the violent verb; (6) the last line is a twist or a bigger number, never a summary.

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

## Day 9 update (23 Oct): retention data, the rule that matters most

The Analytics API now gives "average view percentage" per video. Among videos with 100+ views:
- **Curiosity-gap hooks hold viewers: 81% average watched** (14 videos). *Saturn would float in
  water* (91%), *Crows remember your face for years* (101% = replays), *A day on Venus is longer than
  its year* (83%), *Wombats poop cubes. Scientists finally know why* (79%), *The jellyfish that can
  live forever* (78%). The hook is a claim that sounds impossible and **demands a why/how**; the
  explanation is held back until scenes 3–5; the last line is the twist or the callback.
- **Event hooks lose half the audience: 53% watched** (8 videos). *A crocodile bites with 3,700
  pounds* (24%), *This bird dives at 242 mph* (45%), *This fish chokes sharks with slime* (46%),
  *An orca killed a great white in under 2 minutes* (51%). The hook already IS the whole fact;
  after ten seconds there is nothing left to wait for, so people swipe at 13–16 s of 30.
- YouTube's test audience reacts to exactly this: the channel's reach collapsed in the days these
  event facts took over the queue.

So, from now on, for both channels:
1. **The hook poses a puzzle, not a result.** Not "An orca killed a great white in 2 minutes" but
   "Great whites flee from one animal. It isn't bigger than them." Not "A crocodile bites with 3,700
   pounds" but "A crocodile's bite is 3,700 pounds, and you can hold its mouth shut with one hand."
   Comparisons, paradoxes, impossible properties, "scientists finally know why".
2. **Hold the answer.** Scene 2 deepens the mystery or gives the number; the why/how arrives in the
   second half; the last line pays off or loops back to the hook.
3. Violent, visible footage is still wanted for the first clip (it gets the video tested), but the
   words must open a loop the footage does not close.
4. The queue has been re-ranked: puzzle hooks +2 priority, event hooks −3. Rewrite event ideas into
   puzzle form rather than adding more of them.

## New topics (22 Oct): technology, games, internet

The channel is widening beyond nature and space. Three topics were added to `topics` in channel.yml:
- **technology** — inventions, machines, engineering and records: the first X, the biggest/fastest/
  most expensive machine, how something was built, a failure that changed a design. Stock footage
  exists for almost all of it (rockets, robots, factories, old computers, bridges, ships), so treat it
  like science: the hook names a physical, visible event or extreme number. Start now: about 2 of
  every 10 ideas.
- **games** — facts about Minecraft, GTA, Roblox, Fortnite, Donut SMP, speedruns, records, hidden
  mechanics, how a game was made, money a game or server made. Stock sites have almost no gameplay
  footage, and other people's gameplay clips must never be used (reused-content rule). Until the
  channel has its own footage library (`assets/footage/games/`, coming), keep games to **1 in 10**
  ideas and write hooks that generic footage can carry (keywords like "gaming room neon lights",
  "game controller close up", "server room blinking lights", "pixel art screen", "kid playing video
  game excited"). The number or the twist carries the video, the picture sets the mood.
- **internet** — YouTube and creator records and internet history: the first YouTube video, the most
  viewed video, MrBeast's verified numbers (from major outlets or YouTube itself), how much a viral
  video earned, records on Shorts. Only verifiable numbers from major news outlets or the platforms'
  own announcements; nothing about private people, no gossip, no claims about anyone's private life
  or income that is not published by a major outlet. Footage: "phone scrolling social media",
  "studio camera recording", "crowd stadium lights", "money counting". 1 in 10 ideas.
Give priority 6–8 to the strongest technology ideas so the new topics reach the channel this week.

## Script rules (what the voice says)

- Scene 1 is the hook: ≤ 10 words, creates an open loop, no "did you know". The channel's own data
  (22 Oct: 54% of viewers swipe away) says the first second is everything: scene 1 must be sayable in
  under 3 seconds and its `keywords` must be real, moving footage (an impact, a strike, a dive, an
  explosion), never a still subject. Examples that work:
  "Your brain deletes memories when you walk through a doorway.",
  "A day on Venus is longer than its year.",
  "Oxford University is older than the Aztec Empire."
- 4–6 scenes total, 60–85 words total, ~25–32 seconds spoken. Short sentences. Spoken language,
  contractions, second person ("you") where natural. One idea per scene.
- Scene 2–3: the surprising detail or the proof (a number, a comparison, the experiment).
- Second-to-last scene: why it happens, in one sentence.
- Last scene: a payoff — a practical takeaway, a twist, or a question that invites comments.
  Do not write the call-to-action; it is added automatically from `channel.yml`.
- **Loop ending**: the last line should hand the viewer back to the first — a short callback to the hook
  or a question the hook answers ("So yes: older than trees." / "Now watch it again."), so the video
  re-plays naturally. Replays count as watch time.
- **`first_comment`**: write the channel's own first comment for the video — a sharp question that makes
  people reply ("Would you float on Saturn or sink on Jupiter?") or a bonus fact that extends the video.
  No hashtags, no "like and subscribe".
- `subject` (new, 2–3 words): the one thing the video is about, as it should be drawn: "brown pelican",
  "mantis shrimp", "Saturn planet". The drawn visual style puts it into every picture so a video about a
  pelican never shows a random fish.
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
- `thumbnail_text` (required in practice): **3–6 words, ≤ 32 characters.** It is the headline that pops
  up on screen in the first second of the video (and the thumbnail), so it is the promise: the number
  or the violent verb, nothing else. "15 MILLION BATS. ONE CAVE." "SNAIL. ONE STING. DEAD."
  "LIGHTNING: 5X HOTTER THAN THE SUN". Never a full sentence, never a question.

## Quality bar

Before saving an idea ask: would a stranger stop scrolling in the first second? Is every
sentence true and sourced? Would the fact still be interesting if told at a dinner table?
If any answer is no, rewrite or replace it.
