---
name: product-demo-director
description: Turn product evidence, narration, and footage into a single-focus announcement, dramatic Save-the-Cat, causal investor, sales, or short-form demo with narration-safe cuts, exact-frame deterministic QA, and an advisory AI judge loop.
---

# Product Demo Director

Give it product evidence, footage, and a JSON production contract. It can make a single-focus
announcement film, a dramatic Save-the-Cat product story, or a continuous causal product film, with
per-shot TTS, one continuous generated performance, or one locked human narration master.
It binds every render to source hashes and integer frame boundaries, runs deterministic delivery QA,
then lets a Gemini judge review story and taste.

The motion engine is a single props-driven Remotion composition, so one pipeline renders many
cuts (teaser, walkthrough, race, full demo) from the same assets.

## When to use

- Producing a launch announcement, dramatic Save-the-Cat product story, causal live-product demo, or
  sales walkthrough.
- Re-cutting one set of footage into multiple lengths/formats.
- Narration-locked investor demos where exact claims, frames, continuity, and source framing matter.

Not for: editing arbitrary cinematic footage, or anything where you don't control the shot list.

## Setup (once)

```sh
cd engine && npm install && cd ..
python -m venv .venv && . .venv/bin/activate && pip install -r tools/requirements.txt
playwright install chromium          # only if you use tools/capture.py
export GEMINI_API_KEY=...             # judge + non-auto-paced Gemini TTS + Lyria 3
export ELEVENLABS_API_KEY=...         # required for auto-paced narration maps; also VO + music
```

New announcement scaffolds use `narration.fromMap=true` and `production.autoPaceNarration=true`;
they require `ELEVENLABS_API_KEY` because `pace.py` consumes ElevenLabs character timestamps.
With only `GEMINI_API_KEY`, `vo.py` still speaks non-auto-paced and legacy scripts through Gemini
TTS (`--provider gemini`, voice via `gemini_voice`/`tts_direction`), while `music.py` composes
through Lyria 3 and `judge.py` can review the final cut. ElevenLabs is selected automatically when
its key is present.

## Run the pipeline

A *project* is a folder with `script.json` + an `assets/` dir of clips (and, ideally, a
`brand.json` and a `product.json`). Start one with
`./pdd new projects/my-demo --name "My Product"`. The source-only
`examples/save-the-cat/` project documents how this repository created its own announcement; its
generated media remains ignored. The first three steps below onboard a brand, let the director
capture footage, and draft the script from the product brief:

```sh
# 0a. ONBOARD — auto-extract the brand (palette/font/logo) from the product site, confirm, write brand.json
python tools/onboard.py --project projects/my-demo --url https://yourproduct.com   # or --template / --manual

# 0b. SHOOT — the director records the footage itself -> assets/<name>.mp4 (web app and/or terminal/CLI)
python tools/shoot.py --project projects/my-demo                                  # reads shoot.json
#   (one-shot web:  python tools/shoot.py --url https://app.x.com --goal "tour it" --out assets/web.mp4)

# For a Claude/Codex-operated product, turn a committed whitelisted session into one workbench
# clip with prompt, tool actions, preview, timeline, render, and QA states. The result is a curated
# replay and must be labeled as such; it is not a proprietary agent-UI screen recording.
python tools/workbench.py --project projects/my-demo \
  --session projects/my-demo/_src/codex-workbench.json \
  --out projects/my-demo/assets/codex-workbench.webm

# 0c. DRAFT — choose the story grammar explicitly. Use launch-film for a public announcement.
python tools/script.py --project projects/my-demo --format launch-film --seconds 60

# For a 30-second dramatic product story:
# python tools/script.py --project projects/my-demo --format save-the-cat --seconds 30

# For a three-minute causal product story:
# python tools/script.py --project projects/my-demo --format causal-workflow --seconds 175

# 1. voiceover -> per-shot audio/manifest.json, or one generated narration master. For an
#    announcement, set narration.fromMap=true and author one exact thought + shotN per map entry;
#    ElevenLabs is required and writes character-level timing beside the master.
python tools/vo.py --project projects/my-demo

# 1b. narration pacing -> move each picture cut to a safe frame between complete spoken thoughts
python tools/pace.py --project projects/my-demo --write

# 2. music bed  -> <project>/music.mp3 (sized to the paced runtime, picked up by build.py)
python tools/music.py --project projects/my-demo

# 2b. (optional) regenerate the bespoke SFX palette (a model listens and keeps the best/cue)
python tools/sfx.py

# 3. PREFLIGHT — block source, story, authority, claim, camera, and narration violations
python tools/preflight.py --project projects/my-demo --strict

# 4. ASSEMBLE + RENDER — exact integer-frame plan plus props.json, build-plan.json, artifact.json
python tools/build.py --project projects/my-demo --contracts strict

# 5. FINISH — preserve exact frames while creating a two-pass loudness-normalized, BT.709 web master
python tools/finish.py --input projects/my-demo/out/demo.mp4 \
  --out projects/my-demo/out/demo-final.mp4 --require-artifact

# 6. FINAL-MEDIA QA — bind and decode the exact MP4; check frames, streams, audio, black/silence,
#    and generate review sheets. This gate is deterministic, not a model opinion.
python tools/qa.py --video projects/my-demo/out/demo-final.mp4 \
  --project projects/my-demo --require-artifact --strict

# 7. JUDGE STORY/TASTE — only after deterministic QA; require the artifact manifest so a stale
#    or similarly named MP4 cannot be reviewed by mistake.
python tools/judge.py --video projects/my-demo/out/demo-final.mp4 \
  --require-artifact --all-lenses --runs 1 --fps 6 --context "what this demo is"

# 7a. BEFORE an improve loop: compare the bundled bad fixture with your approved local master
python tools/judge.py --probe --probe-good projects/my-demo/out/demo-final.mp4

# 8. ACCEPT/REJECT — after candidate QA, compare both display orders. Only a 2–0 candidate sweep
#    outside the declared score noise exits successfully.
python tools/compare.py \
  --champion projects/my-demo/out/champion.mp4 \
  --champion-artifact projects/my-demo/out/champion-artifact.json \
  --candidate projects/my-demo/out/candidate.mp4 \
  --candidate-artifact projects/my-demo/out/candidate-artifact.json \
  --candidate-qa projects/my-demo/out/candidate-qa/qa-report.json
```

