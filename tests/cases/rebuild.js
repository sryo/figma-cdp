// Rebuilds a tests/cases/snapshot.js seed under PARENT_ID (default: the current page) and returns
// {root, ids: {sid: newId}, dropped}. A seed whose root is a page rebuilds that page's children
// and flow starting points into the parent page. An instance of a component outside the seed comes
// back as a frame, and a reaction to a node outside it is dropped; both are listed in dropped.
//
//   python3 figma_run.py --file <scratch-url> -e "const SEED = $(cat seed.json); $(cat tests/cases/rebuild.js)"
const parent = typeof PARENT_ID === 'string' ? await figma.getNodeByIdAsync(PARENT_ID) : (typeof PARENT_ID === 'object' && PARENT_ID) || figma.currentPage;
const seed = JSON.parse(JSON.stringify(SEED.root || SEED));
const made = {}, dropped = [], later = [];
const AL = ['layoutMode', 'layoutWrap', 'itemSpacing', 'counterAxisSpacing', 'paddingTop', 'paddingRight', 'paddingBottom',
  'paddingLeft', 'primaryAxisAlignItems', 'counterAxisAlignItems'];
const LOOK = ['name', 'visible', 'opacity', 'rotation', 'blendMode', 'constraints', 'fills', 'strokes', 'strokeWeight', 'strokeAlign',
  'cornerRadius', 'effects', 'clipsContent'];
const TEXT = ['fontSize', 'lineHeight', 'letterSpacing', 'textAlignHorizontal', 'textAlignVertical', 'textCase', 'textDecoration'];
const CREATE = { FRAME: 'createFrame', COMPONENT: 'createComponent', TEXT: 'createText', RECTANGLE: 'createRectangle',
  ELLIPSE: 'createEllipse', LINE: 'createLine', POLYGON: 'createPolygon', STAR: 'createStar', VECTOR: 'createVector', SECTION: 'createSection' };
const isAL = (n) => n && n.layoutMode && n.layoutMode !== 'NONE';
const set = (n, k, v) => { if (v !== undefined) try { n[k] = v; } catch (e) { dropped.push(n.name + '.' + k + ': ' + String(e.message || e)); } };

async function fonts(s) {
  const all = [s.props.fontName].concat((s.segments || []).map((g) => g.fontName)).filter(Boolean);
  for (const f of all) await figma.loadFontAsync(f);
}

// A node's own look and auto layout, before its children; geometry and sizing after them, so a
// HUG frame sizes around its children and a FILL child sees its parent's layout.
async function look(n, s) {
  const p = s.props;
  for (const k of LOOK) set(n, k, p[k]);
  for (const k of AL) set(n, k, p[k]);
  if (s.type === 'TEXT') {
    await fonts(s);
    set(n, 'fontName', p.fontName);
    for (const k of TEXT) set(n, k, p[k]);
    set(n, 'characters', p.characters);
    for (const g of s.segments || []) {
      for (const k of Object.keys(g)) {
        const fn = 'setRange' + k[0].toUpperCase() + k.slice(1);
        if (n[fn] && k !== 'characters' && k !== 'start' && k !== 'end') try { n[fn](g.start, g.end, g[k]); } catch (e) { dropped.push(n.name + ' ' + fn); }
      }
    }
  }
}

function place(n, s, up) {
  const p = s.props;
  const free = !isAL(up) || p.layoutPositioning === 'ABSOLUTE';
  if (p.layoutPositioning === 'ABSOLUTE') set(n, 'layoutPositioning', 'ABSOLUTE');
  const hugText = s.type === 'TEXT' && p.textAutoResize === 'WIDTH_AND_HEIGHT';
  if (!hugText && p.width !== undefined && n.resize) try { n.resize(Math.max(p.width, 0.01), Math.max(p.height, 0.01)); } catch (e) { dropped.push(n.name + ' resize'); }
  if (s.type === 'TEXT') set(n, 'textAutoResize', p.textAutoResize);
  for (const k of ['primaryAxisSizingMode', 'counterAxisSizingMode']) if (isAL(n)) set(n, k, p[k]);
  for (const k of ['layoutSizingHorizontal', 'layoutSizingVertical']) {
    const v = p[k];
    if (v && (v !== 'FIXED' || isAL(n) || isAL(up)) && !(v === 'FILL' && !isAL(up))) set(n, k, v);
  }
  if (free) { set(n, 'x', p.x); set(n, 'y', p.y); }
}

async function build(s, up) {
  let n;
  if (s.type === 'INSTANCE' && made[s.main]) n = made[s.main].createInstance();
  else if (s.type === 'INSTANCE') {
    n = figma.createFrame();
    if (/^s\d+$/.test(s.main || '')) later.push([n, s, up]);
    else dropped.push('instance ' + s.props.name + ' of ' + s.main + ' became a frame');
  } else if (s.type === 'COMPONENT_SET') {
    const holder = figma.createFrame();
    up.appendChild(holder);
    const comps = [];
    for (const c of s.children || []) comps.push(await build(c, holder));
    n = figma.combineAsVariants(comps, up);
    holder.remove();
  } else if (s.type === 'GROUP') {
    // A group can't exist empty: build its children in place, then group them.
    const kids = [];
    for (const c of s.children || []) kids.push(await build(c, up));
    n = figma.group(kids, up);
  } else if (CREATE[s.type] && figma[CREATE[s.type]]) n = figma[CREATE[s.type]]();
  else { n = figma.createFrame(); dropped.push(s.type + ' ' + s.props.name + ' became a frame'); }
  made[s.sid] = n;
  if (n.parent !== up && s.type !== 'COMPONENT_SET' && s.type !== 'GROUP') up.appendChild(n);
  await look(n, s);
  if (s.children && s.type !== 'COMPONENT_SET' && s.type !== 'GROUP') for (const c of s.children) await build(c, n);
  place(n, s, up);
  return n;
}

let top;
if (seed.type === 'PAGE') {
  for (const c of seed.children || []) await build(c, parent);
  top = parent;
} else top = await build(seed, parent);

// Instances whose main component came later in the tree than they did.
for (const [stand, s, up] of later) {
  const n = made[s.main].createInstance();
  up.insertChild(up.children.indexOf(stand), n);
  stand.remove();
  made[s.sid] = n;
  await look(n, s);
  place(n, s, up);
}

const walk = (s, f) => { f(s); (s.children || []).forEach((c) => walk(c, f)); };
const wiring = [];
walk(seed, (s) => { if (s.reactions) wiring.push(s); });
for (const s of wiring) {
  const rs = [];
  for (const r of s.reactions) {
    let ok = true;
    for (const a of r.actions || (r.action ? [r.action] : [])) {
      if (!a.destinationId) continue;
      if (made[a.destinationId]) a.destinationId = made[a.destinationId].id;
      else ok = false;
    }
    if (ok) rs.push(r);
    else dropped.push('reaction on ' + s.props.name + ' to a node outside the seed');
  }
  try { await made[s.sid].setReactionsAsync(rs); } catch (e) { dropped.push('reactions on ' + s.props.name + ': ' + String(e.message || e)); }
}
if (seed.type === 'PAGE' && seed.flow) {
  parent.flowStartingPoints = seed.flow.filter((f) => made[f.nodeId]).map((f) => ({ nodeId: made[f.nodeId].id, name: f.name }));
}
const ids = {};
for (const k of Object.keys(made)) ids[k] = made[k].id;
return { root: top.id, ids, dropped };
