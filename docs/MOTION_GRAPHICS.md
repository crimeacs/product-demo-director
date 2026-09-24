# Motion-graphics films

Some films are best made without footage: a brand/launch spot where the product's value is told in
designed moments. This track produces those films as code (HTML/CSS + `motion/kit.js`), renders them
frame-exact with real motion blur, mixes music and sound design, and gates delivery on deterministic QA.

Worked example: `examples/motion-pdd-self/` (this repository's own 30 s film, 16:9, in the Cutting room
direction). The method below was distilled from a 13-iteration client launch spot the founder called
"so good", and tested on a vertical 9:16 ad with a different concept, look, score and sound palette.

## The method (do not skip steps)

1. **Brief in one breath.** Who buys, the two or three things they must remember, and the one feeling.
   Write the value-led close line first (e.g. "Evidence in. A directed film out."), not a clever negative
   ("Don't post the job" was rejected as not value-led).
2. **Style frames before animation.** Design 2 to 3 genuinely different directions as stills in
   `styleframes.html` (one section per frame, selected by `?f=`), 2 to 3 frames each: hook, proof, close.
   Render them with `motion.py styleframes <project> f=A1 f=A2 f=B1 ...` (writes a sheet). Show them. Ask which frames the founder likes and
   dislikes, and why. Animating before a direction is chosen wasted hours in the example.
3. **Lock the timeline.** A scene table (`SC`) with second-accurate boundaries. Music and every sound
   cue are timed to it, so later polish never breaks sync.
4. **Build scenes in the chosen language**, one idea per scene, then render review stills of every scene
   and look at them at full size (not only a contact sheet).
5. **Render, mix, QA** (`motion.py all`), then watch the finished file end to end.
6. **Iterate on the founder's words literally.** "Smooth" meant one element (the queue), not the film.
   Ask or look closer before changing everything.

## Direction catalogue

Pick contrasting ones for the style frames; invent new ones when the brand calls for it.

