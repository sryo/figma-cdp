// The drifted login screen, edited in place: each of the three diffs fixed, the seeded node
// ids still there, nothing rebuilt beside it.
var page = await targetPage();
var root = await figma.getNodeByIdAsync(EVAL.seed.rootId);
var heading = await figma.getNodeByIdAsync(EVAL.seed.headingId);
var primary = await figma.getNodeByIdAsync(EVAL.seed.primaryId);
var kept = 0;
for (var i = 0; i < EVAL.seed.ids.length; i++) if (await figma.getNodeByIdAsync(EVAL.seed.ids[i])) kept++;
var scope = root ? [root].concat(root.findAll()) : [];
var fill = primary ? solidPaints(primary)[0] : null;
var m = {
  copyFixed: heading && norm(heading.characters) === norm('Welcome back to Lumen') ? 1 : 0,
  fontKept: heading && heading.fontName !== figma.mixed && heading.fontName.style === 'Bold' && heading.fontSize === 28 &&
    !heading.hasMissingFont ? 1 : 0,
  colorFixed: fill && near(toHex(fill.color), EVAL.expect.colors.primary) ? 1 : 0,
  missingAdded: copyMatch(['Forgot your passphrase?'], scope),
  idsPreserved: share(kept, EVAL.seed.ids.length),
  newTopLevel: page.children.filter(function (n) { return n.id !== EVAL.seed.rootId; }).length,
  copy: copyMatch(EVAL.expect.login.copy, scope),
  defaultNames: scope.filter(function (n) { return DEFAULT_NAME.test(n.name); }).length,
};
return {
  metrics: m,
  lower: ['newTopLevel', 'defaultNames'],
  passed: m.copyFixed === 1 && m.fontKept === 1 && m.colorFixed === 1 && m.missingAdded === 1 && m.idsPreserved >= 0.95 && m.newTopLevel === 0,
};
