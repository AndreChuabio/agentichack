# Merit content loop: Higgsfield + compositor, laptop-first

Status: approved design, not yet implemented
Date: 2026-08-13

## Context

Merit needs Instagram content that drives signups and Stripe revenue. The GTM
layer already exists: `MI6/Projects/GTM/` holds the strategy, and
`MI6/Projects/GTM/Loop Handoff.md` records a working pipeline from 2026-08-12 --
an iterate loop on the mini produced captions and Gemini stills, and a manual
compositor produced the one asset judged good (`merit-ugc-in-hand.mp4`: a real
person holding a phone running the real Merit UI).

The handoff also records the expensive lesson: **a generative video model
cannot show the product.** Veo, asked for a Merit ad, invented a plausible app
that was not Merit. What works is generated footage with a flat green phone
screen, matted over with real screenshots. That rule survives every tool
change in this design.

Higgsfield replaces one-off Veo calls as the generation layer. Research
findings (2026-08-13): an official CLI + MCP exists for Claude Code
(`npm i -g @higgsfield/cli`, browser OAuth, no API keys, plan credits flow
through), skills install via `npx skills add higgsfield-ai/skills`, and the
separate platform API (`platform.higgsfield.ai`, `Key ID:SECRET` auth, async
submit/poll, outputs kept ~7 days) suits the mini's adapter posture later. The
account exists and an AI Influencer is being trained in it now.

Nikki's framework (`GTM Automation.md`) requires two stages the old loop
lacked: **Get Approval** and **Measure Result**. Both are in scope here.

### Correction this spec carries

`MI6/Projects/MeritAI/GTM Strategy.md` lists payment infrastructure as the
number-one blocker: "no Stripe or any billing library anywhere in the repo."
That is stale. PR #23 shipped the $99 dossier paywall, PR #25 fixed the webhook
that marks purchases paid, and `STRIPE_PRICE_DOSSIER` is set on Railway
production, so the paywall is live. The manual Payment Link stopgap is
unnecessary. The only open step is a test-card walk of the live purchase.

## Decisions locked

| Decision | Choice | Why |
|---|---|---|
| Where the loop runs first | This Claude Code session on the MacBook, via `/loop` | Fastest to first post; Higgsfield skills land in-session; the mini adapter is not built yet |
| Mini awareness | The shared Drive folder `claudeMeow/loops/<slug>/` plus an MI6 note plus claudemeow tickets | The Drive folder is the surface the bridge and Nikki already read; no new channel invented |
| Loop ownership | Exactly one owner at a time. The mini's `loop-meritai-instagram` stays spent (1/1) while the laptop owns the loop; cutover is an explicit later step | Two systems firing one content loop into one folder is the double-claim problem the fleet already solved for tickets |
| Posting | Human approval, human posts by hand -- in this session during the laptop phase, via the bridge's Telegram notice after cutover | Satisfies Get Approval with zero Meta API work; nothing publishes unattended under Merit's name |
| Higgsfield access | CLI + MCP skills on the laptop (OAuth, no key); platform API key only for the mini phase | Their own recommended path for Claude Code; kills the laptop adapter entirely |
| Presenter | One AI Influencer (Soul ID), reused across all content | Consistent face makes the account a brand; replaces the one-off Veo presenter |
| Product truth | Generated video never depicts the product. Real screenshots, matted in via the green-screen composite | The paid-for Veo lesson; `merit-ugc-in-hand.mp4` is the quality bar |
| Measurement | `round-NNN-metrics.md` files dropped into the loop folder; the next round reads them | Closes Measure Result with zero new code -- the loop session holds Read/Glob and the brief points it at the folder |
| Content pillars | Educational 7-criteria content + product proof, aimed at O-1/EB-1 founders and engineers | Nikki's written ICP in `GTM Automation.md`; no more ICP-in-the-model's-head |

## Hard content rules

These are constraints on every round, stated in the loop brief verbatim:

1. **No testimonials from the influencer.** She is a synthetic person; a
   synthetic person claiming a visa outcome is a fabricated testimonial (FTC
   territory, worst possible category in immigration services). She sells in
   second person with claims traceable to the repo. A real user's consented
   story lifts this rule for that ad only.
2. **The influencer is disclosed as AI.** Account bio names her as an AI
   presenter and posts carry Meta's AI label. Merit's trust posture is "not a
   law firm" honesty; an undisclosed synthetic person in visa marketing
   undercuts exactly that.
