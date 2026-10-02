// A stub Figma Plugin API for offline runs: the importer smoke run (tests/importer_stub.js),
// the perch stub's `figma` global when PERCH_STUB_FIGMA=full, and the eval seeds/scorers
// (tests/eval/offline_test.py). It records a node tree and enforces the rules of the real
// sandbox that scripts most often break: fonts loaded before fontName/characters, FILL
// sizing only inside an auto-layout parent, HUG only on auto-layout frames and text,
// ABSOLUTE positioning only inside auto layout, component properties added on and read from
// the set rather than a variant, and no removing the current page.
//
//   const { createFigma } = require('./figma_stub');
//   global.figma = createFigma();
'use strict';

const CONTAINERS = { DOCUMENT: 1, PAGE: 1, FRAME: 1, COMPONENT: 1, COMPONENT_SET: 1, INSTANCE: 1, GROUP: 1, SECTION: 1 };
const DEFAULT_NAME = { FRAME: 'Frame', TEXT: 'Text', RECTANGLE: 'Rectangle', ELLIPSE: 'Ellipse', COMPONENT: 'Component',
  COMPONENT_SET: 'Component set', INSTANCE: 'Instance', PAGE: 'Page', GROUP: 'Group', VECTOR: 'Vector', SECTION: 'Section' };
const solid = (r, g, b) => [{ type: 'SOLID', visible: true, opacity: 1, blendMode: 'NORMAL', color: { r, g, b } }];
const clone = (v) => (v === undefined ? v : JSON.parse(JSON.stringify(v)));

