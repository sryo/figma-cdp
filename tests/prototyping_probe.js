// Live check of __fx.react / overlayFrame / flow and the audit's prototype counts against the real
// Plugin API, on a throwaway __probe page that it removes. Run it on a scratch file, never a user's:
//
//   python3 figma_run.py --lib --file <scratch-url> tests/prototyping_probe.js
//
// Returns {passed, failures, limits}; limits records what the real API still refuses or ignores.
const fail = [], limits = {};
const check = (what, want, got) => { const w = JSON.stringify(want), g = JSON.stringify(got); if (w !== g) fail.push({ what, want: w, got: g }); };
const refuses = async (what, f, re) => {
  try { await f(); fail.push({ what, want: 'refused', got: 'accepted' }); } catch (e) { if (re && !re.test(String(e.message || e))) fail.push({ what, want: String(re), got: String(e.message || e) }); }
};
for (const p of figma.root.children.filter((p) => p.name === '__probe')) {
  if (p === figma.currentPage) await figma.setCurrentPageAsync(figma.root.children.find((q) => q !== p));
  p.remove();
}
const home = figma.currentPage, pg = figma.createPage();
pg.name = '__probe';
await figma.setCurrentPageAsync(pg);
try {
  const screen = figma.createFrame(); screen.name = 'Home'; screen.resize(1440, 900); pg.appendChild(screen);
  const next = figma.createFrame(); next.name = 'Next'; next.resize(1440, 900); next.x = 1600; pg.appendChild(next);
  const def = figma.createComponent(); def.name = 'State=Default'; pg.appendChild(def);
  const hov = figma.createComponent(); hov.name = 'State=Hover'; pg.appendChild(hov);
  const set = figma.combineAsVariants([def, hov], pg); set.name = '__probe toggle'; set.y = 1200;

  await __fx.react(def, [{ on: 'hover', do: { to: hov, nav: 'change' } }]);
  check('hover CHANGE_TO', ['ON_HOVER', 'CHANGE_TO', null], [def.reactions[0].trigger.type, def.reactions[0].actions[0].navigation, def.reactions[0].actions[0].transition]);

  const btn = figma.createFrame(); btn.name = 'Menu button'; screen.appendChild(btn);
  await __fx.react(btn, [{ on: 'click', do: { to: next } }, { on: { key: 13 }, do: { to: next, anim: 'push-left' } }, { on: { after: 800 }, do: 'back' }]);
  check('triggers', ['ON_CLICK', 'ON_KEY_DOWN', 'AFTER_TIMEOUT'], btn.reactions.map((r) => r.trigger.type));
  check('navigate smart', 'SMART_ANIMATE', btn.reactions[0].actions[0].transition.type);
  check('push', 'PUSH', btn.reactions[1].actions[0].transition.type);
  check('timeout', 800, btn.reactions[2].trigger.timeout);
  await __fx.react(btn, [{ on: 'click', do: { to: next, nav: 'swap' } }], { append: true });
  check('append keeps others', ['ON_KEY_DOWN', 'AFTER_TIMEOUT', 'ON_CLICK'], btn.reactions.map((r) => r.trigger.type));

  const panel = figma.createFrame(); panel.name = 'Menu'; panel.resize(240, 320); pg.appendChild(panel);
  const ov = await __fx.overlayFrame({ base: screen, name: 'Menu overlay', items: [{ node: panel, x: 1180, y: 64 }] });
  check('overlay size', [1440, 900, 0], [ov.width, ov.height, ov.fills.length]);
  check('overlay kids', ['Scrim', 'Menu'], ov.children.map((c) => c.name));
  check('panel place', [1180, 64], [panel.x, panel.y]);
  check('scrim close', ['ON_CLICK', 'CLOSE'], [ov.children[0].reactions[0].trigger.type, ov.children[0].reactions[0].actions[0].type]);
  check('esc close', [[27], 'CLOSE'], [ov.reactions[0].trigger.keyCodes, ov.reactions[0].actions[0].type]);
  await __fx.react(btn, [{ on: 'click', do: { to: ov, nav: 'overlay' } }], { append: true });
  check('overlay action', 'OVERLAY', btn.reactions[2].actions[0].navigation);

  check('flow', [{ nodeId: screen.id, name: 'Main' }], await __fx.flow(pg, screen, 'Main'));
  check('flow rename', [{ nodeId: screen.id, name: 'Start' }], await __fx.flow(pg.id, screen.id, 'Start'));

  const kept = def.createInstance(); screen.appendChild(kept);
  const lost = def.createInstance(); screen.appendChild(lost);
  await __fx.react(lost, [{ on: 'click', do: { to: next } }]);
  check('instance inherits', 'ON_HOVER', kept.reactions[0] && kept.reactions[0].trigger.type);
  check('own replaces', ['ON_CLICK'], lost.reactions.map((r) => r.trigger.type));
  const small = figma.createFrame(); small.name = 'Small'; small.resize(200, 120); small.x = 3200; pg.appendChild(small);
  const opener = figma.createFrame(); opener.name = 'Opener'; screen.appendChild(opener);
  await __fx.react(opener, [{ on: 'click', do: { to: small, nav: 'overlay' } }]);
  const a = await __fx.audit(pg.id);
  check('audit', [0, 1, 1], [a.counts.danglingReactions, a.counts.lostHover, a.counts.overlayNotFullSize]);
  check('audit ids', [[lost.id], [opener.id]], [a.ids.lostHover, a.ids.overlayNotFullSize]);

  await refuses('unknown destination', () => btn.setReactionsAsync([{ trigger: { type: 'ON_CLICK' }, actions: [{ type: 'NODE', destinationId: '999999:1', navigation: 'NAVIGATE', transition: null }] }]), /rejected/);
  await refuses('CHANGE_TO from a plain frame', () => __fx.react(btn, [{ on: 'click', do: { to: hov, nav: 'change' } }]), /rejected/);
  next.remove();
  check('removal drops reactions to it', ['AFTER_TIMEOUT', 'ON_CLICK'], btn.reactions.map((r) => r.trigger.type));

  small.overlayPositionType = 'MANUAL';
  small.overlayBackgroundInteraction = 'CLOSE_ON_CLICK_OUTSIDE';
  limits.overlaySettingsIgnored = small.overlayPositionType === 'CENTER' && small.overlayBackgroundInteraction === 'NONE';
  const col = figma.variables.createVariableCollection('__probe vars');
  try {
    const v = figma.variables.createVariable('period', col, 'STRING');
    v.setValueForMode(col.modes[0].modeId, '30 days');
    try {
      await btn.setReactionsAsync([{ trigger: { type: 'ON_CLICK' }, actions: [{ type: 'SET_VARIABLE', variableId: v.id, variableValue: { type: 'STRING', resolvedType: 'STRING', value: '7 days' } }] }]);
      limits.setVariable = 'accepted';
    } catch (e) { limits.setVariable = 'refused'; }
    try { col.addMode('Second'); limits.secondMode = 'accepted'; } catch (e) { limits.secondMode = 'refused'; }
  } finally { col.remove(); }
} finally {
  await figma.setCurrentPageAsync(home);
  pg.remove();
}
return { passed: !fail.length, failures: fail, limits };
