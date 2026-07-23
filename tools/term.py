#!/usr/bin/env python3
"""Render a terminal / agent session as demo footage — for products that have no web UI
(a CLI, or a Claude skill like this one). It builds an animated, self-typing terminal HTML
(the same look as the shipped promo) and records it with the Playwright recorder in capture.py.

    # from a transcript (a JSON list of {role,text,ok?})
    python tools/term.py --project projects/my-demo --name term_run --transcript shot.json --out projects/my-demo/assets/_raw/term_run.webm

    # from a REAL command's output (records what the product actually prints)
    python tools/term.py --project projects/my-demo --name term_run --cmd "python tools/build.py --project projects/my-demo --dry" \
        --prompt "Demo the skill." --out projects/my-demo/assets/_raw/term_run.webm

    # just write/inspect the HTML (no capture)
    python tools/term.py --transcript shot.json --html-only /tmp/t.html

Roles: user (the prompt), say (assistant prose), tool (a command, green pin), res (tool output,
gutter), ok (a green line), fin (the closing line, gets the blinking cursor). Add "ok":"72 / 100"
to a res/fin line to highlight a token in the accent color.

Backend choice: an HTML terminal recorded via Playwright (not asciinema+agg). It needs no extra
native deps, matches the engine's look exactly, themes cleanly, and gives the line-by-line reveal
that reads as a live session. asciinema is noted as an alternative in docs/CAPTURE.md.

The TEMINAL STAYS MONOSPACE regardless of brand — only --bg / --accent / --ink are themed.
"""
import argparse, html as _html, json, os, re, subprocess, sys

HERE = os.path.dirname(os.path.abspath(__file__))
SPACER_MS = 120    # reveal cadence for a blank spacer
TAIL_MS = 1200     # hold after the last line so the cursor blinks before we cut
TYPE_MS = 26       # per-character typing speed on the user prompt line
BODY_MAX = 760     # px: cap the terminal body; longer sessions scroll-follow inside the window


def line_ms(line):
    """Reveal time per line, proportional to how much there is to read — a long assistant
    sentence holds longer than a one-word result line (flat 780ms read as a metronome)."""
    role = line.get("role", "say")
    if role == "sp":
        return SPACER_MS
    n = len(line.get("text", "") or "")
    if role == "user":
        return 380 + TYPE_MS * n + 320          # typed out char by char, then a beat
    if role in ("say", "fin"):
        return max(560, min(1500, 420 + 16 * n))
    return max(420, min(1100, 320 + 11 * n))    # tool / res / ok

TEMPLATE = """<!doctype html><html><head><meta charset="utf8">{{THEME}}<style>
  *{margin:0;box-sizing:border-box}
  body{background:var(--bg,#0c1310);font-family:"SF Mono",ui-monospace,Menlo,Consolas,monospace;padding:54px 0;min-height:100vh;display:flex;align-items:center;justify-content:center}
  .term{width:1240px;margin:0 auto;background:#0f1814;border:1px solid #1d2a23;border-radius:16px;overflow:hidden;box-shadow:0 30px 90px rgba(0,0,0,.55)}
  .bar{display:flex;align-items:center;gap:9px;padding:15px 18px;background:#13201a;border-bottom:1px solid #1d2a23}
  .dot{width:13px;height:13px;border-radius:50%}.r{background:#ff5f57}.y{background:#febc2e}.g{background:#28c840}
  .ttl{margin-left:14px;color:#5f7468;font-size:15px;font-weight:600}
  .body{padding:28px 32px;font-size:21px;line-height:1.95;min-height:420px;max-height:{{BODY_MAX}}px;overflow:hidden}
  .wrap{transition:transform .45s cubic-bezier(.4,0,.2,1)}
  /* hidden lines take no space: the window hugs its content and grows line by line */
  .ln{display:none;opacity:0;transform:translateY(8px);transition:opacity .35s ease,transform .35s ease}
  .ln.on{opacity:1;transform:none}
  .usr{color:#6f857a}.usr b{color:#aebcb4;font-weight:600}
  .say{color:var(--ink,#eaf2ee)}
  .tool .pin{color:var(--accent,#46b07c);font-weight:700}.tool .cmd{color:#c8d3cc}
  .res{color:#7e9488;padding-left:30px}
  .ok{color:var(--accent,#46b07c);font-weight:700}
  .fin{color:var(--ink,#eaf2ee);font-weight:600}
  .cur{display:inline-block;width:11px;height:22px;background:var(--accent,#46b07c);vertical-align:-4px;margin-left:4px;animation:bl 1s steps(1) infinite}
  @keyframes bl{50%{opacity:0}}
  .sp{height:14px}
</style></head><body>
  <div class="term">
    <div class="bar"><div class="dot r"></div><div class="dot y"></div><div class="dot g"></div><div class="ttl">{{TITLE}}</div></div>
    <div class="body" id="b"><div class="wrap" id="w">
{{LINES}}
    </div></div>
  </div>
  <script>
    const body=document.getElementById('b'), wrap=document.getElementById('w');
    const lns=[...document.querySelectorAll('.ln')];
    let shift=0;
    function follow(ln){ // keep the newest line inside the window (scroll-follow, like a real terminal)
      const bottom=ln.offsetTop+ln.offsetHeight, view=body.clientHeight-28;
      if(bottom-shift>view){ shift=bottom-view; wrap.style.transform=`translateY(${-shift}px)`; }
    }
    function typeInto(ln,cb){ // the user prompt types itself
      const t=ln.querySelector('.typed'); const full=t.dataset.text; let j=0;
      (function tick(){ if(j>full.length){ cb(); return; } t.textContent=full.slice(0,j); j++; setTimeout(tick,{{TYPE_MS}}); })();
    }
    let i=0;(function step(){
      if(i>=lns.length) return;
      const ln=lns[i]; ln.style.display='block'; void ln.offsetHeight; ln.classList.add('on'); follow(ln);
      const ms=parseInt(ln.dataset.ms||'700',10); i++;
      if(ln.querySelector('.typed')) typeInto(ln,()=>setTimeout(step,320));
      else setTimeout(step,ms);
    })();
  </script>
</body></html>"""


