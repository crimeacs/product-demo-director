# Production contract

A product demo is publishable only when three different questions have three different owners:

1. **Is this the intended artifact, and is every factual boundary intact?** Deterministic checks.
2. **Does the rendered film clearly show the product doing the claimed work?** Evidence-backed review.
3. **Is it memorable, well paced, and worth forwarding?** Human taste assisted by an AI judge.

Do not ask a model to decide a file hash, runtime, source crop, authority boundary, or claim
provenance. Do not ask a linter to decide whether a story feels inevitable. The production contract
keeps those responsibilities separate.

## Choose a story format and a production profile

Story format and delivery profile are independent:

| Story format | Use it for | Required grammar |
| --- | --- | --- |
| `launch-film` | A public product or open-source announcement | One self-contained release story, product defined by eight seconds, agent visibly driving the work, artifact proof, and one CTA. Full-frame sequences only. |
| `save-the-cat` | A dramatic product story with transformation and emotional payoff | All fifteen canonical beats, in order. Related beats may share one real shot; the product must create the change rather than become a feature list. |
| `causal-workflow` | A real product doing consequential work | One input follows a visible cause-and-effect chain through evidence, action, result, and outcome. No forced pivot, score card, or captions. |
| `before-after` | A short transformation promo | Exactly one before/after pivot and a real proof beat. `score` or `bars` is allowed only when sourced. |
| `walkthrough` | A chaptered sales or training tour | Each chapter still needs an input, action, and result. |

Draft with an explicit format:

```sh
python tools/script.py \
  --project projects/my-demo \
  --format save-the-cat \
  --seconds 30
```

## Save the Cat for product demos

The framework describes dramatic function, not shot count. A thirty-second film can carry several
inseparable beats in one live clip through `storyBeats`; it should not become fifteen title cards.
The customer, maker, or buyer is the hero. Product Demo Director is the capability that makes a
new choice or outcome possible.

| Beat | Product-demo function |
| --- | --- |
| `opening-image` | Show the old world in one memorable visual. |
| `theme-stated` | Name the human truth underneath the workflow. |
| `setup` | Establish the hero, goal, friction, and stakes. |
| `catalyst` | Introduce a concrete disruption, failure, or deadline. |
| `debate` | Make the familiar but inadequate path genuinely tempting. |
| `break-into-two` | Commit to a new approach and enter the product world. |
| `b-story` | Introduce the relationship or belief that makes the outcome matter. |
| `fun-and-games` | Deliver the product promise through visible behavior. |
| `midpoint` | Land a false victory or false defeat that raises the stakes. |
| `bad-guys-close-in` | Let constraints, errors, or external pressure challenge the first result. |
| `all-is-lost` | Show a real failed check or consequence, not a generic red card. |
| `dark-night-of-the-soul` | Let the hero understand what the first attempt missed. |
| `break-into-three` | Combine product capability with the B-story insight into a new plan. |
| `finale` | Execute the plan and prove the transformation in the product. |
| `final-image` | Mirror the opening visual in the changed world. |

Declare the framework once; its complete beat order becomes part of the deterministic contract:

```json
{
  "production": {
    "storyFramework": "save-the-cat",
    "productBySec": 6,
    "requireLiveProgression": true
  },
  "shots": [
    {
      "n": 1,
      "kind": "clip",
      "src": "product.mp4",
      "storyBeats": ["opening-image", "theme-stated"],
      "durSec": 1.8
    }
  ]
}
```

The `production.profile` controls runtime and presentation defaults:

| Profile | Default hard maximum | Product by | Typical use |
| --- | ---: | ---: | --- |
| `announcement` | 60s | 7s | Public launch film. Single focus, narration-map coverage, thought-safe cuts, and protected narration tail. Aliases: `launch`, `open-source-launch`. |
| `yc_60` | 90s | 8s | Short YC/application cut. Alias: `yc`. |
| `yc_3m` | 180s | 15s | A complete, three-minute YC product story. Aliases: `yc3`, `yc-3m`. |
| `investor` | 180s | 15s | A causal investor demo with room for proof and context. |
| `sales` | 300s | 25s | A longer buyer walkthrough. |