Steps 0a-0c are optional conveniences to *generate* `brand.json` and `script.json` automatically.
The scaffold and source example include authored JSON, while footage, narration, music, renders,
and QA output are generated locally and ignored. `brand.json` is the brand source of truth — its
palette, font, and logo flow into the **engine theme** (not just the CTA wordmark), so the whole cut
adopts the brand. See `docs/CAPTURE.md` for autonomous shoot planning + terminal footage and
`docs/PRODUCTION_CONTRACT.md` for profiles, causal beats, source locks, human narration, claims,
cursor safety, exact-frame artifact binding, and shipping gates.

For final delivery, do a separate technical finishing pass after render when needed: voice isolation
or mastering belongs in the project's `audio/` files, and web-safe video normalization belongs in the
export MP4. Keep these distinct from creative grading, and verify with `ffprobe`, `volumedetect`, and
contact sheets before calling the artifact final.

To iterate automatically, feed `judge.py`'s `specific_upgrades` back into the text/source artifacts
and re-render (pairs well with github.com/crimeacs/auto-improve as the keep/revert gate). Improve
`script.json`, `brand.json`, skill docs, rubrics, or engine code directly; do not treat a binary MP4
as the editable source of truth. Every candidate must pass deterministic gates first. Compare the
champion and candidate in both display orders and ship only a 2–0 winner. A split or roughly
two-point movement is noise. After three rejected in-point/zoom/pacing candidates, stop grinding cut
mechanics; the next gain requires narration, product behavior, story structure, or fresh capture.

## Script schema

`script.json` is both a timeline and, for final-delivery work, a production contract. Each shot is
one of `title | clip | split | stat | cta | score | bars | strip`. The default announcement
contract is generated by `pdd new`; the minimal shape below shows the additional evidence fields
used by a causal live-product profile:

```json
{
  "fps": 30,
  "production": {
    "profile": "yc_3m",
    "hardMaxSec": 180,
    "productBySec": 15,
    "requiredStoryBeats": ["input", "contradiction", "test", "decision", "receipt", "outcome"],
    "requireLiveProgression": true,
    "maxHumanDecisions": 1,
    "enforceSameScreenContinuity": true,
    "requireClaimEvidence": true,
    "sourceManifests": ["_src/codex-workbench.json"]
  },
  "claims": [
    { "id": "measured-result", "status": "verified", "evidence": ["evidence/result.json"] }
  ],
  "narration": {
    "file": "audio/final-human-master.wav",
    "sha256": "<sha256>",
    "expectedDurationSec": 169.62839,
    "durationToleranceSec": 0.01
  },
  "shots": [
    {
      "n": 1,
      "kind": "clip",
      "src": "live-case.mp4",
      "durSec": 18,
      "storyBeat": "test",
      "sourceType": "product",
      "liveState": true,
      "stateId": "test-running",
      "continuityId": "hero-case",
      "actor": "agent",
      "actionRisk": "low-friction",
      "claimIds": ["measured-result"]
    }
  ]
}
```

