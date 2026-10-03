// The three screens built from one component per source component: variants for every source
// state, nested instances (Avatar and Badge inside ListItem...), auto layout with the CSS's
// fill/hug sizing, colors bound to the token variables, every string from the source.
// include: offline/harbor_kit.js
var S = EVAL.expect.screens, screens = [S.dashboard, S.customers, S.invoice];
var kit = await harborKit({ comps: ['Icon', 'Avatar', 'Badge', 'Button', 'Tab', 'Input', 'Tabs', 'ListItem', 'StatCard', 'AppHeader', 'Card'],
  autoLayout: true, sizing: true, bind: true, names: true }).init(screens);
screens.forEach(function (s, i) { kit.screen(s, i * 1400); });
return { ok: true };