`yc_60` is a one-minute editorial target with a 90-second hard safety ceiling; the linter does not
pretend those are the same thing. These are defaults, not creative mandates. The owner's approved
runtime wins; override `hardMaxSec`, `productBySec`, `maxCardRatio`, or `ctaMaxSec` in the project
contract. Never shorten a necessary setup merely to satisfy a generic social-video heuristic.

## Minimal causal-workflow contract

Add a `production` block to `script.json`. Once a project declares `production`,
`editorialContract`, `narration`, or `finalNarration`, `build.py` enables the deterministic gate in
`auto` mode.

```json
{
  "fps": 30,
  "production": {
    "profile": "yc_3m",
    "hardMaxSec": 180,
    "productBySec": 15,
    "maxCardRatio": 0.22,
    "ctaMaxSec": 5,
    "requiredStoryBeats": [
      "setup",
      "input",
      "contradiction",
      "test",
      "restraint",
      "decision",
      "receipt",
      "learning",
      "outcome",
      "handoff",
      "close"
    ],
    "requireLiveProgression": true,
    "maxHumanDecisions": 1,
    "enforceSameScreenContinuity": true,
    "cursorSafeMarginPct": 10,
    "maxConnectedZoomGapSec": 1.5,
    "requireClaimEvidence": true,
    "forbiddenPhrases": [
      "unsupported production claim"
    ]
  },
  "shots": []
}
```

Outside a named `storyFramework`, `requiredStoryBeats` is project-specific. Use only beats the real
workflow needs. A named framework supplies its own complete canonical order. In either case, a
result cannot appear before its initiating event and an outcome cannot be substituted with a
feature list.

## Shot evidence fields

Annotate product clips so the contract can distinguish continuity from repetition and automatic
work from human decisions.

```json
{
  "n": 6,
  "kind": "clip",
  "src": "case-to-receipt.mp4",
  "inSec": 0,
  "durSec": 14.2,
  "storyBeat": "decision",
  "sourceType": "product",
  "liveState": true,
  "stateId": "case-tested-awaiting-signature",
  "continuityId": "cedrus-case",
  "actor": "human",
  "actionRisk": "consequential",
  "cursorRequired": true,
  "cursorSafeMarginPct": 10,
  "claimIds": ["one-accountable-signature"]
}
```

- `storyBeat` connects the shot to the required story order.
- `storyBeats` may declare two inseparable functions in one continuous take, such as
  `["test", "restraint"]`; do not split the footage merely to satisfy metadata.
- `sourceType` distinguishes `product`, `human`, and explanatory material.
- `liveState: true` marks progressive product behavior rather than a prefilled card.
- `stateId` identifies the visible product state. Reusing a screen is not repetition when its state
  or story function advances.
- `continuityId` identifies one screen/session that must remain a single clip with connected camera
  regions. With `enforceSameScreenContinuity`, splitting adjacent shots with the same ID is an error.
- `actor` is `agent`, `human`, or `system`.
- `actionRisk` is `low-friction` or `consequential`. A low-friction human gate is rejected.
- `claimIds` link narration or UI copy to verified claims.

The product's real semantics determine the actor and risk. Do not make every action human-reviewed
to look safe, and do not make a consequential action automatic to look autonomous.
Use `maxHumanDecisions` as a ceiling. If the workflow specifically promises one accountable
signature, use `exactHumanDecisions: 1` so removing that boundary also fails preflight.

For a handoff shot (`sourceType: "external"`), preserve operational specificity: the customer's
named channel or queue, a sender the story has introduced, completed-work counts, exceptions that
still need attention, and a path to the evidence. “All done” in a generic internal channel proves
less than one actionable notification in the system the customer already uses.

## Source preservation and camera continuity

The camera must clarify the real source, not rewrite it.

When footage is generated from a committed repo-native replay, bind the replay source itself:

```json
{
  "production": {
    "sourceManifests": ["_src/codex-workbench.json"]
  }
}
```

Each entry must be a project-relative file. Preflight rejects missing files, directories, absolute
paths, and paths that escape the project (including symlinks). Build records each one as a
`capture-source` input, so changing the replay source changes the build ID and artifact provenance
even when the encoded capture filename stays the same.

Lock moving footage of people—or any source whose composition is evidence—with `sourceLocks`:

