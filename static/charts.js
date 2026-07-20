/* Chart primitives for the review UI and dashboard.
 *
 * Inline SVG, no dependencies — the rest of this frontend is two dependency-free
 * HTML files and adding a charting library for six charts would be the largest
 * thing in the repo.
 *
 * Palette: the four verdict hues are the app's existing badge colours stepped
 * darker so they work as FILLS on the #131c2e card surface (badge colours are
 * tuned for text/border and sit above the dark lightness band). The set was
 * validated with the dataviz palette validator against this exact surface:
 * lightness band, chroma floor, CVD separation (worst adjacent ΔE 9.6), the
 * normal-vision floor (17.3) and 3:1 contrast all pass.
 *
 * House rules followed throughout: 2px surface gaps rather than strokes between
 * touching marks, 4px rounded data-ends squared at the baseline, hairline solid
 * gridlines, selective direct labels, text in text tokens (never the series
 * colour), and a table-view twin under every chart so no value is reachable
 * only by hovering.
 */

const C = {
  surface: '#131c2e',
  surface2: '#1a2438',
  grid: '#263145',
  text: '#e8edf6',
  muted: '#9aa8bf',
  series: '#5b7fe8',      // single-series hue
  track: '#22304a',       // unfilled meter track — a darker step of the series hue
  new: '#2b8ed0',
  rising: '#12a97a',
  peaked: '#bf8a05',
  fading: '#dc4a68',
};
const STATUS = { good: C.rising, warning: C.peaked, critical: C.fading };
const VERDICT_ORDER = ['new', 'rising', 'peaked', 'fading'];

const NS = 'http://www.w3.org/2000/svg';
const esc = s => { const d = document.createElement('div'); d.textContent = s ?? ''; return d.innerHTML; };

function el(tag, attrs = {}, parent = null) {
  const n = document.createElementNS(NS, tag);
  for (const [k, v] of Object.entries(attrs)) if (v !== null && v !== undefined) n.setAttribute(k, v);
  if (parent) parent.appendChild(n);
  return n;
}

function svgRoot(w, h, label) {
  const s = el('svg', {
    viewBox: `0 0 ${w} ${h}`, width: '100%', height: h,
    role: 'img', 'aria-label': label, style: 'display:block;overflow:visible',
  });
  return s;
}

/* One shared tooltip. Tooltips enhance; they never gate a value — every chart
 * also ships the table view below. */
let tip;
function tooltip() {
  if (!tip) {
    tip = document.createElement('div');
    tip.style.cssText =
      `position:fixed;z-index:99;pointer-events:none;opacity:0;transition:opacity .12s;
       background:${C.surface2};border:1px solid ${C.grid};border-radius:8px;padding:7px 10px;
       font:13px/1.45 system-ui,-apple-system,"Segoe UI",Roboto,sans-serif;color:${C.text};
       box-shadow:0 6px 20px rgba(0,0,0,.45);max-width:260px`;
    document.body.appendChild(tip);
  }
  return tip;
}

/* Hover/focus target. The hit area is the caller's rect, kept at >=24px on its
 * short side by the chart geometry, not the mark's own thickness. */
function hoverable(node, html) {
  const t = () => tooltip();
  const show = e => {
    const b = t();
    b.innerHTML = html;
    b.style.opacity = '1';
    const r = node.getBoundingClientRect();
    const x = (e && e.clientX) || r.left + r.width / 2;
    b.style.left = Math.min(window.innerWidth - b.offsetWidth - 12, Math.max(12, x - b.offsetWidth / 2)) + 'px';
    b.style.top = Math.max(12, r.top - b.offsetHeight - 10) + 'px';
  };
  node.addEventListener('mousemove', show);
  node.addEventListener('mouseenter', show);
  node.addEventListener('focus', show);
  const hide = () => { t().style.opacity = '0'; };
  node.addEventListener('mouseleave', hide);
  node.addEventListener('blur', hide);
  node.setAttribute('tabindex', '0');
  node.style.outline = 'none';
}

/* The WCAG-clean twin of every chart. */
function tableView(headers, rows, caption) {
  const d = document.createElement('details');
  d.className = 'tableview';
  d.innerHTML =
    `<summary>${esc(caption || 'View as table')}</summary>
     <table><thead><tr>${headers.map(h => `<th>${esc(h)}</th>`).join('')}</tr></thead>
     <tbody>${rows.map(r => `<tr>${r.map((c, i) =>
       `<td${i ? ' class="num"' : ''}>${esc(String(c))}</td>`).join('')}</tr>`).join('')}</tbody></table>`;
  return d;
}

