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

    # opt-in, designed pages from existing recorded request/response lines
    python tools/term.py --transcript shot.json --focus-spec pages.json --out api.mp4

Roles: user (the prompt), say (assistant prose), tool (a command, green pin), res (tool output,
gutter), ok (a green line), fin (the closing line, gets the blinking cursor). Add "ok":"72 / 100"
to a res/fin line to highlight a token in the accent color.

Backend choice: an HTML terminal recorded via Playwright (not asciinema+agg). It needs no extra
native deps, matches the engine's look exactly, themes cleanly, and gives the line-by-line reveal
that reads as a live session. asciinema is noted as an alternative in docs/CAPTURE.md.

The TEMINAL STAYS MONOSPACE regardless of brand — only --bg / --accent / --ink are themed.
"""
import argparse, html as _html, json, os, re, subprocess, sys
import hashlib, math, shlex, tempfile
from pathlib import Path
from urllib.parse import urlsplit

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


def compile_focus_pages(transcript, spec):
    """Resolve an opt-in presentation from recorded transcript lines, never commands.

    Each page names requestIndex/responseIndex, a title, and startSec/endSec.
    A metrics page names exact JSON fields; values cannot be supplied by the spec.
    Request URLs and response text are parsed for display only. This function has
    no execution or network behavior. Legacy terminal rendering is unchanged.
    """
    if not isinstance(transcript, list) or not isinstance(spec, dict):
        raise ValueError("focus pages require a transcript list and a specification object")
    duration = spec.get("durationSec")
    fps = spec.get("fps", 30)
    if (isinstance(duration, bool) or not isinstance(duration, (int, float))
            or not math.isfinite(duration) or duration <= 0):
        raise ValueError("durationSec must be positive and finite")
    if isinstance(fps, bool) or not isinstance(fps, int) or not 1 <= fps <= 120:
        raise ValueError("fps must be an integer from 1 to 120")
    frames = round(duration * fps)
    if frames < 1 or abs(frames / fps - duration) > 1e-6:
        raise ValueError("durationSec must end on a whole output frame")
    pages = spec.get("pages")
    if not isinstance(pages, list) or not pages:
        raise ValueError("focus pages must not be empty")

    def line(index, role):
        if (isinstance(index, bool) or not isinstance(index, int)
                or not 0 <= index < len(transcript)):
            raise ValueError("transcript line index is out of range")
        value = transcript[index]
        if not isinstance(value, dict) or value.get("role") != role:
            raise ValueError("focus page references the wrong transcript role")
        text = value.get("text")
        if not isinstance(text, str) or not text.strip():
            raise ValueError("referenced transcript text must not be empty")
        return text

    resolved = []
    previous_end = 0.0
    for page in pages:
        if not isinstance(page, dict):
            raise ValueError("each focus page must be an object")
        start, end = page.get("startSec"), page.get("endSec")
        if any(isinstance(x, bool) or not isinstance(x, (int, float))
               or not math.isfinite(x) for x in (start, end)):
            raise ValueError("focus page times must be finite numbers")
        if abs(start - previous_end) > 1e-6 or end <= start or end > duration + 1e-6:
            raise ValueError("focus pages must cover the duration without gaps or overlaps")
        if any(abs(round(x * fps) / fps - x) > 1e-6 for x in (start, end)):
            raise ValueError("focus page boundaries must fall on output frames")
        title = page.get("title")
        if not isinstance(title, str) or not title.strip() or len(title) > 48:
            raise ValueError("focus page title must contain 1 to 48 characters")
        kind = page.get("kind", "exchange")
        if kind == "recorded-text":
            text = line(page.get("recordIndex"), "recorded-product")
            record = transcript[page["recordIndex"]]
            evidence = record.get("source")
            if not isinstance(evidence, dict):
                raise ValueError("recorded product text needs bound source evidence")
            for name in ("video", "frame"):
                binding = evidence.get(name)
                if (not isinstance(binding, dict) or not isinstance(binding.get("path"), str)
                        or not binding["path"] or not re.fullmatch(r"[0-9a-f]{64}", binding.get("sha256", ""))):
                    raise ValueError("recorded product text needs video and frame paths with SHA256 hashes")
            if evidence.get("textSha256") != hashlib.sha256(text.encode()).hexdigest():
                raise ValueError("recorded text differs from the visually verified transcription")
            if evidence.get("verification") != "manual-visual":
                raise ValueError("recorded product text requires an explicit manual visual verification")
            source_time, roi = evidence.get("timeSec"), evidence.get("roiPx")
            if (isinstance(source_time, bool) or not isinstance(source_time, (int, float))
                    or not math.isfinite(source_time) or source_time < 0):
                raise ValueError("recorded product source time must be nonnegative and finite")
            if (not isinstance(roi, list) or len(roi) != 4
                    or any(isinstance(v, bool) or not isinstance(v, (int, float)) or not math.isfinite(v) for v in roi)
                    or any(v < 0 for v in roi[:2]) or any(v <= 0 for v in roi[2:])):
                raise ValueError("recorded product ROI must be x,y,width,height in source pixels")
            dimensions = evidence.get("dimensionsPx")
            if (not isinstance(dimensions, list) or len(dimensions) != 2
                    or any(isinstance(v, bool) or not isinstance(v, int) or v <= 0 for v in dimensions)
                    or roi[0] + roi[2] > dimensions[0] or roi[1] + roi[3] > dimensions[1]):
                raise ValueError("recorded ROI must fit the declared source dimensions")
            separator = page.get("splitOn", "\n")
            if separator not in ("\n", " · "):
                raise ValueError("recorded text may only be reflowed at source line breaks or middle-dot separators")
            blocks = text.split(separator)
            if not 1 <= len(blocks) <= 4 or any(not block.strip() for block in blocks):
                raise ValueError("recorded text needs one to four intact nonempty source phrases")
            layout = page.get("layout", "lines")
            if layout not in ("lines", "value", "statement") or (layout == "value" and len(blocks) != 2):
                raise ValueError("recorded text layout must be lines, statement, or a two-part value")
            resolved.append(dict(kind=kind, startSec=start, endSec=end, title=title,
                                 recordIndex=page["recordIndex"], text=text, blocks=blocks,
                                 splitOn=separator, layout=layout, source=evidence))
            previous_end = end
            continue
        command = line(page.get("requestIndex"), "tool")
        try:
            tokens = shlex.split(command)
        except ValueError as exc:
            raise ValueError("recorded request cannot be parsed") from exc
        if not tokens or tokens[0] != "curl":
            raise ValueError("focus request must reference a recorded curl command")
        urls = [token for token in tokens if token.startswith(("https://", "http://"))]
        if len(urls) != 1:
            raise ValueError("recorded request must contain exactly one HTTP URL")
        method = "POST" if any(token in ("-d", "--data", "--data-raw", "--data-binary", "--data-urlencode", "-F", "--form", "--json")
                               or token.startswith(("--data=", "--data-raw=", "--data-binary=", "--data-urlencode=", "--form=", "--json="))
                               for token in tokens) else "GET"
        if any(token in ("-I", "--head") for token in tokens):
            method = "HEAD"
        for i, token in enumerate(tokens):
            if token in ("-X", "--request"):
                if i + 1 >= len(tokens):
                    raise ValueError("recorded request method is missing")
                method = tokens[i + 1]
            elif token.startswith("-X") and len(token) > 2:
                method = token[2:]
            elif token.startswith("--request="):
                method = token.split("=", 1)[1]
        if not re.fullmatch(r"[A-Z]+", method):
            raise ValueError("recorded request method must be an uppercase HTTP method")
        parsed = urlsplit(urls[0])
        if not parsed.netloc:
            raise ValueError("recorded request URL has no host")
        response = line(page.get("responseIndex"), "res")
        result = dict(kind=kind, startSec=start, endSec=end, title=title,
                      requestIndex=page["requestIndex"], responseIndex=page["responseIndex"],
                      method=method, url=urls[0], host=parsed.netloc,
                      path=parsed.path + (("?" + parsed.query) if parsed.query else ""))
        if kind == "metrics":
            try:
                data = json.loads(response)
            except json.JSONDecodeError as exc:
                raise ValueError("metrics response must be a JSON object") from exc
            fields = page.get("fields")
            if (not isinstance(data, dict) or not isinstance(fields, list)
                    or not 1 <= len(fields) <= 3
                    or not all(isinstance(key, str) for key in fields)
                    or len(set(fields)) != len(fields)):
                raise ValueError("metrics need one to three unique fields from a JSON object")
            metrics = []
            for key in fields:
                if not isinstance(key, str) or key not in data:
                    raise ValueError("metric field is absent from the recorded response")
                value = data[key]
                if (isinstance(value, bool) or not isinstance(value, (int, float))
                        or not math.isfinite(value)):
                    raise ValueError("metric values must be finite recorded numbers")
                metrics.append(dict(key=key, value=value))
            result["metrics"] = metrics
        elif kind == "exchange":
            if not re.fullmatch(r"HTTP\s+\d{3}\s+[^\r\n]{1,60}", response):
                raise ValueError("exchange response must be a complete recorded HTTP status line")
            response_at = page.get("responseAtSec", start)
            if (isinstance(response_at, bool) or not isinstance(response_at, (int, float))
                    or not math.isfinite(response_at) or not start <= response_at < end):
                raise ValueError("responseAtSec must lie inside its page")
            result.update(response=response, responseAtSec=response_at)
        else:
            raise ValueError("focus page kind must be exchange, metrics, or recorded-text")
        resolved.append(result)
        previous_end = end
    if abs(previous_end - duration) > 1e-6:
        raise ValueError("focus pages do not cover the complete duration")
    return dict(durationSec=duration, fps=fps, frames=frames, pages=resolved)


def verify_recorded_sources(plan, source_root):
    """Check declared media/frame bytes before rendering manually transcribed text.

    The binding verifies file identity, not OCR or the truth of a human claim.
    Source time, ROI and manual-verification method remain explicit in the plan.
    """
    recorded = [page for page in plan["pages"] if page["kind"] == "recorded-text"]
    if not recorded:
        return
    if source_root is None:
        raise ValueError("recorded product excerpts require a source_root for hash verification")
    root = Path(source_root).resolve()
    for page in recorded:
        for name in ("video", "frame"):
            binding = page["source"][name]
            path = (root / binding["path"]).resolve()
            if not path.is_relative_to(root) or not path.is_file():
                raise ValueError("recorded source must be an existing file inside source_root")
            payload = path.read_bytes()
            if hashlib.sha256(payload).hexdigest() != binding["sha256"]:
                raise ValueError("recorded source hash mismatch: " + binding["path"])
            if name == "video":
                try:
                    probe = json.loads(subprocess.check_output([
                        "ffprobe", "-v", "error", "-show_streams", "-show_format", "-of", "json", str(path)
                    ], stderr=subprocess.PIPE))
                    stream = next(item for item in probe["streams"] if item.get("codec_type") == "video")
                    duration = float(stream.get("duration") or probe["format"]["duration"])
                    rotation = float(stream.get("tags", {}).get("rotate", 0))
                    for side in stream.get("side_data_list", []):
                        if "rotation" in side:
                            rotation = float(side["rotation"])
                    dimensions = [int(stream["width"]), int(stream["height"])]
                    if round(rotation) % 180 == 90:
                        dimensions.reverse()
                except (subprocess.CalledProcessError, KeyError, ValueError, StopIteration, TypeError) as exc:
                    raise ValueError("recorded video cannot be probed: " + binding["path"]) from exc
                if not math.isfinite(duration) or not 0 <= page["source"]["timeSec"] < duration:
                    raise ValueError("recorded source time must lie inside its video")
                if dimensions != page["source"]["dimensionsPx"]:
                    raise ValueError("recorded video dimensions differ from the source declaration")
            if name == "frame":
                if payload[:8] != b"\x89PNG\r\n\x1a\n" or len(payload) < 24:
                    raise ValueError("recorded source frame must be an extracted PNG")
                dimensions = [int.from_bytes(payload[16:20], "big"), int.from_bytes(payload[20:24], "big")]
                if dimensions != page["source"]["dimensionsPx"]:
                    raise ValueError("recorded frame dimensions differ from the source declaration")


def render_focus_html(transcript, spec, theme=None):
    """A designed recorded-exchange presentation, with deterministic seek(seconds).

    Unlike the legacy terminal this deliberately shows selected complete response
    units. The persistent label identifies the material as a recorded excerpt.
    """
    plan = compile_focus_pages(transcript, spec)
    theme = theme or {}
    colors = {"bg": theme.get("bg", "#f8f7f3"),
              "ink": theme.get("ink", "#151613"),
              "accent": theme.get("accent", "#ed5a24")}
    if any(not re.fullmatch(r"#(?:[\da-fA-F]{3}|[\da-fA-F]{4}|[\da-fA-F]{6}|[\da-fA-F]{8})", c)
           for c in colors.values()):
        raise ValueError("focus presentation colors must be hexadecimal CSS colors")
    sections = []
    for index, page in enumerate(plan["pages"]):
        attrs = f'data-start="{page["startSec"]}" data-end="{page["endSec"]}" data-kind="{page["kind"]}"'
        if page["kind"] == "recorded-text":
            if page["layout"] == "lines":
                rows = []
                for i, block in enumerate(page["blocks"]):
                    match = re.match(r"^(\d+)(.*)$", block)
                    words = (f'<span class="recorded-number">{_esc(match[1])}</span>'
                             f'<span class="recorded-words">{_esc(match[2])}</span>') if match else _esc(block)
                    rows.append(f'<div class="recorded-row" data-delay="{i * .08}">{words}</div>')
                content = '<div class="recorded-lines">' + "".join(rows) + '</div>'
            elif page["layout"] == "value":
                label, value = page["blocks"]
                size = 305 if len(value) <= 5 else 174
                content = (f'<div class="recorded-value"><div class="recorded-label">{_esc(label)}</div>'
                           f'<div class="recorded-main" style="font-size:{size}px">{_esc(value)}</div></div>')
            else:
                content = '<div class="recorded-statement">' + "".join(
                    f'<div class="recorded-statement-line">{_esc(block)}</div>' for block in page["blocks"]
                ) + '</div>'
        elif page["kind"] == "exchange":
            content = (f'<div class="exchange"><div class="request">'
                       f'<b>{_esc(page["method"])}</b><span>{_esc(page["path"])}</span></div>'
                       f'<div class="host">{_esc(page["host"])}</div>'
                       f'<div class="response" data-at="{page["responseAtSec"]}">'
                       f'<span class="response-marker"></span>{_esc(page["response"])}</div></div>')
        else:
            metrics = "".join(f'<div class="metric"><div class="value">{_esc(m["value"])}</div>'
                              f'<div class="key">{_esc(m["key"])}</div></div>' for m in page["metrics"])
            # Wrap at URI path boundaries, keeping every literal path character.
            path = _esc(page["path"]).replace("/", "/<wbr>")
            if len(page["path"]) > 60:
                # Keep a long record identifier with its final route segment,
                # rather than leaving a lonely /result line at the card edge.
                segments = page["path"].rsplit("/", 2)
                if len(segments) == 3:
                    path = _esc(segments[0] + "/") + "<br>" + _esc("/".join(segments[1:]))
            content = (f'<div class="packet-route"><b>{_esc(page["method"])}</b>'
                       f'<div>{_esc(page["host"])}<br><span>{path}</span></div></div>'
                       f'<div class="metrics" style="--columns:{len(page["metrics"])}">{metrics}</div>')
        sections.append(f'<section class="page" id="page-{index}" {attrs}>'
                        f'<h1>{_esc(page["title"])}</h1>{content}</section>')
    style = """
    *{box-sizing:border-box} html,body{margin:0;width:1920px;height:1080px;overflow:hidden}
    body{background:var(--bg);color:var(--ink);font-family:Arial,Helvetica,sans-serif;-webkit-font-smoothing:antialiased}
    .accent-line{position:absolute;left:120px;top:97px;width:86px;height:5px;background:var(--accent)}
    .eyebrow{position:absolute;left:235px;top:75px;font-size:48px;font-weight:600;letter-spacing:3px}
    .page{position:absolute;inset:0;opacity:0;will-change:opacity,transform}
    h1{position:absolute;left:120px;top:186px;margin:0;font-size:132px;line-height:1.1;letter-spacing:-5px;font-weight:600}
    .exchange{position:absolute;left:120px;top:401px;width:1680px;height:434px;padding:49px 54px;background:#fff;border:1px solid #dddcd6;border-radius:25px;box-shadow:0 12px 34px #17171006}
    .request{display:flex;align-items:center;gap:32px;font-family:Menlo,Consolas,monospace;font-size:79px;line-height:1.2;white-space:nowrap;letter-spacing:-3px}
    .request b,.packet-route b{color:var(--accent);font-weight:600}
    .host{font-size:51px;color:#73736d;margin-top:16px;letter-spacing:-1px}
    .response{position:absolute;left:54px;right:54px;bottom:43px;border-top:1px solid #e4e3dd;padding-top:28px;font-size:103px;line-height:1.05;letter-spacing:-2px;display:flex;align-items:center;gap:28px}
    .response-marker{width:17px;height:17px;background:var(--accent);border-radius:50%;flex-shrink:0}
    .packet-route{position:absolute;left:125px;top:377px;width:1670px;display:flex;gap:24px;font-size:42px;line-height:1.4;font-family:Menlo,Consolas,monospace;letter-spacing:-1px;color:#65665f}
    .packet-route b{font-size:50px}.packet-route span{overflow-wrap:anywhere}
    .metrics{position:absolute;left:120px;top:553px;width:1680px;height:320px;display:grid;grid-template-columns:repeat(var(--columns),1fr);background:#fff;border:1px solid #dddcd6;border-radius:25px;box-shadow:0 12px 34px #17171006}
    .metric{margin:30px 0;padding-left:51px;border-right:1px solid #e1e0db}.metric:last-child{border-right:0}
    .value{font-size:177px;line-height:1;font-weight:500;letter-spacing:-8px;font-variant-numeric:tabular-nums}
    .key{margin-top:12px;font-size:67px;line-height:1.1;letter-spacing:-1px}
    .provenance{position:absolute;left:120px;bottom:94px;font-size:57px;line-height:1.2;letter-spacing:-1px;color:#65665f}
    .recorded-lines{position:absolute;left:120px;top:394px;width:1680px}
    .recorded-row{height:144px;display:flex;align-items:center;gap:35px;border-top:1px solid #d8d7d1;will-change:opacity,transform;font-size:92px;line-height:1.1}
    .recorded-row:last-child{border-bottom:1px solid #d8d7d1}
    .recorded-number{width:150px;flex-shrink:0;font-size:139px;line-height:1;letter-spacing:-5px;font-variant-numeric:tabular-nums}
    .recorded-words{white-space:pre-wrap;letter-spacing:-2px}
    .recorded-value{position:absolute;left:120px;top:428px;width:1680px}
    .recorded-label{font-size:65px;line-height:1.2;letter-spacing:2px;color:#65665f}
    .recorded-main{margin-top:34px;line-height:1.05;letter-spacing:-8px;font-weight:500;font-variant-numeric:tabular-nums}
    .recorded-statement{position:absolute;left:120px;top:433px;width:1680px}
    .recorded-statement-line{font-size:66px;line-height:1.25;letter-spacing:0;color:#65665f;margin-top:30px}
    .recorded-statement-line:first-child{font-size:133px;line-height:1.15;letter-spacing:-5px;color:var(--ink);margin-top:0;margin-bottom:70px}
    """
    script = """
    const pages=Array.from(document.querySelectorAll('.page'));
    const ease=t=>t*t*(3-2*t);
    window.__pddSeek=function(seconds){
      const t=Math.max(0,seconds);
      for(const page of pages){
        const start=Number(page.dataset.start),end=Number(page.dataset.end);
        const product=page.dataset.kind==='recorded-text';
        const active=t>=start&&t<end+0.24;
        const enter=product?ease(Math.min(1,Math.max(0,(t-start)/0.45))):(start===0?1:ease(Math.min(1,Math.max(0,(t-start)/0.24))));
        const leave=t<end?1:1-ease(Math.min(1,(t-end)/0.24));
        page.style.opacity=active?String(enter*leave):'0';
        page.style.transform='translateY('+(active?(1-enter)*18-(1-leave)*18:0)+'px)';
        page.setAttribute('aria-hidden',active?'false':'true');
        const response=page.querySelector('.response');
        if(response){const p=ease(Math.min(1,Math.max(0,(t-Number(response.dataset.at))/0.3)));response.style.opacity=String(p);response.style.transform='translateY('+((1-p)*14)+'px)';}
        for(const row of page.querySelectorAll('.recorded-row')){const p=ease(Math.min(1,Math.max(0,(t-start-Number(row.dataset.delay))/0.4)));row.style.opacity=String(p);row.style.transform='translateY('+((1-p)*12)+'px)';}
      }
    };
    window.__pddSeek(0);
    """
    variables = ";".join(f"--{key}:{value}" for key, value in colors.items())
    product_only = all(page["kind"] == "recorded-text" for page in plan["pages"])
    if any(page["kind"] == "recorded-text" for page in plan["pages"]) and not product_only:
        raise ValueError("recorded product and API pages need separate clips with unambiguous provenance labels")
    eyebrow = "PRODUCT" if product_only else "API"
    provenance = "Recorded product · typeset excerpt" if product_only else "Recorded exchange · separate run"
    return ('<!doctype html><html><head><meta charset="utf-8"><title>Recorded API exchange</title>'
            f'<style>:root{{{variables}}}{style}</style></head><body>'
            f'<div class="accent-line"></div><div class="eyebrow">{eyebrow}</div>'
            + "".join(sections)
            + f'<div class="provenance">{provenance}</div>'
            f'<script>(()=>{{{script}}})();</script></body></html>')


def validate_focus_layout(page, plan):
    """Fail before export if actual browser typography clips or crowds its disclosure.

    Text is measured after entrances settle, including delayed responses. No fitting
    silently reduces the fixed reading sizes: authors must choose shorter intact units.
    """
    reports = []
    for index, item in enumerate(plan["pages"]):
        page.evaluate("window.__pddSeek", item["startSec"] + .8)
        report = page.evaluate("""index => {
          const section=document.getElementById('page-'+index);
          // Measure hidden delayed responses as well, at their resting position.
          section.style.transform='none';
          for(const el of section.querySelectorAll('.response,.recorded-row')) el.style.transform='none';
          const problems=[];let count=0;
          function inspect(root, safe){
            const walker=document.createTreeWalker(root,NodeFilter.SHOW_TEXT);
            let node;while(node=walker.nextNode()){
              if(!node.textContent.trim())continue;
              const range=document.createRange();range.selectNodeContents(node);
              for(const rect of range.getClientRects()){
                if(!rect.width||!rect.height)continue;count++;
                if(rect.left<safe[0]-.5||rect.top<safe[1]-.5||rect.right>safe[2]+.5||rect.bottom>safe[3]+.5)
                  problems.push({text:node.textContent.trim().slice(0,90),bounds:[rect.left,rect.top,rect.right,rect.bottom]});
              }
            }
          }
          inspect(section,[96,150,1824,895]);
          for(const el of document.querySelectorAll('.eyebrow,.provenance')) inspect(el,[96,0,1824,1080]);
          const title=section.querySelector('h1').getBoundingClientRect();
          const content=section.querySelector('.exchange,.packet-route,.recorded-lines,.recorded-value,.recorded-statement').getBoundingClientRect();
          if(title.bottom+24>content.top)problems.push({text:'title overlaps the reading area',bounds:[title.left,title.top,title.right,title.bottom]});
          for(const el of section.querySelectorAll('.recorded-lines,.recorded-value,.recorded-statement')){
            const r=el.getBoundingClientRect();
            if(r.bottom>895)problems.push({text:'content intrudes into the provenance footer',bounds:[r.left,r.top,r.right,r.bottom]});
          }
          // A wrapped phrase can remain inside the canvas while colliding with
          // adjacent rows. Its actual text must fit its own semantic row too.
          for(const row of section.querySelectorAll('.recorded-row')){
            const r=row.getBoundingClientRect();
            // Font range boxes include ascender/descender leading around the
            // large numeral; allow that small overhang, never another line.
            inspect(row,[r.left,r.top-10,r.right,r.bottom+10]);
          }
          for(const el of section.querySelectorAll('.recorded-number,.recorded-words,.metric')){
            const r=el.getBoundingClientRect();
            inspect(el,[r.left,150,r.right,895]);
          }
          return {page:index,textFragments:count,problems};
        }""", index)
        if report["problems"]:
            raise ValueError(f"focus layout overflow on page {index}: " + json.dumps(report["problems"]))
        reports.append(report)
    page.evaluate("window.__pddSeek", 0)
    return reports


def render_focus_video(transcript, spec, out_mp4, *, html_path=None, theme=None, source_root=None):
    """Render local generated HTML at exact frame times; never visit the API URL."""
    from playwright.sync_api import sync_playwright
    import capture
    plan = compile_focus_pages(transcript, spec)
    verify_recorded_sources(plan, source_root)
    source = render_focus_html(transcript, spec, theme)
    destination = Path(out_mp4).resolve()
    destination.parent.mkdir(parents=True, exist_ok=True)
    if html_path:
        Path(html_path).parent.mkdir(parents=True, exist_ok=True)
        Path(html_path).write_text(source)
    with tempfile.TemporaryDirectory(prefix="pdd-focus-") as temp:
        with sync_playwright() as playwright:
            browser = capture._launch(playwright)
            context = browser.new_context(viewport={"width":1920,"height":1080}, device_scale_factor=1)
            # Generated media only. No external fonts, images, or live requests.
            context.route("**/*", lambda route: route.abort())
            page = context.new_page()
            page.set_content(source, wait_until="load")
            page.evaluate("document.fonts.ready")
            layout = validate_focus_layout(page, plan)
            for frame in range(plan["frames"]):
                page.evaluate("window.__pddSeek", frame / plan["fps"])
                page.screenshot(path=str(Path(temp) / f"{frame:06d}.png"))
            context.close()
            browser.close()
        temporary_video = Path(temp) / "focus.mp4"
        subprocess.run(["ffmpeg","-v","error","-framerate",str(plan["fps"]),
                        "-i",str(Path(temp)/"%06d.png"),"-frames:v",str(plan["frames"]),
                        "-c:v","libx264","-crf","17","-preset","medium","-pix_fmt","yuv420p",
                        "-video_track_timescale",str(plan["fps"] * 1000),
                        "-movie_timescale",str(plan["fps"] * 1000),
                        "-movflags","+faststart",str(temporary_video)],check=True)
        os.replace(temporary_video, destination)
    return {"path":str(destination),"sha256":hashlib.sha256(destination.read_bytes()).hexdigest(),
            "layoutValidation": layout, **plan}


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
    ap.add_argument("--focus-spec", default="", help="opt-in recorded focus-page JSON; --out is an MP4")
    a = ap.parse_args()

    if a.focus_spec and a.cmd:
        raise SystemExit("--focus-spec requires a saved --transcript; commands are never executed in this mode")

    if a.cmd:
        transcript = transcript_from_cmd(a.cmd, a.prompt or None, a.say or None)
    elif a.transcript:
        transcript = json.load(open(a.transcript))
        if isinstance(transcript, dict):
            transcript = transcript.get("transcript", [])
    else:
        raise SystemExit("provide --transcript or --cmd")

    theme = _brand_theme(a.project) if a.project else {}
    if a.focus_spec:
        spec = json.load(open(a.focus_spec))
        if a.html_only:
            verify_recorded_sources(compile_focus_pages(transcript, spec), a.project or None)
            Path(a.html_only).write_text(render_focus_html(transcript, spec, theme))
            print("focus pages ->", a.html_only)
            return
        if not a.out or not a.out.lower().endswith(".mp4"):
            raise SystemExit("focus pages require --out <file.mp4> or --html-only")
        source_dir = Path(a.project) / "_src" if a.project else Path(a.out).parent
        result = render_focus_video(transcript, spec, a.out,
                                    html_path=source_dir / f"{a.name}.html", theme=theme,
                                    source_root=a.project or None)
        print("rendered focus pages ->", result["path"], f'({result["frames"]} frames)')
        return
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
