#!/usr/bin/env python3
"""Onboard a brand: auto-extract palette / font / logo / name from the product's site, confirm,
and write <project>/brand.json — which build.py turns into the engine theme + CTA wordmark.

    python tools/onboard.py --project examples/acme --url https://acme.com     # extract + confirm
    python tools/onboard.py --project examples/acme --url https://acme.com --yes   # no prompts
    python tools/onboard.py --project projects/my-demo --template                  # PDD default brand, no network
    python tools/onboard.py --project examples/acme --manual                    # quick wizard, no URL
    python tools/onboard.py --project examples/acme --field palette.accent=#ff3366   # pin a value

Extraction (Playwright): name (og:site_name / title), tagline (meta description), font (computed
body family), background + text colors, and a brand ACCENT ranked from <meta theme-color>, CSS
custom properties, and the most frequent saturated button/link color; logo from og:image / icon.
It is heuristic — you confirm and tweak before it writes. Colors are sanity-checked for contrast
(warn only). Requires playwright (+ chromium). No Pillow.
"""
import argparse, json, os, re, sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)

# PDD's own brand == the engine DEFAULT_THEME (so --template self-onboards to a byte-identical look)
TEMPLATE = {
    "name": "Your Product", "tagline": "what it does, in a few words", "url": "example.com",
    "logo": None, "tone": "plain, specific, declarative; no hype", "dark": True,
    "palette": {"bg": "#0c1310", "ink": "#f4f6f3", "accent": "#46b07c", "accentDeep": "#2f6f4f",
                "sub": "rgba(244,246,243,0.66)", "line": "rgba(255,255,255,0.10)", "warn": "#e0a24a"},
    "cta": {"name": "Your ", "accent": "Product"},
}

EXTRACT_JS = r"""() => {
  // Resolve ANY CSS color (lab/oklch/named/hex/rgb) to rgb by painting it on a canvas and
  // reading the pixel back — modern sites use lab()/oklch(), which a hex/rgb regex can't parse.
  const _cv = document.createElement("canvas"); _cv.width = _cv.height = 1;
  const _x = _cv.getContext("2d");
  const toRGB = (c) => {
    if (!c) return "";
    try { _x.fillStyle = "#000"; _x.fillStyle = c; _x.fillRect(0, 0, 1, 1);
          const d = _x.getImageData(0, 0, 1, 1).data;
          if (d[3] === 0) return "transparent";
          return `rgb(${d[0]}, ${d[1]}, ${d[2]})`; } catch (e) { return c; }
  };
  const meta = (n) => (document.querySelector(`meta[property="${n}"],meta[name="${n}"]`)||{}).content || "";
  const cs = getComputedStyle(document.body);
  const fontBody = (cs.fontFamily||"").split(",")[0].replace(/["']/g,"").trim();
  // page background: body, else <html>, else the first large opaque element near the top
  let bg = toRGB(cs.backgroundColor);
  if (bg === "transparent") bg = toRGB(getComputedStyle(document.documentElement).backgroundColor);
  if (bg === "transparent") {
    for (const el of Array.from(document.querySelectorAll("body *")).slice(0, 60)) {
      const r = el.getBoundingClientRect(); const b = toRGB(getComputedStyle(el).backgroundColor);
      if (b !== "transparent" && r.width > 600 && r.top < 200) { bg = b; break; }
    }
  }
  const ink = toRGB(cs.color);
  const themeColor = toRGB(meta("theme-color"));
  // CSS custom properties that look brand/accent related
  const vars = {};
  for (const sh of Array.from(document.styleSheets)) {
    let rules; try { rules = sh.cssRules; } catch(e){ continue; }
    for (const r of Array.from(rules||[])) {
      if (!r.style) continue;
      for (const p of Array.from(r.style)) {
        if (p.startsWith("--") && /(brand|primary|accent|main|theme|color)/i.test(p)) {
          const v = r.style.getPropertyValue(p).trim();
          if (/^#|rgb|hsl|lab|lch|oklch|oklab|color\(/.test(v)) vars[p] = toRGB(v);
        }
      }
    }
  }
  // candidate accent: frequency of button/link backgrounds (resolved to rgb)
  const freq = {};
  for (const el of Array.from(document.querySelectorAll("button,a,[class*=btn],[class*=cta]")).slice(0,400)) {
    const b = toRGB(getComputedStyle(el).backgroundColor);
    if (b && b !== "transparent") freq[b] = (freq[b]||0)+1;
  }
  const cands = Object.entries(freq).sort((a,b)=>b[1]-a[1]).map(x=>x[0]).slice(0,8);
  // logo
  let logo = meta("og:image");
  if (!logo) { const ic = document.querySelector("link[rel~='icon'],link[rel='shortcut icon']"); if (ic) logo = ic.href; }
  if (!logo) { const im = document.querySelector("header img, nav img, img[alt*='logo' i]"); if (im) logo = im.src; }
  const name = meta("og:site_name") || meta("application-name") || document.title.split(/[|\-–—:]/)[0].trim();
  const tagline = (meta("description") || meta("og:description") || "").slice(0,120);
  return { name, tagline, fontBody, bg, ink, themeColor, vars, cands, logo, title: document.title };
}"""


