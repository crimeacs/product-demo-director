// Render a code-built motion film (motion/kit.js contract) to MP4 with real motion blur.
//
//   node tools/motion_render.mjs --film examples/motion-sweat-ident/film.html --out out/film.mp4
//        [--fps 60] [--sub 4] [--shutter 0.5] [--dpr 1] [--workers 8] [--from 0] [--to DUR] [--stills 1.2,5.5]
//
// Serves the repository root over a private local HTTP server (module scripts and fonts do not load
// from file://), runs N headless Chromium workers in parallel, averages SUB sub-frames per output frame
// across the shutter (180 degrees = 0.5) for true motion blur, then encodes H.264 1080p.
// --stills renders only those timestamps as JPEGs next to --out (fast review before a full render).
import http from 'http'; import fs from 'fs'; import path from 'path'; import { execFileSync } from 'child_process';
import { fileURLToPath } from 'url';
const ROOT = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '..');
const args = Object.fromEntries(process.argv.slice(2).reduce((a, v, i, arr) => (v.startsWith('--') ? [...a, [v.slice(2), arr[i + 1]]] : a), []));
const film = args.film, out = path.resolve(args.out || 'out/motion.mp4');
if (!film) { console.error('usage: --film <html> --out <mp4>'); process.exit(2); }
const FPS = +(args.fps || 60), SUB = +(args.sub || 4), SHUT = +(args.shutter || .5), DPR = +(args.dpr || 1), N = +(args.workers || 8);
let chromium;
for (const p of [process.env.PLAYWRIGHT_MODULE, path.join(ROOT, 'engine/node_modules/playwright/index.mjs'), 'playwright']) {
  if (!p) continue; try { ({ chromium } = await import(p)); break; } catch { }
}
if (!chromium) { console.error('playwright not found: npm i -D playwright in engine/ or set PLAYWRIGHT_MODULE'); process.exit(2); }
const TYPES = { '.html': 'text/html', '.js': 'text/javascript', '.mjs': 'text/javascript', '.css': 'text/css', '.woff2': 'font/woff2', '.png': 'image/png', '.jpg': 'image/jpeg', '.svg': 'image/svg+xml', '.json': 'application/json' };
// serve absolute paths, but only under the repository or the film's own folder (localhost, random port)
const ALLOW = [ROOT, path.dirname(path.resolve(film))];
const server = http.createServer((req, res) => {
  const p = path.normalize(decodeURIComponent(req.url.split('?')[0]));
  if (!ALLOW.some(a => p === a || p.startsWith(a + path.sep)) || !fs.existsSync(p) || fs.statSync(p).isDirectory()) { res.writeHead(404); return res.end(); }
  res.writeHead(200, { 'Content-Type': TYPES[path.extname(p)] || 'application/octet-stream' }); fs.createReadStream(p).pipe(res);
});
await new Promise(r => server.listen(0, '127.0.0.1', r));
const url = `http://127.0.0.1:${server.address().port}${path.resolve(film).split(path.sep).join('/')}${args.query ? '?' + args.query : ''}`;
let W = 1920, H = 1080;   // replaced by window.SIZE = [w, h] when the film declares it (e.g. 1080x1920 vertical)
const browser = await chromium.launch({ args: ['--use-angle=swiftshader', '--enable-unsafe-swiftshader', '--ignore-gpu-blocklist'] });
async function page(q = '') {
  const ctx = await browser.newContext({ viewport: { width: W, height: H }, deviceScaleFactor: DPR });
  const p = await ctx.newPage(); p.on('pageerror', e => console.error('PAGE ERROR:', e.message));
  await p.goto(url + (q ? (url.includes('?') ? '&' : '?') + q : '')); if (!args.shots) await p.waitForFunction(() => window.ready === true || (typeof window.ready !== 'object' && window.ready !== false && typeof window.seek === 'function'), null, { timeout: 120000 });
  await p.evaluate(() => document.fonts.ready); await p.waitForTimeout(200); return { ctx, p };
}
fs.mkdirSync(path.dirname(out), { recursive: true });
const t0 = Date.now();
{ const { ctx, p } = await page(args.shots ? args.shots.split(',')[0] : ''); const size = await p.evaluate(() => window.SIZE || null); await ctx.close();
  if (size) { [W, H] = size; if (W % 2 || H % 2) { console.error('window.SIZE must be even'); process.exit(2); } } }
if (args.shots) {   // style frames: one screenshot per query string, e.g. --shots f=C1a,f=C1b
  for (const q of args.shots.split(',')) { const { ctx, p } = await page(q); await p.evaluate(() => document.fonts.ready); await p.waitForTimeout(250);
    const f = out.replace(/\.mp4$/, '') + `_${q.replace(/[^\w]+/g, '_')}.png`; await p.screenshot({ path: f }); console.log('frame', f); await ctx.close(); }
  await browser.close(); server.close(); process.exit(0);
}
if (args.stills) {
  const { ctx, p } = await page();
  for (const t of args.stills.split(',')) { await p.evaluate(t => window.seek(+t), t); const f = out.replace(/\.mp4$/, '') + `_${t}.jpg`; await p.screenshot({ path: f, type: 'jpeg', quality: 92 }); console.log('still', f); }
  await ctx.close(); await browser.close(); server.close(); process.exit(0);
}
const probe = await page(); const DUR = await probe.p.evaluate(() => window.DUR); await probe.ctx.close();
const from = +(args.from || 0), to = Math.min(+(args.to || DUR), DUR);
const frames = Math.round((to - from) * FPS), total = frames * SUB;
const fd = out + '.frames'; fs.rmSync(fd, { recursive: true, force: true }); fs.mkdirSync(fd, { recursive: true });
let done = 0;
await Promise.all(Array.from({ length: N }, async (_, w) => {
  const { ctx, p } = await page();
  for (let i = w; i < total; i += N) {
    const fi = Math.floor(i / SUB), k = i % SUB, t = Math.min(DUR - 1e-3, from + fi / FPS + (SUB > 1 ? k * SHUT / FPS / SUB : 0));
    await p.evaluate(t => window.seek(t), t);
    await p.screenshot({ path: `${fd}/f${String(i).padStart(6, '0')}.jpg`, type: 'jpeg', quality: 95 });
    if (++done % 400 === 0) console.log(`${done}/${total} sub-frames, ${((Date.now() - t0) / 1000).toFixed(0)}s`);
  }
  await ctx.close();
}));
await browser.close(); server.close();
const missing = Array.from({ length: total }, (_, i) => i).filter(i => !fs.existsSync(`${fd}/f${String(i).padStart(6, '0')}.jpg`));
if (missing.length) { console.error('missing sub-frames', missing.slice(0, 10)); process.exit(1); }
const vf = (SUB > 1 ? `tmix=frames=${SUB},select='eq(mod(n\\,${SUB})\\,${SUB - 1})',setpts=N/(${FPS}*TB),` : '') + `scale=${W}:${H}:flags=lanczos`;
execFileSync('ffmpeg', ['-loglevel', 'error', '-y', '-framerate', String(FPS * SUB), '-i', `${fd}/f%06d.jpg`, '-vf', vf, '-r', String(FPS),
  '-c:v', 'libx264', '-crf', '14', '-preset', 'slow', '-profile:v', 'high', '-pix_fmt', 'yuv420p', '-movflags', '+faststart', out]);
fs.rmSync(fd, { recursive: true, force: true });
console.log(`encoded ${out}: ${frames} frames (${SUB} sub-frames each) in ${((Date.now() - t0) / 1000).toFixed(0)}s`);
