# Product Demo Director agent instructions

## Mission

Turn real product evidence and footage into a self-contained product story whose claims, cuts, and
final file are verifiable. Direct the viewer's attention; do not produce a generic onboarding tour,
feature inventory, or unsupported marketing reel.

The customer, operator, or maker is the hero. The product creates the visible change. An agent may
drive the production workflow, but must not become a substitute for product proof.

## Read before acting

- Read `SKILL.md` completely before creating, recutting, or judging a film.
- Read `docs/PRODUCTION_CONTRACT.md` when changing profiles, story beats, claims, authority,
  narration, source locks, camera continuity, artifact binding, or delivery gates.
- Read `docs/CAPTURE.md` before recording a browser, terminal, or agent-operated workflow.
- Read `docs/EDITING.md` before making editorial or pacing decisions.
- Read `CONTRIBUTING.md` before changing repository code or opening a pull request.

Keep this file concise. Put detailed production rules in the documents above and update the closest
source of truth when behavior changes.

## Choose the workflow

1. **New public announcement:** start from the default 60-second, single-focus project.
2. **Dramatic transformation:** use the Save-the-Cat format and keep the product causal.
3. **Consequential or investor workflow:** use the causal-workflow format so input, decision,
   receipt, and outcome remain connected.
4. **Existing authored audio:** use `render`; do not synthesize replacement narration.
5. **Code or contract change:** add focused tests and do not use a generated MP4 as source code.

Do not default to a walkthrough. Establish what changed, why it matters, how the product caused it,
and what proves the outcome.

## Standard commands

```sh
# Workstation setup
./pdd setup                    # add --with-capture only when browser capture is needed
./pdd doctor

# Create and finish a default announcement
./pdd new projects/my-demo --name "My Product"
# Add source footage under projects/my-demo/assets/ and author the production contract.
./pdd demo projects/my-demo

# Existing narration/music, or optional advisory review
./pdd render projects/my-demo
./pdd demo projects/my-demo --judge

# Repository validation
./pdd test
git diff --check
git status --short
```

Copy `.env.example` to `.env` for local provider keys. The default auto-paced announcement requires
`ELEVENLABS_API_KEY`; Gemini is optional for non-auto-paced TTS, music, and advisory judging. Never
print keys, place them in commands or transcripts, or commit `.env`.

`./pdd install-skill` links this checkout into Codex and Claude Code for use from other repositories.
Do not run it unless the user asks for installation; it is not required when working in this clone.

## Directing contract

- Inspect the product, supplied footage, repository state, and evidence before writing the story.
- Use one audience, one central change, and one release promise. Make the product clear by seven
  seconds for an announcement unless the selected profile says otherwise.
- Prefer full-frame sequences. Split screen is disallowed by the default single-focus contract and
  may appear only in an explicitly opted-in legacy profile.
- Use live product states for causality. Stills may explain a sourced fact but cannot prove a state
  transition.
- Keep one continuous source/session in one clip with connected zoom regions. Never simulate
  progress by replaying a conclusion or resetting the same screen with a new crop.
- Motivate every cut and zoom with a new idea, action, state, or piece of evidence. Keep relevant UI,
  people, and cursors inside safe framing.
- Author narration as complete thoughts. For auto-paced projects, generate alignment, run
  `pace.py`, and place picture cuts between thoughts—never through them.
- End on concrete product proof and one CTA. Do not replace proof with a summary card.

## Truth, capture, and safety

- Never invent product behavior, claims, metrics, receipts, customer data, or UI states.
- Bind public claims to project-relative evidence through the production contract. A URL alone is
  not a substitute for the local evidence required by a strict artifact.
- Treat browser sessions, terminal output, logs, manifests, and recordings as potentially
  sensitive. Remove identifiers at the source before capture; do not blur-patch a final render.
- Never put production credentials in capture plans, commands, transcripts, fixtures, or commits.
- Capture authenticated products only with a dedicated seeded or staging account. Keep reusable
  browser state outside the repository and invalidate it after recording.
- Keep consequential human decisions visibly human. Do not portray an agent as having authority it
  did not have.
- A generated workbench replay must come from an allowlisted, committed session and be labeled as a
  curated replay. Do not present it as a recording of proprietary Codex or Claude UI.
- Do not let an AI judge waive preflight, hash, frame, decode, audio, black-frame, silence, evidence,
  or authority failures.

## Files and repository boundaries

- `script.json`, `brand.json`, `product.json`, `shoot.json`, evidence files, and capture-source
  manifests are editable production sources.
- Inspect the Git worktree before editing and preserve unrelated user changes.
- `pdd` is the friendly orchestrator. `tools/contracts.py` owns deterministic production policy;
  the remaining `tools/` files implement individual stages.
- `engine/src/` is the Remotion composition; `tests/` contains Python contract regressions.
- `projects/`, `artifacts/`, per-project `audio/` and `out/`, captures, and generated media stay
  local and are ignored by Git.
- Do not hand-edit generated props, build plans, QA reports, artifact manifests, hashes, or final
  media to make a gate pass. Fix the source and rerun the pipeline.
- Do not overwrite source media during finishing. Write `demo-final.mp4` and its inherited artifact
  beside the creative render.
- Never force-add generated media. The only exception is a small, intentional, reviewed public
  fixture with redistribution rights and an `ASSET_PROVENANCE.md` entry.

## Definition of done

A film is not finished until:

1. Strict preflight passes on the final authored sources.
2. The render, finishing pass, and strict final-media QA succeed with `--require-artifact`.
3. The final MP4, artifact manifest, source hashes, exact frame count, duration, streams, and decode
   all refer to the same file.
4. Opening, cut boundaries, critical ranges, proof, CTA, and ending have been visually inspected;
   narration is not clipped and the protected tail remains.
5. Every visible claim and authority boundary is supported. Any optional judge runs only afterward.

A repository change is not finished until `./pdd test` and `git diff --check` pass, user-facing
behavior is documented, relevant regression tests exist, and no secrets, customer material, local
paths, or generated production files entered the diff.

## Code Review Rules

Flag changes that weaken strict contracts, permit project or symlink escapes, detach a final file
from its artifact, treat advisory model output as a gate override, crop away source truth, expose
credentials or private footage, or change frame math without a regression test. Prefer a narrow fix
to disabling a production check.
