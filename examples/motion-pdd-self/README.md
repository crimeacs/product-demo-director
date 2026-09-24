# Worked example 3: Product Demo Director, "Evidence in. A directed film out." (16:9, 30.5 s)

This repository's own film, made with the motion-graphics track.

- **Style frames first:** `styleframes.html` holds two directions (D1 Cutting room: film stock, ink,
  violet and tape-yellow edit tracks; D2 Projector: black, cream serif, warm light). D1 was animated.
- **Concept:** the tool told in its own craft's notation. A slate claps ("Your product has a story."),
  evidence chips fly into the director and its stages tick off, cut markers start mid-word and snap into
  the gaps between spoken thoughts ("Speech controls picture."), a film strip runs frames from this
  very film ("No footage? Motion graphics."), a receipt prints the delivery checks ("Cut. Print. Ship the
  exact file it checked."), close: "Evidence in. A directed film out."
- **Persistent frame:** running sprocket bands and a live timecode sit above every scene.
- **Sound:** its own `music_v2` bed (hit at 6.2 s, so `musicOffsetSec` is 2.0 and the hit lands on the
  4.2 s turn) and a per-film palette (clapperboard, thud, whoosh, pop, tick, magnetic snap, projector,
  receipt printer).

Truth notes: every stage and check named in the film is one this repository runs (see the README's
pipeline); `app.yourco.com` and `yourco deploy` are placeholder inputs; the strip frames are stills of
this film's own scenes (`img/`).

```sh
python tools/motion.py sfx examples/motion-pdd-self     # needs ELEVENLABS_API_KEY
python tools/motion.py music examples/motion-pdd-self
python tools/motion.py all examples/motion-pdd-self
```
