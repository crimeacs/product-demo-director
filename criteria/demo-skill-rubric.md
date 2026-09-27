# Demo-Production Skill (SKILL.md) — Quality Criteria

Anchors: 50 = an average tool README, 70 = a good runbook, 90+ = an agent following it cold
ships an honest, verified, investor-grade demo on the first pass. Reward operational
precision, not length. Penalize vibes-only guidance, unverifiable claims, and any
instruction an agent cannot act on mechanically.

## Dimensions (total: 100)

### Operator clarity (20 points)
- A cold agent can run the full pipeline start-to-finish from the doc alone: exact commands,
  in order, with inputs and outputs named per step (0-8)
- Environment and providers: which keys enable what, what runs without them, how fallbacks
  are selected (0-6)
- Every optional step says when to skip it and what is lost by skipping (0-6)

### Mechanically verifiable craft rules (20 points)
- Rules are mechanical, not aspirational: numbers, ceilings, and lints an agent can check
  programmatically (narrated-card hold = VO + fixed tail; runtime bounds per mode;
  caption text == spoken line) (0-8)
- Each rule states the specific on-screen failure it prevents, so an agent can recognize
  the violation in rendered frames, not just recite the rule (0-6)
- Rules cover hook, dead air, repetition, and studio craft: camera moves motivated by visible
  evidence and followed by reading holds; clear type hierarchy and complete line reveals;
  cuts/masks that preserve the action and its consequence; source-aligned annotations;
  sparse sound cues that support real actions and preserve speech (0-6)

Studio craft review must inspect the rendered result at delivery size, including the incoming
transition, camera landing, reading hold, and final frame of each title. A type entrance earns no
credit if the complete text never becomes readable. Source context and cursor must survive the
camera move; annotation boxes must remain anchored through it and avoid covering the evidence.
Do not reward a high effect count, constant movement, or a whoosh on every cut. A clean cut, stable
hold, and silence can be the better treatment. Report concrete timestamps, what the viewer cannot
understand or read, and the smallest correction that fixes it.

### Honesty & verification protocol (20 points)
- Verified numbers only: every on-screen claim traceable to a named source the doc
  identifies; no invented metrics (0-5)
- Redaction as a protocol: list the identifiers present in source footage, state the
  removal method (crop, trim, blur), then verify on RENDERED frames — extract at ~1fps
  plus the boundary seconds of every excerpt; never trust a folder or file labeled
  "redacted" (0-5)
- Judge discipline: run the known-bad/known-good probe (`judge.py --probe`) before
  trusting any score; pin an exact model version (gemini-2.5-flash — never a floating
  alias); temperature 0; median of ≥3 runs; read `overall_model` for iteration deltas;
  set the pass bar relative to committed reference cuts, and stop chasing the score when
  changes would violate the mode contract. Use independent story, truth, visual, and buyer
  lenses; the visual lens must inspect the studio craft rules above. Treat sparse sampling and
  unavailable audio as review limits, not proof of a clean result. Neither a model score nor
  clean technical QA certifies top-studio creative quality (0-5)
- Narrative safety: footage and quotes must never read as the product failing — check
  every customer quote out of context; frame honestly and positively, never by inventing
  claims (0-5)

### Story spine (15 points)
- One protagonist, one workflow, before → product-loop → proof → ask; no feature tours (0-4)
- Mode contracts are explicit (e.g. YC: product mid-action first, no wrapper music,
  runtime target, founder-video refusal) with the reasoning attached (0-4)
- Proof-beat discipline: a stated proof hierarchy (paying usage > pull > benchmarks > pilot
  logos > polish), exact numbers over adjectives, and a test-on-your-own-data ask in the
  CTA for AI products (0-4)
- The ending answers what changed for the protagonist (0-3)

### Schema completeness & fidelity (15 points)
- Every script.json field documented with type, default, and effect (0-6)
- Field interactions stated: VO floors vs card ceilings, sound:true, flash/pivot, clicks
  and zoom targeting, take bars; authored camera paths vs legacy framing and source locks;
  title lines vs exact claim text; reveal duration vs readable hold; source-space annotations
  vs camera transforms; explicit quiet cues vs generated sound defaults (0-6)
- Examples are runnable as written (0-3)

### Failure modes & recovery (10 points)
- Names the likely failures (missing keys, silent VO lines, footage shorter than VO,
  missing fonts, judge variance, late-found identifier leaks, unfinished title reveals,
  cropped proof, drifting annotations, and sound masking speech) and the recovery per case (0-6)
- Says what must hard-fail vs what degrades gracefully (0-4)