```json
{
  "production": {
    "sourceLocks": [
      {
        "src": "customer-call.mp4",
        "preserveFraming": true
      }
    ]
  }
}
```

A locked source cannot use `scale`, `startScale`, `endScale`, `panX`, `panY`, or `zooms`, and it
must not use `objectFit: "cover"` unless the lock explicitly permits it.

For product footage:

- Cut only on a route, application, or major product-state change.
- Keep one continuous take while the same screen and causal action remain visible.
- Use multiple `zooms` inside that shot. Nearby regions should pan at a stable scale instead of
  zooming out and back in.
- Keep the narrated target, necessary context, and cursor visible together. A tighter crop is not an
  improvement when it removes the status, safeguard, or action that makes the screen intelligible.
- Use `allowZoomReset: true` only when a deliberate full-frame reset serves the story.
- Use `allowZoomTailClip: true` only when the shot boundary intentionally ends an active connected
  move; otherwise a zoom extending beyond its source shot remains a preflight warning.

`tools/capture.py` writes interaction sidecars. When `cursorRequired` or
`production.requireCursorEvents` is enabled, preflight requires a readable event file and verifies
clicks against both the source-frame margin and active zoom viewport.

## Claims are source-bound

Declare claims once and reference them from shots:

```json
{
  "claims": [
    {
      "id": "seven-additional",
      "status": "verified",
      "evidence": [
        "evidence/frozen-replay.json",
        "assets/replay-live.mp4"
      ]
    }
  ],
  "shots": [
    {
      "n": 8,
      "kind": "clip",
      "src": "replay-live.mp4",
      "durSec": 12,
      "claimIds": ["seven-additional"]
    }
  ]
}
```

With `requireClaimEvidence`, every claim needs a stable ID, `verified` or `approved` status, and
resolvable local evidence. URLs may be recorded as provenance, but the shipping project should keep
the actual supporting receipt, export, or capture whenever possible.

`forbiddenPhrases` is an exact-text guard across VO, captions, titles, and subtitles. It catches
known bad language; it does not replace a semantic truth review. Customer status, pricing, measured
outcomes, and the difference between synthetic and production behavior still require an accountable
human source.

## Global narration and thought-safe picture

Short promos may continue using per-shot VO. For a generated continuous performance, author each
thought once in `narrationMap` and let ElevenLabs return exact character timing:

```json
{
  "narration": {
    "file": "audio/master.mp3",
    "model": "eleven_v3",
    "fromMap": true,
    "timingFile": "audio/master-timing.json"
  },
  "production": {
    "profile": "announcement",
    "autoPaceNarration": true,
    "narrationCutPolicy": "between-thoughts",
    "minNarrationTailSec": 0.75
  },
  "narrationMap": [
    {"id": "problem", "shotN": 1, "text": "The useful moment is buried in a flat recording."},
    {"id": "change", "shotN": 2, "text": "The agent finds it and writes the story."}
  ]
}
```

Run voice generation, pacing, then strict preflight:

```sh
python tools/vo.py --project projects/my-demo --provider elevenlabs
python tools/pace.py --project projects/my-demo --write
python tools/preflight.py --project projects/my-demo --strict
```

`vo.py` writes the provider alignment, audio/text hashes, and exact cue times. `pace.py` preserves
the authored rhythm where it can, but clamps each frame boundary to the safe gap between adjacent
thoughts. It fails instead of accelerating narration or cutting speech when no safe frame exists.

A narration-locked film with a supplied human master uses the same map with externally measured
times:

```json
{
  "narration": {
    "file": "audio/final-human-master.wav",
    "sha256": "<sha256>",
    "expectedDurationSec": 169.62839,
    "durationToleranceSec": 0.01,
    "startsAtSec": 0,
    "volume": 1,
    "mix": true
  },
  "narrationMap": [
    {
      "startSec": 0,
      "endSec": 13.2,
      "beat": "customer problem and founder response"
    },
    {
      "startSec": 13.2,
      "endSec": 29.7,
      "beat": "transcript becomes work and the case opens"
    }
  ]
}
```

Rules:

- The approved recording is authoritative. A transcript is a navigation/index artifact; if it
  differs from what the narrator actually said, cut picture to the recording unless the owner
  explicitly authorizes a pickup.
- `audio/manifest.json` must be empty when the master is mixed by the engine.
- Picture clips must be muted unless `allowSourceAudio` is explicitly declared and audited.
- Hash and duration are checked before render.
- `narrationMap` cannot overlap or run beyond picture. Under `between-thoughts`, no picture boundary
  may land inside a mapped cue; final QA repeats the check against the rendered frame plan.
- `minNarrationTailSec` is measured from the actual audio duration, not a declared estimate.
- Do not globally accelerate a supplied human performance. Reclaim runtime from redundant picture,
  recap, or CTA before damaging speech.
- If a synthetic pickup is authorized, replace a whole clause, retain the original human performance
  elsewhere, and record source samples, replacement text, provider/model/voice, seed, crossfade,
  duration delta, and output hash in a project audit file.

`finalNarration` remains supported as a validation contract for projects that perform an external
finishing/mux pass. Use `narration` when the engine should stage and mix the global master itself.

## Exact frames and artifact binding

Seconds are an authoring convenience; frames are the delivery truth.

`build.py` converts every shot to an integer frame count, calculates one canonical `totalFrames`,
and writes beside the render:

- `props.json` — the exact engine inputs;
- `build-plan.json` — script, brand, source hashes, frame boundaries, and build ID;
- `artifact.json` — output path/hash, measured media, expected frames/runtime, and source records.

Referenced assets are staged in a content-derived, build-scoped Remotion public directory. Render
receives that directory explicitly, so it neither bundles stale `engine/public` footage nor lets two
projects with the same filename contaminate one another.

Always require the artifact manifest when reviewing a final candidate. This prevents an old or
similarly named MP4 from being judged by mistake.

### Finish without losing provenance

The creative Remotion render may still carry browser/encoder color labels or unmastered audio. Make
a separate delivery master; never overwrite the creative source in place:

```sh
python tools/finish.py \
  --input projects/my-demo/out/demo.mp4 \
  --out projects/my-demo/out/demo-final.mp4 \
  --require-artifact \
  --target-lufs -18 --true-peak -1.5
```

`finish.py` performs measured two-pass loudness normalization, writes 48 kHz AAC, converts the
picture to limited-range BT.709/yuv420p, preserves the exact frame count, copies the bound props and
build plan, and emits `demo-final.artifact.json` linked to its parent render. QA and judging should
target the finished MP4. Use `--no-loudnorm` only when an upstream master is already locked.

## Deterministic production gate

Run preflight before spending time on a render:

```sh
python tools/preflight.py \
  --project projects/my-demo \
  --profile yc_3m \
  --strict \
  --out projects/my-demo/out/preflight.json
```

Dry-build and inspect the exact frame plan:

```sh
python tools/build.py \
  --project projects/my-demo \
  --profile yc_3m \
  --contracts strict \
  --dry
```

Render only after preflight passes:

```sh
python tools/build.py \
  --project projects/my-demo \
  --profile yc_3m \
  --contracts strict \
  --out projects/my-demo/out/demo.mp4
```

Then run final-media QA:

```sh
python tools/qa.py \
  --video projects/my-demo/out/demo-final.mp4 \
  --project projects/my-demo \
  --require-artifact \
  --strict
```

`tools/qa.py` verifies the artifact hash, full decode, audio/video streams, exact frame count and
duration, black intervals, unintended silence, and optional loudness/peak targets. It creates a
machine-readable report plus opening, ending, every-five-second, cut-boundary, and declared
critical-range sheets.

Configure delivery QA inside `production.qa`:

```json
{
  "production": {
    "qa": {
      "blackMinSec": 0.1,
      "silenceNoiseDb": -48,
      "silenceMinSec": 0.7,
      "allowedSilenceRanges": [
        { "startSec": 9.8, "endSec": 11.4, "reason": "intentional call reaction" }
      ],
      "allowedBlackRanges": [
        { "startSec": 174.2, "endSec": 174.7, "reason": "intentional final fade" }
      ],
      "targetLufs": -18,
      "lufsTolerance": 1,
      "maxTruePeakDbtp": -1.5,
      "contactEverySec": 5,
      "criticalRanges": [
        {
          "id": "cursor-transition",
          "startSec": 150.23,
          "endSec": 152.73,
          "everyFrame": true,
          "checks": ["cursor visible", "no crop reset"]
        }
      ]
    }
  }
}
```