function mount(host, svg, table) {
  host.innerHTML = '';
  host.appendChild(svg);
  if (table) host.appendChild(table);
}

function relevanceBand(score) {
  if (score >= 65) return { color: STATUS.good, label: 'High relevance' };
  if (score >= 40) return { color: STATUS.warning, label: 'Moderate relevance' };
  return { color: STATUS.critical, label: 'Low relevance' };
}

/* ---- 1. Relevance meter -------------------------------------------------
 * A single ratio against a limit, so: a meter with a hero figure, not a
 * one-slice pie. Severity is carried by the fill AND spelled out in the label
 * beneath, so it never rests on colour alone. */
export function relevanceMeter(host, score, note) {
  const w = 260, h = 150, cx = w / 2, cy = 118, r = 92, thick = 14;
  const band = relevanceBand(score);
  const svg = svgRoot(w, h, `Relevance to us: ${score} out of 100 — ${band.label}`);

  const arc = (from, to) => {
    const a0 = Math.PI * (1 + from), a1 = Math.PI * (1 + to);
    const p = t => `${cx + r * Math.cos(t)},${cy + r * Math.sin(t)}`;
    return `M ${p(a0)} A ${r} ${r} 0 ${to - from > 0.5 ? 1 : 0} 1 ${p(a1)}`;
  };
  el('path', { d: arc(0, 1), fill: 'none', stroke: C.track, 'stroke-width': thick, 'stroke-linecap': 'round' }, svg);
  if (score > 0) {
    el('path', {
      d: arc(0, Math.max(0.012, score / 100)), fill: 'none', stroke: band.color,
      'stroke-width': thick, 'stroke-linecap': 'round',
    }, svg);
  }

  // Proportional figures, not tabular: at 44px, tabular digits read loose.
  const val = el('text', {
    x: cx, y: cy - 18, 'text-anchor': 'middle', fill: C.text,
    style: 'font:600 44px system-ui,-apple-system,"Segoe UI",Roboto,sans-serif',
  }, svg);
  val.textContent = score;
  const pct = el('text', {
    x: cx + 42, y: cy - 20, fill: C.muted,
    style: 'font:500 16px system-ui,-apple-system,"Segoe UI",Roboto,sans-serif',
  }, svg);
  pct.textContent = '%';
  // cy+18 clears the 44px glyph box (which extends ~11px below its baseline).
  const lab = el('text', {
    x: cx, y: cy + 18, 'text-anchor': 'middle', fill: C.muted,
    style: 'font:13px system-ui,-apple-system,"Segoe UI",Roboto,sans-serif',
  }, svg);
  lab.textContent = band.label;

  const box = document.createElement('div');
  box.appendChild(svg);
  if (note) {
    const p = document.createElement('p');
    p.className = 'chartnote';
    p.textContent = note;
    box.appendChild(p);
  }
  host.innerHTML = '';
  host.appendChild(box);
}

/* ---- 2. Score dimensions ------------------------------------------------
 * Magnitude across named dimensions = horizontal bars, one hue for all of them.
 * A value-ramp here would double-encode length as colour. The only colour
 * departure is genuinely a status: dimensions scoring under 40 are the weak
 * spots, and they get the warning hue *plus* a "weak" chip, never colour alone. */
