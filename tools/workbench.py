#!/usr/bin/env python3
"""Render a Codex/Claude production workbench as reproducible demo footage.

The workbench is intentionally data-driven. A committed JSON session describes the
human prompt, real tool actions, whitelisted results, changed files, preview media,
and production phases. The generated HTML is a cinematic replay, not a screenshot of
the proprietary Codex or Claude UI.

    .venv/bin/python tools/workbench.py \
      --project examples/save-the-cat \
      --session examples/save-the-cat/_src/codex-workbench.json \
      --out examples/save-the-cat/assets/codex-workbench.webm

Use ``--html-only`` to inspect the deterministic HTML without recording it.
"""

from __future__ import annotations

import argparse
import html
import json
import os
import re
import subprocess
import sys
import tempfile
from pathlib import Path


HERE = Path(__file__).resolve().parent
INTRO_MS = 700
TAIL_MS = 900

THEME_DEFAULTS = {
    "bg": "#0c1310",
    "panel": "#111a16",
    "ink": "#f4f6f3",
    "sub": "rgba(244,246,243,.62)",
    "accent": "#46b07c",
    "warn": "#e0a24a",
}
CSS_COLOR = re.compile(
    r"(?:#[0-9a-fA-F]{3,8}|(?:rgb|rgba|hsl|hsla)\([0-9.,%\s+-]+\))"
)


def _safe_css_color(value: object, fallback: str) -> str:
    candidate = str(value or "").strip()
    return candidate if CSS_COLOR.fullmatch(candidate) else fallback


def _brand(project: Path) -> dict:
    path = project / "brand.json"
    if not path.exists():
        return {}
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}


def _theme(project: Path) -> dict[str, str]:
    brand = _brand(project)
    palette = brand.get("palette") or brand.get("theme") or {}
    requested = {
        "bg": palette.get("bg") or palette.get("background"),
        "panel": palette.get("panel"),
        "ink": palette.get("ink") or palette.get("text"),
        "sub": palette.get("sub") or palette.get("muted"),
        "accent": palette.get("accent") or palette.get("primary"),
        "warn": palette.get("warn") or palette.get("warning"),
    }
    return {key: _safe_css_color(requested.get(key), fallback)
            for key, fallback in THEME_DEFAULTS.items()}


def _safe_payload(value: dict) -> str:
    # JSON is consumed as data. Escaping '<' prevents a copied string from closing
    # the script tag if a session ever contains HTML-like product text.
    return json.dumps(value, ensure_ascii=False).replace("<", "\\u003c")


