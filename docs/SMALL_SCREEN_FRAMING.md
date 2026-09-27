# Direct for the viewing size

A 1920×1080 export displayed 320px wide reduces every picture pixel by 6×. Smooth camera motion and
technically valid output do not make small UI text readable. Choose the reading goal first: a saved
value, the initiating button, a result count, or a complete status. Measure that region in the source.
For example, a 14px source glyph in a matching 1920px-wide capture is only 7px tall at 3× zoom in
that player. A pleasing desktop camera move can still leave the proof unreadable on a phone.

Readability alone is insufficient. A large value surrounded by severed labels, half a paragraph,
or cropped controls still makes a weak composition. Frame a complete meaningful UI unit and preserve
its relationship to the action: a button with its label, a result card with its limitation, or a
menu with the selected value. Use an overview when spatial context matters and a detail plate when
one complete native component deserves the screen. Do not turn every shot into an extreme crop.

The review room has **Full**, **390px**, and **320px** controls. They resize the same player without
restarting it. Use these views to assess attention, readable words, motion, and the time available to
understand the action. A geometric report is a prompt for that inspection, not a substitute.
When motion review is requested, submit the actual complete video to Google's motion lens at
`--fps 24`, then check its timestamped findings in playback. Static frames and passing QA cannot
establish camera rhythm or continuity. The review receipt records submitted sampling; it does not
prove the provider inspected every source frame.

## Measured reading windows

A clip can supply `framing` instead of `camera` or legacy zoom fields. The default presentation is
`"camera"`, which keeps the source as the scene and connects measured reading windows:

```json
{
  "n":1,"kind":"clip","src":"product.mp4","durSec":8,
  "framing":{
    "sourceWidth":1920,"sourceHeight":1080,
    "viewerWidthPx":320,"minTextPx":12,"safeInsetPct":6,"transitionSec":0.5,
    "motion":{"maxTravelScreensPerSec":1.5,"maxZoomOctavesPerSec":1.2},
    "beats":[
      {"atSec":0,"endSec":1,"rect":{"x":50,"y":25,"width":30,"height":30},
       "label":"Establish the surrounding result card"},
      {"atSec":4,"endSec":8,"rect":{"x":60,"y":35,"width":15,"height":10},
       "textHeightPx":16,"label":"The saved status and its qualifier"}
    ]
  }
}
```

Rectangles use percentages of the original, oriented source. `textHeightPx` is measured glyph ink
height in source display pixels, not a guessed CSS font size. Prefer a conservative capital/digit
sample and document uncertainty; descenders can inflate whole-line measurements. Missing sizes
remain unknown. The builder verifies source dimensions, including rotation and pixel aspect ratio.

Each beat starts with the camera settled and holds through `endSec`. Leave at least `transitionSec`
between beats for the move. The first beat must start at 0. A clip may start in a closeup when its
context is already clear; it need not repeat an establishing zoom at every cut. Keep live actions
inside the chosen region and allow the result to arrive before moving again.

Include `framing.motion` in new measured camera plans. `{}` uses the example's limits: 1.5 screen
units of apparent travel per second and 1.2 zoom octaves per second, with one octave meaning a
doubling of scale. These bound peak eased movement, not source playback speed. Native source FPS
or a 1× source span can coexist with a violent camera move; a frozen source can move quickly too.
The compiler lengthens a move within the gap between reading windows and reports its budget.
`FRAMING_MOTION_BUDGET_EXCEEDED` means that gap cannot hold the move: reduce travel, widen the view,
reallocate time when the story permits, or author a justified cut. Do not steal the reading hold or
accelerate a source action to conceal the problem. Limits are adjustable editorial choices; an
advisory pass still needs playback inspection. Existing plans without `motion` retain fixed timing.

The compiler fits the declared subject into the requested safe area, subject to the source bounds
and zoom ceiling. It projects glyph height through source fit, camera scale, and player width. If the full
region cannot meet the text-size target, it keeps that region intact and reports the shortfall.
It also reports unknown measurements, unavoidable source-edge constraints, and clipping caused by
a cover fit at 1×. These are advisory and separate from technical media QA. A `clear-declared` report
means the supplied measurements meet the geometric targets; it is not automatic visual proof of
readability. Inspect the actual exported frames and moving sequence at the viewing size.

Measured camera framing defaults to an 8× ceiling. An explicit `production.maxZoomScale` may lower it.
Authored camera paths preserve their 2.25× default; a project may explicitly raise their ceiling to 8×.
Source framing locks and human-footage restrictions remain authoritative. Both framing presentations
require `direction.layout: "fullbleed"` when layout is specified; the legacy stage adds an unmeasured
shrink. Detail presentation supplies its own plate layout.

## Complete native detail plates

