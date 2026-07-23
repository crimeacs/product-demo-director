# Codex directs the product demo

This is the source contract for a self-contained, one-minute Product Demo Director film. It answers
four questions in order: what the product is, what inputs it takes, what Claude Code or Codex does,
and what ships at the end.

The visible story is one concrete transformation:

1. A long raw product recording has facts but no story.
2. A human gives Codex one source-bound launch-demo brief.
3. Codex reads the product, brand, evidence, and footage; writes `script.json`; then drives capture,
   ElevenLabs narration and music, the edit, render, finish, and QA.
4. The same evidence becomes a directed product story plus an exact build plan, artifact binding,
   and deterministic QA report.

Save-the-Cat remains structural metadata. No filmmaking labels, archived judge subplot, or
repo-as-protagonist abstraction appears in the film.

## Recreate the film

Generated video, voice, music, and render output stay out of Git. Recreate the safe local footage
from [`assets/README.md`](assets/README.md), then run:

```sh
.venv/bin/python tools/preflight.py --project examples/save-the-cat --allow-pending-generated-narration
.venv/bin/python tools/vo.py --project examples/save-the-cat --provider elevenlabs
.venv/bin/python tools/pace.py --project examples/save-the-cat --write
.venv/bin/python tools/music.py --project examples/save-the-cat --provider elevenlabs
.venv/bin/python tools/preflight.py --project examples/save-the-cat --strict
.venv/bin/python tools/build.py --project examples/save-the-cat --contracts strict
.venv/bin/python tools/finish.py --input examples/save-the-cat/out/demo.mp4 \
  --out examples/save-the-cat/out/demo-final.mp4 --require-artifact --true-peak -2.0
.venv/bin/python tools/qa.py --video examples/save-the-cat/out/demo-final.mp4 \
  --project examples/save-the-cat --require-artifact --strict
```

The continuous narration uses ElevenLabs v3 with George. Provider alignment is retained in
`audio/master-timing.json`, and every visual boundary is paced into a gap between complete thoughts.
The Codex workbench is a source-defined, curated replay built from exact whitelisted production
actions—not a screenshot of a proprietary agent UI. Its disclosure and source receipts live in
[`evidence/agent-run.json`](evidence/agent-run.json). The build artifact separately hashes every
replay JSON source and the static license/capability evidence, so the post-build receipt never has
to hash itself.
