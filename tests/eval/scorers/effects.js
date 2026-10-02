// A visible drop shadow added to the seeded frame itself, its inner shadow kept.
var page = await targetPage();
var main = await figma.getNodeByIdAsync(EVAL.seed.mainId);
var fx = main ? main.effects : [];
var m = {
  dropShadow: fx.some(function (e) { return e.type === 'DROP_SHADOW' && e.visible !== false && e.radius > 0; }) ? 1 : 0,
  effectsKept: fx.some(function (e) { return e.type === 'INNER_SHADOW'; }) ? 1 : 0,
  newTopLevel: page.children.filter(function (n) { return n.id !== EVAL.seed.mainId; }).length,
};
return { metrics: m, lower: ['newTopLevel'], passed: m.dropShadow === 1 && m.effectsKept === 1 && m.newTopLevel === 0 };
