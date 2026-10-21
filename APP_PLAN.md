# Products plan (written 21 Oct 2026)

Goal: $12–15K within 2 years. The channel is the audience machine; products turn an audience
into money. The order below goes from "can sell this week" to "needs an audience first".

## What the research says

- **Google Play**: $25 one-time developer fee, account holder must be 18+ (so Mom's account), and a
  new personal account must run a **closed test with 12 testers for 14 consecutive days** before
  it may publish to production, then apply and wait up to 7 days
  (https://support.google.com/googleplay/android-developer/answer/14151465). A Play Store app is
  3–5 weeks from "done" to "live". Google keeps 15% of the first $1M.
- **Gumroad** sells files and links, pays Indian sellers to a bank account in INR ($100 minimum
  balance), takes 10% + $0.50 per sale, accepts cards, PayPal and UPI from buyers, and handles
  sales tax as merchant of record. Account holder must be 18+ (Mom). Alternatives: Payhip (5%, pays
  via PayPal), Instamojo (Indian, ₹0 plan, 10% + ₹3).
- **"Shorts Studio" (script → finished video, $10 one-time)**: CapCut already does captions,
  text-to-speech and stock footage for free, and InVideo/Pictory/OpusClip cover the AI version.
  A one-person $10 tool cannot compete on that. Dropped.
- **Viewer app from the channel (facts/quiz, $3)**: fact viewers do not buy apps; at a realistic
  0.3% click rate and 2% conversion, 1,000 buyers needs ~17 million views on the promo videos.
  Build it when the channel has an audience (50K+ subscribers), not before.
- **Faceless-channel automation kits** sell on Gumroad at €19–29 (e.g.
  https://helpingtips.gumroad.com/l/youtubeautomationkit), but every listing shows no reviews:
  the product is easy, the buyers are hard. Our pipeline could be one of these once the channel
  has a track record to show; selling it while the channel is throttled would be dishonest.

## Product 1 (now): Fact Vault — $9 one-time

A single-file web app (`products/fact_vault/dist/fact-vault.html`, opens in any browser, no
account, no install, works offline) holding **150 complete Shorts packages**: script in scenes,
footage search per scene (links to Pexels), title, description, tags, hashtags, thumbnail text,
pinned-comment idea, sources, "mark as used", search, topic filter, CSV export, and the prompt
to generate more in the same shape. The ideas come from the channel's own queue (the ones it will
not post: history and date-led hooks, plus a few animals), so the product costs nothing to make.

- Build: `python products/fact_vault/build.py` (ideas in `products/fact_vault/ideas/`).
- Sell: Mom's Gumroad account → new product → upload `fact-vault.html` → price $9 (also allow
  "pay what you want" above $9). Product name "Fact Vault — 150 ready-to-post facts Shorts".
- Where buyers are (creators, not viewers): r/NewTubers and r/youtubers on their self-promo days,
  r/SideProject, X/Twitter with a 20-second screen recording, Pinterest pins ("150 YouTube Shorts
  ideas"), and a short "how I plan 150 Shorts in one afternoon" video on a second channel.
- Honest expectation: tens of sales in the first months ($100–500), not thousands. It is a first
  product and a test of whether creators buy from us; it does not replace the channel or client work.
- Refresh: every month, move another batch of unused ideas in and republish as "Vol. 2".

## Product 2 (when the channel has proof): Shorts Factory kit — $29

This repository packaged for other people: setup guide, the writer prompts, the renderer, the
scheduler. Sell only once the channel can show real numbers, and say plainly what the kit does
(it posts; it does not make a video get views).

## Product 3 (at 50K+ subscribers): Mind Unlocked app — $3 on Google Play

Daily facts + quiz for viewers, no ads, no account. Needs Mom's Play developer account ($25), 12
testers for 14 days (friends, classmates, r/AndroidClosedTesting), and the channel's audience to
sell it to.

## Still the fastest money: services

Making Shorts for other small channels with the pipeline ($5–15 per Short, bundles of 10). The
prospect list is in `content/prospects.md`; message 10 a day with one finished sample.
