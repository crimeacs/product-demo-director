---
name: screen-capturing
description: Capture clean, redacted product-demo footage from a live (auth-gated) web app with Playwright — auth, source-side redaction, smooth navigation, click-to-evidence, and upload-flow beats. Use when recording an app walkthrough for a demo video.
---

# Screen capturing (live web app → demo footage)

Record a real product surface with sensitive data redacted at the source. Playwright drives
Chromium; capture density and the logical viewport are separate choices.

## Auth into a gated app

- Set up a dedicated local or staging capture environment. Use seeded, non-production data and the
  app's documented test-auth flow:
  ```bash
  npm install playwright dotenv && npx playwright install chromium
  PORT=3002 CAPTURE_MODE=seeded-test npm run dev
  ```
  Never put production credentials in a capture command, transcript, or committed fixture.
- Authenticate with a dedicated test account, then save Playwright storage state outside the
  repository. Reuse that state for same-origin navigation and invalidate it after the shoot. If the
  app supports test-only magic links, mint one through its documented development interface rather
  than scripting an administrator credential into the recorder.

## Source-side redaction (do it in the page, not in post)

- Inject a MutationObserver that rewrites any text node matching a token list + patterns
  (street suffixes, `LLC|P\.?C\.?|Trust|Architect`, block/lot `\d+/\d+`, filenames) to the
  literal word **"redacted"**, re-applied on scroll / stage change / navigation. Literal text
  beats blur: a vision model confabulates a fake value from a blurred labeled field.
- Re-inject after every `goto` (a full navigation drops the observer). Guard with a window flag.
  *Failure Mode*: If you re-inject on a page without a window-flag check, multiple concurrent observers will bind to the same DOM nodes. When observer A mutates a node, it triggers observer B, causing an infinite, browser-crashing cascade of duplicate observation loops. Always check `if (window.__redactionObserverActive) return;` before registering.
- A PDF rendered to `<canvas>` is NOT DOM text — the observer can't touch it. Zoom past the
  title block (the cited row is usually mid-page) or box the title region; do not blur the
  whole evidence (it is the proof).

## Smooth, legible motion

- Preserve enough native pixels for the intended crop. A 1920×1080 CSS viewport at DPR 2 does
  **not** make a 1920×1080 recording a Retina source: the recording size still discards pixels.
  Use opt-in `captureScale: 3` (or CLI `--capture-scale 3`) to retain 5760×3240 pixels while
  keeping the same 1920×1080 layout, CSS click positions, and event percentages. Values 1–4 are
  supported; the legacy default remains 1080p video. Equivalent Playwright options are:
  ```javascript
  const context = await browser.newContext({
    viewport: { width: 1920, height: 1080 },
    deviceScaleFactor: 3,
    recordVideo: { dir: './recordings', size: { width: 5760, height: 3240 } }
  });
  ```
- For a still, add `{"screenshot":"evidence.png"}` to capture steps. It writes a lossless,
  viewport-sized PNG using `scale: "device"`, at the current recorded state, next to the raw
  video. Filenames must be simple `.png` names. Use `--no-cursor` for an unannotated source
  screenshot. Capture metadata records CSS viewport, device scale, actual video/PNG dimensions,
  hashes, and screenshot times. `ffprobe` is required for opt-in density; mismatched video
  dimensions fail instead of being labeled high-resolution. Existing bitmap images or canvases
  may still be soft: inspect native pixels, not only file dimensions.
  Opt-in density is applied at Chromium launch as well as context creation: an initial 1×
  recorder frame can otherwise produce a small picture padded into a nominally large video.
- Capture density cannot fix small delivery-size text, incomplete objects, or simultaneous page
  and camera movement. Preserve complete semantic units and inspect the intended crop at 320px.
- Scroll with a stepped `window.scrollBy` loop (~24 steps, ~40ms) — never jump:
  ```javascript
  for (let i = 0; i < 24; i++) {
    await page.evaluate(() => window.scrollBy(0, 40));
    await page.waitForTimeout(40);
  }
  ```
  Hold ~2-2.5s on each section so the editor has a readable beat. Add lead-in/lead-out frames around clicks.
- Let data hydrate (~8s after load) before acting; let pdfjs render (~11s) before holding on it.

## Beats worth capturing

- **Upload entry**: the real start — "new review → upload / pick the file" — so the flow is
  honest about ingestion, not a magic wand.
- **Click-to-evidence**: click an extracted fact; the cited source opens with the value
  highlighted. Strongest "shows its work" proof.
- **Each stage** end to end, in order, so the editor can pick in-points per cut.

