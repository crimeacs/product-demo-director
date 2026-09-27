# examples/autoimprove — the improved skill demos its own improver

`out/demo.mp4` (~35s) is a product demo of [auto-improve](https://github.com/crimeacs/auto-improve),
produced by this skill immediately after auto-improve rewrote the skill's own SKILL.md
(68 → 84, 4 verified keeps) — the score on screen is that run's real result.

## Provenance — every number is from a real run

| Asset | What it is |
|---|---|
| `assets/term_climb.mp4`, `assets/term_gate.mp4` | `term.py` renders of the actual 2026-07-06 session log: baseline 68, the real KEEP lines with their pairwise-gate reasons, iterations 4-7. The gate shot deliberately ends before the final score so the count-up beat owns the reveal. |
| Score beat `84/100` | The real endpoint of the run (`git log improve/skill` in this repo is the verifiable trail). |
| `assets/web_gh.mp4` | Live capture of the public GitHub repo with the synthetic cursor. |
| Audio | Gemini TTS (`Charon`) + a Lyria 3 bed, crossfade-looped to runtime and auto-ducked under VO — the full no-ElevenLabs pipeline. |

This cut also exercises the canon proof-beat rules in SKILL.md: one uncut real run,
exact numbers over adjectives, and a test-on-your-own-data ask ("point it at your file").

## Reproduce

```sh
python tools/vo.py    --project examples/autoimprove --provider gemini
python tools/music.py --project examples/autoimprove --provider lyria
python tools/build.py --project examples/autoimprove
python tools/judge.py --video examples/autoimprove/out/demo.mp4 --fps 4 --runs 3
```