def render_html(session: dict, theme: dict[str, str]) -> str:
    theme = {key: _safe_css_color(theme.get(key), fallback)
             for key, fallback in THEME_DEFAULTS.items()}
    title = html.escape(str(session.get("title") or "Codex · product-demo-director"))
    payload = _safe_payload(session)
    return f"""<!doctype html>
<html><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<style>
  :root{{--bg:{theme['bg']};--panel:{theme['panel']};--ink:{theme['ink']};--sub:{theme['sub']};--accent:{theme['accent']};--warn:{theme['warn']}}}
  *{{box-sizing:border-box}} html,body{{margin:0;width:100%;height:100%;overflow:hidden;background:var(--bg)}}
  body{{font-family:Inter,-apple-system,BlinkMacSystemFont,"Segoe UI",sans-serif;color:var(--ink);
    background:radial-gradient(110% 100% at 78% 0%,rgba(70,176,124,.13),transparent 56%),var(--bg)}}
  .shell{{position:absolute;inset:34px;border:1px solid rgba(255,255,255,.12);border-radius:24px;overflow:hidden;
    box-shadow:0 42px 130px rgba(0,0,0,.55);background:rgba(12,19,16,.88)}}
  .top{{height:72px;display:flex;align-items:center;padding:0 24px;border-bottom:1px solid rgba(255,255,255,.09);
    background:rgba(17,26,22,.94)}}
  .mark{{width:34px;height:34px;border-radius:10px;display:grid;place-items:center;background:var(--accent);color:#07100b;
    font-size:18px;font-weight:950;margin-right:13px;box-shadow:0 0 28px rgba(70,176,124,.32)}}
  .title{{font-weight:820;font-size:20px;letter-spacing:.1px}} .title span{{color:var(--sub);font-weight:620}}
  .run{{margin-left:auto;display:flex;align-items:center;gap:9px;color:var(--accent);font:800 14px ui-monospace,SFMono-Regular,Menlo,monospace;letter-spacing:1.4px}}
  .pulse{{width:9px;height:9px;border-radius:50%;background:var(--accent);box-shadow:0 0 0 0 rgba(70,176,124,.5);animation:pulse 1.8s infinite}}
  @keyframes pulse{{70%{{box-shadow:0 0 0 12px rgba(70,176,124,0)}}100%{{box-shadow:0 0 0 0 rgba(70,176,124,0)}}}}
  .main{{position:absolute;left:0;right:0;top:72px;bottom:82px;display:grid;grid-template-columns:46% 54%;min-height:0;
    transition:grid-template-columns .55s cubic-bezier(.2,.8,.2,1)}}
  .main.focus-agent{{grid-template-columns:100% 0%}} .main.focus-preview{{grid-template-columns:0% 100%}}
  .main.focus-agent .preview,.main.focus-preview .session{{opacity:0;pointer-events:none;padding-left:0;padding-right:0}}
  .session{{position:relative;padding:28px 30px;border-right:1px solid rgba(255,255,255,.09);overflow:hidden;
    opacity:1;transition:opacity .24s ease,padding .55s cubic-bezier(.2,.8,.2,1)}}
  .kicker{{font:800 13px ui-monospace,SFMono-Regular,Menlo,monospace;color:var(--sub);letter-spacing:1.8px;margin-bottom:10px}}
  .prompt{{padding:17px 19px;border-radius:15px;background:rgba(255,255,255,.055);border:1px solid rgba(255,255,255,.09);
    font-size:22px;line-height:1.34;font-weight:650;box-shadow:0 18px 44px rgba(0,0,0,.18)}}
  .agent{{margin-top:20px;display:grid;grid-template-columns:34px 1fr;gap:12px;align-items:start}}
  .avatar{{width:34px;height:34px;border-radius:10px;background:rgba(70,176,124,.15);border:1px solid rgba(70,176,124,.4);
    display:grid;place-items:center;color:var(--accent);font:900 14px ui-monospace,SFMono-Regular,Menlo,monospace}}
  .message{{font-size:19px;line-height:1.42;color:rgba(244,246,243,.92);min-height:54px}}
  .tool{{margin-top:16px;border-radius:14px;border:1px solid rgba(70,176,124,.25);background:#0b120f;overflow:hidden;
    transform:translateY(14px);opacity:0;transition:opacity .34s ease,transform .34s ease}}
  .tool.on{{transform:none;opacity:1}} .toolhead{{display:flex;align-items:center;gap:9px;padding:11px 14px;border-bottom:1px solid rgba(255,255,255,.07);
    color:var(--accent);font:800 13px ui-monospace,SFMono-Regular,Menlo,monospace;letter-spacing:1.3px}}
  .toolcmd{{padding:15px 16px;color:#c8d3cc;font:600 17px/1.35 ui-monospace,SFMono-Regular,Menlo,monospace;white-space:pre-wrap}}
  .result{{margin-top:12px;padding-left:14px;border-left:2px solid var(--accent);color:var(--sub);
    font:650 16px/1.35 ui-monospace,SFMono-Regular,Menlo,monospace;opacity:0;transform:translateX(-8px);transition:.34s ease}}
  .result.on{{opacity:1;transform:none}}
  .files{{position:absolute;left:30px;right:30px;bottom:24px;display:flex;gap:8px;flex-wrap:wrap}}
  .file{{padding:8px 11px;border-radius:9px;border:1px solid rgba(255,255,255,.08);background:rgba(255,255,255,.04);
    color:var(--sub);font:650 13px ui-monospace,SFMono-Regular,Menlo,monospace}}
  .file.changed{{color:var(--accent);border-color:rgba(70,176,124,.28);background:rgba(70,176,124,.08)}}
  .preview{{position:relative;padding:24px;background:linear-gradient(150deg,rgba(255,255,255,.025),rgba(255,255,255,0));overflow:hidden;
    opacity:1;transition:opacity .24s ease,padding .55s cubic-bezier(.2,.8,.2,1)}}
  .previewHead{{display:flex;align-items:center;margin-bottom:14px}} .previewTitle{{font-size:15px;font-weight:850;letter-spacing:1.6px;color:var(--sub)}}
  .phaseNo{{margin-left:auto;color:var(--accent);font:800 13px ui-monospace,SFMono-Regular,Menlo,monospace}}
  .canvas{{position:absolute;left:24px;right:24px;top:60px;bottom:24px;border:1px solid rgba(255,255,255,.1);border-radius:18px;
    background:linear-gradient(145deg,#1b2c23,#17241e);overflow:hidden;box-shadow:inset 0 0 0 1px rgba(0,0,0,.25),0 24px 70px rgba(0,0,0,.28)}}
  .canvasInner{{position:absolute;inset:0;opacity:0;transform:scale(.975);transition:opacity .36s ease,transform .45s cubic-bezier(.2,.8,.2,1)}}
  .canvasInner.on{{opacity:1;transform:none}}
  .video{{width:100%;height:100%;object-fit:cover;filter:saturate(1.04)}}
  .videoScrim{{position:absolute;inset:0;background:linear-gradient(180deg,rgba(0,0,0,.06),transparent 45%,rgba(0,0,0,.5))}}
  .previewLabel{{position:absolute;left:18px;top:18px;padding:7px 11px;border-radius:8px;background:rgba(8,12,10,.78);
    border:1px solid rgba(255,255,255,.14);font:850 12px ui-monospace,SFMono-Regular,Menlo,monospace;letter-spacing:1.2px}}
  .inputGrid{{position:absolute;inset:34px;display:grid;grid-template-columns:1fr 1fr;gap:14px}}
  .inputCard{{position:relative;padding:20px;border-radius:15px;background:linear-gradient(150deg,rgba(70,176,124,.10),rgba(255,255,255,.025));
    border:1px solid rgba(70,176,124,.22);overflow:hidden}}
  .inputCard b{{display:block;font-size:18px;margin-bottom:8px}} .inputCard span{{color:var(--sub);font:600 14px/1.35 ui-monospace,SFMono-Regular,Menlo,monospace}}
  .inputCard:after{{content:"";position:absolute;width:70px;height:70px;border-radius:50%;right:-28px;bottom:-30px;background:rgba(70,176,124,.12)}}
  .story{{position:absolute;inset:34px;display:grid;grid-template-columns:repeat(3,1fr);gap:16px;align-items:center}}
  .beat{{min-height:230px;border-radius:16px;padding:22px 18px;background:linear-gradient(180deg,rgba(255,255,255,.07),rgba(255,255,255,.025));
    border:1px solid rgba(255,255,255,.11);transform:translateY(18px);opacity:0;animation:rise .5s forwards}}
  .beat:nth-child(2){{animation-delay:.12s}} .beat:nth-child(3){{animation-delay:.24s}} @keyframes rise{{to{{transform:none;opacity:1}}}}
  .beat em{{font-style:normal;color:var(--accent);font:850 12px ui-monospace,SFMono-Regular,Menlo,monospace;letter-spacing:1.5px}}
  .beat b{{display:block;margin-top:18px;font-size:20px;line-height:1.28}} .beat span{{display:block;margin-top:12px;color:var(--sub);font-size:15px;line-height:1.35}}
  .timeline{{position:absolute;left:18px;right:18px;bottom:18px;height:94px;padding:14px;border-radius:13px;background:rgba(7,11,9,.88);border:1px solid rgba(255,255,255,.1)}}
  .track{{height:15px;display:flex;gap:5px;margin-bottom:8px}} .clip{{height:100%;border-radius:4px;background:rgba(70,176,124,.72)}}
  .clip.alt{{background:rgba(224,162,74,.65)}} .clip.dim{{background:rgba(255,255,255,.16)}}
  .playhead{{position:absolute;top:8px;bottom:8px;width:2px;background:#fff;left:5%;box-shadow:0 0 10px rgba(255,255,255,.55);animation:play 3s linear infinite}}
  @keyframes play{{to{{left:94%}}}}
  .renderPane{{position:absolute;inset:36px;display:flex;flex-direction:column;justify-content:center}}
  .renderFile{{font-size:34px;font-weight:880}} .renderSub{{margin-top:9px;color:var(--sub);font:650 16px ui-monospace,SFMono-Regular,Menlo,monospace}}
  .progress{{height:16px;border-radius:999px;background:rgba(255,255,255,.08);margin-top:28px;overflow:hidden;border:1px solid rgba(255,255,255,.08)}}
  .progress>div{{height:100%;width:100%;background:linear-gradient(90deg,var(--accent),#7be3ae);transform-origin:left;animation:fill 2.4s cubic-bezier(.2,.8,.2,1) forwards}}
  @keyframes fill{{from{{transform:scaleX(.04)}}to{{transform:scaleX(1)}}}}
  .outputs{{display:flex;gap:10px;margin-top:24px}} .output{{padding:11px 13px;border-radius:10px;background:rgba(70,176,124,.08);border:1px solid rgba(70,176,124,.2);
    color:var(--accent);font:750 14px ui-monospace,SFMono-Regular,Menlo,monospace}}
  .qa{{position:absolute;inset:28px;display:grid;grid-template-columns:38% 62%;gap:20px;align-items:stretch}}
  .qaPass{{border-radius:18px;display:flex;flex-direction:column;align-items:center;justify-content:center;background:radial-gradient(circle at 50% 35%,rgba(70,176,124,.22),rgba(70,176,124,.04));border:1px solid rgba(70,176,124,.28)}}
  .qaPass .check{{width:84px;height:84px;border-radius:50%;display:grid;place-items:center;background:var(--accent);color:#07100b;font-size:48px;font-weight:950;box-shadow:0 0 54px rgba(70,176,124,.36)}}
  .qaPass b{{font-size:27px;margin-top:22px}} .qaPass span{{color:var(--sub);margin-top:7px;font:700 14px ui-monospace,SFMono-Regular,Menlo,monospace}}
  .metrics{{display:grid;grid-template-columns:1fr 1fr;gap:12px}} .metric{{border-radius:14px;padding:17px;background:rgba(255,255,255,.045);border:1px solid rgba(255,255,255,.09)}}
  .metric b{{display:block;font-size:21px}} .metric span{{display:block;margin-top:7px;color:var(--sub);font:650 13px ui-monospace,SFMono-Regular,Menlo,monospace}}
  .delivery{{position:absolute;inset:34px;display:flex;flex-direction:column;justify-content:center}}
  .deliveryTitle{{font-size:29px;font-weight:880;margin-bottom:22px}} .deliveryTitle span{{color:var(--accent)}}
  .deliveryFiles{{display:grid;grid-template-columns:1fr 1fr;gap:12px}}
  .deliveryFile{{padding:18px;border-radius:14px;background:rgba(255,255,255,.045);border:1px solid rgba(255,255,255,.1);
    font:760 16px ui-monospace,SFMono-Regular,Menlo,monospace;transform:translateY(12px);opacity:0;animation:rise .5s forwards}}
  .deliveryFile:nth-child(2){{animation-delay:.1s}} .deliveryFile:nth-child(3){{animation-delay:.2s}} .deliveryFile:nth-child(4){{animation-delay:.3s}}
  .deliveryFile b{{display:block;color:var(--accent);font-size:12px;letter-spacing:1.2px;margin-bottom:7px}}
  .rail{{position:absolute;left:0;right:0;bottom:0;height:82px;display:flex;align-items:center;padding:0 26px;border-top:1px solid rgba(255,255,255,.09);background:rgba(17,26,22,.96)}}
  .stages{{display:flex;align-items:center;gap:10px;flex:1}} .stage{{display:flex;align-items:center;gap:8px;color:rgba(244,246,243,.34);font:800 12px ui-monospace,SFMono-Regular,Menlo,monospace;letter-spacing:1.1px}}
  .stage:after{{content:"";display:block;width:38px;height:1px;background:rgba(255,255,255,.13)}} .stage:last-child:after{{display:none}}
  .stage i{{width:10px;height:10px;border-radius:50%;background:rgba(255,255,255,.14)}} .stage.done,.stage.active{{color:var(--accent)}} .stage.done i{{background:var(--accent)}}
  .stage.active i{{background:var(--accent);box-shadow:0 0 0 6px rgba(70,176,124,.12)}}
  .truth{{color:rgba(244,246,243,.32);font:650 11px ui-monospace,SFMono-Regular,Menlo,monospace;letter-spacing:.8px}}
  .cursor{{position:absolute;z-index:50;width:24px;height:28px;left:76%;top:46%;filter:drop-shadow(0 3px 5px rgba(0,0,0,.55));transition:left .85s cubic-bezier(.3,.8,.2,1),top .85s cubic-bezier(.3,.8,.2,1)}}
  .cursor svg{{width:100%;height:100%}}
</style></head><body>
<div class="shell">
  <div class="top"><div class="mark">C</div><div class="title">{title} <span>· agent workbench</span></div><div class="run"><i class="pulse"></i> DIRECTING</div></div>
  <div class="main">
    <section class="session">
      <div class="kicker">YOU</div><div class="prompt" id="prompt"></div>
      <div class="agent"><div class="avatar">C</div><div><div class="kicker">CODEX</div><div class="message" id="message"></div></div></div>
      <div class="tool" id="tool"><div class="toolhead">● TOOL ACTION</div><div class="toolcmd" id="toolcmd"></div></div>
      <div class="result" id="result"></div><div class="files" id="files"></div>
    </section>
    <section class="preview"><div class="previewHead"><div class="previewTitle" id="previewTitle"></div><div class="phaseNo" id="phaseNo"></div></div><div class="canvas" id="canvas"></div></section>
  </div>
  <footer class="rail"><div class="stages" id="stages"></div><div class="truth">CURATED REPLAY · WHITELISTED OUTPUT</div></footer>
  <div class="cursor" id="cursor"><svg viewBox="0 0 26 30"><path d="M2 2 L2 24 L8.5 18.5 L12.5 27 L16.5 25 L12.5 17 L21 16.5 Z" fill="#fff" stroke="#151a17" stroke-width="1.7" stroke-linejoin="round"/></svg></div>
</div>
<script>
const session={payload};
const stages=['INPUTS','STORY','CAPTURE','EDIT','RENDER','VERIFY'];
const $=id=>document.getElementById(id);
$('prompt').textContent=session.prompt||'';
function escText(v){{const d=document.createElement('div');d.textContent=v??'';return d.innerHTML}}
function escAttr(v){{return escText(v).replaceAll('"','&quot;').replaceAll("'",'&#39;')}}
function cards(items,kind){{return (items||[]).map((item,i)=>{{
  const bits=String(item).split(' · '); return `<div class="${{kind}}"><b>${{escText(bits[0])}}</b><span>${{escText(bits.slice(1).join(' · '))}}</span></div>`;
}}).join('')}}
function renderCanvas(p){{
  const mode=p.mode||'inputs'; let body='';
  if((mode==='prompt'||mode==='capture'||mode==='edit')&&p.previewSrc){{
    body=`<div class="canvasInner"><video class="video" src="${{escAttr(p.previewSrc)}}" autoplay muted loop playsinline></video><div class="videoScrim"></div><div class="previewLabel">${{escText(p.previewLabel||'LIVE PREVIEW')}}</div>${{mode==='edit'?`<div class="timeline"><div class="playhead"></div><div class="track"><div class="clip" style="width:24%"></div><div class="clip alt" style="width:16%"></div><div class="clip" style="width:32%"></div><div class="clip dim" style="width:21%"></div></div><div class="track"><div class="clip dim" style="width:17%"></div><div class="clip" style="width:36%"></div><div class="clip alt" style="width:13%"></div><div class="clip" style="width:26%"></div></div><div class="track"><div class="clip alt" style="width:93%"></div></div></div>`:''}}</div>`;
  }} else if(mode==='script'){{
    const labels=['HOOK','CHANGE','PROOF'];
    body=`<div class="canvasInner"><div class="story">${{(p.steps||[]).slice(0,3).map((x,i)=>`<div class="beat"><em>${{labels[i]||'BEAT'}}</em><b>${{escText(String(x).split(' · ')[0])}}</b><span>${{escText(String(x).split(' · ').slice(1).join(' · '))}}</span></div>`).join('')}}</div></div>`;
  }} else if(mode==='render'){{
    body=`<div class="canvasInner"><div class="renderPane"><div class="renderFile">demo-final.mp4</div><div class="renderSub">Remotion · exact-frame timeline</div><div class="progress"><div></div></div><div class="outputs"><div class="output">build-plan.json</div><div class="output">artifact.json</div><div class="output">H.264 / AAC</div></div></div></div>`;
  }} else if(mode==='qa'){{
    const metrics=(p.steps||['60.000 s · runtime','1800 · exact frames','-18.0 LUFS · audio','BT.709 · web color','0 · black issues','0 · silence issues']);
    body=`<div class="canvasInner"><div class="qa"><div class="qaPass"><div class="check">✓</div><b>STRICT QA PASS</b><span>artifact-bound · 0 issues</span></div><div class="metrics">${{metrics.slice(0,6).map(x=>{{const b=String(x).split(' · ');return `<div class="metric"><b>${{escText(b[0])}}</b><span>${{escText(b.slice(1).join(' · '))}}</span></div>`}}).join('')}}</div></div></div>`;
  }} else if(mode==='delivery'){{
    const files=(p.steps||['demo-final.mp4 · finished film','build-plan.json · exact frames','artifact.json · source bindings','qa-report.json · delivery proof']);
    body=`<div class="canvasInner"><div class="delivery"><div class="deliveryTitle">One film. <span>Four receipts.</span></div><div class="deliveryFiles">${{files.slice(0,4).map(x=>{{const b=String(x).split(' · ');return `<div class="deliveryFile"><b>${{escText(b.slice(1).join(' · ')||'DELIVERY')}}</b>${{escText(b[0])}}</div>`}}).join('')}}</div></div></div>`;
  }} else {{
    body=`<div class="canvasInner"><div class="inputGrid">${{cards(p.steps||[],'inputCard')}}</div></div>`;
  }}
  $('canvas').innerHTML=body; requestAnimationFrame(()=>{{const n=$('canvas').querySelector('.canvasInner');if(n)n.classList.add('on')}});
}}
let idx=0,timer=null;
function show(i){{
  const p=session.phases[i]; idx=i; if(!p)return;
  const focus=['agent','preview'].includes(p.focus)?p.focus:'balanced';
  document.querySelector('.main').className=`main ${{focus==='balanced'?'':'focus-'+focus}}`;
  $('message').textContent=p.message||''; $('toolcmd').textContent=p.tool||''; $('result').textContent=p.result||'';
  $('previewTitle').textContent=p.label||p.mode||'PREVIEW'; $('phaseNo').textContent=`${{String(i+1).padStart(2,'0')}} / ${{String(session.phases.length).padStart(2,'0')}}`;
  $('files').innerHTML=(p.files||[]).map(f=>`<div class="file ${{String(f).startsWith('+')?'changed':''}}">${{escText(f)}}</div>`).join('');
  $('tool').classList.remove('on'); $('result').classList.remove('on'); setTimeout(()=>$('tool').classList.add('on'),240); setTimeout(()=>$('result').classList.add('on'),610);
  $('stages').innerHTML=stages.map((s,j)=>`<div class="stage ${{j<(p.stage||0)?'done':j===(p.stage||0)?'active':''}}"><i></i>${{s}}</div>`).join('');
  renderCanvas(p); const c=p.cursor||[72,48]; $('cursor').style.left=c[0]+'%'; $('cursor').style.top=c[1]+'%';
  clearTimeout(timer);
  if(i+1<session.phases.length) timer=setTimeout(()=>show(i+1),Math.max(1000,p.durationMs||3500));
}}
setTimeout(()=>show(0),{INTRO_MS});
</script></body></html>"""