## Map the timeline after capture

Every change to the capture script shifts every downstream in-point. After re-recording,
extract a frame grid (every ~6s), read them, and re-derive the in-point for each beat
(upload / evidence / each stage) before assembling — stale in-points are the #1 silent defect.

## Acceptance

- No client identifier legible at fps=24 (verify the actual frames; a confabulated value over
  a "redacted" field is a false positive).
- Smooth (no jump-scrolls), hydrated (no loading spinners in the held beats), 1080p crisp.

## Autonomous shoot planning (`tools/shoot.py`)

You don't have to pre-record. Describe the shoot in `<project>/shoot.json` and the director records
it into `<project>/assets/<name>.mp4`:

```json
{ "shots": [
  { "name": "dash", "kind": "web", "url": "https://app.example.com",
    "goal": "scroll the report, then click Run", "speed": 1.0, "captureScale": 3 },
  { "name": "term_run", "kind": "terminal", "speed": 1.7,
    "transcript": [ {"role":"user","text":"..."}, {"role":"tool","text":"Bash(...)"} ] }
] }
```

```sh
python tools/shoot.py --project projects/my-demo                 # shoot every shot
python tools/shoot.py --project projects/my-demo --plan-only      # write/validate web plans, no recording
python tools/shoot.py --url https://x.com --goal "tour it" --out a.mp4   # one-shot web
python tools/capture.py --url https://x.com --steps steps.json --capture-scale 3 --out raw.webm
```

For a **web** shot with no `steps`, the director *plans* it: it probes the live page (scroll height,
visible CTAs) and an LLM emits scroll/click steps that are **validated and clamped against that DOM**
before recording — scroll targets are bounded, and a click is dropped unless its text was actually
seen (a `fallback_selector` from the probe is attached). If planning is unavailable it falls back to
a safe full-page scroll, so a shoot never hard-fails. Steps are written to `assets/<name>.steps.json`
and reused on the next run (pass `--replan` to regenerate). Raw recordings land in `assets/_raw/`
(gitignored); the normalized MP4 lands in `assets/`. Default shots remain 1920×1080/30fps;
opt-in density preserves the captured raster through normalization at 30fps. Each `.capture.json`
sidecar binds raw and normalized video hashes and dimensions; event metadata keeps the logical
CSS viewport rather than substituting the larger pixel dimensions. Raw PNGs remain untouched.

The engine uses PNG composition frames and BT.709 output to avoid an intermediate JPEG loss.
`tools/finish.py` now copies an already compliant H.264/yuv420p, limited-range BT.709 picture
stream while finishing audio. Missing or different color tags still require a real conversion;
`--video-mode encode` forces it, and `--video-mode copy` rejects incompatible input. The finish
receipt records the chosen path and independent artifact QA still applies. Higher density costs
memory and recording/encoding time; it does not establish motion cadence or creative quality.

Reference: [Playwright video size](https://playwright.dev/python/docs/videos#record-video),
[screenshot scale](https://playwright.dev/python/docs/api/class-page#page-screenshot-option-scale),
and [Remotion image format](https://www.remotion.dev/docs/config#setvideoimageformat).

LLM ladder (planning only, never hardcodes keys): the `anthropic` SDK if `ANTHROPIC_API_KEY` is set,
else the `claude -p` CLI if present, else `google-genai` with `GEMINI_API_KEY`/`GOOGLE_API_KEY`.

## Terminal / agent footage (`tools/term.py`)

Products with no web UI (a CLI, or a Claude skill like this one) are shot as a terminal session.
`term.py` renders an animated, self-typing terminal HTML (the same look as the shipped promo) and
records it with the Playwright recorder — no extra native deps.

```sh
# from a transcript of {role,text,ok?}  (roles: user, say, tool, res, ok, fin)
python tools/term.py --project P --name term_run --transcript shot.json --out P/assets/_raw/term_run.webm
# or from a REAL command's output (records what the product actually prints)
python tools/term.py --project P --cmd "python tools/build.py --project P --dry" --prompt "Demo it." --out ...
python tools/term.py --transcript shot.json --html-only /tmp/t.html      # inspect the animation only
```

Add `"ok": "72 / 100"` to a `res`/`fin` line to highlight a token in the accent color. The terminal
stays **monospace** regardless of brand; only `--bg`/`--accent`/`--ink` are themed from `brand.json`.

*Alternative backend:* `asciinema rec out.cast` → `agg out.cast out.gif` → `ffmpeg` to mp4. It needs
those native tools installed and won't match the engine's look, so the HTML terminal is the default.
