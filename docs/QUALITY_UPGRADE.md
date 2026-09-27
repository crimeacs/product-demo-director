# Production quality upgrade

This pass improves the existing production pipeline and adds a local review room. It preserves
the authored footage and narration; it does not claim that automated checks establish creative taste.

## Changes that affect the film

- Crossfades hold the final outgoing picture without playing source video or speech past its cut.
- Static scale/focus settings now affect the render; framing locks keep protected footage intact.
- Short inserts reach full opacity, and cards retain their text through the cut rather than dipping
  toward black.
- Music ducks under live source speech, loops when needed, and uses one timeline-wide volume curve.
- Images wait for loading, composition themes no longer share mutable state, and Python and
  JavaScript agree on half-frame rounding.
- Build identity includes imported engine modules, configuration, and the builder itself. Asset
  staging is atomic and reuses matching files; nested logos keep their source paths.

## Narration and delivery integrity

- Voice generation preserves the previous master when synthesis or alignment fails. Cache reuse
  checks both audio and timing hashes. Pronunciation replacements align correctly to authored cues.
- Visual-only shots can occupy actual gaps between spoken thoughts. Contracts enforce cue order,
  containment, timing locks, unique IDs, source starts, and the profile's narration tail.
- Final QA combines decoding, black detection, silence detection, and loudness into one FFmpeg
  pass. A failed analyzer, missing measurement, missing proof image, or early-ending audio track
  blocks delivery.
- Finishing preserves parent provenance even when source and output share a filename stem.
- The AI judge validates artifact-bound props, cleans up uploads, stops after processing timeout,
  and labels partial reviews. Pairwise acceptance rejects incomplete or nonfinite scores and hides
  candidate/champion identity from the reviewer.
- Four transitive Node dependencies were updated through compatible audit fixes. The production
  dependency audit reports zero vulnerabilities.

## Review workflow

Run `./pdd check <project>` for a strict preflight, or add `--before-audio` before generated narration
exists. Run `./pdd review <project> --serve` to open the project at the printed local URL.

The review room provides a film player, searchable shot sequence, narration, timeline, shot loops,
findings, and source receipts. It uses exact rendered timing only when the plan matches the current
script and selected artifact. Stale inputs, altered props, and mismatched QA cannot inherit a pass.
Before a render exists, the same interface serves as a story preview. Successful demo/render runs
generate the review automatically.

The optional server binds to loopback, supports HTTP byte ranges and conditional range requests,
blocks paths and symlinks outside the project, and does not list directories. No external services
are needed. Review pages are snapshots and must be regenerated after edits.

## Verification

- Baseline: 95 Python tests passed. Updated suite: **178 tests passed**, including the actual
  TypeScript frame/mix helpers and real FFmpeg integration cases.
- TypeScript compilation and `git diff --check` passed.
- Production npm audit: **zero vulnerabilities**.
- Two small real Remotion renders verified cut colors, audio stopping at the cut, music looping,
  logo loading, frame counts, and card visibility.
- The existing 60-second showcase was copied into `artifacts/quality-upgrade/` and rendered,
  finished, and strictly verified twice. The final cut is **1,800 frames / 60.000 seconds**,
  **−17.9 LUFS**, **−2.8 dBTP**, with **zero QA findings**.
- Browser checks covered desktop and mobile layouts, exact shot selection, narration updates,
  search, looping, and the verified delivery state. Screenshots are in
  `artifacts/quality-upgrade/review-proof/`.

Live generation and model-review APIs were not called. Those paths use mocked provider regression
tests; the complete rendering check uses existing narration and footage. Capture-browser setup
remains optional and was not installed during this pass.

Generated films, review pages, and screenshots remain local under the ignored `artifacts/` folder.
No release was published and no repository commit was created.
