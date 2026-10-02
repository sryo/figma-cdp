// A "Main" frame that already carries an inner shadow, which adding a drop shadow must keep.
var page = await targetPage();
var main = mkFrame(page, 'Main', 'NONE', { fill: 'surface' });
main.resize(800, 600);
main.effects = [{ type: 'INNER_SHADOW', color: { r: 0, g: 0, b: 0, a: 0.1 }, offset: { x: 0, y: 1 }, radius: 2, spread: 0,
  visible: true, blendMode: 'NORMAL' }];
return { mainId: main.id };
