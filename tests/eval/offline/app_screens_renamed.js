// The good build with every layer renamed to Figma's defaults: the scorer reads structure and
// strings, not names, so the component metrics must not move.
// include: offline/harbor_kit.js
var S = EVAL.expect.screens, screens = [S.dashboard, S.customers, S.invoice];
var kit = await harborKit({ comps: ['Icon', 'Avatar', 'Badge', 'Button', 'Tab', 'Input', 'Tabs', 'ListItem', 'StatCard', 'AppHeader', 'Card'],
  autoLayout: true, sizing: true, bind: true, names: true }).init(screens);
screens.forEach(function (s, i) { kit.screen(s, i * 1400); });
var page = await targetPage();
page.findAll().forEach(function (n) {
  if (n.type === 'COMPONENT' && n.parent && n.parent.type === 'COMPONENT_SET') return;  // variant names carry the values
  n.name = { TEXT: 'Text', INSTANCE: 'Instance', COMPONENT: 'Component', COMPONENT_SET: 'Component' }[n.type] || 'Frame';
});
return { ok: true };
