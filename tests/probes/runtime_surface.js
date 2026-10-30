// The members the live Plugin API has on the objects a probe can make, without reading any of
// them (a getter that throws can't break the walk). `figma_api.mjs runtime` diffs the result
// against the typings: members the typings lack are leads for api-unknown, typed members the
// runtime lacks are a typings bump not yet shipped (or one the file's editor doesn't have).
//
//   python3 tests/probes/figma_probe.py --file <scratch-url> --out <dir> runtime_surface
//   node tests/api/figma_api.mjs runtime <dir>/runtime_surface.json
const made = { PluginAPI: figma, VariablesAPI: figma.variables, PageNode: pg };
for (const [iface, create] of [['FrameNode', 'createFrame'], ['TextNode', 'createText'], ['RectangleNode', 'createRectangle'],
  ['EllipseNode', 'createEllipse'], ['ComponentNode', 'createComponent']]) {
  made[iface] = figma[create]();
  pg.appendChild(made[iface]);
}
made.InstanceNode = made.ComponentNode.createInstance();
pg.appendChild(made.InstanceNode);
for (const [iface, obj] of Object.entries(made)) {
  const members = {};
  for (let o = obj; o && o !== Object.prototype; o = Object.getPrototypeOf(o)) {
    for (const k of Object.getOwnPropertyNames(o)) {
      if (k in members || k === 'constructor' || k.startsWith('_')) continue;
      const d = Object.getOwnPropertyDescriptor(o, k);
      members[k] = typeof d.value === 'function' ? 'method' : d.get && !d.set ? 'ro' : 'prop';
    }
  }
  note(iface, members);
}