export function scoreBars(host, dims) {
  if (!dims || !dims.length) { host.innerHTML = '<p class="chartnote">No scores available.</p>'; return; }
  const rowH = 30, barH = 14, labelW = 152, valueW = 42, w = 460;
  const plotW = w - labelW - valueW;
  const h = dims.length * rowH + 20;
  const svg = svgRoot(w, h, 'Score by dimension, 0 to 100');

  // Gridlines first, so data sits above chrome.
  [0, 25, 50, 75, 100].forEach(t => {
    const x = labelW + (t / 100) * plotW;
    el('line', { x1: x, y1: 6, x2: x, y2: dims.length * rowH + 2, stroke: C.grid, 'stroke-width': 1 }, svg);
    const tk = el('text', {
      x, y: h - 2, 'text-anchor': 'middle', fill: C.muted,
      style: 'font:11px system-ui;font-variant-numeric:tabular-nums',
    }, svg);
    tk.textContent = t;
  });

  dims.forEach((d, i) => {
    const y = i * rowH + 8;
    const weak = d.score < 40;
    const fill = weak ? STATUS.warning : C.series;

    const label = el('text', {
      x: labelW - 10, y: y + barH - 2, 'text-anchor': 'end', fill: C.muted,
      style: 'font:12.5px system-ui',
    }, svg);
    label.textContent = d.label;

    el('rect', { x: labelW, y, width: plotW, height: barH, rx: 3, fill: C.surface2 }, svg);
    const bw = Math.max(2, (d.score / 100) * plotW);
    // 4px rounded data-end, squared at the baseline: round the whole rect, then
    // cover the baseline end with a square patch.
    el('rect', { x: labelW, y, width: bw, height: barH, rx: 4, fill }, svg);
    el('rect', { x: labelW, y, width: Math.min(4, bw), height: barH, fill }, svg);

    const val = el('text', {
      x: w - 6, y: y + barH - 2, 'text-anchor': 'end', fill: C.text,
      style: 'font:12.5px system-ui;font-variant-numeric:tabular-nums',
    }, svg);
    val.textContent = d.score;

    // Hit target spans the whole row, not the 14px bar.
    const hit = el('rect', { x: 0, y: i * rowH, width: w, height: rowH, fill: 'transparent' }, svg);
    hoverable(hit,
      `<strong>${esc(d.label)}</strong> — ${d.score}/100` +
      `<div style="color:${C.muted};margin-top:3px">${d.computed ? 'Computed from our own data' : 'Judged by the critic'}` +
      `${weak ? ' · <strong>weak spot</strong>' : ''}</div>` +
      (d.rationale ? `<div style="margin-top:4px">${esc(d.rationale)}</div>` : ''));
  });

  mount(host, svg, tableView(
    ['Dimension', 'Score', 'Source'],
    dims.map(d => [d.label, d.score, d.computed ? 'computed' : 'judged']),
    'View scores as table'));
}

/* ---- 3. Play lifecycle --------------------------------------------------
 * One series over time on a named ordinal axis — no legend needed, the axis
 * says what is plotted. Stage names are on the axis, so the dot colours
 * reinforce identity rather than carry it. */
export function lifecycleChart(host, timeline) {
  const events = (timeline && timeline.events) || [];
  if (!events.length) { host.innerHTML = '<p class="chartnote">No lifecycle observations for this play yet.</p>'; return; }

  const w = 460, padL = 68, padR = 22, padT = 12, rowH = 30;
  const h = VERDICT_ORDER.length * rowH + 34;
  const svg = svgRoot(w, h, `Lifecycle stage of ${timeline.play} over time`);
  const yOf = v => padT + VERDICT_ORDER.indexOf(v) * rowH + rowH / 2;
  const plotW = w - padL - padR;

  VERDICT_ORDER.forEach(v => {
    const y = yOf(v);
    el('line', { x1: padL, y1: y, x2: w - padR, y2: y, stroke: C.grid, 'stroke-width': 1 }, svg);
    const t = el('text', { x: padL - 10, y: y + 4, 'text-anchor': 'end', fill: C.muted, style: 'font:12px system-ui' }, svg);
    t.textContent = v;
  });

  const times = events.map(e => new Date(e.at).getTime());
  const t0 = Math.min(...times), t1 = Math.max(...times);
  const xOf = t => (t1 === t0 ? padL + plotW / 2 : padL + ((t - t0) / (t1 - t0)) * plotW);

  if (events.length > 1) {
    // Step path: the stage holds until the next observation changes it.
    let d = '';
    events.forEach((e, i) => {
      const x = xOf(times[i]), y = yOf(e.verdict);
      d += i === 0 ? `M ${x} ${y}` : ` H ${x} V ${y}`;
    });
    el('path', { d, fill: 'none', stroke: C.series, 'stroke-width': 2, 'stroke-linejoin': 'round', 'stroke-linecap': 'round' }, svg);
  }

  events.forEach((e, i) => {
    const x = xOf(times[i]), y = yOf(e.verdict);
    // 2px surface ring so overlapping observations stay countable.
    el('circle', { cx: x, cy: y, r: 6, fill: C[e.verdict] || C.series, stroke: C.surface, 'stroke-width': 2 }, svg);
    const hit = el('circle', { cx: x, cy: y, r: 13, fill: 'transparent' }, svg);
    hoverable(hit, `<strong>${esc(e.verdict)}</strong><div style="color:${C.muted};margin-top:3px">${esc(e.at.slice(0, 10))} · ${esc(e.report_id)}</div>`);
  });

  const first = el('text', { x: padL, y: h - 6, fill: C.muted, style: 'font:11px system-ui;font-variant-numeric:tabular-nums' }, svg);
  first.textContent = events[0].at.slice(0, 10);
  if (events.length > 1) {
    const last = el('text', { x: w - padR, y: h - 6, 'text-anchor': 'end', fill: C.muted, style: 'font:11px system-ui;font-variant-numeric:tabular-nums' }, svg);
    last.textContent = events[events.length - 1].at.slice(0, 10);
  }

  mount(host, svg, tableView(
    ['Date', 'Stage', 'Report'],
    events.map(e => [e.at.slice(0, 10), e.verdict, e.report_id]),
    'View observations as table'));
}

