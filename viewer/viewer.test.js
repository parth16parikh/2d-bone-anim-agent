// Unit tests for the pure logic in viewer.js. Run with:  node --test viewer/viewer.test.js
const test = require('node:test');
const assert = require('node:assert/strict');

require('./samples.js');
const V = require('./viewer.js');
const samples = globalThis.RIG_SAMPLES;
const elf = () => JSON.parse(JSON.stringify(samples.elf_front.skeleton));
const knight = () => JSON.parse(JSON.stringify(samples.knight_side.skeleton));
const byName = (sk, name) => sk.bones.find((b) => b.name === name);
const count = (svg, pattern) => (svg.match(pattern) || []).length;
const OPTS = { labels: true, joints: true, links: true, grid: true, bounds: false, depth: true, extras: true, flip: false, color: 'side' };
const SIZE = { w: 800, h: 600 };
const model = (sk, extra) => Object.assign({ skeleton: sk, report: null, selected: null }, extra);

test('the three samples are present and valid', () => {
  assert.deepEqual(Object.keys(samples).sort(), ['chibi_mage_front', 'elf_front', 'knight_side']);
  for (const s of Object.values(samples)) assert.doesNotThrow(() => V.parseSkeleton(JSON.stringify(s.skeleton)));
});

test('parseSkeleton explains what is wrong', () => {
  assert.throws(() => V.parseSkeleton('{oops'), /not valid JSON/);
  assert.throws(() => V.parseSkeleton('{"height": 2}'), /no "bones" list/);
  assert.throws(() => V.parseSkeleton('{"bones": [], "height": 0}'), /valid "height"/);
  assert.throws(() => V.parseSkeleton(JSON.stringify({ height: 2, bones: [{ id: 0, parent_id: -1, name: 'root', world_head: [0, 0] }] })), /root.*world_head and world_tail/);
  assert.throws(() => V.parseSkeleton(JSON.stringify({ height: 2, bones: [{ id: 'a', parent_id: -1, name: 'root', world_head: [0, 0], world_tail: [0, 1] }] })), /integer id/);
  assert.throws(() => V.parseSkeleton(JSON.stringify({ height: 2, bones: [{ parent_id: -1 }] })), /has no name/);
});

test('classifyFile tells skeletons from reports', () => {
  assert.equal(V.classifyFile(JSON.stringify(elf())).kind, 'skeleton');
  assert.equal(V.classifyFile(JSON.stringify(samples.elf_front.report)).kind, 'report');
  assert.throws(() => V.classifyFile('{"hello": 1}'), /neither/);
  assert.throws(() => V.classifyFile('[1,2'), /not valid JSON/);
  assert.throws(() => V.parseReport('{"bones": []}'), /no "issues" list/);
});

test('kindOf follows the naming convention', () => {
  assert.equal(V.kindOf('upper_arm_L'), 'left');
  assert.equal(V.kindOf('thigh_R'), 'right');
  assert.equal(V.kindOf('hip'), 'center');
  assert.equal(V.kindOf('extra_hair_1_L'), 'extra');
  assert.equal(V.kindOf('extra_cape'), 'extra');
  assert.equal(V.sideOf('foot_L'), 'L');
  assert.equal(V.sideOf('head'), null);
});

test('drawOrder puts far limbs behind the torso and near limbs in front', () => {
  const sk = knight();
  const order = V.drawOrder(sk.bones, true).map((b) => b.name);
  assert.ok(order.indexOf('thigh_L') < order.indexOf('spine'), 'the far (left) leg draws behind the torso');
  assert.ok(order.indexOf('spine') < order.indexOf('thigh_R'), 'the near (right) leg draws in front');
  assert.ok(order.indexOf('extra_cape_1') < order.indexOf('spine'), 'a behind-layer cape draws behind the torso');
  assert.ok(order.indexOf('extra_sword') > order.indexOf('hand_R'), 'a front-layer sword draws in front of the near hand');
});

test('drawOrder can fall back to id order', () => {
  const sk = knight();
  assert.deepEqual(V.drawOrder(sk.bones, false).map((b) => b.id), sk.bones.map((b) => b.id));
});

