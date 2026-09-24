# Worked example 2: Sweat, "Onboarding that never clocks out" (vertical 9:16, 21 s)

Built as a boundary test of this track: a different concept, format, palette, typography, motion language,
music and sound palette from `examples/motion-sweat-ident`, following `docs/MOTION_GRAPHICS.md` step by step.

- **Style frames first:** `styleframes.html` holds three directions (C1 Swiss poster, C2 night blueprint,
  C3 paper cut); `styleframes_sheet.jpg` is what `motion.py styleframes` rendered. C2 was animated.
- **v1 -> v2, "push it to be designed":** v1 was a sequence of good slides. v2 (this file) became one
  designed object: a persistent drawing sheet (registration marks, a title block whose TIME and STATUS fields
  keep counting), giant outlined timestamps as the recurring hero, an isometric document with dimension
  lines, DETAIL A / DETAIL B bubbles on the rejected and accepted documents, a schematic bus for the one
  call, and a parts-list table with the analyst's match ringed. See "Make it look designed" in the docs.
- **Concept:** flip the story. Friday 6 pm the office goes dark; a clock rolls through the night while
  uploads are checked on arrival (bylaws rejected, certificate accepted), one API call resolves four checks,
  an analyst's lamp switches on for the hard call; Monday 9:00 at dawn the queue is clear.
  Close: "Onboarding that never clocks out."
- **Motion language:** line art drawn on with stroke reveals, glide-in type, a night-to-dawn sky.
- **Sound:** `motion.py music` (ElevenLabs music_v2, prompt in `motion.json`; the bed opens with 1.6 s of
  near-silence so `musicOffsetSec` is 1.6) and `motion.py sfx` (a per-film palette from `sfxPrompts`:
  pencil draw, scanner sweep, reject blip, accept chime, relay tick, lamp, dawn swell, clock roll).
- **QA:** 1080x1920, 60 fps, 21.0 s, -13.9 LUFS, no silence, no black frames (`contact_sheet.jpg`).

Truth notes as in example 1: fictional companies and people, SPECIMEN documents, real applicant wording,
and an illustrative "one call" checklist.

```sh
python tools/motion.py sfx examples/motion-sweat-nightshift     # needs ELEVENLABS_API_KEY
python tools/motion.py music examples/motion-sweat-nightshift
python tools/motion.py all examples/motion-sweat-nightshift
```