| Direction | Language | When |
|---|---|---|
| **Ident** (chosen for the benchmark spot) | Solid colour blocks (hot accent / ink / cream), huge grotesque cropped off-frame (Bricolage 800, tight tracking), pills with flat offset shadows, roundels, ✕ / ✓ verdict discs, hard colour-block wipes | Confident startup launch, punchy social cut |
| Editorial | Paper stock + grain, large serif with italics (Instrument Serif), hairline rules, ledgers, ink stamps | Premium, calm, trust-heavy brands (the benchmark's founder rejected it for a punchy startup) |
| Kinetic UI | Dark charcoal, one accent, redrawn product objects (specimen docs, check lists, analyst card), measured AI callouts | Product-proof heavy films |
| Blueprint set | A drawing sheet that persists across scenes: registration marks, a title block with live fields (drawing no., time, scale, status), line art drawn on by stroke reveals, detail bubbles (DETAIL A/B) that enlarge the decisive part, a parts-list table with the right row ringed, one warm signal colour | Stories about time, process, precision, reliability |
| Cutting room (the worked example) | Warm film stock, running sprocket bands top and bottom, a live timecode, a clapperboard slate, edit-timeline tracks in ink / violet / tape yellow, a red playhead and cut markers that snap into place, a film strip of real output frames | Tools for makers, anything about editing, production or shipping |
| Swiss poster | Off-white, signal red block, strict grid, huge numerals | Bold data-led statements |
| Paper cut | Pastel paper layers with soft shadows, friendly rounded type | Warm, human, consumer-facing brands |
| Soft 3D | Real 3D plates (Blender scripts) composited under 2D type | Only when the brand is tactile; costs time |

## Make it look designed, not animated slides

The first cut of the boundary test was rejected as not "designed": each scene was a good slide, but the
film had no system. What fixed it (v1 -> v2 of the vertical test ad):

- **A persistent frame that belongs to the metaphor.** One set of chrome lives above every scene and never
  wipes away: the drawing sheet's border and title block, the film's sprockets and timecode. Scenes change
  inside it. That frame is what makes 20 seconds read as one designed object.
- **Live fields in the chrome.** A clock, timecode or status in the frame keeps counting through the
  transitions; it ties the scenes to one timeline and rewards a second viewing.
- **Borrow the notation of a real craft.** Detail bubbles, dimension lines, parts lists, slates, cut
  markers. Real notation carries meaning (DETAIL A is where to look) and reads as expensive; decoration
  does not.
- **One recurring hero device** that changes meaning per scene (a giant outlined timestamp rolling
  through the sheets; a playhead that becomes a cut marker).
- **Collision pass before rendering.** Render stills at the busiest moment of every scene and check
  labels, chrome and hero type for overlaps at full size; v2 needed four nudges that the contact sheet hid.

## Craft rules (from Ben Marriott's commentary and the founder's feedback)

- **One idea per screen, big type.** Readable at a glance on a phone. Never busy product screenshots.
- **Premium and playful, never sterile.** Every scene has one satisfying moment (a verdict pop, a ring
  drawn around the right record, a minute flipping on the beat).
- **Hits snap, flows glide.** Use `pop()` (overshoot + squash) for stamps, verdicts and slam words; use
  `glide()` (eased arrival, soft settle, slight tilt that straightens) for lists and queues, plus a slow
  idle float and a decaying `wobble()` when the world reacts to a hit. A queue that pops like a stamp
  reads as jittery (founder feedback, v11 -> v13).
- **Hold, then hit.** Stillness before the big moments; limited animation gives the flashy moments room.
- **Detail density without clutter.** Real-looking specimen documents (headers, fields, seal, signature,
  SPECIMEN watermark), boxes measured to the exact text (`callout()`), real messages in quotes. The founder
  explicitly asked to keep this level of detail.
- **Colour with confidence.** A limited palette with one hot accent; full-bleed colour moments.
- **Analogue finish, lightly.** Grain overlay; nothing that takes over.
- **Transitions are designed.** Colour-block wipes from a direction (`sceneWipes()`), never a generic fade.
- **Sound on every hit.** A cue sheet (`cues.json`) with one cue per visible event; one music bed with its
  drop landing on the turn (`musicOffsetSec` aligns them). A new film deserves its own sound: write
  `musicPrompt` (instruments, BPM, timed structure, no artist names; the provider rejects them) and
  `sfxPrompts`, then `motion.py music` and `motion.py sfx` (palette in `<project>/sfx`, `sfxDir: "sfx"`).
  Map the bed's energy before placing the offset; beds often open with a silent fade-in.

## Never again (rejected in the example)

- Real product screenshots in the frame ("crazy complicated and cluttered").
- A TTS narrator ("very AI and not fun to watch"). Music + SFX + type carry it; add a human voice only if supplied.
- AI-generated footage or cinematic AI trailers ("AI slop"); AI re-animations of our frames ("too simple").
- Generic dark-glass UI or plain light UI themes ("cheap, not like an expensive designer designed it").
- Negative or clever-but-empty close lines; lead with the value.
- Claims the evidence cannot back: label illustrative checklists honestly, never invent metrics or speeds.

## Technical contract

- Setup once: `cd engine && npm i -D playwright && npx playwright install chromium` (the renderer uses Node
  Playwright; or point `PLAYWRIGHT_MODULE` at an existing `playwright/index.mjs`). Generate the SFX palette
  with `python tools/sfx.py`, and a music bed per film (ElevenLabs music) when the film has one.

- `window.DUR` seconds; `window.seek(t)` renders the full frame for `t`, deterministically, from any order.
  No clocks, no requestAnimationFrame, seeded randomness only. Never give an element `id="ready"`.
- Frame size: 1920x1080 by default; declare `window.SIZE = [1080, 1920]` for vertical (any even size).
- Every scene container must fill the stage (`inset:0`). An absolutely positioned container without a size
  makes its text wrap at nearly zero width (every word on its own line).
- Fonts come from `motion/fonts/fonts.css` (OFL, bundled) so headless renders match.
- Avoid expensive CSS in every frame (`backdrop-filter`, stacked large blurs): it made one render 4x
  slower for an effect nobody could see.
- `tools/motion_render.mjs` serves the repo locally, renders with N parallel Chromium workers, and averages
  4 sub-frames over a 180-degree shutter per output frame (1080p60, about 6 minutes for 33 s on 10 cores).
- `motion.py qa` fails on silence, black frames or loudness outside -16.5 to -12.5 LUFS; then look at the
  contact sheet and the finished file yourself.

```sh
python tools/motion.py new projects/my-film
python tools/motion.py stills projects/my-film 1.5 6 12 20 30
python tools/motion.py all projects/my-film      # render -> mix -> qa
```
