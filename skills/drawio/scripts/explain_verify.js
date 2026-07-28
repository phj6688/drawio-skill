/* explain_verify.js: look at a built explain page the way a browser does.
 *
 *   npm i playwright && npx playwright install chromium
 *   node explain_verify.js PAGE.html
 *
 * The check that matters is alignment: every hotspot must sit on the shape it
 * claims to cover. A hotspot layer can be off by a constant and still look
 * plausible in a screenshot, so this measures it instead of trusting it.
 *
 * A cell that draws a shape MUST match a shape. Cells styled fillColor=none;
 * strokeColor=none (legend labels, titles) draw no shape at all and are matched
 * against their rendered label instead; letting those two cases share one rule
 * is how a systematic offset once passed as "100% aligned".
 */
'use strict';
let chromium;
try { ({ chromium } = require('playwright')); }
catch (e) {
  console.error('playwright not installed.\n  npm i playwright && npx playwright install chromium');
  process.exit(2);
}
const path = require('path');
const fs = require('fs');

const target = process.argv[2];
if (!target) { console.error('usage: node explain_verify.js PAGE.html'); process.exit(2); }
const FILE_PATH = path.resolve(target);
if (!fs.existsSync(FILE_PATH)) { console.error(`no such file: ${FILE_PATH}`); process.exit(2); }

let fails = [];
function check(name, ok, detail) {
  console.log((ok ? 'PASS  ' : 'FAIL  ') + name + (detail ? `  [${detail}]` : ''));
  if (!ok) fails.push(name + (detail ? `: ${detail}` : ''));
}