For an explicitly requested legacy before/after promo, the lighter timeline remains valid. `score` is an animated count-up,
`bars` visualizes sourced take scores clearing a pass line, and `strip` pans a filmstrip of shots:

```json
{
  "fps": 30,
  "music": "calm confident minimal corporate underscore, soft pulse, no drums",
  "brand": { "name": "Product Demo ", "accent": "Director" },
  "pronounce": { "ACME": "Ack-me" },
  "voice_settings": { "stability": 0.32, "style": 0.75, "similarity_boost": 0.85, "use_speaker_boost": true },
  "shots": [
    { "n": 1, "kind": "title", "title": "Your demo is a flat screen recording.", "durSec": 2.6, "vo": "..." },
    { "n": 2, "kind": "clip",  "src": "raw.mp4",      "inSec": 2, "chapter": "BEFORE", "scale": 1.0, "startScale": 1.0, "endScale": 1.18, "focusX": 50, "focusY": 68, "captionTop": 160, "vo": "..." },
    { "n": 3, "kind": "clip",  "src": "raw.mp4",      "chapter": "AFTER", "flash": true, "scale": 1.2, "accentAtSec": 1.4, "captionBottom": 150, "vo": "..." },
    { "n": 4, "kind": "split", "srcL": "raw.mp4", "labelL": "Raw", "srcR": "directed.mp4", "labelR": "Directed", "durSec": 4, "vo": "..." },
    { "n": 5, "kind": "stat",  "title": "Scored 92 / 100.", "durSec": 2.5, "vo": "..." },
    { "n": 6, "kind": "cta",   "title": "the demo your product deserves", "durSec": 3, "vo": "..." }
  ]
}
```

Notes:
- When a shot has `vo`, the on-screen caption defaults to that exact line. Override with an explicit
  `caption`, or set `caption: false` when subtitles would cover the live product. Any visible
  subtitle must match the spoken words.
- Use `narration.fromMap=true` plus exact `narrationMap[].text` and `shotN` for a generated master.
  When `production.autoPaceNarration=true`, configure `ELEVENLABS_API_KEY`: ElevenLabs character
  alignment fills the cue times, then `pace.py --write` moves the cuts before music/render. Gemini
  TTS remains valid when auto-pacing is disabled. A strict cut may occur only between complete
  mapped thoughts, and picture must retain the declared narration tail. Keep per-shot VO for short
  promos. Never globally accelerate supplied narration.
- `storyBeat`, `stateId`, and `liveState` describe causal progress. A final answer that is already
  visible before its initiating event fails the live-product contract.
- `actor` is `agent`, `human`, or `system`; `actionRisk` is `low-friction` or `consequential`.
  Low-friction work should not wait for human approval. Consequential work stays human unless the
  production contract explicitly authorizes autonomy.
- Keep one `continuityId` in one clip while the same screen and action continue. Put connected
  `zooms` inside that shot; split only on a declared route, application, or major state change.
- Lock human and other composition-sensitive sources with `preserveFraming` or
  `production.sourceLocks`. A locked source cannot be cropped or pushed in.
- Bind repo-native capture/replay files with `production.sourceManifests`. Each entry must be a
  project-relative file; its hash becomes a `capture-source` artifact input and changes the build ID.
- `focusX`/`focusY` are percentage anchors for the zoom origin. Use them to land motion on the
  thing the viewer must read or click, while keeping its context and cursor visible.
- `startScale`/`endScale` create a controlled push-in without changing the base `scale`; keep UI
  text legible and avoid zooming away from the narrated action.
- `captionTop` and `captionBottom` are pixel offsets. Use them when captions would cover a text
  field, CTA, report card, or browser/player controls.
- `accentAtSec` delays a sound effect until the actual completion event inside a shot. Use it for
  "report finished" or "purchase confirmed" moments instead of firing the sound at shot start.
- `clickX`/`clickY`/`clickAtSec` (clip) spring-zoom into a real click — `capture.py` overlays a
  visible eased cursor with a click ripple during web shoots and writes `<clip>.events.json`
  (click coords + timestamps), so these values come from the recording, not guesswork.
