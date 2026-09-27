# Editorial timing and engagement review

The editorial audit checks whether declared source events receive time and appear alongside their
narration. It provides concrete review prompts, not a retention score or a guarantee that the film
is compelling. A technically valid export can still open on an unnecessary login screen, spend too
long describing a progress indicator, or mention a finding before the viewer can see it.

Run an audit without changing the project:

```sh
./pdd editorial projects/my-demo
```

Add `--write` to save `out/editorial-report.json`. The default prints JSON only. Neither mode changes
the script, source media, or narration. The CLI exits nonzero for invalid declarations; editorial
warnings remain advisory and do not substitute for preflight, final media QA, or watching the film.
The direct equivalent is `python tools/editorial.py --project projects/my-demo`.

## Declare what the source actually shows

Add `sourceBeats` to a clip after inspecting its original, normalized video. Use the source file's
clock, before the shot's in-point or playback map is applied:

```json
{
  "n": 3,
  "kind": "clip",
  "src": "case.mp4",
  "inSec": 10,
  "durSec": 8,
  "sourceBeats": [
    {
      "id": "start-investigation",
      "sourceSec": 10.8,
      "kind": "action",
      "cueId": "launch",
      "leadInSec": 0.5,
      "label": "Reviewer starts the investigation"
    },
    {
      "id": "source-receipt-arrives",
      "sourceSec": 15,
      "kind": "proof",
      "cueId": "receipt",
      "readHoldSec": 2,
      "label": "Fetched-source receipt becomes visible"
    }
  ]
}
```

Each beat needs a globally unique `id`, a finite nonnegative `sourceSec`, and a `kind`: `action`,
`proof`, or `navigation`. Optional `leadInSec` and `readHoldSec` default to 0.5 and 1.5 seconds.
`label` is descriptive metadata; it does not add an overlay to the film.

The example's click appears 0.8 seconds into the shot and the receipt appears five seconds into it.
When `sourceTimeline` is present, the audit uses the same frame-compiled source mapping as the
renderer. Navigation compression and reading holds therefore change where a source event lands.
An event at the exclusive end of a shot is omitted: there is no final picture frame there.

Capture marks are not automatically verified source beats. A mark labeled “answer” can be recorded
while a decision panel is visible. A “recorded” mark can occur after a six-second hold. Check the
picture and distinguish event onset from the end of an observation. Unversioned capture clocks,
browser wall time, and raw capture timestamps must be converted to the normalized source clock
before authoring these declarations.

## Shape the source playback deliberately

`sourceTimeline` replaces the implicit continuous playback from `inSec`. Its source endpoints must
be contiguous and chronological, beginning at `inSec` when provided. Each span gives its output
duration in seconds:

```json
{
  "kind": "clip", "src": "case.mp4", "inSec": 10, "durSec": 8,
  "sourceTimeline": [
    {"fromSec": 10, "toSec": 12, "durSec": 2, "mode": "realtime"},
    {"fromSec": 12, "toSec": 16, "durSec": 2, "mode": "navigation"},
    {"fromSec": 16, "toSec": 16, "durSec": 2, "mode": "hold"},
    {"fromSec": 16, "toSec": 18, "durSec": 2, "mode": "realtime"}
  ]
}
```

Here two seconds of real action precede navigation at 2× speed; the result frame then stays visible
for two seconds before realtime playback resumes. `realtime` plays at 1×, `navigation` explicitly
declares compressed navigation, and `hold` repeats one frame (`fromSec` must equal `toSec`). Source
gaps and reversals are invalid. Span durations must sum to shot `durSec` within one output frame.
The compiler rounds cumulative boundaries at script `fps`, gives each span at least one frame, and
ends exactly at the shot's final frame. Use frame-aligned durations for precise beats.

Navigation is capped at 2× by default; `production.maxNavigationRate` may explicitly raise the cap
up to 4×. Human footage (`sourceType: "human"`), native source audio (`sound: true`), and consequential
human actions (`actor: "human", actionRisk: "consequential"`) require realtime playback throughout,
including after frame rounding. Do not label meaningful actions as navigation to compress them.

`sourceBeats.sourceSec` remains on the source clock. Camera keyframes, annotation `atSec`/`endSec`,
and sound-cue times are local **output** seconds after this map; annotation geometry is still in
source-frame percentages. `narrationMap` aligned times remain on the whole-film output clock.

## Link narration to evidence

An optional beat `cueId` must reference exactly one `narrationMap` entry with that `id`, assigned to
the same shot or to a consecutive picture interval that contains it. Narration times use the whole
film's clock:

```json
{
  "narrationMap": [
    {"id": "launch", "shotN": 3, "startSec": 12.2, "endSec": 14.5,
     "text": "The reviewer starts the investigation."},
    {"id": "receipt", "shotN": 3, "startSec": 16.8, "endSec": 19.2,
     "text": "The receipt identifies the source it read."}
  ]
}
```

This example assumes shot three begins at film time 12 seconds. Its receipt then appears at 17
seconds, 0.2 seconds after the corresponding spoken cue begins. One spoken thought may have several
source beats; each cue ID must still identify a single narration entry. Duplicate IDs, unknown
references, cues outside the assigned picture interval, and timing ranges outside that interval
are invalid declarations.