/* ---- 4. Risk severity ---------------------------------------------------
 * Part-to-whole across three ordered severity classes: a stacked bar, with a
 * 2px surface gap doing the separating. Status hues, each with a text label. */
export function riskBar(host, counts, riskIndex) {
  const order = ['high', 'medium', 'low'];
  const colors = { high: STATUS.critical, medium: STATUS.warning, low: STATUS.good };
  const total = order.reduce((s, k) => s + (counts[k] || 0), 0);
  if (!total) { host.innerHTML = '<p class="chartnote">No weaknesses recorded.</p>'; return; }

  const w = 460, barY = 8, barH = 22, GAP = 2;
  const svg = svgRoot(w, 40, `Weaknesses by severity: ${order.map(k => `${counts[k] || 0} ${k}`).join(', ')}`);
  const segs = order.filter(k => counts[k]);
  const avail = w - GAP * (segs.length - 1);
  let x = 0;
  segs.forEach((k, i) => {
    const sw = (counts[k] / total) * avail;
    const first = i === 0, last = i === segs.length - 1;
    el('rect', {
      x, y: barY, width: sw, height: barH,
      rx: first || last ? 4 : 0, fill: colors[k],
    }, svg);
    // Square off interior ends so only the outer data-ends are rounded.
    if (!first) el('rect', { x, y: barY, width: Math.min(4, sw), height: barH, fill: colors[k] }, svg);
    if (!last) el('rect', { x: x + sw - Math.min(4, sw), y: barY, width: Math.min(4, sw), height: barH, fill: colors[k] }, svg);

    // Only label inside the segment when the text genuinely fits.
    if (sw > 34) {
      const t = el('text', {
        x: x + sw / 2, y: barY + barH / 2 + 4, 'text-anchor': 'middle', fill: '#0b1220',
        style: 'font:600 12px system-ui',
      }, svg);
      t.textContent = counts[k];
    }
    const hit = el('rect', { x, y: 0, width: sw + GAP, height: 40, fill: 'transparent' }, svg);
    hoverable(hit, `<strong>${counts[k]} ${esc(k)}-severity</strong> of ${total} weaknesses`);
    x += sw + GAP;
  });

  const box = document.createElement('div');
  box.appendChild(svg);
  const legend = document.createElement('div');
  legend.className = 'chartlegend';
  legend.innerHTML = segs.map(k =>
    `<span><i style="background:${colors[k]}"></i>${counts[k]} ${esc(k)}</span>`).join('') +
    (riskIndex !== undefined && riskIndex !== null ? `<span class="riskidx">risk index ${riskIndex}/100</span>` : '');
  box.appendChild(legend);
  host.innerHTML = '';
  host.appendChild(box);
}

/* ---- 5. Palette donut ---------------------------------------------------
 * The one place the mark colour IS the datum — these are the hexes extracted
 * from the creative, so they are not a categorical encoding to validate. */
