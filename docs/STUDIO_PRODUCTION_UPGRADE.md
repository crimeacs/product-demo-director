# Studio production upgrade — 2026-09-15

This pass upgrades the film-producing system: source-grounded planning, a compiled motion treatment,
frame-addressable rendering, typography, camera choreography, transitions, annotations, sound, and
the creative review criteria. The production grammar is documented in [STUDIO_DIRECTION.md](STUDIO_DIRECTION.md).

## What changed

- **Planner:** studio intent per shot, coherent type and motion rules, source limits, narration density,
  and bounded repairs containing the rejected draft. Owner production constraints take precedence.
  Edited capture click sidecars supply observed targets and exact timestamps automatically.
- **Direction compiler:** resolved treatment without rewriting story or narration; explicit camera
  paths win, source framing locks remain authoritative, classic projects retain their old treatment.
  New projects default to studio; `pdd direct PROJECT --write` opts an existing project in.
- **Motion:** deterministic camera arrivals with zero velocity/acceleration at reading holds, bounded
  source transforms, opaque reveal/push transitions over a frozen outgoing picture, and no tail audio.
- **Composition:** optically fitted headline lines, authored emphasis, masked/staggered type, brand
  de-duplication, restrained product staging, and annotations attached to the fitted source plane.
  Portrait and 4:3 geometry accounts for contain/cover placement. Legacy zoom behavior is retained.
- **Sound:** three deterministic local editorial cues, sparse automatic placement, authored cue timing,
  and explicit silence. Silent studio builds no longer require unused legacy sound assets.
- **Contracts:** finite/range checks, source-grounded camera targets, camera/click visibility, no conflicting
  camera systems, and explicit real values for studio score/bar graphics. Compiled direction and sound
  inputs are bound to the build and the exact delivered film.
- **Creative review:** judge prompts evaluate hierarchy, reveal completion, reading holds, motivated
  motion, annotation alignment, and sound restraint. They require observed defects, not invented ones.

## Rendered evidence

Generated media stays local and ignored by Git. The reusable study script is in `examples/studio`.

| Film | Local output | Picture | Audio | Strict QA |
| --- | --- | --- | --- | --- |
| Motion study | `artifacts/studio-showcase/out/demo-final.mp4` | 26.5s / 795 frames | −18.1 LUFS / −3.6 dBTP | Pass, zero findings |
| Existing announcement, studio treatment | `artifacts/studio-announcement/out/demo-final.mp4` | 60s / 1800 frames | −17.9 LUFS / −3.2 dBTP | Pass, zero findings |

The announcement preserves the original narration bytes, narration alignment, shot durations,
source ranges, title wording, and claims. Its treatment changes independently of those editorial
inputs. The study was revised after inspecting rendered frames: an annotation spanning a changing
layout was removed, and the ending proof was returned to its full framing for legibility.

The exported H.264/AAC deliveries are BT.709 limited-range/yuv420p with measured two-pass loudness
normalization. Each has its own artifact, build plan, compiled direction plan, props, QA receipt,
and local review page. Final images and playback were inspected; samples are under
`artifacts/studio-inspection`. QA verifies media and provenance, not artistic equivalence to a studio.

## Verification

- 248 Python/TypeScript-backed regression and integration tests pass.
- Engine TypeScript check, `git diff --check`, and local dependency doctor pass.
- Tests include real dry builds, deterministic cue PCM/WAV generation, source staging, malformed
  direction input, source locks, classic compatibility, source aspect ratios, cursor visibility,
  capture-event grounding, narration preservation, and FPS override transition budgets.
- No new rendering dependencies or external services were added. Live model drafting/judging was
  not run because this environment has no configured generation/judge key; planner repairs and
  grounding were exercised through local fixtures.

The pre-existing working tree was preserved. This pass does not publish or commit the project.

## Editorial production follow-up — 2026-09-16

A client review exposed two problems that export QA alone could not catch: a menu cut
after its opening action and a findings sequence whose useful content arrived too late. The
director now gives these decisions an explicit, reusable representation:

- `sourceTimeline` compiles continuous recorded footage into realtime action, bounded navigation
  speed, and inspected reading holds. Source events, cursor checks, contracts, and rendering share
  the same frame map. Human decisions and native-audio footage retain realtime playback.
- `sourceBeats` connects an observed event to an aligned spoken thought. `pdd editorial` reports
  missing action lead-in, late evidence, short reading windows, unanchored narration, and first
  declared proof. Missing observations stay unknown; warnings are advisory.
- Review pages show the story-timing report only when it matches the selected rendered artifact.
  Input snapshots preserve the exact script, brand, evidence, media, and engine used in each build.
  Changed code or parsed JSON cannot silently acquire a successful receipt for different inputs.
- Build fixes cover project-root logos, FPS overrides before source compilation, failure-safe
  publication, and empty claim evidence. A zero-byte receipt or directory cannot satisfy local
  evidence validation; valid binary evidence remains supported.
- Review seeking and looping use one frame-boundary helper with a 0.5-microsecond tolerance for
  browser clock rounding. Seeking to frame 694 at 30 fps keeps shot four selected even when the
  browser reports 23.133333 seconds. Playback does not advance a half frame early.
- The production skill now requires checking narrated quantities and absolute claims against the
  actual evidence and its limits. Advisory judge scores are not a mandatory shipping gate.

The isolated client candidate runs 67.300 seconds from a preserved,
aligned 92-second working master. It removes five complete statements, including two unsupported
absolute claims; presents the ledger at 23.133 seconds; preserves the account-menu opening; and
uses focused camera arrivals, an explicit policy spotlight, and a restrained typographic close.
The separately recorded shopper test and API exchange are labeled in the film. The API transcript
was reproduced byte-for-byte from the frozen request/response evidence and is bound with it.

The final regression run passes **318 tests**, including actual rendered source-timing pixels,
real dry builds, evidence binding, advisory-report isolation, and empty-evidence regressions.
The engine TypeScript check and `git diff --check` pass. See
[EDITORIAL_DIRECTION.md](EDITORIAL_DIRECTION.md) for authoring and interpretation.
The subsequent player boundary correction passes 28 focused review/server/timing tests and was
verified in the browser against the reported fractional seek. It changes no rendered media.

The candidate keeps a visible first-proof advisory at 18.067 seconds against the default 15-second
target. The edit preserves the recorded intake-to-investigation-to-shopping sequence. These checks
do not measure audience retention or certify artistic quality; watch the finished film and test
engagement with viewers.
