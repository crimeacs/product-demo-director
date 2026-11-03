# Studio direction

Studio direction gives the renderer a visual intention for each shot: establish a context, demonstrate
an action, focus attention, land a payoff, or resolve the film. The planner selects those intentions
from the actual footage. The motion compiler turns them into a consistent treatment without changing
the story, source ranges, narration, or claims.

New projects and drafts from `tools/script.py` default to studio mode. Existing scripts retain their
existing appearance unless they opt in. Story formats remain independent: a causal workflow, walkthrough,
Save-the-Cat film, or before/after promo can all use studio direction.

```json
{
  "creativeDirection": {
    "style": "studio",
    "tone": "precise",
    "soundDesign": "sparse"
  }
}
```

Use `style: "classic"` to explicitly retain the legacy treatment. `precise` uses measured motion;
`editorial` gives type and composition more expression; `energetic` increases animation emphasis.
Tone is consistent across the film. Energy can vary between individual shots.

Preview a studio treatment for an existing project:

```sh
pdd direct projects/my-demo
```

The default is a dry preview. To persist studio defaults and write `out/direction-plan.json`:

```sh
pdd direct projects/my-demo --write
```

This preserves authored story and narration. The saved plan is a draft preview, not proof of the final
render or a replacement for the build's source-bound artifact.

## Start with the visual argument

Write one sentence describing what changes and what visible event proves it. Then find the source
range that contains that event, including enough context before it and enough reading time after it.
The strongest differentiation deserves the longest useful hold. Navigation and decorative setup
should earn their time.

A useful rhythm is a concise opening statement, a continuous product action, one focused explanation,
a quiet proof hold, and one ending. These are functions, not a required five-shot template. A single
continuous clip can demonstrate the action and land its result.

Choose the composition for the evidence:

| Intention | Typical use | Motion decision |
| --- | --- | --- |
| `establish` | Introduce a surface or idea | A stage can create hierarchy when the source remains legible. |
| `demonstrate` | Show input, action, and state change | Use fullbleed, preserve continuity, leave room to read. |
| `focus` | Explain a known source region | Arrive at a grounded target, then hold; omit the target when unknown. |
| `payoff` | Let a real result register | Hold the proof. A result's importance does not require a larger effect. |
| `resolve` | Close on a fresh state or CTA | One concise ending with settled motion. |

Avoid giving every shot an entrance, zoom, highlight, and sound. Contrast makes a few deliberate
gestures matter. The product's visible change should remain more interesting than the decoration.
Readable phone text is only one requirement: complete UI units, a clear composition, and an
understandable relationship between action and result still matter. A sequence of enlarged sentence
fragments does not become studio quality because its font-size estimate passes.

Choose the balance of recordings, typography, and sourced graphics for this film's purpose. Count
presentation by what the viewer sees: slides and generated cards remain presentation when exported
as MP4 clips. Mark externally encoded graphics with `visualTreatment: "presentation"`, preserve their
provenance labels, and include their time in `maxCardRatio`. This permits designed explanations while
keeping them distinct from observed product behavior.

## Authoring grammar

Direction fields are additive to the existing shot schema:

```json
{
  "n": 1,
  "kind": "clip",
  "src": "receipt.mp4",
  "inSec": 3,
  "durSec": 6,
  "sourceType": "product",
  "liveState": true,
  "continuityId": "receipt-screen",
  "direction": {
    "intent": "demonstrate",
    "layout": "fullbleed",
    "energy": 0.25
  },
  "transition": "cut"
}
```

