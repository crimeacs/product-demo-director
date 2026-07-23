# Color Grading Playbook

Primary reference: Alexis Van Hurkman, *Color Correction Handbook*, 2nd Edition (Peachpit Press,
2013). The copyrighted book is not bundled with this repository.

This document is not a substitute for the book. It distills working rules for this product-demo
director: screen recordings, web UI, UGC talking heads, product proof, and fast Remotion edits.

## Default Stance

Grade only when it solves a visible problem or supports the story. Do not apply a decorative look
because the pipeline has a color tool available.

For product demos, the viewer must trust the interface. The grade should usually disappear:
neutral whites, legible text, stable brand colors, consistent shots, and no clipped UI detail.

For UGC/founder footage, preserve the authentic phone-video feel unless the brief explicitly asks
for a polished commercial look. Heavy blur side-fills, global vignettes, pushed contrast, or obvious
warm/cool washes can make real footage feel synthetic.

## Correction Before Look

Treat the work as two passes:

1. Correction: fix technical problems.
2. Grade: add a motivated style.

Correction means:

- Exposure is readable.
- UI text and faces are not crushed, clipped, or washed out.
- Whites/grays that should be neutral do not carry a distracting cast.
- Product brand colors are close enough to the live product that the demo feels truthful.
- Shots in the same sequence match each other.

Only after that should the director add style, and style must be named in the script or project:
`clean-saas`, `founder-phone`, `premium-report`, `urgent-audit`, etc. No unnamed grade.

## Six Product-Demo Color Jobs

Adapted for this repo from the book's core colorist tasks.

1. Fix color/exposure errors.
   - Correct phone HDR/HLG exports into a stable delivery space before judging the look.
   - Do not mistake browser/player overlays for the rendered grade.
   - If a shot is too dim, lift it enough for clarity; do not crush blacks to look cinematic.

2. Make key elements look right.
   - Product UI text is a key element.
   - Founder skin tone is a key element.
   - CTA buttons, prices, report scores, and result cards are key elements.
   - If the grade makes these less legible, the grade failed.

3. Match shots in the sequence.
   - Adjacent screen recordings should have similar white background brightness.
   - Adjacent founder clips should not swing from warm to cool or bright to dark unless the
     location/time visibly changed.
   - Match by perception, not only numbers; a shot with a different background may need a small
     compensating adjustment to feel matched.

4. Create style only after matching.
   - A product demo style should usually be subtle: clean, neutral, confident.
   - Strong looks belong in transitions, chapter cards, or abstract beats, not over proof UI.

5. Create depth and focus.
   - Prefer framing, zoom, and caption placement before color tricks.
   - If color is used for depth, lower background saturation slightly and preserve the important
     foreground/product element.
   - A tiny saturated accent can carry attention better than saturating the whole frame.

6. Maintain delivery legality and compatibility.
   - Avoid clipped whites/blacks and excessive chroma.
   - Keep final output broadly playable: H.264/AAC MP4, 30 fps unless the project says otherwise,
     and a web-safe pixel format.

## Scope-Inspired Checks

Use scopes where possible, but the practical director workflow can approximate them with FFmpeg
and visual QA.

Waveform/luma reasoning:

- UI backgrounds should not blow out into unreadable white.
- Text and important borders need enough contrast after any grade.
- Do not lower shadows so far that captions, terminal text, dark UI, hair, or shirt detail vanish.

RGB parade reasoning:

- Neutral whites/grays should have roughly balanced red, green, and blue.
- If highlights are blue/yellow/green without a creative reason, correct the cast.
- If only shadows carry a cast, fix shadows gently; shadow color balance is easy to overcorrect.

Vectorscope reasoning:

- Distance from center is saturation. If the whole trace expands after a saturation push, check
  whether shadows and highlights became noisy or unnatural.
- A lopsided trace is not automatically wrong, but it is a prompt to ask whether the image should
  be dominated by that hue.
- For faces, do not chase perfect math if the viewer's perception is better with a small correction.

## Saturation Rules

Do not just raise global saturation.

If a shot needs more color:

- Keep shadows less saturated than midtones.
- Keep highlights clean, especially whites in UI and sky/clouds in phone footage.
- Add saturation in the midtones or specific accents before touching the whole image.
- Watch for color bleed, ringing, low-chroma-format artifacts, and brand-color distortion.

For SaaS/product UI:

- Preserve true UI colors.
- Let the product's accent color remain the strongest color.
- Avoid color casts over white UI surfaces. They make the product look broken or fake.

For talking heads:

- Skin should look healthy and plausible, not orange, green, gray, or overly smooth.
- If the face is the proof of authenticity, avoid stylized washes.
- Do not add a dark vignette unless the shot is intentionally commercial/interview styled.

## Contrast Rules

Contrast creates clarity, but excess contrast destroys proof.

For UI:

- Text must remain legible at final delivery size.
- Do not clip white cards, charts, input bars, report panels, or pricing text.
- Do not crush dark code blocks or terminal footage.

For phone/founder footage:

- Preserve face detail over punchy blacks.
- Outdoor HDR clips often need technical normalization, not a creative contrast push.
- If the shot is already bright/sunlit, avoid adding extra pop that makes skin or sky harsh.

For product-demo rhythm:

- Use cut timing, zoom, SFX, and captions for energy before relying on contrast.
- A grade should not be the main motion-design device.

## Shot Matching Workflow

Use this order:

1. Pick the hero/reference shot for the sequence.
2. Normalize technical issues in every shot.
3. Match exposure and contrast.
4. Match white balance/color temperature.
5. Match saturation.
6. Check key elements: face, UI text, brand accent, CTA, score/price.
7. Only then apply a small shared look, if any.

For a mixed UGC + screen-recording demo:

- Do not force phone footage and UI footage into the same stylized look.
- Match within each family: founder-to-founder, screen-to-screen, report-to-report.
- Let UGC feel like UGC and product footage feel like product footage.

## Director Grade Names

Use explicit grade intent in project notes or script comments.

Recommended:

- `none`: no creative grade; only normalize format/legibility.
- `clean-saas`: neutral whites, preserved brand accents, very mild contrast.
- `founder-phone`: authentic phone footage; no vignette, no blur side-fill, no stylized wash.
- `premium-report`: slightly deeper midtone contrast on report pages, no clipped UI.
- `urgent-audit`: modest cool shadows or tighter contrast, used sparingly for problem beats.

Avoid:

- `cinematic` without specifics.
- `make it pop`.
- `dark vignette` on product proof.
- `warm founder` unless skin tone is checked.
- `global saturation + contrast` as a look.

## FFmpeg Implementation Notes

For no creative grade, use scale/pad/crop/re-encode only. Avoid `eq`, `hue`, `curves`,
`colorlevels`, `lut*`, `tonemap`, or saturation filters unless the grade calls for them.

Plain founder/UGC landscape normalization:

```sh
ffmpeg -i input.mov -filter_complex \
  "[0:v]scale=-2:1080:force_original_aspect_ratio=decrease,pad=1920:1080:(ow-iw)/2:(oh-ih)/2:color=white,fps=30,setsar=1,format=yuv420p[v]" \
  -map "[v]" -map 0:a? -c:v libx264 -crf 18 -preset medium -c:a aac -b:a 160k output.mp4
```

Use blurred side-fill only when the creative brief asks for that social-video convention, and do
not combine it with brightness/saturation/contrast tweaks by default.

If a source is HDR/HLG and browsers make it look wrong, treat that as technical normalization.
Document it separately from creative grading. Do not call a technical conversion a "look."

## QA Checklist

Run this before calling a video final:

- Contact sheet at 1 fps.
- Targeted contact sheet around any critique or revised beat.
- Audio peak/loudness check if the render was rebuilt.
- Visual check on:
  - first founder frame
  - first screen-recording frame
  - paid/revenue beat
  - final CTA/founder close
- Confirm no player controls hide captions in normal playback.
- Confirm no grade makes the product less credible.

FFmpeg helpers:

```sh
ffmpeg -y -i out.mp4 -vf "fps=1,scale=384:-1,tile=8x7" -frames:v 1 qa/sheet.jpg
ffmpeg -hide_banner -nostats -i out.mp4 -af volumedetect -f null -
ffprobe -hide_banner -v error -show_entries format=duration:stream=codec_name,width,height,pix_fmt,color_space,color_transfer,color_primaries -of json out.mp4
```

## Acceptance Bar

A grade is accepted only if:

- It improves clarity or emotional intent.
- It does not look like an app-wide filter.
- It preserves truthful product UI.
- It preserves plausible skin tone.
- It survives contact-sheet review.
- The user can name why it exists.

If any of those fail, remove the grade and ship a clean correction.