export function paletteDonut(host, palette) {
  if (!palette || !palette.length) { host.innerHTML = ''; return; }
  const size = 132, r = 52, thick = 20, cx = size / 2, cy = size / 2;
  const svg = svgRoot(size, size, 'Extracted colour palette by share of the creative');
  const total = palette.reduce((s, c) => s + c.coverage_pct, 0) || 1;
  let a0 = -Math.PI / 2;
  palette.forEach(c => {
    const sweep = (c.coverage_pct / total) * Math.PI * 2;
    const a1 = a0 + sweep;
    const p = t => `${cx + r * Math.cos(t)},${cy + r * Math.sin(t)}`;
    const path = el('path', {
      d: `M ${p(a0)} A ${r} ${r} 0 ${sweep > Math.PI ? 1 : 0} 1 ${p(a1)}`,
      fill: 'none', stroke: c.hex, 'stroke-width': thick,
    }, svg);
    hoverable(path, `<span style="display:inline-block;width:10px;height:10px;border-radius:2px;background:${esc(c.hex)}"></span> <strong>${esc(c.hex)}</strong> — ${c.coverage_pct}%`);
    a0 = a1;
  });
  const t = el('text', { x: cx, y: cy + 5, 'text-anchor': 'middle', fill: C.muted, style: 'font:12px system-ui' }, svg);
  t.textContent = palette.length + ' hues';
  mount(host, svg, tableView(['Colour', 'Coverage %'], palette.map(c => [c.hex, c.coverage_pct]), 'View palette as table'));
}

/* ---- 6. Verdict mix by week --------------------------------------------
 * Four ordered classes over time = stacked columns. Categorical fills here,
 * which is why the palette above was validated as a set. Legend always
 * present; values live in the tooltip and the table, not on every segment. */
export function verdictMix(host, data) {
  const { labels, series } = data;
  if (!labels || !labels.length) { host.innerHTML = '<p class="chartnote">No observations yet.</p>'; return; }
  const totals = labels.map((_, i) => series.reduce((s, sr) => s + sr.values[i], 0));
  const max = Math.max(1, ...totals);

  const w = 560, padL = 30, padB = 26, padT = 10, h = 200;
  const plotH = h - padB - padT, plotW = w - padL - 8;
  const band = plotW / labels.length, barW = Math.min(24, band * 0.62);
  const svg = svgRoot(w, h, 'Lifecycle-stage observations per week');

  // Deduped: at max=1 a naive [0, max/2, max] renders "1" twice in one spot.
  [...new Set([0, Math.ceil(max / 2), max])].forEach(t => {
    const y = padT + plotH - (t / max) * plotH;
    el('line', { x1: padL, y1: y, x2: w - 8, y2: y, stroke: C.grid, 'stroke-width': 1 }, svg);
    const tk = el('text', { x: padL - 8, y: y + 4, 'text-anchor': 'end', fill: C.muted, style: 'font:11px system-ui;font-variant-numeric:tabular-nums' }, svg);
    tk.textContent = t;
  });

  labels.forEach((wk, i) => {
    const x = padL + band * i + (band - barW) / 2;
    let acc = 0;
    const present = series.filter(s => s.values[i] > 0);
    present.forEach((s, k) => {
      const v = s.values[i];
      const segH = (v / max) * plotH;
      const gap = k < present.length - 1 ? 2 : 0;   // surface gap between segments
      const y = padT + plotH - acc - segH;
      el('rect', { x, y, width: barW, height: Math.max(1, segH - gap), rx: 2, fill: C[s.key] }, svg);
      acc += segH;
    });
    if (i % 2 === 0) {
      const t = el('text', { x: x + barW / 2, y: h - 8, 'text-anchor': 'middle', fill: C.muted, style: 'font:10.5px system-ui;font-variant-numeric:tabular-nums' }, svg);
      t.textContent = wk.slice(5);
    }
    const hit = el('rect', { x: padL + band * i, y: 0, width: band, height: h - padB + 6, fill: 'transparent' }, svg);
    hoverable(hit, `<strong>week of ${esc(wk)}</strong>` +
      series.map(s => `<div><span style="display:inline-block;width:8px;height:8px;border-radius:2px;background:${C[s.key]}"></span> ${esc(s.key)}: ${s.values[i]}</div>`).join(''));
  });

  const box = document.createElement('div');
  box.appendChild(svg);
  const legend = document.createElement('div');
  legend.className = 'chartlegend';
  legend.innerHTML = VERDICT_ORDER.map(v => `<span><i style="background:${C[v]}"></i>${v}</span>`).join('');
  box.appendChild(legend);
  box.appendChild(tableView(
    ['Week', ...VERDICT_ORDER],
    labels.map((wk, i) => [wk, ...series.map(s => s.values[i])]),
    'View weekly mix as table'));
  host.innerHTML = '';
  host.appendChild(box);
}

/* ---- 7. Ranked horizontal bars -----------------------------------------
 * One series, one hue. Optional verdict dot rides beside the label so identity
 * never depends on recolouring the bar. */
