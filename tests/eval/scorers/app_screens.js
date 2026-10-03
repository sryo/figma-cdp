// Three screens of the Harbor app (fixtures/harbor) at realistic scale. Graded on how the
// build uses components, not only whether it does:
//   instanceShare        share of source component usages drawn as instances
//   reusedComponentized  share of source components used 2+ times that became exactly one
//                        component every usage instances (icons: one per icon name)
//   splitComponents      extra components made for one source component (duplicates)
//   variantCoverage      share of the source's states/props (tone, state, size, selected...)
//                        the components carry as variants or boolean properties
//   variantMatch         share of instances set to their usage's state
//   nestedShare          share of usages nested in another component's usage (Avatar in
//                        ListItem, Badge in StatCard, Tab in Tabs...) that are instances inside
//                        that instance; listItemAvatarNested is the ListItem → Avatar slice
//   sizingMatch          fill/hug/fixed per axis on the boxes the CSS sizes
//   copy, inventedCopy   source strings shown; text layers the source does not have
// plus quality(): autoLayoutShare, boundPaintShare, defaultNames, duplicateComponents...
var pages = evalPages();
var page = await targetPage();
var S = EVAL.expect.screens, screens = [S.dashboard, S.customers, S.invoice];
var read = await readScreens(page, screens, EVAL.expect);
var strings = [], shown = 0, total = 0;
read.screens.forEach(function (f) {
  var want = Object.keys(setOf(f.screen.strings));
  strings = strings.concat(want);
  total += want.length;
  if (f.region) shown += Math.round(copyMatch(want, [f.region].concat(f.region.findAll ? f.region.findAll() : [])) * want.length);
});
var m = Object.assign(await quality(pages), await componentMetrics(read, EVAL.expect, pages), {
  screensFound: share(read.screens.filter(function (f) { return f.region; }).length, screens.length),
  copy: share(shown, total),
  inventedCopy: inventedCopy(read, strings),
});
return {
  metrics: m,
  lower: QUALITY_LOWER.concat(COMPONENT_LOWER),
  passed: m.screensFound === 1 && m.instanceShare >= 0.85 && m.reusedComponentized >= 0.9 && m.splitComponents === 0 &&
    m.variantCoverage >= 0.9 && m.variantMatch >= 0.9 && m.nestedShare >= 0.8 && m.sizingMatch >= 0.8 &&
    m.copy >= 0.95 && m.inventedCopy <= 2 && m.autoLayoutShare >= 0.9,
};