def duration_ms(session: dict) -> int:
    phases = session.get("phases") if isinstance(session.get("phases"), list) else []
    return INTRO_MS + sum(max(1000, int(p.get("durationMs", 3500))) for p in phases) + TAIL_MS


def _validate_preview_sources(session: dict, project: Path) -> None:
    assets = (project / "assets").resolve()
    source_dir = (project / "_src").resolve()
    for index, phase in enumerate(session.get("phases") or []):
        preview = phase.get("previewSrc")
        if not preview:
            continue
        candidate = (source_dir / str(preview)).resolve()
        try:
            candidate.relative_to(assets)
        except ValueError as exc:
            raise SystemExit(f"phase {index + 1} previewSrc must resolve under {assets}") from exc
        if candidate.suffix.lower() not in {".mp4", ".webm", ".mov", ".m4v"}:
            raise SystemExit(f"phase {index + 1} previewSrc must be a supported video file")
        if not candidate.is_file():
            raise SystemExit(f"phase {index + 1} previewSrc does not exist: {candidate}")


def main() -> None:
    sys.path.insert(0, str(HERE))
    parser = argparse.ArgumentParser()
    parser.add_argument("--project", required=True)
    parser.add_argument("--session", required=True, help="JSON workbench session")
    parser.add_argument("--out", default="")
    parser.add_argument("--html-only", default="")
    args = parser.parse_args()

    project = Path(args.project).resolve()
    session_path = Path(args.session).resolve()
    session = json.loads(session_path.read_text(encoding="utf-8"))
    if not isinstance(session.get("phases"), list) or not session["phases"]:
        raise SystemExit("session must contain a non-empty phases list")
    _validate_preview_sources(session, project)
    rendered = render_html(session, _theme(project))
    html_path = Path(args.html_only).resolve() if args.html_only else project / "_src" / "codex-workbench.html"
    html_path.parent.mkdir(parents=True, exist_ok=True)
    html_path.write_text(rendered, encoding="utf-8")
    if args.html_only:
        print(f"html -> {html_path} ({duration_ms(session)/1000:.1f}s)")
        return
    if not args.out:
        raise SystemExit("provide --out <file.webm> or --html-only <file.html>")
    import capture

    output = Path(args.out).resolve()
    output.parent.mkdir(parents=True, exist_ok=True)
    raw_handle = tempfile.NamedTemporaryFile(
        prefix=f".{output.stem}-", suffix=".raw.webm", dir=output.parent, delete=False
    )
    raw_handle.close()
    raw_output = Path(raw_handle.name)
    try:
        capture.run(html_path.as_uri(), [{"wait": duration_ms(session)}], str(raw_output), quiet=True, cursor=False)
        subprocess.run([
            "ffmpeg", "-y", "-v", "error", "-ss", "0.8", "-i", str(raw_output),
            "-t", f"{duration_ms(session) / 1000:.3f}", "-an", "-c:v", "libvpx-vp9",
            "-crf", "30", "-b:v", "0", str(output),
        ], check=True)
    finally:
        if raw_output.exists():
            raw_output.unlink()
    print(f"captured -> {output} (~{duration_ms(session)/1000:.1f}s)")


if __name__ == "__main__":
    main()