`layout` is `fullbleed` or `stage`; `energy` is a finite number from zero to one. A stage is useful for
a simple, readable surface, but shrinking an entire dense desktop is not a detail treatment. Use a
connected source camera when context matters; use `framing.presentation: "detail"` to place one whole
native component on the brand canvas. The detail grammar requires one fixed source rectangle spanning
the entire shot and fits it inside a separate output rectangle. Set `framing.entranceSec: 0` for a
stationary first frame when an arrival would distract from the source action. See the example and constraints in
[SMALL_SCREEN_FRAMING.md](SMALL_SCREEN_FRAMING.md#complete-native-detail-plates). Source framing locks
remain authoritative. Energy changes presentation, never source playback speed.

### Camera: arrive, then let the viewer look

Camera coordinates are percentages of the original source frame. Use coordinates only when you have
inspected the footage or the manifest supplies a known region. A text description such as “the
receipt appears” does not locate that receipt.

If a known target is sufficient, author `direction.focus: {"x": 62, "y": 44}` with `intent: "focus"`.
The compiler can resolve a restrained move toward it. For exact choreography, author a camera path:

```json
{
  "camera": [
    {"atSec": 0, "scale": 1, "focusX": 50, "focusY": 50, "ease": "smooth"},
    {"atSec": 1.2, "scale": 1.4, "focusX": 62, "focusY": 44, "ease": "settle"},
    {"atSec": 5.8, "scale": 1.4, "focusX": 62, "focusY": 44, "ease": "linear"}
  ]
}
```

This example assumes a six-second shot and a verified target at `(62, 44)`. The final pair of equal
keyframes holds the composition while the viewer reads. Keyframe times are shot-relative and strictly
increasing; keep them within `durSec`. Authored paths default to a 2.25× ceiling;
`production.maxZoomScale` may explicitly raise it as high as 8×. Supported easing values are
`smooth`, `drive`, `settle`, and `linear`. Authored camera paths and legacy `zooms` are mutually exclusive.
The last camera state holds to the end of the shot.

Keep the target, its necessary context, and the cursor visible throughout the move. Enlarging one
number while cropping away its label or safeguard weakens the proof. Do not reframe human or locked
footage to add motion. If the source lacks resolution for the intended crop, use a wider hold or
capture it again.

For new measured camera plans, include `framing.motion` (use `{}` for the starting limits of
1.5 screens/second and 1.2 zoom octaves/second). The compiler budgets apparent image travel and scale
change across the available gap while preserving reading windows and source actions. Resolve an
infeasible move with less travel, a wider composition, more justified time, or an honest cut. See
[measured reading windows](SMALL_SCREEN_FRAMING.md#measured-reading-windows) for fields and reports.
Source native FPS and 1× playback describe source cadence; they do not limit rendered camera speed.
Inspect both clocks rather than attributing fast viewport travel to sped-up footage.

The legacy `zooms` path retains useful ideas from the pinned OpenScreen port in `Timeline.tsx`:
nearby regions connect through a pan instead of resetting wide, and a damped spring carries velocity
without a bounce. This continuity is useful when the viewer must follow a control to its result.
Do not apply a new independent zoom at every narration sentence.

Its timestamps differ from authored camera keyframes. A legacy region starts its lead-in about
1.02 seconds before `atSec` and reaches nominal full strength **0.5 seconds after** `atSec`; the spring
can add further lag. Regions separated by at most 1.5 seconds connect with a one-second target pan.
Thus a click time copied directly into `zooms[].atSec` does not promise a settled camera at the click.
Near the start of a shot, its lead-in can precede the clip, so the first frame need not be a wide view.
Account for that timing and inspect the actual motion; use explicit camera arrivals or measured
reading windows when precise settlement matters. Leave a real hold after motion and after the native
result appears. A smooth trajectory without time to comprehend the result is still poorly timed.

### Typography and annotations

Display type can establish a thought before the product proves it. Author line breaks as semantic
units, preserve the full title text, and emphasize a phrase that actually appears in the title:

```json
{
  "kind": "title",
  "title": "From question to evidence",
  "titleLines": ["From question", "to evidence"],
  "emphasis": "evidence",
  "durSec": 2.5,
  "direction": {"intent": "establish", "layout": "fullbleed", "energy": 0.6}
}
```

For a grounded source region, an annotation can identify what changed without repeating the narrator:

```json
{
  "annotations": [
    {
      "atSec": 2,
      "endSec": 5.5,
      "x": 42,
      "y": 32,
      "width": 40,
      "height": 24,
      "label": "Source receipt"
    }
  ]
}
```

This rectangle is an example, not a locator to reuse across unrelated footage. `x` and `y` identify
the source rectangle's top-left corner; dimensions are source percentages. The full rectangle must
fit inside the source and its timing must fit inside the shot. The referenced content must already
be visible when the annotation arrives. An annotation must not pretend to be product UI, imply a
verified result before it exists, or cover the context needed to judge it.

### Transitions and sound

Use `cut` for most changes of subject. A `reveal` can introduce a new artifact; a `push` can connect a
real directional change; `xfade` can communicate elapsed time. Prefer one expressive transition
family in a film. Keep a continuous live take when the viewer needs to see cause and effect.

`soundDesign: "sparse"` permits the studio treatment's restrained cues. Use
`soundDesign: "silent"` to disable studio sound cues; this does not mute narration or music. An empty
shot-level `soundCues: []` suppresses automatic cues for that shot. For an inspected visible event,
time a cue explicitly:

```json
{
  "soundCues": [
    {"atSec": 2.2, "sound": "studio_tick", "volume": 0.18}
  ]
}
```

Studio cues are `studio_air`, `studio_tick`, and `studio_resolve`. Existing accent names also work.
Cue times are shot-relative; volume is from zero to one. A source-grounded arrival can justify a cue.
A success sound is not evidence of success. Leave reading sections quiet and avoid stacking an
authored accent with another sound for the same event.

## Planner inputs and repair

The planner receives the supplied brand palette and type information as well as source descriptions.
Footage manifests can retain `sourceType`, `preserveFraming`, `continuityId`, `focusRegions`, `events`,
dimensions, and source/evidence references. Add precise observations to those fields after reviewing
the actual media. The planner uses these as context; supplying metadata is not an automated visual
verification of its truth. A concrete locator looks like:

```json
{
  "name": "receipt.mp4",
  "seconds": 12,
  "contents": "The source receipt opens after the request.",
  "sourceType": "product",
  "focusRegions": [
    {"label": "Source receipt", "x": 42, "y": 32, "width": 40, "height": 24}
  ]
}
```

The text-only planner rejects generated camera targets without a supplied `focusRegions` locator.
Targets must fall inside a known region; annotations must reproduce a supplied rectangle. A point
locator with just `x` and `y` can ground a focus target but cannot justify an annotation rectangle.
Normal captures are enriched automatically from their same-stem `.events.json` sidecar when it
declares schema version 2 and `timebase: "edited-media-seconds"`. Recorded clicks supply point
locators with their exact source timestamp; they do not manufacture a surrounding rectangle.
The planner converts source time to shot time by subtracting `inSec`, and rejects event targets
outside the selected source range. Raw or ambiguous event clocks are not used as motion evidence.
With no concrete locator, the planner uses a wider composition. This gate applies to model-generated
drafts; manually inspected scripts remain authorable through the production grammar.

`tools/script.py` checks source names and duration, source framing declarations, story requirements,
narration density, and the same studio grammar used by production validation. It allows at most two
repairs. Each repair includes the rejected JSON and exact findings, so the model can repair the edit
instead of guessing what its previous attempt contained. Owner-provided `product.production`
constraints override conflicting model output.

For a generated narration master, author `narration.fromMap: true` and complete spoken thoughts with
`shotN` in `narrationMap`. Drafting allows the voice and alignment to remain pending. Actual synthesis
and `pace.py` determine the final cut timing. Do not manufacture narration timestamps or combine a
master with per-shot voice files. A draft passing validation is not a finished artifact passing QA.

## Inspect the result

Run the existing preflight, narration/pacing, build, and final QA pipeline in [EDITING.md](EDITING.md).
Watch at delivery size with sound. Inspect each transition and critical source range. Confirm that:

- The opening establishes a real reason to watch and the product becomes understandable quickly.
- The viewer can follow each action and read its result before attention moves again.
- Motion arrives at the evidence and settles; typography supports a coherent hierarchy.
- The sound marks meaningful events while the narration remains clear.
- The proof survives every crop, stage, annotation, and transition.
- The subject remains a complete meaningful UI unit at Full and the intended small-screen width;
  source pixels are sharp enough, and context labels sit outside a detail plate without covering it.
- There is one ending, with no unsupported claim or invented product behavior.

When asked to review motion, submit the complete actual export with
`judge.py --require-artifact --lens motion --fps 24` (and the requested model), then verify its
timestamped observations in playback. Inspect before, during, and after each move; contact sheets
and technical QA cannot establish sequence rhythm. The receipt distinguishes submitted sampling
from unverified provider frame selection. Scores remain advisory.

Deterministic checks protect execution and evidence. Art direction still needs visual judgment:
compare renders, identify the specific weak moment, and improve that moment without diluting the
strongest parts of the film.