For a moving camera, `shot.sourceWindow` can isolate one complete source module before the camera
transform. Its `x/y/width/height` are source percentages. Pixels outside the window reveal the flat
brand canvas, so a complete form can grow and settle without unrelated half-lines appearing at the
frame edges. The mask keeps original pixels, action timing, and audio. It must contain every measured
target and recorded click, and cannot be combined with a detail plate or override a source lock.
Choose it from an inspected module that remains complete throughout the shot. The text-only planner
requires an observed rectangle valid for the whole selected source interval.

Use `framing.presentation: "detail"` for a whole inspected control, card, or panel. The selected source
rectangle is fitted without distortion inside a maximum output rectangle, centered on a flat brand
canvas. There is no duplicate desktop behind it and no reconstruction of product text. For example:

```json
{
  "n":2,"kind":"clip","src":"product.mp4","durSec":6,
  "title":"Saved review policy",
  "caption":"Recorded product session","captionFontSize":72,"captionTop":940,
  "framing":{
    "presentation":"detail","entranceSec":0,
    "sourceWidth":1920,"sourceHeight":1080,
    "viewerWidthPx":320,"minTextPx":12,
    "screenRect":{"x":7,"y":25,"width":86,"height":55},
    "beats":[
      {"atSec":0,"endSec":6,"rect":{"x":62,"y":30,"width":22,"height":12},
       "textHeightPx":20,"label":"Complete saved policy control and its label"}
    ]
  }
}
```

These example coordinates require inspection before use. `beats[0].rect` uses percentages of the
**oriented source**; `screenRect` uses percentages of the **output canvas**. The default screen box
is `(7,25,86,55)`. The complete ROI keeps its source aspect ratio, so its visible plate can be narrower
or shorter than that box. Inherited `objectFit: "cover"` or `"contain"` does not crop the detail again.

Detail requires exactly one beat from `atSec: 0` through the shot's `durSec`. Verify that the complete
component remains inside that fixed rectangle across every selected source frame, including opened
menus or changing results. Source playback spans, genuine frozen frames, and audio keep their existing
timing. Detail does not support source annotations or simultaneous camera/zoom fields, and cannot
override a source framing lock. Use real narrative/state boundaries when choosing a detail shot;
do not invent a `transitionReason` to bypass continuity checks.

The compiler writes `sourceDetail` into the rendered props; author `framing`, not that generated field.
The current plate has square edges. `framing.entranceSec: 0` keeps it stationary from its first frame;
source video still follows its own clock. Omit the field for the restrained 0.4-second entrance,
or author a duration from 0 to 1 second when an arrival serves the edit. Its editorial `title` fits
at most two lines above the plate, within
60–72 design pixels; shorten copy or lower `screenRect` if that reserved band cannot hold it.
Provenance captions default to a separate band below the plate, including its entrance travel.
Use `captionStyle: "readout"` for plain theme-ink editorial text on the detail canvas; it keeps the
measured caption band without a subtitle scrim. With `entranceSec: 0`, the readout remains visible
from the first through the last frame of its window. Keep evidence, provenance, and UI labels distinct.
Explicit caption positions that overlap the plate or leave the canvas fail preflight, and the renderer
checks the loaded font before capturing either text band. The full-shot beat declares ROI ownership, not six seconds of settled
reading: reserve useful reading time after arrival and after the real result appears.

Plate scale is `q = min(outputBoxWidth / sourceROIWidth, outputBoxHeight / sourceROIHeight)`.
Projected glyph height is `sourceGlyphHeight × q × viewerWidth / outputWidth`. This fit preserves the
whole object instead of applying the camera zoom ceiling or trimming it to achieve a text target.
The report retains a text-size shortfall and flags source pixels enlarged beyond 1× at the declared
viewing width. Inspect softness and compression at Full as well as 320px; a native crop preserves
evidence but cannot create detail the capture never contained.

## Readable editorial evidence

When a complete native paragraph is unreadable at delivery size, do not keep enlarging a soft
raster. A `title` shot may use `evidenceExcerpt` with concise `finding`, `source`, `limitation`,
and `label` strings. This is an editorial presentation, not reconstructed product UI. Declare
`sourceType: "generated"`, `visualTreatment: "presentation"`, and `claimIds` pointing to the frozen
recorded evidence. Preserve the source's uncertainty; label paraphrases as editorial excerpts and
use quotation marks only for exact words. Include its time in `maxCardRatio` intentionally.

The renderer keeps every field visible from the first frame, briefly settles the main finding,
and then holds. Finding type is 100–120 design pixels; supporting fields are at least 72, or 12 pixels
at a 320px-wide view of a 1920px export. Copy that cannot fit fails instead of shrinking. Give the
viewer time to read the source and limitation as well as the finding.

## Centered compositions

