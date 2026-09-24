/* Product Demo Director · motion kit
 *
 * Deterministic building blocks for code-built motion-graphics films rendered frame by frame.
 * Contract every film must keep (tools/motion_render.mjs depends on it):
 *   window.DUR = <seconds>;  window.seek(t) renders the complete frame for time t, synchronously
 *   (or returns a Promise when it must await image decode), with no clocks, no requestAnimationFrame
 *   and no unseeded randomness. Seeking to any t, in any order, must give the identical frame.
 *   Never give an element id="ready" (it shadows window.ready).
 *
 * Load with <script src="../../motion/kit.js"></script> (path relative to the film) before the film script.
 */
(function (g) {
  const $ = id => document.getElementById(id);
  const cl = (x, a = 0, b = 1) => Math.min(b, Math.max(a, x));
  const P = (t, a, b) => cl((t - a) / (b - a));                 // normalised progress of t in [a,b]
  const L = (a, b, x) => a + (b - a) * x;                        // lerp
  const eo = x => (x >= 1 ? 1 : 1 - Math.pow(2, -10 * x));       // ease-out expo: arrivals
  const eio = x => (x < .5 ? 4 * x * x * x : 1 - Math.pow(-2 * x + 2, 3) / 2); // ease-in-out cubic: moves
  const backOut = (c1 = 1.7) => x => { const c3 = c1 + 1; return 1 + c3 * Math.pow(x - 1, 3) + c1 * Math.pow(x - 1, 2); };
  const back = backOut(2.0);      // punchy overshoot for hits (slams, stamps, verdicts)
  const soft = backOut(1.15);     // gentle settle for flowing elements (lists, queues, cards)
  // squash-and-stretch after an impact at time a: + = squash (wider/shorter). Use sx:1+q*.5, sy:1-q.
  const squash = (u, a, amp = .22) => { const k = u - a; return k < 0 || k > .4 ? 0 : Math.sin(k / .4 * Math.PI * 1.5) * Math.exp(-k * 8) * amp; };
  // decaying wobble for "the world reacts to the hit" (px)
  const wobble = (u, a, amp = 10, f = 9, d = 3.2) => (u > a ? Math.sin((u - a) * f) * Math.exp(-(u - a) * d) * amp : 0);

  // Set transform/opacity/blur on an element. r in degrees; sx/sy multiply s for squash.
  function S(el, { op = 1, x = 0, y = 0, s = 1, r = 0, sx = 1, sy = 1, b = 0 } = {}) {
    el = typeof el === 'string' ? $(el) : el;
    el.style.opacity = op;
    el.style.transform = `translate(${x}px,${y}px) scale(${s * sx},${s * sy}) rotate(${r}deg)`;
    el.style.filter = b > .05 ? `blur(${b}px)` : 'none';
  }
  // Hit: fast overshoot pop with squash on landing. For stamps, verdicts, slam words.
  function pop(el, u, a, { from = 0, dx = 0, dy = 0, r = 0, d = .2 } = {}) {
    const k = P(u, a, a + d), q = squash(u, a + d * .9);
    S(el, { op: cl(P(u, a, a + .08)), s: L(from, 1, back(k)), sx: 1 + q * .5, sy: 1 - q, x: (1 - eo(k)) * dx, y: (1 - eo(k)) * dy, r });
  }
  // Flow: smooth glide-in with a soft settle. For queues, lists, cards that arrive in sequence.
  function glide(el, u, a, { dx = 60, dy = -70, r0 = 0, r = 0, s0 = .86, d = .7, extraY = 0 } = {}) {
    const k = P(u, a, a + d);
    S(el, { op: cl(P(u, a, a + .22)), s: L(s0, 1, soft(k)), x: (1 - eo(k)) * dx, y: (1 - eo(k)) * dy + extraY, r: L(r0, r, eo(k)) });
  }
  // Scene visibility + solid colour-block wipes. scenes: [[id, start, end], ...]; dirs: {id:[dx,dy]}.
  function sceneWipes(t, scenes, dirs, lead = .3) {
    scenes.forEach(([id, a, b], i) => {
      const el = $(id); el.style.visibility = t >= a - lead && t < b ? 'visible' : 'hidden'; el.style.zIndex = 10 + i;
      if (i === 0 || !dirs[id]) { el.style.clipPath = 'none'; return; }
      const k = eio(P(t, a - lead, a + .02)), [dx, dy] = dirs[id], v = (1 - k) * 100;
      el.style.clipPath = `inset(${dy > 0 ? v : 0}% ${dx < 0 ? v : 0}% ${dy < 0 ? v : 0}% ${dx > 0 ? v : 0}%)`;
    });
  }
  // Measured callout: outline box around a real element + elbow leader + label pill at labelX.
  // Call once at load, BEFORE any transform is applied, so the geometry is exact.
  function callout(id, target, label, { labelX = 640, dy = 0, stage = 'stage' } = {}) {
    const st = $(stage).getBoundingClientRect(), rr = target.getBoundingClientRect();
    const x = rr.left - st.left - 8, y = rr.top - st.top - 6, w = rr.width + 16, h = rr.height + 12, cy = y + h / 2, ly = cy + dy, ex = labelX - 24;
    $(id).innerHTML = `<div class="r" style="left:${x}px;top:${y}px;width:${w}px;height:${h}px"></div>` +
      `<div class="l" style="left:${x + w}px;top:${cy - 1.5}px;width:${ex - (x + w)}px"></div>` +
      `<div class="l" style="left:${ex - 1.5}px;top:${Math.min(cy, ly) - 1.5}px;width:3px;height:${Math.abs(ly - cy) + 3}px"></div>` +
      `<div class="l" style="left:${ex}px;top:${ly - 1.5}px;width:24px"></div>` +
      `<div class="t" style="left:${labelX}px;top:${ly - 20}px">${label}</div>`;
  }
  // Typewriter text with a blinking caret while typing.
  function typed(el, text, u, a, b, caret = '▍') {
    el = typeof el === 'string' ? $(el) : el;
    const n = Math.floor(cl(P(u, a, b)) * text.length);
    el.textContent = text.slice(0, n) + (u > a && u < b + .3 && Math.floor(u * 4) % 2 === 0 ? caret : '');
  }
  g.MK = { $, cl, P, L, eo, eio, backOut, back, soft, squash, wobble, S, pop, glide, sceneWipes, callout, typed };
})(window);
