/* Rig viewer: draws a skeleton.json (and its validation_report.json) so a rig can be checked by eye.
 *
 * Everything above the "UI" marker is pure logic with no DOM, so it can be unit-tested in Node
 * (viewer.test.js). World coordinates are Unity units with Y up; the screen flips Y.
 */
(function (root) {
  'use strict';

  const EXTRA_PREFIX = 'extra_';
  const LINK_TOLERANCE = 0.005; // fraction of the height, as in the validator

  function fail(message) { throw new Error(message); }
  function isPoint(p) { return Array.isArray(p) && p.length === 2 && p.every(Number.isFinite); }
  function esc(text) {
    return String(text).replace(/[&<>"']/g, (c) => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c]));
  }

  // ---------- parsing ----------

  function parseJson(text) {
    try { return JSON.parse(text); } catch (e) { return fail('This is not valid JSON: ' + e.message); }
  }

  function checkSkeleton(data) {
    if (!data || !Array.isArray(data.bones)) fail('This does not look like a skeleton.json: it has no "bones" list.');
    if (!Number.isFinite(data.height) || data.height <= 0) fail('The skeleton has no valid "height".');
    data.bones.forEach((b, i) => {
      const where = 'Bone ' + i + (b && b.name ? ' (' + b.name + ')' : '');
      if (!b || typeof b.name !== 'string') fail(where + ' has no name.');
      if (!Number.isInteger(b.id) || !Number.isInteger(b.parent_id)) fail(where + ' needs an integer id and parent_id.');
      if (!isPoint(b.world_head) || !isPoint(b.world_tail)) fail(where + ' needs world_head and world_tail as [x, y].');
    });
    return data;
  }

  function checkReport(data) {
    if (!data || !Array.isArray(data.issues)) fail('This does not look like a validation_report.json: it has no "issues" list.');
    return data;
  }

  function parseSkeleton(text) { return checkSkeleton(parseJson(text)); }
  function parseReport(text) { return checkReport(parseJson(text)); }

  /** Decide from the content whether a file is a skeleton or a report. */
  function classifyFile(text) {
    const data = parseJson(text);
    if (data && Array.isArray(data.bones)) return { kind: 'skeleton', data: checkSkeleton(data) };
    if (data && Array.isArray(data.issues)) return { kind: 'report', data: checkReport(data) };
    return fail('This is neither a skeleton.json (needs "bones") nor a validation_report.json (needs "issues").');
  }

  // ---------- bones ----------

  function sideOf(name) { return name.endsWith('_L') ? 'L' : name.endsWith('_R') ? 'R' : null; }

  /** left, right, center or extra: what the colour follows. */
  function kindOf(name) {
    if (name.startsWith(EXTRA_PREFIX)) return 'extra';
    const side = sideOf(name);
    return side === 'L' ? 'left' : side === 'R' ? 'right' : 'center';
  }

  /** Draw order key: depth, shifted by the extra bone's layer as the Unity importer does. */
  function drawKey(b) { return (b.depth || 0) + (b.layer === 'behind' ? -0.5 : b.layer === 'front' ? 0.5 : 0); }

  function drawOrder(bones, byDepth) {
    const list = bones.slice();
    return byDepth ? list.sort((a, b) => drawKey(a) - drawKey(b) || a.id - b.id) : list.sort((a, b) => a.id - b.id);
  }

  function worldAngle(b) {
    return Math.atan2(b.world_tail[1] - b.world_head[1], b.world_tail[0] - b.world_head[0]) * 180 / Math.PI;
  }

  function boundsOf(sk) {
    const xs = [0], ys = [0, sk.height];
    sk.bones.forEach((b) => { xs.push(b.world_head[0], b.world_tail[0]); ys.push(b.world_head[1], b.world_tail[1]); });
    return { minX: Math.min(...xs), maxX: Math.max(...xs), minY: Math.min(...ys), maxY: Math.max(...ys) };
  }

  /** Bones whose head is not on the parent's tail: limb roots, the hip, the jaw, extras on a head. */
  function linkGaps(sk) {
    const byId = new Map(sk.bones.map((b) => [b.id, b]));
    const eps = LINK_TOLERANCE * sk.height;
    const gaps = [];
    sk.bones.forEach((b) => {
      const parent = byId.get(b.parent_id);
      if (!parent) return;
      const gap = Math.hypot(b.world_head[0] - parent.world_tail[0], b.world_head[1] - parent.world_tail[1]);
      if (gap > eps) gaps.push({ child: b.name, parent: parent.name, gap, from: parent.world_tail, to: b.world_head });
    });
    return gaps;
  }

  /** The bone as a diamond from pivot to tip, in world coordinates. */
  function boneShape(b, height) {
    const [hx, hy] = b.world_head, [tx, ty] = b.world_tail;
    const dx = tx - hx, dy = ty - hy;
    const len = Math.hypot(dx, dy) || 1e-9;
    const nx = -dy / len, ny = dx / len;
    const w = Math.min(Math.max(0.18 * len, 0.006 * height), 0.045 * height);
    const mx = hx + dx * 0.18, my = hy + dy * 0.18;
    return [[hx, hy], [mx + nx * w, my + ny * w], [tx, ty], [mx - nx * w, my - ny * w]];
  }

  function childrenOf(sk) {
    const map = new Map();
    sk.bones.forEach((b) => { if (!map.has(b.parent_id)) map.set(b.parent_id, []); map.get(b.parent_id).push(b); });
    return map;
  }

  /** The hierarchy as a flat list of { bone, level }, depth first, in id order. */
  function treeRows(sk) {
    const kids = childrenOf(sk);
    const ids = new Set(sk.bones.map((b) => b.id));
    const rows = [];
    const walk = (bone, level) => {
      rows.push({ bone, level });
      (kids.get(bone.id) || []).slice().sort((a, b) => a.id - b.id).forEach((c) => walk(c, level + 1));
    };
    sk.bones.filter((b) => b.parent_id === -1 || !ids.has(b.parent_id)).sort((a, b) => a.id - b.id).forEach((r) => walk(r, 0));
    return rows;
  }

  function fmt(n, digits) { return Number.isFinite(n) ? n.toFixed(digits === undefined ? 3 : digits) : '-'; }

  function describeBone(b, sk) {
    const byId = new Map(sk.bones.map((x) => [x.id, x]));
    const parent = byId.get(b.parent_id);
    return [
      ['id', String(b.id)],
      ['parent', parent ? parent.name + ' (' + parent.id + ')' : 'none (root)'],
      ['head', '(' + fmt(b.world_head[0]) + ', ' + fmt(b.world_head[1]) + ')'],
      ['tail', '(' + fmt(b.world_tail[0]) + ', ' + fmt(b.world_tail[1]) + ')'],
      ['length', fmt(b.length)],
      ['angle', fmt(worldAngle(b), 1) + '°'],
      ['depth', String(b.depth)],
      ['layer', b.layer || '-'],
      ['ik chain', b.ik_chain || '-'],
      ['mirror of', b.mirror_of || '-'],
      ['local pos', b.local_position ? '(' + fmt(b.local_position[0]) + ', ' + fmt(b.local_position[1]) + ')' : '-'],
      ['local rot', b.local_rotation_deg === undefined ? '-' : fmt(b.local_rotation_deg, 1) + '°'],
    ];
  }

  /** Bone names the report points at. A spec name such as extra_horn also covers the built bones
   *  extra_horn_L, extra_horn_R, extra_horn_1 ... when the skeleton is given. */
  function reportBones(report, sk) {
    const names = new Set();
    if (!report) return names;
    const all = sk ? sk.bones.map((b) => b.name) : [];
    report.issues.forEach((i) => (i.bones || []).forEach((n) => {
      names.add(n);
      all.filter((x) => x.startsWith(n + '_') && x.startsWith(EXTRA_PREFIX)).forEach((x) => names.add(x));
    }));
    return names;
  }

  // ---------- colours ----------

  const IK_COLORS = { arm_L: '#1c7ed6', arm_R: '#e8590c', leg_L: '#0ca678', leg_R: '#ae3ec9' };

  function depthRange(sk) {
    const depths = sk.bones.map((b) => b.depth || 0);
    return { min: Math.min(...depths), max: Math.max(...depths) };
  }

  function colorFor(b, mode, range) {
    if (mode === 'depth') {
      const d = b.depth || 0;
      if (d === 0) return 'var(--c-center)';
      const t = d > 0 ? d / Math.max(range.max, 1) : d / Math.min(range.min, -1);
      return d > 0 ? 'hsl(24 90% ' + (58 - 14 * t) + '%)' : 'hsl(214 80% ' + (62 - 14 * t) + '%)';
    }
    if (mode === 'ik') return IK_COLORS[b.ik_chain] || 'var(--c-none)';
    return 'var(--c-' + kindOf(b.name) + ')';
  }

  // ---------- SVG ----------

  const STEPS = [0.05, 0.1, 0.25, 0.5, 1, 2, 5, 10];
  function gridStep(zoom) { return STEPS.find((s) => s * zoom >= 56) || STEPS[STEPS.length - 1]; }

  function fitView(sk, size, pad) {
    const b = boundsOf(sk);
    const w = Math.max(b.maxX - b.minX, 1e-6), h = Math.max(b.maxY - b.minY, 1e-6);
    const zoom = Math.min((size.w - 2 * pad) / w, (size.h - 2 * pad) / h);
    return { cx: (b.minX + b.maxX) / 2, cy: (b.minY + b.maxY) / 2, zoom };
  }

  const num = (n) => (Math.round(n * 10) / 10).toString();

  /** The whole picture as an SVG string. `m` = { skeleton, report, selected }, `o` = display options. */
  function renderSvg(m, view, o, size) {
    const sk = m.skeleton, H = sk.height, flip = o.flip ? -1 : 1;
    const X = (x) => size.w / 2 + flip * (x - view.cx) * view.zoom;
    const Y = (y) => size.h / 2 - (y - view.cy) * view.zoom;
    const P = (p) => num(X(p[0])) + ',' + num(Y(p[1]));
    const bad = reportBones(m.report, sk);
    const range = depthRange(sk);
    const byId = new Map(sk.bones.map((b) => [b.id, b]));
    const sel = m.selected === null || m.selected === undefined ? null : byId.get(m.selected);
    const out = [];
    out.push('<rect class="bg" x="0" y="0" width="' + size.w + '" height="' + size.h + '" fill="var(--stage-bg)"/>');

    if (o.grid) {
      const step = gridStep(view.zoom), half = size.w / 2 / view.zoom;
      const x0 = Math.floor((view.cx - half) / step), x1 = Math.ceil((view.cx + half) / step);
      for (let k = x0; k <= x1; k++) {
        const x = k * step;
        out.push('<line class="grid" x1="' + num(X(x)) + '" y1="0" x2="' + num(X(x)) + '" y2="' + size.h + '"/>');
        out.push('<text class="tick" x="' + num(X(x) + 3) + '" y="' + (size.h - 6) + '">' + esc(+x.toFixed(3)) + '</text>');
      }
      const halfY = size.h / 2 / view.zoom;
      const y0 = Math.floor((view.cy - halfY) / step), y1 = Math.ceil((view.cy + halfY) / step);
      for (let k = y0; k <= y1; k++) {
        const y = k * step;
        out.push('<line class="grid" x1="0" y1="' + num(Y(y)) + '" x2="' + size.w + '" y2="' + num(Y(y)) + '"/>');
        out.push('<text class="tick" x="6" y="' + num(Y(y) - 3) + '">' + esc(+y.toFixed(3)) + '</text>');
      }
    }
    out.push('<line class="ground" x1="0" y1="' + num(Y(0)) + '" x2="' + size.w + '" y2="' + num(Y(0)) + '"/>');
    out.push('<line class="axis" x1="' + num(X(0)) + '" y1="0" x2="' + num(X(0)) + '" y2="' + size.h + '"/>');
    out.push('<line class="height" x1="0" y1="' + num(Y(H)) + '" x2="' + size.w + '" y2="' + num(Y(H)) + '"/>');
    out.push('<text class="tick height-label" x="' + (size.w - 8) + '" y="' + num(Y(H) - 4) + '" text-anchor="end">height ' + esc(H) + '</text>');
    if (o.bounds) {
      const xa = X(-H), xb = X(H);
      out.push('<rect class="bounds" x="' + num(Math.min(xa, xb)) + '" y="' + num(Y(1.2 * H)) + '" width="' + num(Math.abs(xb - xa)) + '" height="' + num(Y(0) - Y(1.2 * H)) + '"/>');
    }

    if (o.links) {
      linkGaps(sk).forEach((g) => out.push('<line class="link" x1="' + P(g.from).split(',')[0] + '" y1="' + P(g.from).split(',')[1] + '" x2="' + P(g.to).split(',')[0] + '" y2="' + P(g.to).split(',')[1] + '"/>'));
    }

    const bones = drawOrder(sk.bones, o.depth).filter((b) => o.extras || kindOf(b.name) !== 'extra');
    bones.forEach((b) => {
      const pts = boneShape(b, H).map(P).join(' ');
      const color = colorFor(b, o.color, range);
      const cls = 'bone' + (bad.has(b.name) ? ' bad' : '') + (kindOf(b.name) === 'extra' ? ' extra' : '');
      out.push('<polygon class="' + cls + '" data-id="' + b.id + '" points="' + pts + '" fill="' + color + '" stroke="' + color + '"><title>' + esc(b.name) + '</title></polygon>');
    });

    if (o.joints) {
      bones.forEach((b) => out.push('<circle class="joint" cx="' + num(X(b.world_head[0])) + '" cy="' + num(Y(b.world_head[1])) + '" r="' + (kindOf(b.name) === 'extra' ? 2.3 : 3.2) + '"/>'));
    }

    bones.filter((b) => bad.has(b.name)).forEach((b) => {
      const mid = [(b.world_head[0] + b.world_tail[0]) / 2, (b.world_head[1] + b.world_tail[1]) / 2];
      out.push('<circle class="issue-ring" cx="' + num(X(mid[0])) + '" cy="' + num(Y(mid[1])) + '" r="14"/>');
    });

    if (sel) {
      const parent = byId.get(sel.parent_id);
      if (parent) out.push('<polygon class="parent-outline" points="' + boneShape(parent, H).map(P).join(' ') + '"/>');
      (childrenOf(sk).get(sel.id) || []).forEach((c) => out.push('<polygon class="child-outline" points="' + boneShape(c, H).map(P).join(' ') + '"/>'));
      out.push('<polygon class="sel-outline" points="' + boneShape(sel, H).map(P).join(' ') + '"/>');
    }

    const labelled = o.labels ? bones : sel ? [sel] : [];
    labelled.forEach((b) => {
      const kind = kindOf(b.name);
      const natural = flip * (b.world_tail[0] - b.world_head[0]) >= 0 ? 'start' : 'end';
      // left labels go right, right labels go left (so a near and a far limb do not collide in the
      // side view), and extras go opposite their direction (so they clear the spine labels)
      const anchor = kind === 'left' ? (flip > 0 ? 'start' : 'end')
        : kind === 'right' ? (flip > 0 ? 'end' : 'start')
        : kind === 'extra' ? (natural === 'start' ? 'end' : 'start') : natural;
      const dx = anchor === 'start' ? 5 : -5;
      out.push('<text class="label" x="' + num(X(b.world_tail[0]) + dx) + '" y="' + num(Y(b.world_tail[1]) + 3) + '" text-anchor="' + anchor + '">' + esc(b.name) + '</text>');
    });

    return '<svg xmlns="http://www.w3.org/2000/svg" width="' + size.w + '" height="' + size.h + '" viewBox="0 0 ' + size.w + ' ' + size.h + '" font-family="ui-sans-serif, system-ui, sans-serif">' + out.join('') + '</svg>';
  }

  const api = {
    parseSkeleton, parseReport, classifyFile, sideOf, kindOf, drawKey, drawOrder, worldAngle, boundsOf,
    linkGaps, boneShape, treeRows, describeBone, reportBones, colorFor, depthRange, gridStep, fitView,
    renderSvg, esc, fmt, IK_COLORS,
  };
  if (typeof module !== 'undefined' && module.exports) module.exports = api;
  root.RigViewer = api;

  // ---------- UI ----------

  if (typeof document === 'undefined') return;
  const $ = (id) => document.getElementById(id);
  const opts = { labels: true, joints: true, links: true, grid: true, bounds: false, depth: true, extras: true, flip: false, color: 'side' };
  const state = { skeleton: null, report: null, selected: null, view: { cx: 0, cy: 1, zoom: 200 }, size: { w: 800, h: 600 }, source: '', lastText: '', lastReportText: '', hoverId: null };

  function updateLegend() {
    const sw = (color, text) => '<span><i class="sw" style="background:' + color + '"></i>' + text + '</span> ';
    const legend = {
      side: sw('var(--c-left)', 'left') + sw('var(--c-right)', 'right') + sw('var(--c-center)', 'center') + sw('var(--c-extra)', 'extra'),
      depth: sw('hsl(214 80% 50%)', 'behind (negative)') + sw('var(--c-center)', 'torso plane (0)') + sw('hsl(24 90% 46%)', 'in front (positive)'),
      ik: Object.keys(IK_COLORS).map((k) => sw(IK_COLORS[k], k)).join('') + sw('var(--c-none)', 'not in a chain'),
    };
    $('legend').innerHTML = (legend[opts.color] || '') + '<span>dashed line = offset from the parent\'s tail</span>';
  }

  function notice(message, isError) {
    const el = $('notice');
    el.textContent = message || '';
    el.className = message ? (isError ? 'error' : 'info') : '';
  }

  function stageSize() {
    const r = $('stage').getBoundingClientRect();
    return { w: Math.max(200, Math.round(r.width)), h: Math.max(200, Math.round(r.height)) };
  }

  function render() {
    state.size = stageSize();
    if (!state.skeleton) { $('stage').innerHTML = '<div class="empty">Drop a <code>skeleton.json</code> here, choose files, or load a sample.</div>'; return; }
    $('stage').innerHTML = renderSvg(state, state.view, opts, state.size);
    const sel = $('stage').querySelector('.bone[data-id="' + state.selected + '"]');
    if (sel) sel.classList.add('selected');
  }

  function fit() {
    if (!state.skeleton) return;
    state.view = fitView(state.skeleton, stageSize(), 56);
    render();
  }

  function showDetails(id) {
    const box = $('details');
    const b = state.skeleton && state.skeleton.bones.find((x) => x.id === id);
    if (!b) { box.innerHTML = '<p class="muted">Hover or click a bone.</p>'; return; }
    box.innerHTML = '<h3>' + esc(b.name) + '</h3><dl>' + describeBone(b, state.skeleton).map((r) => '<dt>' + esc(r[0]) + '</dt><dd>' + esc(r[1]) + '</dd>').join('') + '</dl>';
  }

  function select(id) {
    state.selected = id;
    render();
    showDetails(id === null ? state.hoverId : id);
    document.querySelectorAll('#tree li').forEach((li) => li.classList.toggle('active', Number(li.dataset.id) === id));
  }

  function buildTree() {
    const bad = reportBones(state.report, state.skeleton);
    $('tree').innerHTML = treeRows(state.skeleton).map((r) => {
      const b = r.bone;
      const chips = (b.depth ? '<span class="chip">d ' + b.depth + '</span>' : '') + (b.ik_chain ? '<span class="chip ik">' + esc(b.ik_chain) + '</span>' : '') + (b.layer ? '<span class="chip">' + esc(b.layer) + '</span>' : '');
      return '<li data-id="' + b.id + '" class="' + kindOf(b.name) + (bad.has(b.name) ? ' bad' : '') + '" style="padding-left:' + (8 + r.level * 12) + 'px"><span class="dot"></span>' + esc(b.name) + chips + '</li>';
    }).join('');
  }

  function buildMeta() {
    const sk = state.skeleton, md = sk.metadata || {};
    const extras = sk.bones.filter((b) => kindOf(b.name) === 'extra').length;
    const rows = [
      ['view', sk.view + (sk.facing ? ' (facing ' + sk.facing + ')' : '')], ['pose', sk.rest_pose], ['style', sk.style],
      ['height', fmt(sk.height, 2) + ' units, ' + sk.pixels_per_unit + ' PPU'], ['bones', sk.bones.length + ' (' + extras + ' extra)'],
      ['model', md.model || '-'], ['attempts', md.iterations === undefined ? '-' : String(md.iterations)],
    ];
    $('rigTitle').textContent = sk.rig_name || 'skeleton';
    $('meta').innerHTML = '<dl>' + rows.map((r) => '<dt>' + esc(r[0]) + '</dt><dd>' + esc(r[1]) + '</dd>').join('') + '</dl>'
      + (sk.source_prompt ? '<p class="prompt">“' + esc(sk.source_prompt) + '”</p>' : '')
      + (md.assumptions && md.assumptions.length ? '<ul class="assume">' + md.assumptions.map((a) => '<li>' + esc(a) + '</li>').join('') + '</ul>' : '');
  }

  function buildReport() {
    const box = $('report');
    if (!state.report) { box.innerHTML = '<p class="muted">No validation report loaded. Drop <code>validation_report.json</code> too.</p>'; return; }
    const r = state.report, errors = r.issues.filter((i) => i.severity === 'error').length;
    const ok = r.passed !== undefined ? r.passed : errors === 0;
    const metrics = r.metrics ? Object.keys(r.metrics).map((k) => '<dt>' + esc(k.replace(/_/g, ' ')) + '</dt><dd>' + esc(fmt(r.metrics[k], 4)) + '</dd>').join('') : '';
    box.innerHTML = '<p class="badge ' + (ok ? 'pass' : 'fail') + '">' + (ok ? 'PASSED' : 'FAILED') + ' · ' + errors + ' errors, ' + (r.issues.length - errors) + ' warnings</p>'
      + (r.issues.length ? '<ul class="issues">' + r.issues.map((i) => '<li data-bone="' + esc((i.bones || [])[0] || '') + '"><b>' + esc(i.code) + '</b> ' + esc(i.message) + '</li>').join('') + '</ul>' : '')
      + (metrics ? '<dl class="metrics">' + metrics + '</dl>' : '');
  }

  let pendingSelect = null;

  function setSkeleton(sk, keepView) {
    state.skeleton = sk;
    if (state.selected !== null && !sk.bones.some((b) => b.id === state.selected)) state.selected = null;
    buildMeta(); buildTree(); buildReport();
    if (keepView) render(); else fit();
    showDetails(state.selected);
    if (pendingSelect) {
      const wanted = sk.bones.find((b) => b.name === pendingSelect);
      pendingSelect = null;
      if (wanted) select(wanted.id);
    }
  }

  function setReport(report) { state.report = report; buildReport(); buildTree(); render(); }

  function loadText(text, label, keepView) {
    const file = classifyFile(text);
    if (file.kind === 'skeleton') { state.lastText = text; setSkeleton(file.data, keepView); notice(label ? 'Loaded ' + label : '', false); }
    else { state.lastReportText = text; if (state.skeleton) setReport(file.data); else { state.report = file.data; } notice(label ? 'Loaded ' + label : '', false); }
  }

  async function loadFiles(files) {
    const list = Array.from(files), texts = [];
    for (const f of list) texts.push({ name: f.name, text: await f.text() });
    // skeletons first, so a report dropped with them attaches to the skeleton
    const parsed = [];
    for (const t of texts) {
      try { parsed.push({ name: t.name, file: classifyFile(t.text), text: t.text }); } catch (e) { notice(t.name + ': ' + e.message, true); return; }
    }
    parsed.sort((a, b) => (a.file.kind === 'skeleton' ? -1 : 1) - (b.file.kind === 'skeleton' ? -1 : 1));
    if (parsed.some((p) => p.file.kind === 'skeleton') && !parsed.some((p) => p.file.kind === 'report')) state.report = null;
    state.source = '';
    stopWatching();
    parsed.forEach((p) => loadText(p.text, p.name, false));
    if (parsed.length > 1) notice('Loaded ' + parsed.map((p) => p.name).join(' and '), false);
  }

  function loadSample(name) {
    const s = root.RIG_SAMPLES && root.RIG_SAMPLES[name];
    if (!s) { notice('Unknown sample "' + name + '".', true); return; }
    state.report = s.report;
    stopWatching();
    setSkeleton(checkSkeleton(JSON.parse(JSON.stringify(s.skeleton))), false);
    notice('Sample: ' + name, false);
    $('sample').value = name;
  }

  // ---- watching a served file ----

  let timer = null;
  function stopWatching() { if (timer) clearInterval(timer); timer = null; $('watchState').textContent = ''; }

  async function fetchText(url) {
    const res = await fetch(url, { cache: 'no-store' });
    if (!res.ok) throw new Error(res.status + ' ' + res.statusText);
    return res.text();
  }

  async function pollOnce(src, first) {
    try {
      const text = await fetchText(src);
      if (text !== state.lastText) {
        loadText(text, first ? src : '', !first);
        try {
          const reportUrl = src.replace(/[^/]*$/, 'validation_report.json');
          const reportText = await fetchText(reportUrl);
          if (reportText !== state.lastReportText) loadText(reportText, '', true);
        } catch (e) { state.report = null; state.lastReportText = ''; buildReport(); buildTree(); render(); } // the report is optional
        $('watchState').textContent = 'updated ' + new Date().toLocaleTimeString();
      }
    } catch (e) {
      if (first) notice('Could not load ' + src + ': ' + e.message + '. Serve the folder over http (see the README) or drop the file here.', true);
    }
  }

  function startWatching(src) {
    stopWatching();
    if (src !== state.source) { state.lastText = ''; state.lastReportText = ''; state.report = null; }
    state.source = src;
    pollOnce(src, true);
    if ($('opt-watch').checked) timer = setInterval(() => pollOnce(src, false), 1500);
  }

  // ---- the out/ folder picker (only when served by `rig-agent view`) ----

  function rigLabel(r) {
    const mark = r.passed === true ? 'ok' : r.passed === false ? 'FAILED' : 'no report';
    return r.name + '  -  ' + (r.view || '?') + ', ' + r.bones + ' bones, ' + mark;
  }

  let rigListKey = '';
  function fillRigList(rigs) {
    const list = $('rigList'), current = state.source;
    const key = JSON.stringify(rigs);
    if (key === rigListKey) { list.value = rigs.some((r) => r.path === current) ? current : ''; return; }
    rigListKey = key;
    list.innerHTML = '<option value="">Choose a rig...</option>' + rigs.map((r) =>
      '<option value="' + esc(r.path) + '">' + esc(rigLabel(r)) + '</option>').join('');
    if (rigs.some((r) => r.path === current)) list.value = current;
    $('rigListNote').textContent = rigs.length + ' rig' + (rigs.length === 1 ? '' : 's') + ' found, newest first';
  }

  async function refreshRigList() {
    try {
      const res = await fetch('/api/rigs', { cache: 'no-store' });
      if (!res.ok) return false;
      const data = await res.json();
      $('rigsSection').hidden = false;
      fillRigList(data.rigs || []);
      return true;
    } catch (e) { return false; }
  }

  async function initRigList() {
    if (location.protocol === 'file:') return;
    if (!(await refreshRigList())) return;
    $('rigList').addEventListener('change', (e) => { if (e.target.value) startWatching(e.target.value); });
    setInterval(refreshRigList, 4000);
  }

  // ---- save PNG ----

  function resolvedSvg() {
    const style = getComputedStyle(document.documentElement);
    let svg = renderSvg(state, state.view, opts, state.size);
    svg = svg.replace(/var\((--[\w-]+)\)/g, (m, name) => style.getPropertyValue(name).trim() || m);
    const css = ['grid', 'ground', 'axis', 'height', 'bounds', 'link', 'joint', 'label', 'tick', 'bone', 'sel-outline', 'parent-outline', 'child-outline', 'issue-ring']
      .map((c) => cssFor(c, style)).join('');
    return svg.replace('>', '><style>' + css + '</style>');
  }

  function cssFor(cls, style) {
    const v = (n) => style.getPropertyValue(n).trim();
    const rules = {
      grid: 'stroke:' + v('--grid') + ';stroke-width:1', ground: 'stroke:' + v('--ground') + ';stroke-width:2.5', axis: 'stroke:' + v('--grid') + ';stroke-width:1.5',
      height: 'stroke:' + v('--muted') + ';stroke-width:1;stroke-dasharray:6 5', bounds: 'fill:none;stroke:' + v('--warn') + ';stroke-width:1.5;stroke-dasharray:8 6',
      link: 'stroke:' + v('--muted') + ';stroke-width:1.3;stroke-dasharray:3 3', joint: 'fill:' + v('--panel') + ';stroke:' + v('--ink') + ';stroke-width:1.2',
      label: 'font-size:11px;fill:' + v('--ink') + ';stroke:' + v('--stage-bg') + ';stroke-width:3;paint-order:stroke', tick: 'font-size:10px;fill:' + v('--muted'),
      bone: 'fill-opacity:.55;stroke-width:1.6;stroke-linejoin:round', 'sel-outline': 'fill:none;stroke:' + v('--sel') + ';stroke-width:3', 'parent-outline': 'fill:none;stroke:' + v('--sel') + ';stroke-width:1.6;stroke-dasharray:4 3',
      'child-outline': 'fill:none;stroke:' + v('--sel') + ';stroke-width:1.2;opacity:.7', 'issue-ring': 'fill:none;stroke:' + v('--bad') + ';stroke-width:2.5',
    };
    return '.' + cls + '{' + rules[cls] + '}';
  }

  function savePng() {
    if (!state.skeleton) return;
    const img = new Image();
    img.onload = () => {
      const canvas = document.createElement('canvas');
      canvas.width = state.size.w * 2; canvas.height = state.size.h * 2;
      const ctx = canvas.getContext('2d');
      ctx.scale(2, 2); ctx.drawImage(img, 0, 0);
      canvas.toBlob((blob) => {
        const a = document.createElement('a');
        a.href = URL.createObjectURL(blob);
        a.download = (state.skeleton.rig_name || 'skeleton') + '.png';
        a.click();
        setTimeout(() => URL.revokeObjectURL(a.href), 2000);
      });
    };
    img.src = 'data:image/svg+xml;charset=utf-8,' + encodeURIComponent(resolvedSvg());
  }

  // ---- wiring ----

  function initUI() {
    document.querySelectorAll('[data-opt]').forEach((el) => {
      el.addEventListener('change', () => { opts[el.dataset.opt] = el.type === 'checkbox' ? el.checked : el.value; updateLegend(); render(); });
    });
    $('opt-watch').addEventListener('change', () => { if (!$('opt-watch').checked) stopWatching(); else if (state.source) startWatching(state.source); });
    $('fit').addEventListener('click', fit);
    $('savePng').addEventListener('click', savePng);
    $('pick').addEventListener('change', (e) => { if (e.target.files.length) loadFiles(e.target.files); e.target.value = ''; });
    $('sample').innerHTML = '<option value="">Load a sample...</option>' + Object.keys(root.RIG_SAMPLES || {}).map((k) => '<option value="' + esc(k) + '">' + esc(k.replace(/_/g, ' ')) + '</option>').join('');
    $('sample').addEventListener('change', (e) => { if (e.target.value) loadSample(e.target.value); });

    $('tree').addEventListener('click', (e) => { const li = e.target.closest('li'); if (li) select(Number(li.dataset.id)); });
    $('report').addEventListener('click', (e) => {
      const li = e.target.closest('li[data-bone]');
      const first = li && Array.from(reportBones({ issues: [{ bones: [li.dataset.bone] }] }, state.skeleton))
        .map((n) => state.skeleton.bones.find((b) => b.name === n)).filter(Boolean).sort((a, b) => a.id - b.id)[0];
      if (first) select(first.id);
    });

    const stage = $('stage');
    let drag = null;
    stage.addEventListener('pointerdown', (e) => {
      const hit = e.target.closest ? e.target.closest('.bone') : null;
      drag = { x: e.clientX, y: e.clientY, cx: state.view.cx, cy: state.view.cy, moved: false, id: hit ? Number(hit.dataset.id) : null };
      stage.setPointerCapture(e.pointerId);
    });
    stage.addEventListener('pointermove', (e) => {
      const r = stage.getBoundingClientRect();
      if (state.skeleton) $('coords').textContent = 'x ' + fmt((e.clientX - r.left - state.size.w / 2) / state.view.zoom * (opts.flip ? -1 : 1) + state.view.cx, 3) + '   y ' + fmt(state.view.cy - (e.clientY - r.top - state.size.h / 2) / state.view.zoom, 3);
      if (drag) {
        const dx = e.clientX - drag.x, dy = e.clientY - drag.y;
        if (!drag.moved && Math.hypot(dx, dy) > 4) drag.moved = true;
        if (drag.moved) { state.view.cx = drag.cx - dx / state.view.zoom * (opts.flip ? -1 : 1); state.view.cy = drag.cy + dy / state.view.zoom; render(); }
      } else {
        const el = document.elementFromPoint(e.clientX, e.clientY), hit = el && el.closest && el.closest('.bone');
        stage.querySelectorAll('.bone.hover').forEach((n) => n.classList.remove('hover'));
        state.hoverId = hit ? Number(hit.dataset.id) : null;
        if (hit) hit.classList.add('hover');
        if (state.selected === null) showDetails(state.hoverId);
      }
    });
    stage.addEventListener('pointerup', () => { if (drag && !drag.moved) select(drag.id); drag = null; });
    stage.addEventListener('wheel', (e) => {
      if (!state.skeleton) return;
      e.preventDefault();
      const r = stage.getBoundingClientRect(), flip = opts.flip ? -1 : 1;
      const px = e.clientX - r.left - state.size.w / 2, py = e.clientY - r.top - state.size.h / 2;
      const wx = state.view.cx + flip * px / state.view.zoom, wy = state.view.cy - py / state.view.zoom;
      state.view.zoom = Math.min(4000, Math.max(20, state.view.zoom * Math.exp(-e.deltaY * 0.0015)));
      state.view.cx = wx - flip * px / state.view.zoom; state.view.cy = wy + py / state.view.zoom;
      render();
    }, { passive: false });
    window.addEventListener('keydown', (e) => {
      if (e.target.tagName === 'INPUT' || e.target.tagName === 'SELECT') return;
      if (e.key === 'f') fit();
      if (e.key === 'l') { $('opt-labels').click(); }
      if (e.key === 'Escape') select(null);
    });

    window.addEventListener('dragover', (e) => { e.preventDefault(); document.body.classList.add('dragging'); });
    window.addEventListener('dragleave', (e) => { if (e.target === document.documentElement || !e.relatedTarget) document.body.classList.remove('dragging'); });
    window.addEventListener('drop', (e) => { e.preventDefault(); document.body.classList.remove('dragging'); if (e.dataTransfer.files.length) loadFiles(e.dataTransfer.files); });
    new ResizeObserver(() => { if (state.skeleton) render(); }).observe($('stage'));

    const params = new URLSearchParams(location.search);
    pendingSelect = params.get('select');
    if (params.get('sample')) loadSample(params.get('sample'));
    else if (params.get('src')) startWatching(params.get('src'));
    else render();
    ['labels', 'joints', 'links', 'grid', 'bounds', 'depth', 'extras', 'flip'].forEach((k) => { if (params.has(k)) { opts[k] = params.get(k) !== '0'; $('opt-' + k).checked = opts[k]; } });
    if (params.get('color')) { opts.color = params.get('color'); $('opt-color').value = opts.color; }
    updateLegend();
    render();
    initRigList();
  }

  initUI();
})(typeof window !== 'undefined' ? window : globalThis);
