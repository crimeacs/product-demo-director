#!/usr/bin/env python3
"""Capture smooth 'after' footage of a live web app with Playwright.

Records 1920x1080 at 2x device scale, with stepped smooth-scroll and optional clicks,
so the screen recording has motion the editor can push into. Drive it from a steps JSON.

    python tools/capture.py --url https://app.example.com --steps steps.json --out raw.webm

steps.json is a list of actions, run in order:
    [
      {"wait": 1200},
      {"scroll_to": 1400, "steps": 24, "pause": 40},
      {"click_text": "Run audit"},
      {"click_selector": "button.cta"},
      {"wait": 1500}
    ]

AUTH: most real apps are gated. Put your own sign-in in `auth_hook(context, page)` below
(magic link, cookie injection, basic form fill). It is a no-op by default.

Requires: pip install playwright, plus either Playwright Chromium or a local Chrome/Chromium.
Set PDD_BROWSER_EXECUTABLE to override browser discovery.
"""
import argparse, json, os, time
from playwright.sync_api import sync_playwright

W, H = 1920, 1080

# A visible, eased synthetic cursor + click ripple (the raw recording already *looks* directed),
# and an interaction event log so the engine can key zooms off real clicks (clickX/clickY/clickAtSec).
CURSOR_JS = """() => {
  if (window.__pddCur) return;
  const cur = document.createElement('div');
  cur.id = '__pdd_cursor';
  cur.innerHTML = `<svg width="26" height="30" viewBox="0 0 26 30"><path d="M2 2 L2 24 L8.5 18.5 L12.5 27 L16.5 25 L12.5 17 L21 16.5 Z"
    fill="#fff" stroke="#1a1a1a" stroke-width="1.6" stroke-linejoin="round"/></svg>`;
  Object.assign(cur.style, { position: 'fixed', left: '0px', top: '0px', zIndex: 2147483647,
    pointerEvents: 'none', filter: 'drop-shadow(0 2px 5px rgba(0,0,0,.4))',
    transform: 'translate(-2px,-2px)' });
  document.body.appendChild(cur);
  let x = innerWidth * 0.55, y = innerHeight * 0.45;
  const put = () => { cur.style.left = x + 'px'; cur.style.top = y + 'px'; };
  put();
  const ease = t => t < 0.5 ? 2*t*t : 1 - Math.pow(-2*t + 2, 2) / 2;
  window.__pddCur = {
    async move(tx, ty, ms = 650) {
      const sx = x, sy = y, t0 = performance.now();
      // a light arc so the path reads as a hand, not a robot
      const mx = (sx + tx) / 2 + (ty - sy) * 0.08, my = (sy + ty) / 2 - (tx - sx) * 0.08;
      return new Promise(res => { (function f(){ const p = Math.min(1, (performance.now() - t0) / ms), e = ease(p);
        x = (1-e)*(1-e)*sx + 2*(1-e)*e*mx + e*e*tx; y = (1-e)*(1-e)*sy + 2*(1-e)*e*my + e*e*ty; put();
        p < 1 ? requestAnimationFrame(f) : res(); })(); });
    },
    ripple(rx, ry) {
      const r = document.createElement('div');
      Object.assign(r.style, { position: 'fixed', left: rx + 'px', top: ry + 'px', zIndex: 2147483646,
        width: '14px', height: '14px', borderRadius: '50%', border: '2.5px solid rgba(255,255,255,.95)',
        boxShadow: '0 0 12px rgba(0,0,0,.35)', transform: 'translate(-50%,-50%) scale(1)', opacity: '0.95',
        pointerEvents: 'none', transition: 'transform .5s cubic-bezier(.2,.6,.3,1), opacity .5s ease' });
      document.body.appendChild(r);
      requestAnimationFrame(() => { r.style.transform = 'translate(-50%,-50%) scale(3.4)'; r.style.opacity = '0'; });
      setTimeout(() => r.remove(), 700);
    },
  };
}"""


def auth_hook(context, page):
    """Override me. Example (magic link): mint a link server-side, then
    page.goto(link); page.wait_for_load_state('networkidle')."""
    return