def _esc(s):
    return _html.escape(str(s), quote=False)


def _ok(line):
    """trailing accent-highlighted token, e.g. {'text':'overall ','ok':'72 / 100'}"""
    return f' <span class="ok">{_esc(line["ok"])}</span>' if line.get("ok") else ""


def _line_html(line, is_last):
    role = line.get("role", "say")
    text = _esc(line.get("text", ""))
    cur = '<span class="cur"></span>' if is_last else ""
    ms = f' data-ms="{line_ms(line)}"'
    if role == "user":
        # the prompt types itself char by char (data-text drives the JS typist)
        attr = _html.escape(str(line.get("text", "")), quote=True)
        return f'      <div class="ln usr"{ms}><b>&gt;</b> <span class="typed" data-text="{attr}"></span>{cur}</div>'
    if role == "tool":
        return f'      <div class="ln tool"{ms}><span class="pin">⏺</span> <span class="cmd">{text}</span>{cur}</div>'
    if role == "res":
        return f'      <div class="ln res"{ms}>⎿  {text}{_ok(line)}{cur}</div>'
    if role == "ok":
        return f'      <div class="ln ok"{ms}>{text}{cur}</div>'
    if role == "fin":
        return f'      <div class="ln fin"{ms}>{text}{_ok(line)}{cur}</div>'
    return f'      <div class="ln say"{ms}>{text}{_ok(line)}{cur}</div>'


def _with_spacers(transcript):
    """Reproduce the promo's grouping: a blank line before each say/fin that follows output."""
    out = []
    prev = None
    for i, ln in enumerate(transcript):
        role = ln.get("role", "say")
        if i > 0 and role in ("say", "fin") and prev in ("res", "ok", "tool", "fin"):
            out.append({"role": "sp"})
        out.append(ln)
        prev = role
    return out


def render_html(transcript, theme=None, title="claude — product-demo-director"):
    theme = theme or {}
    vars_ = []
    for k, css in (("bg", "--bg"), ("accent", "--accent"), ("ink", "--ink")):
        if theme.get(k):
            vars_.append(f"{css}:{theme[k]}")
    theme_block = f"<style>:root{{{';'.join(vars_)}}}</style>" if vars_ else ""
    lines = _with_spacers(transcript)
    parts = []
    last_real = max((i for i, l in enumerate(lines) if l.get("role") != "sp"), default=-1)
    for i, ln in enumerate(lines):
        if ln.get("role") == "sp":
            parts.append('      <div class="sp ln"></div>')
        else:
            parts.append(_line_html(ln, i == last_real))
    return (TEMPLATE.replace("{{THEME}}", theme_block)
                    .replace("{{TITLE}}", _esc(title))
                    .replace("{{LINES}}", "\n".join(parts))
                    .replace("{{TYPE_MS}}", str(TYPE_MS))
                    .replace("{{BODY_MAX}}", str(BODY_MAX)))


