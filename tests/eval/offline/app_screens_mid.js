// A typical half-way build: rows, badges, buttons, cards and the header are components, but the
// Avatar is drawn inside the ListItem component instead of instanced, Inputs and Tabs are plain
// frames, the Badge set covers two of four tones and is duplicated on one screen, sizing is
// left at the defaults, colors are hex, two strings are missing and one is made up.
// include: offline/harbor_kit.js
var S = EVAL.expect.screens, screens = [S.dashboard, S.customers, S.invoice];
var kit = await harborKit({ comps: ['Icon', 'Badge', 'Button', 'ListItem', 'StatCard', 'AppHeader', 'Card'],
  values: { Badge: ['success', 'danger'] }, split: ['Badge'], autoLayout: true, sizing: false, bind: false, names: true,
  drop: ['Lifetime value', '$18,400'], invent: ['Lorem ipsum dolor sit amet'] }).init(screens);
screens.forEach(function (s, i) { kit.screen(s, i * 1400); });
return { ok: true };