def _rgb(s):
    if not s:
        return None
    s = s.strip()
    m = re.match(r"#([0-9a-fA-F]{3,6})", s)
    if m:
        h = m.group(1)
        if len(h) == 3:
            h = "".join(c * 2 for c in h)
        return (int(h[0:2], 16), int(h[2:4], 16), int(h[4:6], 16))
    m = re.match(r"rgba?\(([^)]+)\)", s)
    if m:
        parts = [p.strip() for p in m.group(1).split(",")]
        try:
            return tuple(int(float(parts[i])) for i in range(3))
        except Exception:
            return None
    return None


def _hex(rgb):
    return "#%02x%02x%02x" % tuple(max(0, min(255, int(c))) for c in rgb)


def _lum(rgb):
    def ch(c):
        c /= 255.0
        return c / 12.92 if c <= 0.03928 else ((c + 0.055) / 1.055) ** 2.4
    r, g, b = rgb
    return 0.2126 * ch(r) + 0.7152 * ch(g) + 0.0722 * ch(b)


def _contrast(a, b):
    la, lb = _lum(a), _lum(b)
    hi, lo = max(la, lb), min(la, lb)
    return (hi + 0.05) / (lo + 0.05)


def _sat(rgb):
    r, g, b = [c / 255.0 for c in rgb]
    mx, mn = max(r, g, b), min(r, g, b)
    if mx == 0:
        return 0
    return (mx - mn) / mx


def _deepen(rgb, f=0.7):
    return tuple(int(c * f) for c in rgb)


def palette_from(ex):
    bg = _rgb(ex.get("bg")) or (12, 19, 16)
    ink = _rgb(ex.get("ink")) or (244, 246, 243)
    dark = _lum(bg) < 0.4
    # accent: theme-color, then any brand css var, then the most saturated frequent button color
    accent = None
    notes = []
    for src, label in [(ex.get("themeColor"), "theme-color")] + \
                      [(v, f"css var {k}") for k, v in (ex.get("vars") or {}).items()]:
        c = _rgb(src)
        if c and _sat(c) >= 0.25:
            accent, accent_from = c, label
            break
    if not accent:
        best = None
        for cstr in ex.get("cands", []):
            c = _rgb(cstr)
            if c and _sat(c) >= 0.3 and _contrast(c, bg) >= 1.6:
                if best is None or _sat(c) > _sat(best):
                    best = c
        if best:
            accent, accent_from = best, "button color"
    if not accent:
        accent, accent_from = (70, 176, 124), "template default"
    # contrast warnings (warn only — do not auto-snap a deliberate brand)
    if _contrast(ink, bg) < 4.5:
        notes.append(f"ink/bg contrast {_contrast(ink,bg):.1f} (<4.5) — text may be hard to read")
    if _contrast(accent, bg) < 2.0:
        notes.append(f"accent/bg contrast {_contrast(accent,bg):.1f} (<2.0) — accent may be faint")
    # grad: the elevated corner of card backgrounds — a subtle blend of bg toward the accent,
    # derived here because the engine's DEFAULT grad is dark and clashes with light brands
    grad = tuple(int(b + (a - b) * (0.16 if dark else 0.10)) for b, a in zip(bg, accent))
    pal = {
        "bg": _hex(bg), "ink": _hex(ink), "accent": _hex(accent), "accentDeep": _hex(_deepen(accent)),
        "sub": f"rgba({ink[0]},{ink[1]},{ink[2]},0.66)", "line": "rgba(255,255,255,0.10)" if dark else "rgba(0,0,0,0.10)",
        "warn": "#e0a24a", "grad": _hex(grad), "gradFilm": _hex(grad),
    }
    return pal, accent_from, notes, dark


def split_wordmark(name):
    parts = (name or "Product").split()
    if len(parts) >= 2:
        return " ".join(parts[:-1]) + " ", parts[-1]
    return name + " ", ""