def reveal_ms(transcript):
    return sum(line_ms(l) for l in _with_spacers(transcript)) + TAIL_MS


def _brand_theme(project):
    """Read <project>/brand.json palette for --bg/--accent/--ink (defensive; missing -> engine default)."""
    if not project:
        return {}
    p = os.path.join(project, "brand.json")
    if not os.path.exists(p):
        return {}
    try:
        b = json.load(open(p))
    except Exception:
        return {}
    pal = b.get("palette", {}) or b.get("colors", {}) or {}
    th = b.get("theme", {}) or {}
    out = {}
    for k, aliases in (("bg", ("bg", "background")), ("accent", ("accent", "primary", "green")),
                       ("ink", ("ink", "text", "foreground"))):
        for a in aliases:
            v = th.get(a) or pal.get(a)
            if v:
                out[k] = v
                break
    return out


ANSI = re.compile(r"\x1b\[[0-9;]*[A-Za-z]")


def transcript_from_cmd(cmd, prompt=None, say=None, max_lines=12):
    """Run a real command and turn its output into a transcript (records what the product prints)."""
    r = subprocess.run(cmd, shell=True, capture_output=True, text=True, cwd=HERE + "/..")
    raw = (r.stdout or "") + (("\n" + r.stderr) if r.stderr else "")
    out_lines = [ANSI.sub("", l) for l in raw.splitlines() if l.strip()][:max_lines]
    t = [{"role": "user", "text": prompt or cmd}]
    if say:
        t.append({"role": "say", "text": say})
    t.append({"role": "tool", "text": f"Bash({cmd})"})
    for l in out_lines:
        t.append({"role": "res", "text": l})
    t.append({"role": "fin", "text": f"exit {r.returncode}"})
    return t


def render_and_capture(transcript, out_webm, project=None, name="term", theme=None, title=None):
    """Write the HTML into <project>/_src/<name>.html (committed, reproducible) and record it."""
    import capture
    theme = theme if theme is not None else _brand_theme(project)
    htmldir = os.path.join(project, "_src") if project else os.path.dirname(os.path.abspath(out_webm))
    os.makedirs(htmldir, exist_ok=True)
    html_path = os.path.join(htmldir, f"{name}.html")
    open(html_path, "w").write(render_html(transcript, theme, title or "claude — product-demo-director"))
    ms = reveal_ms(transcript)
    capture.run("file://" + os.path.abspath(html_path), [{"wait": ms}], out_webm, quiet=True)
    return out_webm


def main():
    sys.path.insert(0, HERE)  # so `import capture` works when run as a script
    ap = argparse.ArgumentParser()
    ap.add_argument("--transcript", default="", help="path to a JSON list of {role,text,ok?}")
    ap.add_argument("--cmd", default="", help="run this command; build a transcript from its output")
    ap.add_argument("--prompt", default="", help="the user line shown above a --cmd run")
    ap.add_argument("--say", default="", help="an assistant line shown before a --cmd run")
    ap.add_argument("--project", default="", help="project dir (for brand.json theme + _src/)")
    ap.add_argument("--name", default="term")
    ap.add_argument("--title", default="claude — product-demo-director")
    ap.add_argument("--out", default="", help="output .webm (record) — required unless --html-only")
    ap.add_argument("--html-only", default="", help="write the HTML to this path and stop (no capture)")
    a = ap.parse_args()

    if a.cmd:
        transcript = transcript_from_cmd(a.cmd, a.prompt or None, a.say or None)
    elif a.transcript:
        transcript = json.load(open(a.transcript))
        if isinstance(transcript, dict):
            transcript = transcript.get("transcript", [])
    else:
        raise SystemExit("provide --transcript or --cmd")

    theme = _brand_theme(a.project) if a.project else {}
    if a.html_only:
        open(a.html_only, "w").write(render_html(transcript, theme, a.title))
        print("html ->", a.html_only, f"(reveal ~{reveal_ms(transcript)/1000:.1f}s)")
        return
    if not a.out:
        raise SystemExit("provide --out <file.webm> or --html-only <file.html>")
    render_and_capture(transcript, a.out, a.project or None, a.name, theme, a.title)
    print("captured ->", a.out, f"(~{reveal_ms(transcript)/1000:.1f}s)")


if __name__ == "__main__":
    main()