def smooth_scroll(page, to_y, steps=24, pause=40):
    page.evaluate(
        """async ([toY, steps, pause]) => {
            const start = window.scrollY;
            const delta = (toY - start) / steps;
            for (let i = 0; i < steps; i++) {
                window.scrollBy(0, delta);
                await new Promise(r => setTimeout(r, pause));
            }
        }""",
        [to_y, steps, pause],
    )


def _browser_executable():
    override = os.environ.get("PDD_BROWSER_EXECUTABLE", "").strip()
    candidates = [
        override,
        "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome",
        "/Applications/Chromium.app/Contents/MacOS/Chromium",
        "/Applications/Microsoft Edge.app/Contents/MacOS/Microsoft Edge",
        "/usr/bin/google-chrome",
        "/usr/bin/google-chrome-stable",
        "/usr/bin/chromium",
        "/usr/bin/chromium-browser",
        "/usr/bin/microsoft-edge",
    ]
    for candidate in candidates:
        if candidate and os.path.isfile(candidate) and os.access(candidate, os.X_OK):
            return candidate
    return ""


def _launch(p):
    options = {"args": ["--force-color-profile=srgb", "--hide-scrollbars"]}
    executable = _browser_executable()
    if executable:
        options["executable_path"] = executable
    return p.chromium.launch(**options)


def run(url, steps, out, scale=2, quiet=False, cursor=True):
    """Record `url` following `steps`, write a webm to `out`, and RETURN the out path.
    Also writes <out-stem>.events.json — cursor clicks + scroll landings with timestamps —
    so the build can key engine zooms off real interactions."""
    out_dir = os.path.dirname(os.path.abspath(out)) or "."
    os.makedirs(out_dir, exist_ok=True)
    events = []
    last_cursor = [None, None]
    with sync_playwright() as p:
        browser = _launch(p)
        context = browser.new_context(
            viewport={"width": W, "height": H},
            device_scale_factor=scale,
            record_video_dir=out_dir,
            record_video_size={"width": W, "height": H},
        )
        page = context.new_page()
        t0 = time.monotonic()   # ~video start (recording begins with the page)
        auth_hook(context, page)
        page.goto(url, wait_until="networkidle")
        page.wait_for_timeout(800)
        if cursor and not url.startswith("file://"):   # term footage has no pointer
            page.evaluate(CURSOR_JS)

        def clickable(loc):
            box = loc.bounding_box()
            if not box:
                return None
            return box["x"] + box["width"] / 2, box["y"] + box["height"] / 2

        def do_click(loc, label):
            pt = clickable(loc)
            if pt and cursor and not url.startswith("file://"):
                page.evaluate("([x,y]) => window.__pddCur && window.__pddCur.move(x,y)", list(pt))
                page.wait_for_timeout(700)
                page.evaluate("([x,y]) => window.__pddCur && window.__pddCur.ripple(x,y)", list(pt))
                last_cursor[:] = [pt[0], pt[1]]
            loc.click(timeout=4000)
            if pt:
                events.append({"t": round(time.monotonic() - t0, 2), "type": "click",
                               "xPct": round(pt[0] / W * 100, 1), "yPct": round(pt[1] / H * 100, 1),
                               "label": label})

        def reinstall_cursor():
            if cursor and not url.startswith("file://"):
                page.evaluate(CURSOR_JS)   # idempotent; restores the pointer after a navigation
                if last_cursor[0] is not None:
                    page.evaluate("([x,y]) => window.__pddCur && window.__pddCur.move(x,y)", last_cursor)

        for st in steps:
            if "wait" in st:
                page.wait_for_timeout(int(st["wait"]))
            if "scroll_to" in st:
                smooth_scroll(page, int(st["scroll_to"]), int(st.get("steps", 24)), int(st.get("pause", 40)))
                events.append({"t": round(time.monotonic() - t0, 2), "type": "scroll", "y": int(st["scroll_to"])})
            if "type_selector" in st:      # cursor glides to the field, clicks, then types like a hand
                try:
                    loc = page.locator(st["type_selector"]).first
                    do_click(loc, st["type_selector"])
                    page.keyboard.type(st.get("text", ""), delay=int(st.get("delay", 70)))
                    events.append({"t": round(time.monotonic() - t0, 2), "type": "type", "text": st.get("text", "")})
                except Exception as e:
                    if not quiet: print("  type miss:", st["type_selector"], e)
                page.wait_for_timeout(int(st.get("after", 800)))
            if "click_text" in st:
                try:
                    do_click(page.get_by_text(st["click_text"], exact=bool(st.get("exact"))).first, st["click_text"])
                except Exception as e:
                    # fall back to a selector the planner grounded in the real DOM, if given
                    fb = st.get("fallback_selector")
                    if fb:
                        try:
                            do_click(page.locator(fb).first, st["click_text"])
                        except Exception as e2:
                            if not quiet: print("  click_text miss:", st["click_text"], e2)
                    elif not quiet:
                        print("  click_text miss:", st["click_text"], e)
                page.wait_for_timeout(int(st.get("after", 1200)))
                reinstall_cursor()
            if "click_selector" in st:
                try:
                    do_click(page.locator(st["click_selector"]).first, st["click_selector"])
                except Exception as e:
                    if not quiet: print("  click_selector miss:", st["click_selector"], e)
                page.wait_for_timeout(int(st.get("after", 1200)))
                reinstall_cursor()
        page.wait_for_timeout(600)
        video_path = page.video.path()
        context.close()
        browser.close()
    # Playwright names the file itself; rename to the requested out path.
    if os.path.abspath(video_path) != os.path.abspath(out):
        os.replace(video_path, out)
    ev_path = os.path.splitext(out)[0] + ".events.json"
    json.dump(events, open(ev_path, "w"), indent=2)
    if not quiet:
        print("captured ->", out, f"({len(events)} events -> {os.path.basename(ev_path)})")
    return out


