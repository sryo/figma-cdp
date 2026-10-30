// A case's rebuild seed: the subtree under SNAP_ID as plain JSON that tests/cases/rebuild.js
// rebuilds on any file (the scratch file, or the stub). Journal scripts name the user file's node
// ids, so they can't be replayed elsewhere; a seed can. Node ids become seed ids s1, s2, … in
// depth-first order, and a reaction or instance pointing outside the subtree keeps only the
// target's name ("ext:<name>"), which rebuild drops or turns into a frame.
//
//   python3 tests/cases/case.py snapshot <case> --node <id> --file <url>
//   python3 figma_run.py --file <url> -e "const SNAP_ID = '12:34', SNAP_MAX = 500; $(cat tests/cases/snapshot.js)"
//
// Kept: type, name, geometry, auto layout, fills/strokes/effects, text and its fonts, reactions,
// instance → main component, variants. Not kept: style and variable bindings, image bytes (the
// hash only works in the same file), instance overrides, plugin data. Mixed text styles come back
// as segments when the API offers getStyledTextSegments.
const MAX = typeof SNAP_MAX === 'number' ? SNAP_MAX : 2000;
const PROPS = ['name', 'visible', 'opacity', 'x', 'y', 'width', 'height', 'rotation', 'blendMode', 'constraints',
  'layoutPositioning', 'layoutSizingHorizontal', 'layoutSizingVertical', 'fills', 'strokes', 'strokeWeight', 'strokeAlign',
  'cornerRadius', 'effects', 'clipsContent', 'layoutMode', 'layoutWrap', 'itemSpacing', 'counterAxisSpacing',
  'paddingTop', 'paddingRight', 'paddingBottom', 'paddingLeft', 'primaryAxisAlignItems', 'counterAxisAlignItems',
  'primaryAxisSizingMode', 'counterAxisSizingMode', 'fontName', 'fontSize', 'lineHeight', 'letterSpacing',
  'textAlignHorizontal', 'textAlignVertical', 'textAutoResize', 'textCase', 'textDecoration', 'characters'];
const SEGMENT = ['fontName', 'fontSize', 'fills', 'lineHeight', 'letterSpacing', 'textCase', 'textDecoration'];
const root = typeof SNAP_ID === 'string' ? await figma.getNodeByIdAsync(SNAP_ID) : SNAP_ID;
if (!root) throw new Error('snapshot: no node ' + SNAP_ID);
const sid = new Map(), mains = [], reacts = [];
let count = 0, truncated = false;
const plain = (v) => JSON.parse(JSON.stringify(v));
async function walk(n) {
  const out = { sid: 's' + (sid.size + 1), type: n.type, props: {} };
  sid.set(n.id, out.sid);
  count++;
  for (const k of PROPS) {
    let v;
    try { v = n[k]; } catch (e) { continue; }
    if (v === undefined || typeof v === 'function') continue;
    if (v === figma.mixed) { (out.mixed = out.mixed || []).push(k); continue; }
    out.props[k] = plain(v);
  }
  if (out.mixed && n.type === 'TEXT' && n.getStyledTextSegments) {
    out.segments = n.getStyledTextSegments(SEGMENT.filter((k) => out.mixed.includes(k))).map(plain);
  }
  if (n.type === 'INSTANCE') {
    const main = await n.getMainComponentAsync();
    if (main) mains.push([out, main]);
    // An instance reads its main component's reactions until it has its own (even an empty list).
    if (!main || JSON.stringify(n.reactions) !== JSON.stringify(main.reactions)) reacts.push([out, n.reactions || []]);
    return out;
  }
  if (n.reactions && n.reactions.length) reacts.push([out, n.reactions]);
  if (n.type === 'PAGE' && n.flowStartingPoints && n.flowStartingPoints.length) out.flow = plain(n.flowStartingPoints);
  if (n.children) {
    out.children = [];
    for (const c of n.children) {
      if (count >= MAX) { truncated = true; break; }
      out.children.push(await walk(c));
    }
  }
  return out;
}
const ref = (id, name) => sid.get(id) || 'ext:' + name;
const seed = await walk(root);
for (const [out, main] of mains) out.main = ref(main.id, main.name);
for (const [out, rs] of reacts) {
  out.reactions = [];
  for (const r of plain(rs)) {
    // The API fills the legacy `action` beside `actions` and refuses a reaction that sets both.
    if (r.actions) delete r.action;
    for (const a of r.actions || (r.action ? [r.action] : [])) {
      if (a.destinationId) {
        const d = await figma.getNodeByIdAsync(a.destinationId);
        a.destinationId = ref(a.destinationId, d ? d.name : '?');
      }
    }
    out.reactions.push(r);
  }
}
if (seed.flow) seed.flow = seed.flow.map((f) => ({ nodeId: ref(f.nodeId, '?'), name: f.name }));
return { seed: 1, nodes: count, truncated, root: seed };
