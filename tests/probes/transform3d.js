// 3D transforms on the real Plugin API. The typings (1.142.0) have none of these members; the
// runtime does (runtime_surface, 2026-11-12), and its validation errors name the shapes.
//
//   python3 tests/probes/figma_probe.py --file <scratch-url> transform3d
//
// transform3d: {type:'NONE'} | {type:'FIXED_ORDER', translateZ, rotateX, rotateY, rotateZ,
// backfaceVisible?, visible?} on every layer. scene3d: null | {perspective, preserve3d, visible?}
// on frames, components and instances. transformOrigin: {x, y}, each {unit:'PERCENT'|'PIXELS', value}.
const near = (a, b) => Math.abs(a - b) < 1e-3;
const frame = figma.createFrame(); frame.resize(200, 200); pg.appendChild(frame);
const rect = figma.createRectangle(); frame.appendChild(rect); rect.x = 50; rect.y = 50;
const T = (o) => Object.assign({ type: 'FIXED_ORDER', translateZ: 0, rotateX: 0, rotateY: 0, rotateZ: 0 }, o);

check('defaults', [{ type: 'NONE' }, null, { x: { unit: 'PERCENT', value: 50 }, y: { unit: 'PERCENT', value: 50 } }],
  [rect.transform3d, frame.scene3d, rect.transformOrigin]);
check('scene3d only on frame-likes', [false, false], ['scene3d' in rect, 'scene3d' in figma.group([figma.createRectangle()], pg)]);

const flat = { rot: rect.rotation, rel: rect.relativeTransform, box: rect.absoluteBoundingBox, render: rect.absoluteRenderBounds };
try {
  rect.transform3d = T({ translateZ: 25, rotateX: 10, rotateY: 20, rotateZ: 30 });
  const t = rect.transform3d;
  check('transform3d readback', ['FIXED_ORDER', true, true, true, true, true, true],
    [t.type, near(t.translateZ, 25), near(t.rotateX, 10), near(t.rotateY, 20), near(t.rotateZ, 30), t.backfaceVisible, t.visible]);
  limit('SceneNode.transform3d', 'works');
} catch (e) { limit('SceneNode.transform3d', 'refused', e); }
check('2D geometry is untouched', flat, { rot: rect.rotation, rel: rect.relativeTransform, box: rect.absoluteBoundingBox, render: rect.absoluteRenderBounds });
rect.rotation = 45;
check('rotation is not rotateZ', [true, true], [near(rect.rotation, 45), near(rect.transform3d.rotateZ, 30)]);
rect.rotation = 0;

try {
  rect.transformOrigin = { x: { unit: 'PERCENT', value: 0 }, y: { unit: 'PIXELS', value: 12 } };
  check('transformOrigin readback', { x: { unit: 'PERCENT', value: 0 }, y: { unit: 'PIXELS', value: 12 } }, rect.transformOrigin);
  limit('SceneNode.transformOrigin', 'works');
} catch (e) { limit('SceneNode.transformOrigin', 'refused', e); }

try {
  frame.scene3d = { perspective: 500, preserve3d: true };
  check('scene3d readback', { perspective: 500, preserve3d: true, visible: true }, frame.scene3d);
  limit('FrameNode.scene3d', 'works');
} catch (e) { limit('FrameNode.scene3d', 'refused', e); }
check('preserve3d leaves the frame as it was', [true, 1, [true]], [frame.clipsContent, frame.opacity, frame.fills.map((p) => p.visible)]);

// getCSSAsync shows the order Figma applies: translateZ, then rotateX, rotateY, rotateZ.
check('layer css', ['translateZ(25px) rotateX(10deg) rotateY(20deg) rotateZ(30deg)', '0% 12px'],
  await rect.getCSSAsync().then((c) => [c.transform, c['transform-origin']]));
check('frame css', ['500px', 'preserve-3d'], await frame.getCSSAsync().then((c) => [c.perspective, c['transform-style']]));
rect.transform3d = T({ rotateY: 20, backfaceVisible: false });
check('backface css', 'hidden', (await rect.getCSSAsync())['backface-visibility']);

// A PNG export renders the tilt and the perspective.
const size = async () => (await frame.exportAsync({ format: 'PNG' })).length;
rect.fills = [{ type: 'SOLID', color: { r: 1, g: 0, b: 0 } }];
rect.transform3d = { type: 'NONE' }; frame.scene3d = null;
const plain = await size();
rect.transform3d = T({ rotateY: 60 }); frame.scene3d = { perspective: 300, preserve3d: false };
if (await size() === plain) limit('exportAsync(3D)', 'ignored', 'the export is the flat one'); else limit('exportAsync(3D)', 'works');

for (const [member, make] of [['TextNode.transform3d', () => figma.createText()], ['ComponentNode.transform3d', () => figma.createComponent()]]) {
  const n = make(); pg.appendChild(n);
  try { n.transform3d = T({ rotateX: 10 }); limit(member, n.transform3d.type === 'FIXED_ORDER' ? 'works' : 'ignored'); } catch (e) { limit(member, 'refused', e); }
}
const main = figma.createComponent(); pg.appendChild(main); main.transform3d = T({ rotateX: 10 });
check('an instance starts from its main', true, near(main.createInstance().transform3d.rotateX, 10));

await refuses('transform3d needs a type', () => { rect.transform3d = { rotateX: 10 }; }, /Expected \.type to be one of the following: NONE, FIXED_ORDER/);
await refuses('FIXED_ORDER needs all four numbers', () => { rect.transform3d = { type: 'FIXED_ORDER', rotateX: 10 }; }, /Required value missing at \.translateZ/);
await refuses('transform3d takes no other key', () => { rect.transform3d = T({ depth: 5 }); }, /Unrecognized key: "depth"/);
await refuses('scene3d needs both fields', () => { frame.scene3d = { perspective: 500 }; }, /Required value missing at \.preserve3d/);
await refuses('transformOrigin takes unit objects', () => { rect.transformOrigin = { x: 0, y: 0 }; }, /Expected object, received number at \.x/);

// The Motion keyframe fields for 3D, also outside the typings' KeyframePropertyFieldName.
const key = (v, at) => ({ timelinePosition: at, value: { type: 'FLOAT', value: v } });
for (const [name, node] of [['TRANSFORM_3D_ROTATION_X', rect], ['TRANSFORM_3D_ROTATION_Y', rect], ['TRANSFORM_3D_ROTATION_Z', rect],
  ['TRANSFORM_3D_TRANSLATION_Z', rect], ['SCENE_3D_PERSPECTIVE', frame]]) {
  try {
    node.applyManualKeyframeTrack({ type: 'PROPERTY', name }, { keyframes: [key(0, 0), key(180, 1)] });
    const kf = (node.manualKeyframeTracks[name] || { keyframes: [] }).keyframes;
    limit('KeyframeField.' + name, kf.length === 2 && near(kf[1].value.value, 180) ? 'works' : 'ignored');
  } catch (e) { limit('KeyframeField.' + name, 'refused', e); }
}