function createFigma() {
  let nextId = 1, propSeq = 1;
  const byId = {};
  const loadedFonts = {};
  const variables = {}, collections = {};
  const mixed = Symbol('mixed');
  let currentPage = null;
  const isAL = (n) => n && n.layoutMode && n.layoutMode !== 'NONE';

  function makeNode(type) {
    const id = (type === 'PAGE' || type === 'DOCUMENT' ? '0:' : '1:') + nextId++;
    const t = { id, type, name: DEFAULT_NAME[type] || type, parent: null, removed: false, visible: true,
      x: 0, y: 0, width: 100, height: 100, opacity: 1, rotation: 0,
      constraints: { horizontal: 'MIN', vertical: 'MIN' }, layoutPositioning: 'AUTO', layoutGrow: 0, layoutAlign: 'INHERIT',
      componentPropertyReferences: null, boundVariables: {}, fillStyleId: '', effects: [], strokes: [], strokeWeight: 1 };
    if (CONTAINERS[type]) t.children = [];
    if (type === 'FRAME' || type === 'COMPONENT' || type === 'COMPONENT_SET' || type === 'INSTANCE') {
      Object.assign(t, { layoutMode: 'NONE', itemSpacing: 0, paddingTop: 0, paddingRight: 0, paddingBottom: 0, paddingLeft: 0,
        primaryAxisSizingMode: 'AUTO', counterAxisSizingMode: 'AUTO', primaryAxisAlignItems: 'MIN', counterAxisAlignItems: 'MIN',
        layoutWrap: 'NO_WRAP', cornerRadius: 0, clipsContent: type !== 'COMPONENT_SET',
        fills: type === 'FRAME' ? solid(1, 1, 1) : [] });
      t._sizing = { h: 'FIXED', v: 'FIXED' };
    }
    if (type === 'TEXT') Object.assign(t, { characters: '', fontName: { family: 'Inter', style: 'Regular' }, fontSize: 12,
      textAutoResize: 'WIDTH_AND_HEIGHT', fills: solid(0, 0, 0), _sizing: { h: 'HUG', v: 'HUG' } });
    if (type === 'RECTANGLE' || type === 'ELLIPSE' || type === 'VECTOR') Object.assign(t, { fills: solid(0.85, 0.85, 0.85), cornerRadius: 0, _sizing: { h: 'FIXED', v: 'FIXED' } });
    if (type === 'COMPONENT' || type === 'COMPONENT_SET') t._props = {};
    if (type === 'PAGE') delete t.constraints;

    const api = {
      appendChild(c) { insert(proxy, c, t.children.length); },
      insertChild(i, c) { insert(proxy, c, i); },
      remove() {
        if (type === 'PAGE' && proxy === currentPage) throw new Error('Cannot remove the current page');
        if (t.parent) t.parent.children.splice(t.parent.children.indexOf(proxy), 1);
        markRemoved(proxy);
      },
      resize(w, h) { t.width = w; t.height = h; },
      resizeWithoutConstraints(w, h) { t.width = w; t.height = h; },
      rescale(s) { t.width *= s; t.height *= s; },
      findAll(fn) { const out = []; walk(proxy, (n) => { if (n !== proxy && (!fn || fn(n))) out.push(n); }); return out; },
      findOne(fn) { let hit = null; walk(proxy, (n) => { if (!hit && n !== proxy && fn(n)) hit = n; }); return hit; },
      findChildren(fn) { return t.children.filter((c) => !fn || fn(c)); },
      findAllWithCriteria(q) { return api.findAll((n) => !q.types || q.types.indexOf(n.type) !== -1); },
      getRangeAllFontNames() { return [t.fontName]; },
      setRangeFontName() {}, setRangeFontSize() {}, setRangeFills() {}, setRangeTextDecoration() {},
      setBoundVariable(field, v) { t.boundVariables[field] = v ? { type: 'VARIABLE_ALIAS', id: v.id } : undefined; },
      createInstance() {
        if (type !== 'COMPONENT') throw new Error('createInstance is only on components');
        const inst = makeNode('INSTANCE');
        copyInto(proxy, inst);
        inst._raw.name = t.name.indexOf('=') !== -1 && t.parent && t.parent.type === 'COMPONENT_SET' ? t.parent.name : t.name;
        inst._raw._main = proxy;
        if (currentPage) currentPage.appendChild(inst);
        return inst;
      },
      async getMainComponentAsync() { return t._main && !t._main.removed ? t._main : null; },
      detachInstance() {
        if (type !== 'INSTANCE') throw new Error('detachInstance is only on instances');
        t.type = 'FRAME'; t._main = null;
        return proxy;
      },
      addComponentProperty(name, ptype, def) {
        if (type === 'COMPONENT' && t.parent && t.parent.type === 'COMPONENT_SET') throw new Error('Cannot add properties to a variant; add them to the component set');
        if (!t._props) throw new Error('addComponentProperty is only on components and component sets');
        const key = ptype === 'VARIANT' ? name : name + '#' + (propSeq++) + ':0';
        t._props[key] = { type: ptype, defaultValue: def };
        return key;
      },
      setProperties(values) {
        if (type !== 'INSTANCE') throw new Error('setProperties is only on instances');
        const main = t._main;
        const set = main && main.parent && main.parent.type === 'COMPONENT_SET' ? main.parent : null;
        const variant = Object.assign({}, main ? main.variantProperties || {} : {});
        let swap = false;
        for (const k of Object.keys(values)) {
          if (set && k in variant) { variant[k] = values[k]; swap = true; continue; }
          t._overrides = t._overrides || {};
          t._overrides[k] = values[k];
        }
        if (swap) {
          const next = set.children.find((c) => Object.keys(variant).every((k) => (c.variantProperties || {})[k] === variant[k]));
          if (!next) throw new Error('No variant matches ' + JSON.stringify(variant));
          t._main = next;
        }
        for (const [k, v] of Object.entries(t._overrides || {})) {
          walk(proxy, (n) => { const r = n.componentPropertyReferences; if (r && r.characters === k) n._raw.characters = v; });
        }
      },
      clone() { const c = makeNode(type); copyInto(proxy, c); if (t.parent) insert(t.parent, c, t.parent.children.indexOf(proxy) + 1); return c; },
      async loadAsync() {},
    };

    const proxy = new Proxy(t, {
      get(target, k) {
        if (k === '_raw') return target;
        if (k in api) return api[k];
        if (k === 'layoutSizingHorizontal') return target._sizing ? target._sizing.h : undefined;
        if (k === 'layoutSizingVertical') return target._sizing ? target._sizing.v : undefined;
        if (k === 'mainComponent') return target._main || null;
        if (k === 'componentPropertyDefinitions') return defs(target);
        if (k === 'componentProperties' && target.type === 'INSTANCE') return instanceProps(target);
        if (k === 'variantProperties') return variantProps(target);
        if (k === 'isAsset' || k === 'key') return k === 'key' ? 'k' + target.id : false;
        return target[k];
      },
      set(target, k, v) {
        if (target.removed) throw new Error('The node with id "' + target.id + '" does not exist');
        if (target.type === 'TEXT') {
          if (k === 'fontName' && !loadedFonts[v.family + '/' + v.style]) throw new Error('fontName set before loadFontAsync: ' + JSON.stringify(v));
          if (k === 'characters' && !loadedFonts[target.fontName.family + '/' + target.fontName.style]) throw new Error('characters set before a loaded fontName');
          if ((k === 'fontSize' || k === 'textAutoResize') && !loadedFonts[target.fontName.family + '/' + target.fontName.style]) throw new Error(k + ' set before a loaded fontName');
        }
        if (k === 'layoutSizingHorizontal' || k === 'layoutSizingVertical') {
          if (v === 'FILL' && !isAL(target.parent)) throw new Error('FILL can only be set on children of auto-layout frames');
          if (v === 'HUG' && !(target.type === 'TEXT' || isAL(target))) throw new Error('HUG can only be set on auto-layout frames and text nodes');
          target._sizing = target._sizing || { h: 'FIXED', v: 'FIXED' };
          target._sizing[k === 'layoutSizingHorizontal' ? 'h' : 'v'] = v;
          return true;
        }
        if (k === 'layoutPositioning' && v === 'ABSOLUTE' && !isAL(target.parent)) throw new Error('ABSOLUTE positioning needs an auto-layout parent');
        if (k === 'layoutMode' && v !== 'NONE' && target._sizing && target.type !== 'TEXT') {
          target._sizing = { h: 'HUG', v: 'HUG' };
        }
        // The legacy sizing fields and layoutSizing* are two views of one state.
        if ((k === 'primaryAxisSizingMode' || k === 'counterAxisSizingMode') && isAL(target)) {
          const primaryIsH = target.layoutMode === 'HORIZONTAL';
          const axis = (k === 'primaryAxisSizingMode') === primaryIsH ? 'h' : 'v';
          target._sizing[axis] = v === 'AUTO' ? 'HUG' : 'FIXED';
        }
        if ((k === 'layoutGrow' || k === 'layoutAlign') && isAL(target.parent) && target._sizing) {
          const primaryIsH = target.parent.layoutMode === 'HORIZONTAL';
          const axis = (k === 'layoutGrow') === primaryIsH ? 'h' : 'v';
          if (k === 'layoutGrow' ? v > 0 : v === 'STRETCH') target._sizing[axis] = 'FILL';
        }
        if (k === 'fills' || k === 'strokes' || k === 'effects') v = clone(v);
        if (k === 'componentPropertyReferences') v = clone(v);
        target[k] = v;
        return true;
      },
    });
    byId[id] = proxy;
    return proxy;
  }

  function defs(t) {
    if (!t._props) return undefined;
    const out = {};
    if (t.type === 'COMPONENT_SET') {
      const axes = {};
      for (const c of t.children) for (const [k, v] of Object.entries(variantProps(c._raw) || {})) {
        axes[k] = axes[k] || [];
        if (axes[k].indexOf(v) === -1) axes[k].push(v);
      }
      for (const [k, vals] of Object.entries(axes)) out[k] = { type: 'VARIANT', defaultValue: vals[0], variantOptions: vals };
    }
    if (t.type === 'COMPONENT' && t.parent && t.parent.type === 'COMPONENT_SET') {
      throw new Error('Can only get definitions of a component set or non-variant component');
    }
    return Object.assign(out, clone(t._props));
  }
  function variantProps(t) {
    if (t.type === 'INSTANCE') return t._main ? variantProps(t._main._raw) : null;
    if (t.type !== 'COMPONENT' || !t.parent || t.parent.type !== 'COMPONENT_SET') return null;
    const out = {};
    t.name.split(',').forEach((pair) => {
      const i = pair.indexOf('=');
      if (i > 0) out[pair.slice(0, i).trim()] = pair.slice(i + 1).trim();
    });
    return out;
  }
  function instanceProps(t) {
    const out = {};
    const main = t._main;
    if (!main) return out;
    for (const [k, v] of Object.entries(variantProps(main._raw) || {})) out[k] = { type: 'VARIANT', value: v };
    const owner = main.parent && main.parent.type === 'COMPONENT_SET' ? main.parent : main;
    const d = owner.componentPropertyDefinitions || {};
    for (const [k, def] of Object.entries(d)) if (def.type !== 'VARIANT') {
      out[k] = { type: def.type, value: (t._overrides && k in t._overrides) ? t._overrides[k] : def.defaultValue };
    }
    return out;
  }
  function insert(parent, c, i) {
    if (c.removed) throw new Error('The node with id "' + c.id + '" does not exist');
    const raw = c._raw;
    if (raw.parent) raw.parent.children.splice(raw.parent.children.indexOf(c), 1);
    raw.parent = parent;
    parent._raw.children.splice(i, 0, c);
    if (raw._sizing && !isAL(parent) && raw._sizing.h === 'FILL') raw._sizing.h = 'FIXED';
    if (raw._sizing && !isAL(parent) && raw._sizing.v === 'FILL') raw._sizing.v = 'FIXED';
  }
  function markRemoved(n) { n._raw.removed = true; (n._raw.children || []).forEach(markRemoved); }
  function walk(n, fn) { fn(n); (n._raw.children || []).forEach((c) => walk(c, fn)); }
  function copyInto(src, dst) {
    const s = src._raw, d = dst._raw;
    for (const k of ['name', 'width', 'height', 'fills', 'strokes', 'effects', 'cornerRadius', 'layoutMode', 'itemSpacing',
      'paddingTop', 'paddingRight', 'paddingBottom', 'paddingLeft', 'characters', 'fontName', 'fontSize', 'textAutoResize',
      'constraints', 'layoutPositioning', 'boundVariables', 'componentPropertyReferences', 'primaryAxisAlignItems',
      'counterAxisAlignItems', 'opacity', 'visible']) if (k in s) d[k] = clone(s[k]);
    if (s._sizing) d._sizing = clone(s._sizing);
    for (const c of s.children || []) {
      const cc = makeNode(c.type === 'COMPONENT' ? 'FRAME' : c.type);
      copyInto(c, cc);
      if (c._raw._main) cc._raw._main = c._raw._main;
      cc._raw.parent = dst;
      d.children.push(cc);
    }
  }

  const root = makeNode('DOCUMENT');
  root._raw.name = 'Stub file';
  const firstPage = makeNode('PAGE');
  firstPage._raw.name = 'Page 1';
  insert(root, firstPage, 0);
  currentPage = firstPage;

  function create(type) {
    const n = makeNode(type);
    insert(currentPage, n, currentPage._raw.children.length);
    return n;
  }

  const figma = {
    mixed,
    root,
    get currentPage() { return currentPage; },
    set currentPage(p) { throw new Error('Setting figma.currentPage is not supported; use setCurrentPageAsync'); },
    async setCurrentPageAsync(p) { if (p.type !== 'PAGE' || p.removed) throw new Error('not a page'); currentPage = p; },
    async loadAllPagesAsync() {},
    async saveVersionHistoryAsync(title) { return { id: 'v' + nextId++, title }; },
    createPage() { const p = makeNode('PAGE'); insert(root, p, root._raw.children.length); return p; },
    createFrame: () => create('FRAME'),
    createComponent: () => create('COMPONENT'),
    createText: () => create('TEXT'),
    createRectangle: () => create('RECTANGLE'),
    createEllipse: () => create('ELLIPSE'),
    createComponentFromNode(n) {
      const c = makeNode('COMPONENT');
      copyInto(n, c);
      insert(n.parent, c, n.parent._raw.children.indexOf(n));
      n.remove();
      return c;
    },
    combineAsVariants(nodes, parent) {
      if (!nodes.length || nodes.some((n) => n.type !== 'COMPONENT')) throw new Error('combineAsVariants takes components');
      const set = makeNode('COMPONENT_SET');
      insert(parent, set, parent._raw.children.length);
      nodes.forEach((n) => insert(set, n, set._raw.children.length));
      return set;
    },
    createImage: (bytes) => { if (!(bytes instanceof Uint8Array)) throw new Error('createImage takes Uint8Array'); return { hash: 'h' + bytes.length }; },
    base64Decode: (s) => Uint8Array.from(Buffer.from(s, 'base64')),
    createNodeFromSvg: (svg) => { if (!/^\s*<svg/.test(svg)) throw new Error('bad svg'); const f = create('FRAME'); f.resize(24, 24); return f; },
    getNodeById() { throw new Error('getNodeById is not supported with documentAccess: dynamic-page; use getNodeByIdAsync'); },
    getNodeByIdAsync: async (id) => (byId[id] && !byId[id].removed ? byId[id] : null),
    // Every family loads except "Missing", so font fallback paths are exercised.
    loadFontAsync: async (f) => { if (f.family === 'Missing') throw new Error('font not found'); loadedFonts[f.family + '/' + f.style] = true; },
    async listAvailableFontsAsync() { return [{ fontName: { family: 'Inter', style: 'Regular' } }]; },
    getLocalPaintStylesAsync: async () => [],
    getLocalTextStylesAsync: async () => [],
    variables: {
      createVariableCollection(name) {
        const c = { id: 'VariableCollectionId:' + nextId++, name, modes: [{ modeId: 'm1', name: 'Mode 1' }], defaultModeId: 'm1', variableIds: [],
          remove() { this.variableIds.forEach((id) => delete variables[id]); delete collections[this.id]; } };
        collections[c.id] = c;
        return c;
      },
      createVariable(name, collection, type) {
        const c = typeof collection === 'string' ? collections[collection] : collection;
        const v = { id: 'VariableID:' + nextId++, name, resolvedType: type, variableCollectionId: c.id, valuesByMode: {},
          setValueForMode(m, val) { this.valuesByMode[m] = val; }, remove() { delete variables[this.id]; } };
        variables[v.id] = v;
        c.variableIds.push(v.id);
        return v;
      },
      getLocalVariablesAsync: async (type) => Object.values(variables).filter((v) => !type || v.resolvedType === type),
      getLocalVariableCollectionsAsync: async () => Object.values(collections),
      getVariableByIdAsync: async (id) => variables[id] || null,
      getVariableCollectionByIdAsync: async (id) => collections[id] || null,
      setBoundVariableForPaint(paint, field, v) {
        const p = clone(paint);
        p.boundVariables = Object.assign({}, p.boundVariables, { [field]: { type: 'VARIABLE_ALIAS', id: v.id } });
        if (v.valuesByMode.m1) { const c = v.valuesByMode.m1; p.color = { r: c.r, g: c.g, b: c.b }; }
        return p;
      },
    },
  };
  return figma;
}

module.exports = { createFigma };
