# Claude Code instructions

@AGENTS.md

Treat `AGENTS.md` as the canonical repository contract. Follow it for both production work and code
changes; do not duplicate or weaken its rules here.

## Starting a task

- For a request to create, recut, capture, render, or judge a demo, read `SKILL.md` completely before
  editing files or running provider-backed stages.
- Read only the task-relevant production references named in `AGENTS.md`.
- Inspect existing product evidence before proposing a story. Ask a focused question only when the
  audience, intended change, or required evidence cannot be discovered safely.
- Keep new working projects under `projects/<slug>/` so footage, narration, renders, and QA outputs
  remain local and ignored.
- Prefer the `./pdd` commands in `AGENTS.md`. Use individual `tools/*.py` stages when diagnosing or
  intentionally controlling one stage of the documented pipeline.
- Do not invoke paid providers, capture authenticated pages, or render media merely to explore the
  repository. Run those stages only when the user's requested production requires them.

## Claude-specific behavior

- This root file loads automatically in Claude Code. Use `/memory` if you need to verify which
  instruction files are active.
- `./pdd install-skill --target claude` is optional and only needed to expose Product Demo Director
  while Claude works from another repository. Do not install it without the user's request.
- Never paste provider keys into chat or shell history. Read local configuration through the
  documented environment variables without printing values; verify a required key exists before a
  provider-backed stage.
- Do not declare a film complete from a visual impression or model score. Report the exact final
  media path and the deterministic preflight/QA result required by `AGENTS.md`.

For a typical launch request, interpret “make a demo” as: inspect evidence, identify one meaningful
change, author a source-bound single-focus story, capture missing states, synthesize or stage
narration, pace cuts between thoughts, render, finish, run strict QA, and then optionally judge.
