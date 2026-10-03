// Flat drawings: no components at all, no auto layout, off-palette hex colors, default layer
// names, several strings dropped and placeholder copy left in.
// include: offline/harbor_kit.js
var S = EVAL.expect.screens, screens = [S.dashboard, S.customers, S.invoice];
var kit = await harborKit({ comps: [], autoLayout: false, sizing: false, bind: false, names: false,
  offPalette: { primary: '#3366ff', surface: '#fefefe', border: '#dddddd', 'text-muted': '#777777' },
  drop: ['Northwind Studio', 'Diaz & Co.', 'Assigned automatically', 'Customer since', 'June 2023'],
  invent: ['Lorem ipsum', 'Button', 'Label'] }).init(screens);
screens.forEach(function (s, i) { kit.screen(s, i * 1400); });
return { ok: true };
