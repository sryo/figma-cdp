// How Figma renders a 3D transform, measured on a PNG export: what the capture import relies on
// when it turns a page's CSS into transform3d / scene3d (references/capture.md → Geometry & transforms).
//
//   python3 tests/probes/figma_probe.py --file <scratch-url> transform3d_render
//
// A red 100x200 rectangle in a white 400x400 frame; each check is the box around the red pixels,
// against the box CSS gives the same values, within a pixel.
const frame = figma.createFrame(); frame.resize(400, 400); pg.appendChild(frame);
frame.fills = [{ type: 'SOLID', color: { r: 1, g: 1, b: 1 } }];
const rect = figma.createRectangle(); frame.appendChild(rect); rect.resize(100, 200);
rect.fills = [{ type: 'SOLID', color: { r: 1, g: 0, b: 0 } }];
const T = (o) => Object.assign({ type: 'FIXED_ORDER', translateZ: 0, rotateX: 0, rotateY: 0, rotateZ: 0 }, o);
const place = (rel, t3, scene) => { rect.relativeTransform = rel; rect.transform3d = T(t3); frame.scene3d = scene || null; };
const red = async () => {
  const bmp = await createImageBitmap(new Blob([await frame.exportAsync({ format: 'PNG' })], { type: 'image/png' }));
  const g = new OffscreenCanvas(bmp.width, bmp.height).getContext('2d');
  g.drawImage(bmp, 0, 0);
  const d = g.getImageData(0, 0, bmp.width, bmp.height).data;
  let x0 = 1e9, y0 = 1e9, x1 = -1, y1 = -1;
  for (let y = 0; y < bmp.height; y++) for (let x = 0; x < bmp.width; x++) {
    const k = (y * bmp.width + x) * 4;
    if (d[k] > 200 && d[k + 1] < 90 && d[k + 2] < 90) { x0 = Math.min(x0, x); x1 = Math.max(x1, x + 1); y0 = Math.min(y0, y); y1 = Math.max(y1, y + 1); }
  }
  return [x0, y0, x1, y1];
};
const about = async (what, want) => { const got = await red(); check(what, true, got.every((v, k) => Math.abs(v - want[k]) <= 1.5) || got); };
const AT = [[1, 0, 150], [0, 1, 100]];

// rotateY(60deg) with no perspective: the width shrinks to cos 60 about the centre.
place(AT, { rotateY: 60 });
await about('no scene is an orthographic tilt', [175, 100, 225, 300]);
// The tilt is applied in the layer's own box, inside its 2D transform: a quarter turn makes the squeezed side the vertical one.
place([[0, -1, 300], [1, 0, 150]], { rotateY: 60 });
await about('the 2D transform applies after the tilt', [100, 175, 300, 225]);
// transformOrigin moves the axis and leaves the 2D placement alone.
place(AT, { rotateY: 60 });
rect.transformOrigin = { x: { unit: 'PIXELS', value: 0 }, y: { unit: 'PIXELS', value: 0 } };
check('transformOrigin leaves relativeTransform', AT, rect.relativeTransform);
await about('the tilt turns about transformOrigin', [150, 100, 200, 300]);
rect.transformOrigin = { x: { unit: 'PERCENT', value: 50 }, y: { unit: 'PERCENT', value: 50 } };
// perspective: the viewer faces the frame's centre, as CSS perspective-origin 50% 50%.
place(AT, { rotateY: 60 }, { perspective: 400, preserve3d: false });
await about('perspective at the centre', [172, 88, 222.6, 312]);
place([[1, 0, 250], [0, 1, 100]], { rotateY: 60 }, { perspective: 400, preserve3d: false });
await about('perspective looks from the frame centre', [284, 88, 313, 312]);
place([[1, 0, 250], [0, 1, 100]], { translateZ: 10, rotateX: 20, rotateY: 30, rotateZ: 40 }, { perspective: 400, preserve3d: false });
await about('the full order is CSS translateZ rotateX rotateY rotateZ', [213.7, 111, 366.6, 314.8]);
// A perspective of 0 is not "none": the render collapses. A very far viewer is the orthographic picture.
place(AT, { rotateY: 60 }, { perspective: 0, preserve3d: false });
check('perspective 0 is not orthographic', false, (await red()).every((v, k) => Math.abs(v - [175, 100, 225, 300][k]) <= 1.5));
place(AT, { rotateY: 60 }, { perspective: 1e6, preserve3d: false });
await about('a far perspective is orthographic', [175, 100, 225, 300]);
