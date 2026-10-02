// Login screen built from the seeded Button set and Input: instances of both, no new
// button/input components, copy and colors from the source.
var pages = evalPages();
var page = await targetPage();
var nodes = screenNodes(page);
var used = await instancesOf([page], [EVAL.seed.buttonSetId, EVAL.seed.inputId]);
var buttons = used.filter(function (u) { return u.set && u.set.id === EVAL.seed.buttonSetId; }).length;
var inputs = used.filter(function (u) { return u.main.id === EVAL.seed.inputId; }).length;
var seeded = {};
seeded[EVAL.seed.buttonSetId] = 1; seeded[EVAL.seed.inputId] = 1;
var dupes = nodesOf(pages).filter(function (n) {
  if (seeded[n.id] || (n.parent && seeded[n.parent.id])) return false;
  if (n.type !== 'COMPONENT_SET' && n.type !== 'COMPONENT') return false;
  return /button|input|field/.test(baseName(n.name));
}).length;
var colors = colorMatch(EVAL.expect.login.colors, page.findAll());
var m = Object.assign(await quality(pages), {
  buttonInstances: buttons,
  inputInstances: inputs,
  newDuplicateComponents: dupes,
  copy: copyMatch(EVAL.expect.login.copy, nodes),
  onPalette: colors.onPalette,
  tokensUsed: colors.tokensUsed,
});
return {
  metrics: m,
  lower: QUALITY_LOWER.concat(['newDuplicateComponents']),
  passed: buttons >= 2 && inputs >= 2 && dupes === 0 && m.copy >= 0.9 && m.onPalette >= 0.9,
};
