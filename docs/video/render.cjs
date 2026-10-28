// Render stage.html frame by frame with Playwright and encode it with ffmpeg.
//
//   node render.cjs video   <timeline.json> <out.mp4> [--fps 30] [--workers 4]
//   node render.cjs stills  <timeline.json> <out-dir> <t1,t2,...>
//   node render.cjs poster  <timeline.json> <out.png> <t> [label]
//
// Every frame is produced by seeking the stage to an exact time, so the
// output is deterministic and independent of rendering speed.
const { chromium } = require('playwright');
const { spawn } = require('child_process');
const fs = require('fs');
const path = require('path');

const STAGE = 'file://' + path.join(__dirname, 'stage.html');
const W = 1920, H = 1080;

function opt(name, fallback) {
  const i = process.argv.indexOf(name);
  return i > 0 ? Number(process.argv[i + 1]) : fallback;
}

async function openStage(browser, timeline) {
  const page = await browser.newPage({ viewport: { width: W, height: H }, deviceScaleFactor: 1 });
  await page.goto(STAGE, { waitUntil: 'load' });
  await page.evaluate(tl => window.setup(tl), timeline);
  return page;
}

async function renderSegment(timeline, fps, from, to, out, index) {
  const browser = await chromium.launch();
  const page = await openStage(browser, timeline);
  const ff = spawn('ffmpeg', ['-hide_banner', '-loglevel', 'error', '-y',
    '-f', 'image2pipe', '-framerate', String(fps), '-c:v', 'png', '-i', '-',
    '-c:v', 'libx264', '-preset', 'slow', '-crf', '20', '-tune', 'animation',
    '-pix_fmt', 'yuv420p', '-g', String(fps * 2), '-r', String(fps), out], { stdio: ['pipe', 'inherit', 'inherit'] });
  const done = new Promise((res, rej) => ff.on('close', c => (c === 0 ? res() : rej(new Error('ffmpeg ' + c)))));
  const started = Date.now();
  for (let f = from; f < to; f++) {
    await page.evaluate(t => window.render(t), f / fps);
    const png = await page.screenshot({ type: 'png' });
    if (!ff.stdin.write(png)) await new Promise(r => ff.stdin.once('drain', r));
    if ((f - from) % (fps * 10) === 0) {
      const pct = (100 * (f - from) / (to - from)).toFixed(0);
      console.log(`worker ${index}: frame ${f - from}/${to - from} (${pct}%) ${((Date.now() - started) / 1000).toFixed(0)}s`);
    }
  }
  ff.stdin.end();
  await done;
  await browser.close();
}

async function video(timelinePath, out) {
  const timeline = JSON.parse(fs.readFileSync(timelinePath, 'utf8'));
  const fps = opt('--fps', 30), workers = opt('--workers', 4);
  const total = Math.ceil(timeline.duration * fps);
  const per = Math.ceil(total / workers);
  const dir = path.dirname(path.resolve(out));
  const parts = [];
  const jobs = [];
  for (let i = 0; i < workers; i++) {
    const from = i * per, to = Math.min(total, from + per);
    if (from >= to) break;
    const part = path.join(dir, `part${i}.mp4`);
    parts.push(part);
    jobs.push(renderSegment(timeline, fps, from, to, part, i));
  }
  await Promise.all(jobs);
  const list = path.join(dir, 'parts.txt');
  fs.writeFileSync(list, parts.map(p => `file '${p}'`).join('\n'));
  await new Promise((res, rej) => spawn('ffmpeg', ['-hide_banner', '-loglevel', 'error', '-y', '-f', 'concat', '-safe', '0', '-i', list, '-c', 'copy', out], { stdio: 'inherit' })
    .on('close', c => (c === 0 ? res() : rej(new Error('concat ' + c)))));
  parts.forEach(p => fs.unlinkSync(p));
  fs.unlinkSync(list);
  console.log(`video: ${total} frames -> ${out}`);
}

async function stills(timelinePath, outDir, times) {
  const timeline = JSON.parse(fs.readFileSync(timelinePath, 'utf8'));
  fs.mkdirSync(outDir, { recursive: true });
  const browser = await chromium.launch();
  const page = await openStage(browser, timeline);
  for (const t of times.split(',').map(Number)) {
    await page.evaluate(t => window.render(t), t);
    await page.screenshot({ path: path.join(outDir, `t${t.toFixed(2).padStart(7, '0')}.png`) });
  }
  await browser.close();
}

async function poster(timelinePath, out, t, label) {
  const timeline = JSON.parse(fs.readFileSync(timelinePath, 'utf8'));
  const browser = await chromium.launch();
  const page = await openStage(browser, timeline);
  await page.evaluate(([on, l]) => window.poster(on, l), [true, label || null]);
  await page.evaluate(t => window.render(t), t);
  await page.screenshot({ path: out });
  await browser.close();
}

(async () => {
  const [mode, a, b, c, d] = process.argv.slice(2);
  if (mode === 'video') await video(a, b);
  else if (mode === 'stills') await stills(a, b, c);
  else if (mode === 'poster') await poster(a, b, Number(c), d);
  else throw new Error('usage: node render.cjs video|stills|poster ...');
})().catch(e => { console.error(e); process.exit(1); });