Generated sheets are evidence for inspection, not an excuse to skip it. In particular, review every
frame of high-risk cursor/camera transitions and both sides of every cut.

## Deterministic checks versus AI review

| Deterministic and blocking | AI-assisted and advisory |
| --- | --- |
| Exact input/output path and SHA-256 | Whether the causal story is clear after one watch |
| Asset existence, duration, and frame boundaries | Whether the unique differentiation is memorable |
| Runtime/profile limits and CTA boundary | Narration naturalness and information density |
| Global narration hash, duration, and double-mix prevention | Buyer comprehension and emotional pacing |
| Source framing locks and same-screen continuity declarations | Whether a hold feels deliberate or merely slow |
| Cursor event/margin checks | Whether the final proof feels satisfying |
| Claim IDs, evidence files, exact forbidden phrases | Semantic trust risks that exact-text lint cannot catch |
| Human/automatic authority annotations | Visual hierarchy and legibility in context |
| Artifact binding, full decode, black/silence/loudness gates | Comparative taste between two otherwise valid cuts |

An AI score can never waive a deterministic failure.

After deterministic QA passes, bind the judge to the exact artifact:

```sh
python tools/judge.py --probe \
  --probe-good projects/my-demo/out/demo-final.mp4

python tools/judge.py \
  --video projects/my-demo/out/demo-final.mp4 \
  --require-artifact \
  --props projects/my-demo/out/props.json \
  --fps 6 \
  --runs 3 \
  --context "A causal live-product demo for a first-time buyer"
```

Before delivery, run independent lenses instead of trusting one blended aesthetic score:

```sh
python tools/judge.py --video projects/my-demo/out/demo-final.mp4 \
  --require-artifact --all-lenses --runs 1 --fps 6
```

The story, product-truth, visual-continuity, and first-time-buyer reports remain separate. Their
weakest result is the review floor; a high polish score cannot average away weak product truth. Use
median `--runs 3` on the lens that actually gates the next revision.

For live-product profiles, remaining on one screen is continuity when product state or evidence
advances. The judge should penalize replayed conclusions or repeated states with no new story
information—not the source filename.

For forensic continuity review, inspect contiguous short clips at high sampling FPS and require a
timestamped finding with visible evidence. Whole-video model passes are useful for coarse narrative
lenses, but they can miss single-frame defects or invent timestamps. Reject findings outside the
measured runtime or unsupported by the transcript, frames, or evidence manifest.

## Improve loop and the cut-mechanics plateau

Run the improve loop like an experiment:

1. Keep a reproducible champion.
2. Change one hypothesis at a time.
3. Pass deterministic preflight and final QA before any aesthetic comparison.
4. Compare champion and candidate in both display orders.
5. Ship a candidate only when it wins both comparisons and violates no fixed contract.
6. Treat a split verdict or roughly two-point score movement as noise.
7. Restore the champion after a rejected candidate.
8. After three plausible mechanical candidates fail, stop adjusting in-points, zooms, and pacing.

The reusable gate performs these checks directly:

```sh
python tools/compare.py \
  --champion out/champion.mp4 --champion-artifact out/champion-artifact.json \
  --candidate out/candidate.mp4 --candidate-artifact out/candidate-artifact.json \
  --candidate-qa out/candidate-qa/qa-report.json \
  --champion-score 68.0 --candidate-score 70.4 --noise-floor 2
```

Exit `0` means ship; exit `2` means retain the champion or treat the result as inconclusive.

Three rejected recuts of the same payout-review film established the plateau rule: a shorter open
lost the story and cropped necessary UI; corrected zooms moved only inside judge noise; pacing alone
did not improve the integrated film. The next real gains came from a human narration master, fresh
causal capture, progressive reasoning, bounded authority, packet-backed queue proof, and a truthful
finale.

When the recurring complaint requires a new action, source, line, or product state, classify it as
`recapture`, `narration change`, `claim change`, or `product change`. Do not disguise it as a recut.