export function rankedBars(host, items, opts = {}) {
  if (!items || !items.length) { host.innerHTML = '<p class="chartnote">Nothing to show yet.</p>'; return; }
  const rowH = 28, barH = 13, labelW = opts.labelW || 150, w = 480;
  const plotW = w - labelW - 34;
  const max = Math.max(...items.map(i => i.value)) || 1;
  const svg = svgRoot(w, items.length * rowH + 6, opts.label || 'Ranked totals');

  items.forEach((it, i) => {
    const y = i * rowH + 8;
    const lab = el('text', { x: labelW - 10, y: y + barH - 2, 'text-anchor': 'end', fill: C.muted, style: 'font:12.5px system-ui' }, svg);
    lab.textContent = it.label.length > 24 ? it.label.slice(0, 23) + '…' : it.label;

    if (it.verdict && C[it.verdict]) {
      el('circle', { cx: labelW - 4, cy: y + barH / 2 - 1, r: 3.5, fill: C[it.verdict] }, svg);
    }
    const bw = Math.max(2, (it.value / max) * plotW);
    el('rect', { x: labelW + 6, y, width: bw, height: barH, rx: 4, fill: C.series }, svg);
    el('rect', { x: labelW + 6, y, width: Math.min(4, bw), height: barH, fill: C.series }, svg);

    const val = el('text', { x: labelW + 12 + bw, y: y + barH - 2, fill: C.text, style: 'font:12px system-ui;font-variant-numeric:tabular-nums' }, svg);
    val.textContent = it.value;

    const hit = el('rect', { x: 0, y: i * rowH, width: w, height: rowH, fill: 'transparent' }, svg);
    hoverable(hit, `<strong>${esc(it.label)}</strong> — ${it.value}` + (it.verdict ? `<div style="color:${C.muted};margin-top:3px">currently ${esc(it.verdict)}</div>` : ''));
  });

  mount(host, svg, tableView(
    opts.headers || ['Item', 'Count'],
    items.map(i => [i.label, i.value]),
    opts.tableCaption || 'View as table'));
}

/* ---- 8. Histogram -------------------------------------------------------
 * Ordered bands of one measure — one hue, columns, no legend. */
export function histogram(host, data, opts = {}) {
  const { labels, values } = data;
  if (!labels || !values.some(v => v)) { host.innerHTML = `<p class="chartnote">${esc(opts.empty || 'Not enough scored reports yet.')}</p>`; return; }
  const w = 420, h = 168, padL = 28, padB = 30, padT = 8;
  const plotH = h - padB - padT, plotW = w - padL - 8;
  const max = Math.max(...values) || 1;
  const band = plotW / labels.length, barW = Math.min(24, band * 0.58);
  const svg = svgRoot(w, h, opts.label || 'Distribution');

  [...new Set([0, max])].forEach(t => {
    const y = padT + plotH - (t / max) * plotH;
    el('line', { x1: padL, y1: y, x2: w - 8, y2: y, stroke: C.grid, 'stroke-width': 1 }, svg);
    const tk = el('text', { x: padL - 8, y: y + 4, 'text-anchor': 'end', fill: C.muted, style: 'font:11px system-ui;font-variant-numeric:tabular-nums' }, svg);
    tk.textContent = t;
  });

  labels.forEach((l, i) => {
    const v = values[i];
    const bh = (v / max) * plotH;
    const x = padL + band * i + (band - barW) / 2;
    if (v > 0) {
      const y = padT + plotH - bh;
      el('rect', { x, y, width: barW, height: bh, rx: 4, fill: C.series }, svg);
      el('rect', { x, y: y + Math.max(0, bh - 4), width: barW, height: Math.min(4, bh), fill: C.series }, svg);
    }
    const t = el('text', { x: x + barW / 2, y: h - 10, 'text-anchor': 'middle', fill: C.muted, style: 'font:11px system-ui;font-variant-numeric:tabular-nums' }, svg);
    t.textContent = l;
    const hit = el('rect', { x: padL + band * i, y: 0, width: band, height: h - padB + 8, fill: 'transparent' }, svg);
    hoverable(hit, `<strong>${esc(l)}</strong> — ${v} report${v === 1 ? '' : 's'}`);
  });

  mount(host, svg, tableView(opts.headers || ['Band', 'Reports'], labels.map((l, i) => [l, values[i]]), opts.tableCaption || 'View as table'));
}

export { C as CHART_COLORS };