test('drawKey shifts by the layer', () => {
  assert.equal(V.drawKey({ depth: 1, layer: 'behind' }), 0.5);
  assert.equal(V.drawKey({ depth: 0, layer: 'front' }), 0.5);
  assert.equal(V.drawKey({ depth: -1 }), -1);
});

test('boundsOf includes the ground origin and the full height', () => {
  const sk = elf();
  const b = V.boundsOf(sk);
  assert.equal(b.minY, Math.min(0, ...sk.bones.map((x) => Math.min(x.world_head[1], x.world_tail[1]))));
  assert.ok(b.maxY >= sk.height - 1e-9 && b.minX < 0 && b.maxX > 0);
});

test('linkGaps finds exactly the bones that do not start on their parent tail', () => {
  const gaps = V.linkGaps(elf()).map((g) => g.child).sort();
  assert.deepEqual(gaps, ['hip', 'thigh_L', 'thigh_R', 'upper_arm_L', 'upper_arm_R']);
  const side = V.linkGaps(knight()).map((g) => g.child);
  assert.ok(side.includes('upper_arm_L') && side.includes('jaw') && !side.includes('upper_arm_R'), 'only the far arm is offset');
});

test('boneShape is a diamond from head to tail', () => {
  const b = byName(elf(), 'forearm_L');
  const shape = V.boneShape(b, 2);
  assert.equal(shape.length, 4);
  assert.deepEqual(shape[0], b.world_head);
  assert.deepEqual(shape[2], b.world_tail);
  const w = Math.hypot(shape[1][0] - shape[3][0], shape[1][1] - shape[3][1]);
  assert.ok(w > 0 && w <= 2 * 0.045 * 2 + 1e-9, 'full width is at most twice 4.5% of the height');
});

test('treeRows lists parents before children with growing levels', () => {
  const sk = elf();
  const rows = V.treeRows(sk);
  assert.equal(rows.length, sk.bones.length);
  assert.equal(rows[0].bone.name, 'root');
  assert.equal(rows[0].level, 0);
  const seen = new Set();
  for (const r of rows) {
    if (r.bone.parent_id !== -1) assert.ok(seen.has(r.bone.parent_id), r.bone.name + ' comes after its parent');
    seen.add(r.bone.id);
  }
  assert.equal(rows.find((r) => r.bone.name === 'forearm_L').level, rows.find((r) => r.bone.name === 'upper_arm_L').level + 1);
});

test('describeBone lists the fields a reviewer needs', () => {
  const sk = elf();
  const rows = Object.fromEntries(V.describeBone(byName(sk, 'forearm_L'), sk));
  assert.equal(rows['parent'], 'upper_arm_L (' + byName(sk, 'upper_arm_L').id + ')');
  assert.equal(rows['ik chain'], 'arm_L');
  assert.equal(rows['mirror of'], 'forearm_R');
  assert.match(rows['angle'], /^-45\.0/);
  assert.equal(V.describeBone(byName(sk, 'root'), sk)[1][1], 'none (root)');
});

test('reportBones collects the bones named in issues', () => {
  const report = { issues: [{ bones: ['a', 'b'] }, { bones: ['b', 'c'] }, {}] };
  assert.deepEqual([...V.reportBones(report)].sort(), ['a', 'b', 'c']);
  assert.equal(V.reportBones(null).size, 0);
});

test('a spec name in a report also covers the built twins and chain segments', () => {
  const sk = { bones: [{ name: 'extra_horn_L' }, { name: 'extra_horn_R' }, { name: 'extra_cape_1' }, { name: 'extra_cape_2' }, { name: 'extra_hornet' }, { name: 'head' }] };
  const report = { issues: [{ bones: ['extra_horn'] }, { bones: ['extra_cape'] }, { bones: ['head'] }] };
  assert.deepEqual([...V.reportBones(report, sk)].sort(), ['extra_cape', 'extra_cape_1', 'extra_cape_2', 'extra_horn', 'extra_horn_L', 'extra_horn_R', 'head']);
  assert.ok(!V.reportBones(report, sk).has('extra_hornet'), 'a longer name is not a segment');
});