- `takes` + `passLine` (+ optional `takeLabels`) on a `bars` shot render REAL take scores clearing
  a pass line — feed it the judge history of the video itself.
- `sound: true` (clip) plays the clip's own audio — for UGC talking heads or a finished-demo excerpt.
- A narrated card (`title`/`stat`/`score`/`bars`/`cta`) holds for exactly VO + ~0.7s and is then cut
  (dead-air ceiling); opt out with `"hold": true`. The music bed ducks under every VO line and
  fades out at the end automatically.
- `accent` on a shot fires a palette sound on that beat (`click`, `data_tick`, `success_chime`,
  `confirm_cash`, `pivot_boom`); the pivot also gets a `riser` + boom automatically.
- `production.profile="announcement"` enables single-focus shots, required continuity IDs,
  narration-map coverage, between-thought cut enforcement, and protected end padding. Split-screen
  fails unless the production explicitly opts into the legacy treatment.
- `flash: true` (or `chapter: "AFTER"`) marks a legacy before/after pivot. It is not required or
  desirable merely because a causal workflow advances to a new state.
- `pronounce` rewrites spellings for the TTS audio only; captions keep the real spelling.
- `brand.name` + `brand.accent` render the CTA wordmark (accent tail colored).

## Craft rules

The methodology — each rule was a real mistake first — lives in `docs/EDITING.md` (the edit),
`docs/CAPTURE.md` (capturing live-app footage), and `docs/COLOR_GRADING.md` (color correction
and grading). Read them before authoring a script. Highlights:

- **Choose one causal unit of work.** Follow input → evidence → hypothesis → test → result →
  bounded decision → durable outcome. If the beats can be reordered, the cut is a feature list.
- **Make progress appear.** Reasoning, recommendations, and results arrive after their initiating
  events. Do not reveal a complete answer in the first frame and call it live AI.
- **Make authority visible.** The agent owns reversible, low-friction work; the accountable human
  appears only at a consequential boundary. Restraint under uncertainty is proof of judgment.
- **Escalate with a falsifiable test.** When one signal is inconclusive, show what evidence would
  change the decision, run the lowest-friction check, and update the case from the result. Another
  feature panel does not create the same causal pressure.
- **Use live takes for causality.** Stills and slides may explain sourced context, but they cannot
  prove that the product initiated work, changed state, learned, or completed a queue.
- **Show evidence, not only counters.** A scale claim needs events, receipts, or at least one
  completed packet. Rows disappearing quickly demonstrate motion, not casework.
- **Captions are optional; subtitles are exact.** Suppress duplicated text when it obscures dense
  UI. If text functions as a subtitle, it must match the spoken words.
- **One spoken action per visible step.** Use language a real operator would say, not an inventory
  of capabilities or API-like status prose. For an approved human master, the recording outranks an
  older written draft.
- **Pace by meaning.** Remove inert time, but retain the setup and decision holds that make the
  causal story legible.
- **Keep the camera connected.** One screen/session gets one clip and connected focus regions, not
  jumpy same-screen crop resets. Keep target, context, status, safeguard, and cursor visible.
- **Preserve people.** Moving customer, founder, or teammate footage retains its recorded framing
  unless the brief explicitly authorizes a punch-in.
- **Make integrations inhabited.** A Slack/email/case-system handoff lands in the customer's named
  operational context and reports completed work, exceptions, and evidence. Avoid generic internal
  channels or codenames the viewer has never met.
- **Introduce people after they speak.** Let the first complete sentence land, then use a brief
  freeze-frame name/role treatment if useful; return to the original moving composition afterward.
- **Show the work.** Open from the real entry point and include one click-to-evidence beat.
- **Redact identifiers, never the value.** Hide client marks; keep the proof sharp and legible.
- **Be honest.** Only verified claims; neither invent autonomy nor add unnecessary human gates.
- **End once.** After the operational payoff, show only necessary proof, one fresh forward-looking
  state, and one CTA.
- **Correction before look.** Product demos must preserve trust: neutral UI whites, legible text,
  stable brand colors, plausible skin, and matched adjacent shots. Do not apply a decorative
  color grade by default. UGC/founder footage should stay authentic unless the brief explicitly
  asks for a stylized commercial look; avoid global vignettes, blurred side-fill, saturation
  pushes, and brightness tweaks as defaults.

## Proof beats (the YC/PG canon rules)

How the proof shot earns belief — distilled from the YC/PG canon; violating these reads as
AI-washing to professional evaluators:

- **Proof hierarchy.** Rank what you show: real paying usage with exact numbers > pull signals
  (demand outpacing supply, users asking for features, word-of-mouth) > benchmark wins >
  pilot logos > polish. Never present pilots as product-market fit — name them as exactly what
  they are ("paid pilot, live" is strong *because* it claims nothing more).
- **Exact numbers beat adjectives.** "$11.4k in 3 months" beats "strong early traction";
  "68 → 84 in 8 iterations" beats "dramatically better". If the footage can show the number
  moving, never say the adjective at all.
- **Survive the AI-washing gauntlet.** One uncut real run on screen, exact figures, and a
  test-on-your-own-data ask in the CTA ("point it at yours"). A demo that only shows curated
  moments invites the question it can't answer.
- **Formidable register.** Plain, concise, matter-of-fact narration; confidence through
  substance, never asserted ("blazing fast" is banned; a visible timer is not).
- **Show the real authority boundary plainly.** A consequential payout, block, or policy decision
  may require one accountable signature; a reversible evidence request or research step may run
  automatically. Adding a reviewer to every step makes a real autonomous product look like a
  presentation tool, while hiding a consequential reviewer makes the demo untrustworthy.
- **Earnest beats polished.** A rough real run with real numbers outranks a beautiful
  simulation — polish only ever amplifies proof, it never substitutes for it.

## When it breaks

- **Preflight rejects a low-friction human gate** → model the real workflow. Let the agent or system
  execute reversible evidence gathering automatically; reserve the human action for the actual
  consequential boundary.
- **Preflight rejects a same-screen cut** → combine the adjacent source excerpts into one clip and
  use connected `zooms`. Add `transitionReason` only for a real route, application, or major state
  change—not to silence the check.
- **A crop makes the target larger but removes status, controls, or cursor** → widen or move the
  focus region. Legibility includes the context that explains what the UI is doing.
- **A locked customer/founder source is cropped or punched in** → remove camera transforms and use
  `objectFit: "contain"`. Preserve the recorded framing unless the source owner approved a change.
- **Global narration hash/duration fails** → restore the approved human master or deliberately
  update its contract and audit. Do not stretch, speed, or silently replace it to make the timeline
  pass.
- **No ElevenLabs key** → an auto-paced narration map stops in `vo.py` before synthesis because
  Gemini TTS does not return the character alignment required by `pace.py`. Configure
  `ELEVENLABS_API_KEY`, or deliberately disable `production.autoPaceNarration` and author timing
  another way. Gemini TTS / Lyria remain valid for non-auto-paced and legacy narration/music
  (`GEMINI_API_KEY`), and projects with supplied or locally cached audio can still render. A 401
  is deterministic—replace the key; do not retry it.
- **A VO line fails or renders empty** → `vo.py` exits non-zero (a silent shot must never ship).
  Re-run after fixing; unchanged lines are cached and not re-billed.
- **Footage shorter than the VO line** → the clip freezes on its last frame (build floors clip
  duration at VO + 0.2s). Shorten the line or cut a longer excerpt — never ship the freeze.
- **Type renders as serif** → the brand font isn't installed; `build.py` appends the bundled
  Inter stack automatically, but always check captions in extracted frames.
- **Judge scores swing between runs on identical content** (±10 documented) → median-of-3 is the
  default; confirm `--probe` passes, use order-reversed pairwise comparison, and frame-verify any
  specific claim the judge makes before acting on it. A split does not beat the champion.
- **Judge is pointed at the wrong or stale MP4** → require `artifact.json`. The
  `judge.py --require-artifact` gate rejects a path or hash that does not match the bound output.
- **The cut passes the judge but contains a black frame, silence, cropped cursor, or incomplete error
  page** → the judge cannot waive delivery evidence. Run `qa.py --require-artifact --strict` and
  inspect opening/ending, every-five-second, cut-boundary, and configured critical-range sheets.
- **Three plausible zoom, in-point, or pacing candidates lose or split** → restore the champion and
  stop mechanical recutting. Recapture a missing action/state, revise narration, or change the story.
- **Identifier discovered in a rendered frame** → fix the source excerpt (crop or trim — never
  blur-patch the render), re-render, then re-verify the excerpt's boundary seconds at ~1fps.
  A folder or file named "redacted" is not evidence of redaction.

## License

MIT licensed. See [`LICENSE`](./LICENSE) and [`THIRD_PARTY_NOTICES.md`](./THIRD_PARTY_NOTICES.md).
