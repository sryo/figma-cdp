// Which ways of painting an SVG shape createNodeFromSvg understands. The capture walker serializes
// inline SVG markup as the page has it, so a paint that only resolves against the page (a CSS
// variable, currentColor, a stylesheet rule) must be resolved before import if Figma can't.
//
//   python3 tests/probes/figma_probe.py --file <scratch-url> svg_paint
//
// Each form paints a 10×10 square red; `works` means the imported vector is red, `ignored` that it
// came out another color or unpainted (the error field says which), `throws` that it didn't parse.
const RED = '#ff0000';
const forms = {
  'createNodeFromSvg(fill attribute hex)': `<path d="M0 0H10V10H0Z" fill="${RED}"/>`,
  'createNodeFromSvg(fill attribute rgb())': '<path d="M0 0H10V10H0Z" fill="rgb(255, 0, 0)"/>',
  'createNodeFromSvg(style fill)': `<path d="M0 0H10V10H0Z" style="fill:${RED}"/>`,
  'createNodeFromSvg(stylesheet class)': `<style>.a{fill:${RED}}</style><path class="a" d="M0 0H10V10H0Z"/>`,
  'createNodeFromSvg(currentColor from color attribute)': `<g color="${RED}"><path d="M0 0H10V10H0Z" fill="currentColor"/></g>`,
  'createNodeFromSvg(var() with a fallback)': `<path d="M0 0H10V10H0Z" fill="var(--c, ${RED})"/>`,
  'createNodeFromSvg(var() defined on the svg)': `<path d="M0 0H10V10H0Z" style="--c:${RED};fill:var(--c)"/>`,
  'createNodeFromSvg(var() defined only on the page)': '<path d="M0 0H10V10H0Z" fill="var(--page-only)"/>',
  'createNodeFromSvg(color(srgb))': '<path d="M0 0H10V10H0Z" fill="color(srgb 1 0 0)"/>',
  'createNodeFromSvg(rgba() with alpha)': '<path d="M0 0H10V10H0Z" fill="rgba(255, 0, 0, 0.5)"/>',
  'createNodeFromSvg(baked style with opacity)': '<path d="M0 0H10V10H0Z" style="fill: rgb(255, 0, 0); fill-opacity: 0.5; stroke: none;"/>',
  'createNodeFromSvg(stroke currentColor)': `<g color="${RED}"><path d="M0 0H10V10H0Z" fill="none" stroke="currentColor"/></g>`,
};
const hex = (c) => '#' + [c.r, c.g, c.b].map((v) => Math.round(v * 255).toString(16).padStart(2, '0')).join('');
for (const [member, inner] of Object.entries(forms)) {
  let node;
  try {
    node = figma.createNodeFromSvg(`<svg xmlns="http://www.w3.org/2000/svg" width="10" height="10" viewBox="0 0 10 10">${inner}</svg>`);
  } catch (e) { limit(member, 'throws', e); continue; }
  pg.appendChild(node);
  const shape = node.findOne((n) => n.type === 'VECTOR');
  const paints = shape ? (/stroke/.test(member) ? shape.strokes : shape.fills) : [];
  const solid = paints.find((p) => p.type === 'SOLID' && p.visible !== false);
  const got = solid ? hex(solid.color) : shape ? 'unpainted' : 'no vector';
  if (got === RED && /alpha|opacity/.test(member) && Math.abs((solid.opacity === undefined ? 1 : solid.opacity) - 0.5) > 0.01) limit(member, 'ignored', 'opacity ' + solid.opacity);
  else if (got === RED) limit(member, 'works');
  else limit(member, 'ignored', got);
}
