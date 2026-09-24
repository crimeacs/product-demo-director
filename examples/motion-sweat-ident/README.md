# Worked example: Sweat, "Let us sweat for you" (motion graphics, 33 s)

The approved final of a 13-iteration session (founder: "THIS IS SOOOOO GOOD! I LOVE IT").
Direction: **Ident** (see `docs/MOTION_GRAPHICS.md`). Two offers side by side: a real-time KYB /
document-check API and expert analysts who use AI, nights and weekends.

| Scene | Time | Beat |
|---|---|---|
| s1 | 0.0-3.7 | "Friday." / giant 6:02 in ink on orange; application pills glide in and stack; minute flips to 6:03 on the hit |
| s2 | 3.7-6.5 | Ink block: "Or, send us the queue." slams on the music drop; "Real-time KYB API + expert analysts who use AI" |
| s3 | 6.5-13.2 | Specimen bylaws scanned, measured callouts (entity ✓, type bylaws ✗), orange ✕; certificate accepted with ink ✓; real applicant messages |
| s4 | 13.2-17.6 | "One call." four check pills tick on the beat, "Ready." |
| s5 | 17.6-25.4 | "Some cases need a person." registry records, the right one ringed; analyst on shift; "Your team makes the call." request documents + note |
| s6 | 25.4-28.8 | The two offers, orange and ink halves |
| s7 | 28.8-33.2 | "Let us sweat for you." + wordmark |

Files: `film.html` (the film), `cues.json` (sound cues), `motion.json` (render + mix settings; the music
bed starts at 10.0 s so its drop lands on the 4.25 s slam), `music.mp3` (not committed; generate it with ElevenLabs `music_v2`, prompt below, ~44 s), `styleframes.html` + `sf_* stills` (the two style-frame directions shown before animating:
A editorial was disliked, B ident was chosen).

Truth notes: companies and people are fictional (Mawingu Test Traders, Kestrel Freight, Maya C.);
documents are marked SPECIMEN; the merchant messages are the real product's wording; the "one call"
checklist illustrates the combined offer and is not a single recorded API response.

```sh
python tools/motion.py all examples/motion-sweat-ident
```

Music prompt used (ElevenLabs music, prompt mode, 35 s requested, 44 s returned; the bed's drop sits at 14.2 s):

> Punchy modern tech launch track, 110 BPM, tight electronic drums, deep sub bass, bright plucky synth hook,
> confident and fun, no vocals. Structure: 0:00-0:03 tense filtered intro with ticking hats building; 0:03-0:04
> hard drop with a big hit; 0:04-0:17 driving groove with the synth hook; 0:17-0:25 slightly lighter half-time
> groove, warm; 0:25-0:29 build back up; 0:29-0:34 final full-energy chorus ending on a clean final hit.

The SFX palette (`engine/public/sfx/*.mp3`) is generated locally with `python tools/sfx.py`.