def probe(url):
    """Open `url` and return facts a shoot planner needs: scroll height, viewport, title,
    visible CTAs (text + a grounded selector + y), and headings. No recording."""
    with sync_playwright() as p:
        browser = _launch(p)
        context = browser.new_context(viewport={"width": W, "height": H}, device_scale_factor=2)
        page = context.new_page()
        auth_hook(context, page)
        page.goto(url, wait_until="networkidle")
        page.wait_for_timeout(800)
        info = page.evaluate(
            """() => {
              const vis = (el) => { const r = el.getBoundingClientRect(); const s = getComputedStyle(el);
                return r.width > 12 && r.height > 8 && s.visibility !== 'hidden' && s.display !== 'none'; };
              const re = /(get started|try|demo|run|sign up|start|book|install|launch|create|watch|explore)/i;
              const ctas = [];
              for (const el of Array.from(document.querySelectorAll('a,button,[role=button],[class*=btn],[class*=cta]'))) {
                if (!vis(el)) continue;
                const t = (el.innerText || '').trim();
                if (!t || t.length > 40 || !re.test(t)) continue;
                const tid = el.getAttribute('data-testid');
                const r = el.getBoundingClientRect();
                ctas.push({ text: t, selector: tid ? `[data-testid="${tid}"]` : `text=${t}`,
                            y: Math.round(r.top + window.scrollY) });
                if (ctas.length >= 8) break;
              }
              const headings = Array.from(document.querySelectorAll('h1,h2'))
                .filter(vis).slice(0, 6).map(h => (h.innerText || '').trim()).filter(Boolean);
              return { scrollHeight: document.documentElement.scrollHeight, viewportH: window.innerHeight,
                       title: document.title, ctas, headings };
            }"""
        )
        context.close()
        browser.close()
    return info


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--url", required=True)
    ap.add_argument("--steps", default="", help="path to a steps JSON (see module docstring)")
    ap.add_argument("--out", default="raw.webm")
    args = ap.parse_args()
    steps = json.load(open(args.steps)) if args.steps else [{"scroll_to": H * 2, "steps": 40, "pause": 45}]
    run(args.url, steps, args.out)


if __name__ == "__main__":
    main()