3. **Generated video never shows Merit's UI.** Screens in generated footage are
   flat green (`#10FF22`) for the matte, or off. Real UI enters only through
   the compositor from real screenshots.
4. **No invented numbers.** User counts, approval rates, and outcomes that do
   not exist in the repo do not exist in the content. Round-001 already held
   this line unprompted; it stays explicit anyway.

## Architecture

| Piece | What it is | Where |
|---|---|---|
| Loop driver | `/loop` in this session; each tick is one round | MacBook, this session |
| Round state | `loops/merit-instagram/round-NNN.md`, `ledger.md`, assets -- claudemeow's exact archive shape | Local workdir, mirrored to Drive |
| Generation | Higgsfield skills (stills: Nano Banana Pro / Soul; plates: Seedance / Kling with the influencer; Marketing Studio presets for feed stills) | Higgsfield, via CLI/MCP |
| Real screenshots | claude-in-chrome against the logged-in browser, phone viewport | MacBook |
| Compositor | Local recreations of `build-reel-frames` + `assemble_reel` + `composite_hand` (the originals are untracked on the mini); measured matte values from the handoff carried over | MacBook, `web/qa/` sibling scripts |
| Approval | Finished asset + caption presented in-session; Andre posts from the phone | Human |
| Measurement | Andre drops `round-NNN-metrics.md` (likes, saves, profile taps, link clicks) into the Drive loop folder; next round reads any metrics file present | Human + Drive |
| Mini awareness | Assets and rounds uploaded to `claudeMeow/loops/merit-instagram/` via the Drive MCP; MI6 note `Projects/MeritAI/Content Loop Implementation.md` (new note, linked, never restructuring Nikki's; check for her live sessions before writing) carrying WIP status and the Stripe correction | Drive + MI6 |
| Phase-2 handoff | Issues filed on `Meowteam6/claudemeow`: platform-API adapter beside `GeminiImages` (Keychain key `claudemeow-higgsfield-key`, redacted repr, per-round cap), issue #193 retargeted to the compositor, loop cutover | Mini fleet |

## The round, end to end

1. Read previous round + ledger + any metrics files from the loop folder.
2. Write `round-NNN.md`: critique of the last round **against its metrics**,
   caption, shot list, plate prompts, still prompts.
3. Generate stills and influencer plates through Higgsfield skills. Credit
   guard: at most 4 stills and 1 video plate per round unless Andre approves
   more.
4. Screenshot the real UI for the surfaces this round features.
5. Composite: matte real screens into plates, build feed frames, assemble the
   reel with hard cuts.
6. Upload round + assets to the Drive loop folder.
7. Present caption + assets for approval. Andre posts.
8. Metrics arrive later as a file; the next round starts at step 1.

## Phases

- **Phase 0 (human, now):** Instagram Business account (the true blocker);
  Higgsfield CLI setup (`npm i -g @higgsfield/cli`, `higgsfield auth login`,
  `npx skills add higgsfield-ai/skills`); finish training the influencer;
  ten-minute test-card walk of the live $99 purchase.
- **Phase 1 (this week):** first three rounds driven by `/loop` here; first
  reel and stills posted; MI6 note written; metrics convention exercised once.
- **Phase 2 (tickets to the fleet):** platform-API key minted in Higgsfield
  Cloud; adapter built by the mini executor; #193 retargeted; compositor
  scripts committed to claudemeow.
- **Phase 3 (cutover):** mini loop re-briefed and renewed; laptop loop stops;
  ownership transfers explicitly. Never both.

## Cost guards

- Higgsfield: Plus plan credits; per-round cap above; no Ultra until the loop
  proves volume.
- Model spend: one session per round, same as the mini loop's $0.46/round
  baseline; `/loop` budget capped with `x<n>` rounds per week.
- No paid distribution until a channel converts (B2C Strategy rule).

## Testing / verification

1. Dry round with generation stubbed: round file, ledger row, Drive upload,
   correct folder shape.
2. First real round end to end, with the composite checked against the rules:
   no generated UI, influencer disclosed, no testimonial, no invented numbers.
3. Metrics loop: drop a metrics file, confirm the next round's critique cites
   it.
4. Ownership: confirm the mini loop still reports spent while the laptop loop
   runs.
5. ffmpeg on this laptop verified for `colorkey` + `format=rgba` before the
   first composite (the mini's build lacked drawtext; this one is unverified).

## Out of scope

Instagram Graph API posting, autonomous publishing, other Meowteam6 products,
paid ads, the X/Twitter channel, and any content the hard rules forbid.