test('renderSvg rings the twins of a spec-named issue', () => {
  const sk = { schema_version: '1.0', height: 2, bones: [
    { id: 0, name: 'root', parent_id: -1, world_head: [0, 0], world_tail: [0, 0.05], depth: 0 },
    { id: 1, name: 'extra_horn_L', parent_id: 0, world_head: [0, 1], world_tail: [0, 1.2], depth: 0 },
    { id: 2, name: 'extra_horn_R', parent_id: 0, world_head: [0, 1], world_tail: [0, 1.2], depth: 0 }] };
  const svg = V.renderSvg({ skeleton: sk, report: { issues: [{ bones: ['extra_horn'] }] }, selected: null }, { cx: 0, cy: 1, zoom: 100 }, OPTS, SIZE);
  assert.equal((svg.match(/class="issue-ring"/g) || []).length, 2);
});

test('colours follow the chosen mode', () => {
  const range = { min: -1, max: 1 };
  assert.equal(V.colorFor({ name: 'thigh_L' }, 'side', range), 'var(--c-left)');
  assert.equal(V.colorFor({ name: 'extra_x' }, 'side', range), 'var(--c-extra)');
  assert.equal(V.colorFor({ name: 'hip', depth: 0 }, 'depth', range), 'var(--c-center)');
  assert.match(V.colorFor({ name: 'a', depth: 1 }, 'depth', range), /^hsl\(24/);
  assert.match(V.colorFor({ name: 'a', depth: -1 }, 'depth', range), /^hsl\(214/);
  assert.equal(V.colorFor({ name: 'a', ik_chain: 'arm_L' }, 'ik', range), V.IK_COLORS.arm_L);
  assert.equal(V.colorFor({ name: 'a', ik_chain: null }, 'ik', range), 'var(--c-none)');
});

test('fitView keeps every bone inside the viewport', () => {
  const sk = knight();
  const view = V.fitView(sk, SIZE, 56);
  const X = (x) => SIZE.w / 2 + (x - view.cx) * view.zoom;
  const Y = (y) => SIZE.h / 2 - (y - view.cy) * view.zoom;
  for (const b of sk.bones) for (const p of [b.world_head, b.world_tail]) {
    assert.ok(X(p[0]) >= 55 && X(p[0]) <= SIZE.w - 55 && Y(p[1]) >= 55 && Y(p[1]) <= SIZE.h - 55, b.name);
  }
});

test('gridStep grows as the view zooms out', () => {
  assert.ok(V.gridStep(400) < V.gridStep(100));
  assert.ok(V.gridStep(100) * 100 >= 56);
});

test('renderSvg draws one polygon per bone, in a valid svg', () => {
  const sk = elf();
  const svg = V.renderSvg(model(sk), V.fitView(sk, SIZE, 56), OPTS, SIZE);
  assert.match(svg, /^<svg [^>]*width="800" height="600"/);
  assert.equal(count(svg, /<polygon class="bone/g), sk.bones.length);
  assert.equal(count(svg, /<circle class="joint"/g), sk.bones.length);
  assert.ok(svg.includes('class="ground"') && svg.includes('class="height"'));
  assert.equal(count(svg, /class="label"/g), sk.bones.length);
});

test('options switch layers on and off', () => {
  const sk = elf(), view = V.fitView(sk, SIZE, 56);
  const extras = sk.bones.filter((b) => b.name.startsWith('extra_')).length;
  assert.equal(count(V.renderSvg(model(sk), view, { ...OPTS, extras: false }, SIZE), /<polygon class="bone/g), sk.bones.length - extras);
  assert.equal(count(V.renderSvg(model(sk), view, { ...OPTS, labels: false }, SIZE), /class="label"/g), 0);
  assert.equal(count(V.renderSvg(model(sk), view, { ...OPTS, joints: false }, SIZE), /class="joint"/g), 0);
  assert.equal(count(V.renderSvg(model(sk), view, { ...OPTS, grid: false }, SIZE), /class="grid"/g), 0);
  assert.equal(count(V.renderSvg(model(sk), view, OPTS, SIZE), /class="bounds"/g), 0);
  assert.equal(count(V.renderSvg(model(sk), view, { ...OPTS, bounds: true }, SIZE), /class="bounds"/g), 1);
  assert.equal(count(V.renderSvg(model(sk), view, { ...OPTS, links: false }, SIZE), /class="link"/g), 0);
  assert.equal(count(V.renderSvg(model(sk), view, OPTS, SIZE), /class="link"/g), V.linkGaps(sk).length);
});

test('the validator box spans x in [-H, H] and y in [0, 1.2 H]', () => {
  const sk = elf(), view = { cx: 0, cy: 1, zoom: 100 };
  const svg = V.renderSvg(model(sk), view, { ...OPTS, bounds: true }, SIZE);
  const m = svg.match(/<rect class="bounds" x="([\d.-]+)" y="([\d.-]+)" width="([\d.-]+)" height="([\d.-]+)"/);
  // x from X(-2) = 200, width 4 units = 400 px; y from Y(2.4) = 160, height 2.4 units = 240 px
  assert.deepEqual(m.slice(1).map(Number), [200, 160, 400, 240]);
});

test('a selection adds outlines and a label even when labels are off', () => {
  const sk = elf(), view = V.fitView(sk, SIZE, 56);
  const svg = V.renderSvg(model(sk, { selected: byName(sk, 'forearm_L').id }), view, { ...OPTS, labels: false }, SIZE);
  assert.equal(count(svg, /class="sel-outline"/g), 1);
  assert.equal(count(svg, /class="parent-outline"/g), 1);
  assert.equal(count(svg, /class="child-outline"/g), 1);
  assert.equal(count(svg, /class="label"/g), 1);
  assert.ok(svg.includes('>forearm_L</text>'));
});

test('bones named in the report get a red ring and the bad class', () => {
  const sk = elf(), view = V.fitView(sk, SIZE, 56);
  const report = { issues: [{ code: 'x', bones: ['hand_R'] }] };
  const svg = V.renderSvg(model(sk, { report }), view, OPTS, SIZE);
  assert.equal(count(svg, /class="issue-ring"/g), 1);
  assert.equal(count(svg, /class="bone bad"/g), 1);
});

test('face left mirrors the drawing across the centre line', () => {
  const sk = knight();
  const view = { cx: 0, cy: 1, zoom: 100 };
  const x = (opts) => Number(V.renderSvg(model(sk), view, opts, SIZE).match(/data-id="21" points="([\d.-]+),/)[1]);
  assert.ok(Math.abs(x(OPTS) + x({ ...OPTS, flip: true }) - SIZE.w) < 0.2);
});

test('bone names are escaped in the svg', () => {
  const sk = elf();
  sk.bones[1].name = 'hip<script>&"';
  const svg = V.renderSvg(model(sk), V.fitView(sk, SIZE, 56), OPTS, SIZE);
  assert.ok(!svg.includes('<script>'));
  assert.ok(svg.includes('hip&lt;script&gt;&amp;&quot;'));
});

test('labels of near and far limbs go to opposite sides in the side view', () => {
  const sk = knight(), view = V.fitView(sk, SIZE, 56);
  const svg = V.renderSvg(model(sk), view, OPTS, SIZE);
  const anchor = (name) => svg.match(new RegExp('text-anchor="(start|end)">' + name + '</text>'))[1];
  assert.equal(anchor('thigh_L'), 'start');
  assert.equal(anchor('thigh_R'), 'end');
});

test('depth colouring renders behind and in front limbs differently', () => {
  const sk = knight(), view = V.fitView(sk, SIZE, 56);
  const svg = V.renderSvg(model(sk), view, { ...OPTS, color: 'depth' }, SIZE);
  assert.ok(svg.includes('fill="hsl(24') && svg.includes('fill="hsl(214'));
});

// ---------- animation ----------

const TWO = () => ({
  height: 2, bones: [
    { id: 0, name: 'root', parent_id: -1, local_position: [0, 0], local_rotation_deg: 90, length: 1, world_head: [0, 0], world_tail: [0, 1] },
    { id: 1, name: 'arm', parent_id: 0, local_position: [1, 0], local_rotation_deg: -90, length: 0.5, world_head: [0, 1], world_tail: [0.5, 1] },
  ],
});
const clipOf = (rotations, extra) => Object.assign({ fps: 4, frame_count: 5, loop: true, ground_speed: 0, rotations, positions: {} }, extra);

test('classifyFile recognises an animation clip, and parseAnimation explains problems', () => {
  const clip = clipOf({ arm: [0, 1, 2, 1, 0] });
  assert.equal(V.classifyFile(JSON.stringify(clip)).kind, 'animation');
  assert.throws(() => V.parseAnimation('{"rotations": {}}'), /frame_count/);
  assert.throws(() => V.parseAnimation(JSON.stringify(clipOf({ arm: [0, 1] }))), /needs 5 frames/);
});

test('poseAt without a clip reproduces the skeleton', () => {
  for (const sk of [knight(), elf()]) {
    const posed = V.poseAt(sk, null, 0);
    sk.bones.forEach((b, i) => {
      for (const k of ['world_head', 'world_tail']) {
        assert.ok(Math.hypot(posed.bones[i][k][0] - b[k][0], posed.bones[i][k][1] - b[k][1]) < 5e-6, b.name + ' ' + k);
      }
    });
  }
});

test('poseAt applies the clip: rotations turn children with their parent, positions move them', () => {
  const clip = clipOf({ root: [90, 90, 180, 90, 90] }, { positions: { arm: [[1, 0], [0.5, 0], [1, 0], [1, 0], [1, 0]] } });
  const f1 = V.poseAt(TWO(), clip, 1).bones, f2 = V.poseAt(TWO(), clip, 2).bones;
  assert.deepEqual(f1[1].world_head.map((v) => +v.toFixed(9)), [0, 0.5]); // halfway up the root
  // root turned to point left: the arm (local -90) now points up, starting at (-1, 0)
  assert.deepEqual(f2[1].world_head.map((v) => +v.toFixed(9)), [-1, 0]);
  assert.deepEqual(f2[1].world_tail.map((v) => +v.toFixed(9)), [-1, 0.5]);
});

test('clipMismatch names bones the rig does not have', () => {
  assert.deepEqual(V.clipMismatch(clipOf({ arm: [0, 0, 0, 0, 0], tail: [0, 0, 0, 0, 0] }), TWO()), ['tail']);
});

test('frameAt loops over the frames before the closing key', () => {
  const clip = clipOf({});
  assert.deepEqual([0, 0.26, 0.5, 0.99, 1.0, 1.3].map((s) => V.frameAt(clip, s)), [0, 1, 2, 3, 0, 1]);
  assert.equal(V.frameAt(Object.assign(clipOf({}), { loop: false }), 10), 4);
});

test('onionFrames are distinct neighbours that wrap around the loop', () => {
  const clip = Object.assign(clipOf({}), { frame_count: 25 }); // 24-frame cycle, step 2
  assert.deepEqual(V.onionFrames(clip, 0, 2), [22, 2, 20, 4]);
  assert.ok(!V.onionFrames(clip, 5, 2).includes(5));
});

test('renderSvg draws onion-skin ghosts and moving ground marks', () => {
  const sk = knight(), view = V.fitView(sk, SIZE, 40);
  const plain = V.renderSvg(model(sk), view, OPTS, SIZE);
  assert.equal(count(plain, /class="ghost"/g), 0);
  assert.equal(count(plain, /class="ground-mark"/g), 0);
  const svg = V.renderSvg(model(sk, { ghosts: [sk, sk] }), view, Object.assign({}, OPTS, { groundShift: 0.13 }), SIZE);
  assert.equal(count(svg, /class="ghost"/g), 2 * sk.bones.length);
  assert.ok(count(svg, /class="ground-mark"/g) > 5);
  // the marks move with the shift
  const later = V.renderSvg(model(sk), view, Object.assign({}, OPTS, { groundShift: 0.2 }), SIZE);
  assert.notEqual(svg.match(/class="ground-mark"[^>]*/)[0], later.match(/class="ground-mark"[^>]*/)[0]);
});