def extract(url):
    from playwright.sync_api import sync_playwright
    with sync_playwright() as p:
        b = p.chromium.launch(args=["--force-color-profile=srgb", "--hide-scrollbars"])
        ctx = b.new_context(viewport={"width": 1440, "height": 900}, device_scale_factor=2)
        pg = ctx.new_page()
        pg.goto(url, wait_until="networkidle")
        pg.wait_for_timeout(800)
        ex = pg.evaluate(EXTRACT_JS)
        ctx.close(); b.close()
    return ex


def download_logo(url, project):
    if not url:
        return None
    try:
        import requests
        r = requests.get(url, timeout=15)
        if r.status_code >= 300 or not r.content:
            return None
        ext = ".png"
        for e in (".svg", ".png", ".jpg", ".jpeg", ".webp"):
            if url.lower().split("?")[0].endswith(e):
                ext = e; break
        os.makedirs(os.path.join(project, "assets"), exist_ok=True)
        dest = os.path.join(project, "assets", "logo" + ext)
        open(dest, "wb").write(r.content)
        return "logo" + ext
    except Exception:
        return None


def apply_fields(brand, fields):
    for f in fields:
        if "=" not in f:
            continue
        k, v = f.split("=", 1)
        cur = brand
        keys = k.split(".")
        for kk in keys[:-1]:
            cur = cur.setdefault(kk, {})
        cur[keys[-1]] = v
    return brand


def confirm(brand, notes, yes):
    print("\n=== extracted brand ===")
    print(f"  name    : {brand['name']}")
    print(f"  tagline : {brand['tagline']}")
    print(f"  url     : {brand['url']}")
    print(f"  logo    : {brand.get('logo')}")
    print(f"  font    : {brand.get('font')}")
    for k, v in brand["palette"].items():
        print(f"  {k:10s}: {v}")
    print(f"  cta     : {brand['cta']['name']!r} + {brand['cta']['accent']!r}")
    for n in notes:
        print("  ! " + n)
    if yes:
        return brand
    print("\nEdit a field as key=value (e.g. palette.accent=#ff3366, cta.accent=Director), blank to accept:")
    while True:
        try:
            line = input("> ").strip()
        except EOFError:
            break
        if not line:
            break
        apply_fields(brand, [line])
    return brand


def wizard():
    def ask(label, default):
        try:
            v = input(f"{label} [{default}]: ").strip()
        except EOFError:
            v = ""
        return v or default
    b = json.loads(json.dumps(TEMPLATE))
    b["name"] = ask("Product name", b["name"])
    b["tagline"] = ask("Tagline", b["tagline"])
    b["url"] = ask("URL", b["url"])
    b["palette"]["bg"] = ask("Background color", b["palette"]["bg"])
    b["palette"]["ink"] = ask("Text color", b["palette"]["ink"])
    b["palette"]["accent"] = ask("Accent color", b["palette"]["accent"])
    acc = _rgb(b["palette"]["accent"])
    if acc:
        b["palette"]["accentDeep"] = _hex(_deepen(acc))
    nm, tail = split_wordmark(b["name"])
    b["cta"] = {"name": nm, "accent": tail}
    return b


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--project", required=True)
    ap.add_argument("--url", default="")
    ap.add_argument("--out", default="")
    ap.add_argument("--template", action="store_true")
    ap.add_argument("--manual", action="store_true")
    ap.add_argument("--yes", action="store_true")
    ap.add_argument("--no-logo", action="store_true")
    ap.add_argument("--field", action="append", default=[], help="override key=value (dotted), repeatable")
    a = ap.parse_args()

    proj = os.path.abspath(a.project)
    os.makedirs(proj, exist_ok=True)
    out = a.out or os.path.join(proj, "brand.json")

    if a.template:
        brand = json.loads(json.dumps(TEMPLATE))
        notes = []
    elif a.manual or not a.url:
        brand = wizard()
        notes = []
    else:
        print(f"extracting brand from {a.url} ...")
        ex = extract(a.url)
        pal, accent_from, notes, dark = palette_from(ex)
        nm, tail = split_wordmark(ex.get("name") or "Product")
        logo = None if a.no_logo else download_logo(ex.get("logo"), proj)
        brand = {
            "name": ex.get("name") or "Product", "tagline": ex.get("tagline", ""),
            "url": re.sub(r"^https?://", "", a.url).rstrip("/"), "logo": logo,
            "font": ex.get("fontBody") or "Inter", "tone": "plain, specific, declarative; no hype",
            "dark": dark, "palette": pal, "cta": {"name": nm, "accent": tail},
            "_source": {"url": a.url, "accentFrom": accent_from},
        }
    brand = apply_fields(brand, a.field)
    brand = confirm(brand, notes, a.yes or a.template)
    json.dump(brand, open(out, "w"), indent=2)
    print(f"\nwrote {out}")


if __name__ == "__main__":
    main()