(async () => {
  const html = fs.readFileSync(FILE_PATH, 'utf8');
  const m = html.match(/const TEXTS = (\{[\s\S]*?\});\nconst ALSO/);
  if (!m) { console.error('not an explain page (no TEXTS block)'); process.exit(2); }
  const TEXTS = JSON.parse(m[1]);

  const browser = await chromium.launch();
  const ctx = await browser.newContext({ viewport: { width: 1600, height: 1000 } });
  const page = await ctx.newPage();
  const errors = [];
  page.on('console', e => { if (e.type() === 'error') errors.push(e.text()); });
  page.on('pageerror', e => errors.push('pageerror: ' + e.message));

  await page.goto('file://' + FILE_PATH, { waitUntil: 'load' });
  await page.waitForTimeout(700);
  check('page loads without console errors', errors.length === 0, errors.slice(0, 2).join(' | '));

  const dgs = await page.evaluate(() => CFG.dgs);
  const comps = await page.evaluate(() => CFG.comps);
  check('diagrams present', dgs.length > 0, `${dgs.length} diagrams, ${comps.length} components`);

  let totalHot = 0, totalOk = 0;
  for (const dg of dgs) {
    if (comps.includes(dg)) {
      await page.click('.tab[data-tab="__comp"]');
      await page.click(`.pill[data-comp="${dg}"]`);
    } else {
      await page.click(`.tab[data-tab="${dg}"]`);
    }
    await page.waitForTimeout(380);

    const a = await page.evaluate(d => {
      const canvas = document.querySelector(`.dgcanvas[data-dg="${d}"]`);
      const svg = canvas.querySelector('svg');
      const shapes = [...svg.querySelectorAll('rect,path,ellipse')]
        .map(r => r.getBoundingClientRect()).filter(r => r.width > 20 && r.height > 12);
      // drawio puts label text in a <div> inside a page-sized <foreignObject>,
      // so the foreignObject is useless as an anchor; measure the inner div.
      const labels = [...svg.querySelectorAll('foreignObject div, text')]
        .map(t => t.getBoundingClientRect()).filter(r => r.width > 2 && r.height > 2);
      const out = { total: 0, ok: 0, byLabel: 0, shapeReq: 0, shapeOk: 0, misses: [] };
      document.querySelectorAll(`.hot[data-dg="${d}"]`).forEach(h => {
        const hb = h.getBoundingClientRect();
        out.total++;
        const needsShape = h.dataset.shape === '1';
        if (needsShape) out.shapeReq++;
        let best = Infinity;
        for (const r of shapes) {
          const e = Math.abs(r.left - hb.left) + Math.abs(r.top - hb.top) +
                    Math.abs(r.width - hb.width) + Math.abs(r.height - hb.height);
          if (e < best) best = e;
        }
        // A swimlane draws its body BELOW the title bar, so the drawn rect shares
        // left/right/bottom with the cell but starts lower. The hotspot correctly
        // covers the whole lane.
        const swimlane = shapes.some(r =>
          Math.abs(r.left - hb.left) <= 3 && Math.abs(r.right - hb.right) <= 3 &&
          Math.abs(r.bottom - hb.bottom) <= 3 &&
          r.top > hb.top && (r.top - hb.top) < hb.height * 0.5);
        if (best <= 6 || swimlane) { out.ok++; if (needsShape) out.shapeOk++; }
        else if (needsShape) {
          out.misses.push(`${h.dataset.id.split('::')[1]}(shape ${best.toFixed(0)})`);
        } else {
          const inside = labels.some(r => {
            const cx = r.left + r.width / 2, cy = r.top + r.height / 2;
            return cx >= hb.left - 2 && cx <= hb.right + 2 &&
                   cy >= hb.top - 2 && cy <= hb.bottom + 2 &&
                   r.width <= hb.width * 1.6 + 4 && r.height <= hb.height * 3 + 4;
          });
          if (inside) { out.ok++; out.byLabel++; }
          else out.misses.push(`${h.dataset.id.split('::')[1]}(${best.toFixed(0)})`);
        }
      });
      return out;
    }, dg);
    totalHot += a.total; totalOk += a.ok;
    check(`[${dg}] hotspots align`, a.ok === a.total && a.shapeOk === a.shapeReq,
      `${a.ok}/${a.total}, shape-required ${a.shapeOk}/${a.shapeReq}, ` +
      `${a.byLabel} by label, misses: ${a.misses.slice(0, 3).join(' ')}`);
  }
  check('EVERY hotspot aligns', totalOk === totalHot, `${totalOk}/${totalHot}`);

  // clicking a leaf opens a populated panel
  const firstDg = dgs[0];
  await page.click(`.tab[data-tab="${firstDg}"]`);
  await page.waitForTimeout(300);
  const leaf = await page.evaluate(d => {
    const l = [...document.querySelectorAll(`.hot[data-dg="${d}"][data-leaf="1"]`)];
    l.sort((a, b) => a.offsetWidth * a.offsetHeight - b.offsetWidth * b.offsetHeight);
    return l.length ? l[0].dataset.id : null;
  }, firstDg);
  if (leaf) {
    await page.click(`.hot[data-dg="${firstDg}"][data-id="${leaf}"]`);
    await page.waitForTimeout(250);
    const card = await page.evaluate(d => {
      const c = document.querySelector(`.detail[data-dg="${d}"] .dcard`);
      return { hidden: c.hidden, title: c.querySelector('.dtitel').textContent,
               what: c.querySelector('.dwhat p').textContent.length };
    }, firstDg);
    check('clicking a box opens a populated panel', !card.hidden && card.what > 10,
      `${leaf} -> "${card.title}"`);
    // the deep link the panel advertises must actually resolve
    const hash = await page.evaluate(() => location.hash);
    check('deep link written to the URL', hash.includes('/'), hash);
    await page.goto('file://' + FILE_PATH + hash, { waitUntil: 'load' });
    await page.waitForTimeout(600);
    const restored = await page.evaluate(d =>
      !document.querySelector(`.detail[data-dg="${d}"] .dcard`).hidden, firstDg);
    check('deep link reopens that box on reload', restored === true, hash);
  }

  // walk mode advances the selection
  await page.click(`.zb[data-dg="${firstDg}"][data-act="walk"]`);
  await page.waitForTimeout(300);
  const sel1 = await page.evaluate(d =>
    (document.querySelector(`.hot[data-dg="${d}"].sel`) || {}).dataset?.id, firstDg);
  await page.click(`.zb[data-dg="${firstDg}"][data-act="walk"]`);
  await page.waitForTimeout(300);
  const sel2 = await page.evaluate(d =>
    (document.querySelector(`.hot[data-dg="${d}"].sel`) || {}).dataset?.id, firstDg);
  check('walk advances to the next box', sel1 && sel2 && sel1 !== sel2, `${sel1} -> ${sel2}`);

  // no horizontal overflow anywhere
  for (const [w, h, name] of [[1600, 1000, 'desktop'], [390, 844, 'mobile']]) {
    const c2 = await browser.newContext({ viewport: { width: w, height: h } });
    const p2 = await c2.newPage();
    await p2.goto('file://' + FILE_PATH, { waitUntil: 'load' });
    await p2.waitForTimeout(400);
    const tabs = await p2.evaluate(() => CFG.tabs);
    for (const t of tabs) {
      await p2.click(`.tab[data-tab="${t}"]`);
      await p2.waitForTimeout(300);
      const ov = await p2.evaluate(() =>
        ({ d: document.documentElement.scrollWidth, w: window.innerWidth }));
      check(`[${name}/${t}] no horizontal page scroll`, ov.d <= ov.w + 1, `${ov.d} vs ${ov.w}`);
    }
    await c2.close();
  }

  check('no console errors after full interaction', errors.length === 0, errors.slice(0, 3).join(' | '));
  await browser.close();
  console.log('\n' + (fails.length
    ? `${fails.length} FAILURE(S):\n - ${fails.join('\n - ')}`
    : `ALL CHECKS PASSED (${Object.keys(TEXTS).length} popups, ${totalHot} hotspots)`));
  process.exit(fails.length ? 1 : 0);
})();