Opt in with `shot.direction.align: "center"` for a common centered axis across native detail
headings, editorial evidence excerpts, and studio cards including the close. The existing left
alignment remains the default. Detail captions already center within their reserved band; native
UI pixels and source timing remain unchanged. Choose a symmetric `framing.screenRect` such as
`{"x":7,"y":23,"width":86,"height":59}` so the complete native plate shares the heading's center.
The compiler carries the title alignment into `sourceDetail`; do not author that generated field.
Centering does not justify shrinking the product or enlarging redundant overlay copy. Keep one
brief heading, the complete active UI component, and one compact readout, with equal outer margins.

## Sharp recorded excerpts

Do not ship a giant soft raster strip merely because it is now large enough to read. A structured
recorded exchange can be presented at output resolution with `tools/term.py --focus-spec`: API pages
reference saved request/response entries and retain their actual routes, status, and counts. This
mode never executes the recorded command.

For a short UI result, the opt-in `recorded-text` page can reflow an exact visually checked transcript.
It requires the original video and extracted frame hashes, source time, source-pixel rectangle,
dimensions, and a hash of the transcribed text. Rendering verifies those source files. Only source
line breaks or middle-dot separators may divide the text; labels, values, negatives, and qualifiers
stay intact. The picture says **Recorded product · typeset excerpt** throughout. This is an editorial
quotation, not a simulation of the product interface. Return to real workflow footage where the
action and its spatial context matter. A text hash binds a readback; it does not independently prove
that the readback is correct, so inspect it against the bound source frame before rendering.

Count these excerpts as presentation time even when encoded as a `kind: "clip"` MP4. Slide/generated
sources already count toward `maxCardRatio`; external graphics also need
`visualTreatment: "presentation"` and an honest visible provenance label. Native recordings and
designed graphics can coexist when the brief calls for them. Choose their proportion for the story;
file format or a source label must not disguise a presentation-heavy edit as live product proof.

## Capture and source truth

For source glyph height `h`, source-to-output fit `f`, camera scale `s`, output width `W`, and viewer
width `v`, projected glyph height is `h × f × s × v / W`. Doubling zoom doubles text size but also
halves the visible source span. The report cannot inspect contrast, compression, occlusion, changing
UI, or whether the declared reading goal is meaningful.

A long desktop paragraph may be impossible to show completely and legibly in a 320px landscape
player. Choose a complete smaller fact or recapture a responsive layout. Never crop away a negative,
qualifier, unit, or relevant outcome to make the size estimate pass. High-density capture improves
sharpness; it does not increase the amount of information a small screen can comfortably hold.

The planner only uses observed `focusRegions` rectangles and measured `sourceDisplay` dimensions.
A region observed at a single timestamp authorizes a held source frame, not a claim that the same
rectangle remains valid throughout moving footage. Supply a verified visibility interval for that.
Manual scripts remain responsible for their observations.

### Supply observations to the planner

Record inspected regions in the project's `assets/footage.json`. `name` identifies a video under
`assets/`; rectangle coordinates are percentages of its oriented display dimensions. For example:

```json
[
  {
    "name": "product.mp4",
    "seconds": 12,
    "contents": "The saved status and its qualifier are visible from 3 to 8 seconds.",
    "sourceType": "product",
    "focusRegions": [
      {
        "label": "The saved status and its qualifier",
        "x": 60, "y": 35, "width": 15, "height": 10,
        "timebase": "edited-media-seconds",
        "startSec": 3, "endSec": 8,
        "textHeightPx": 16
      }
    ]
  }
]
```

The footage loader, `load_footage` in `tools/script.py`, uses FFprobe to add `sourceDisplay.width`
and `sourceDisplay.height` to the planner's context, including orientation and pixel aspect ratio.
It does not rewrite the manifest. Supply region and glyph measurements from visual inspection;
FFprobe supplies dimensions, not observed reading goals.

`edited-media-seconds` means the clock of the source video **after capture edits**, not the original
recording's wall clock. Region `startSec`/`endSec` describe when that rectangle was verified in the
source. In contrast, `framing.beats[].atSec`/`endSec` use the shot's output clock. With `inSec: 3` and
normal playback, the example region can support a reading beat from output second 0 through 5.
When a `sourceTimeline` changes playback timing or holds a frame, the planner checks the mapped
source times against the observation interval. Inspect the entire interval before declaring it;
one screenshot does not prove that a region stays visible while the source moves.

Short context captions may use `captionFontSize` (16–160 output pixels; for example, 72 gives a 12px
em at 320px playback, with a smaller actual glyph height). Large captions use an adaptive word
budget and wrap oversized words. Check that labels remain readable without covering the evidence.

Compiled camera paths/detail plates and per-shot `framingReport` entries are saved in the direction plan and bound
to the rendered artifact. The review room displays them only for the matching video, build, and
props. A technical pass or a good estimate does not establish studio quality or engagement. Review
the entire moving sequence for complete UI objects, context, sharpness, composition, and real reading
holds; inspect the isolated frame as well as how the viewer arrived there.