Draft cues can omit timing until synthesis and alignment. Their lag is **unknown**. The audit never
invents timestamps. It measures lag from the cue's beginning, so write focused thoughts rather than
attaching several unrelated actions to one long paragraph.
Legacy cues without `shotN` or `shotNs` remain valid with unknown picture alignment; a source beat
cannot use one as an anchor until it has an explicit assignment containing that shot.

## Change the picture beneath a continuous master

A manually edited film may cut from context to a complete detail while one spoken thought
continues. Preserve the existing narration audio, exact words, and character alignment. Opt into
`production.narrationCutPolicy: "continuous-audio"` and assign that thought with `shotNs`:

```json
{
  "production": {
    "narrationCutPolicy": "continuous-audio",
    "autoPaceNarration": false
  },
  "narrationMap": [
    {
      "id": "saved-policy",
      "shotNs": [3, 4],
      "startSec": 12.2,
      "endSec": 17.8,
      "text": "The saved policy schedules the next check.",
      "beat": "proof"
    }
  ]
}
```

This example assumes shots 3 and 4 together contain film times 12.2–17.8. Use `shotN` or `shotNs`,
never both. A span must contain unique, known shot IDs in consecutive picture order; it cannot
skip or reverse shots. Its cue range must fit the combined picture interval. A source beat can
anchor the cue on either member, and the review room shows the same thought on both.

`continuous-audio` requires an existing mixed `narration.file` and `narration.timingFile`. Complete
map text must still match the master declaration, and existing audio/timing hashes and range
checks still apply. This policy changes picture editing permission, not the voice. It and `shotNs`
reject `autoPaceNarration`; set the picture durations manually. The `between-thoughts`
policy continues to reject picture cuts within spoken thoughts, even if a span is declared.

For two views of one source state, set `presentationCut: true` on the incoming clip and give a
nonempty `transitionReason`, such as "Read the complete saved policy." This explicitly describes
an editorial view change; keep the actual `stateId` unchanged. The exception to same-screen cut
rules requires a context/detail switch or a changed complete detail rectangle, the same source
file, and contiguous chronological source endpoints within one output frame. `sourceTimeline`
holds and navigation are checked in their real source clock. It does not permit omitted source
time, a replay disguised as continuation, arbitrary crop resets, or bypassing human, source-lock,
and cursor contracts. Use [source-detail composition](SMALL_SCREEN_FRAMING.md) sparingly when a
complete native component benefits from its own reading view.

## What the report measures

| Metric or finding | Basis and limitation |
| --- | --- |
| First declared proof | Earliest visible frame of a valid `proof` source beat. No proof declaration means unknown, even if `storyBeat` says `evidence`. |
| Setup share | Full durations of shots explicitly tagged `setup`, `input`, or `opening-image`. This measures authored classification, not visual analysis. |
| Navigation share | Frame durations explicitly marked `navigation` in `sourceTimeline`, plus whole shots tagged `storyBeat: "navigation"`. A navigation point alone has no known duration. |
| Initiation pre-roll | Available output time before an `action`, compared with its requested `leadInSec`. |
| Proof reading window | Output time remaining after a `proof`, compared with its requested `readHoldSec`. |
| Evidence lag | Declared event time minus the aligned cue's start time. |
| Long shots without anchors | Narrated shots above the configured duration that contain cues without `sourceBeats` links. A long continuous shot can still be the correct edit. |

Time remaining after a proof is a necessary timing condition, not proof that the content remains
visible or legible. The audit does not inspect scrolling, camera motion, font size, occlusion, source
authenticity, claim validity, or whether the declared event occurred. Inspect the actual reading
window at delivery size. Source beats must be honest observations, not labels added to make a report
look better.

Before accepting the edit, compare the narration's quantities and absolute wording with visible
counts and stated limitations. A fetched page does not necessarily establish the entity-specific
fact the voice describes; a list of findings can include unresolved items with no supporting citation.
Keep those distinctions in the spoken claim. The timing audit cannot verify factual scope.

Unknown shares are `null`, with an explicit status. Declared shares cover only the supplied timing
or classification; they are not a complete inventory of unannotated footage. The report also gives
cue and source-beat counts so missing coverage is visible.

## Set thresholds for the audience

The defaults are review prompts for a concise product film. Change or disable them in the script:

```json
{
  "production": {
    "editorial": {
      "firstProofBySec": 15,
      "maxEvidenceLagSec": 2,
      "maxUnanchoredShotSec": 12,
      "maxSetupRatio": 0.3,
      "maxNavigationRatio": 0.25
    }
  }
}
```

These are the defaults. Each threshold accepts `null` to disable its warning. Seconds must be finite
and nonnegative; ratios must be between zero and one. Unknown threshold names are errors so a typo
cannot silently leave a review preference unapplied.

A sales walkthrough may need more setup than a short announcement. A consequential decision may
need a longer hold than navigation. Do not compress a real action or weaken a production contract to
satisfy an advisory target. First decide which complete thoughts matter; then give each one the source
range needed to demonstrate it.

Report status is `invalid` for malformed declarations, `needs-review` for advisory warnings,
`unknown` when proof or referenced narration timing is unavailable, and `clear-declared` when the
declared checks have no findings requiring review. **`clear-declared` is not a creative-quality pass.**

The standalone report describes the script it read and includes that script's hash. A build may bind
an editorial report to its build ID and props hash. Use a matching bound report when reviewing a
render; a newer script's report must not be presented as an assessment of an older video.
