// Removes the rep's pages and its "<prefix> tokens" variable collection, leaving an empty
// "Page 1" when nothing else is left. A run's page may be the current one, and Figma refuses
// to remove that, so another page is shown first.
var pages = evalPages();
if (belongs(figma.currentPage.name)) {
  var keep = figma.root.children.filter(function (p) { return !belongs(p.name); })[0];
  if (!keep) { keep = figma.createPage(); keep.name = 'Page 1'; }
  await figma.setCurrentPageAsync(keep);
}
pages.forEach(function (p) { p.remove(); });
var cols = (await figma.variables.getLocalVariableCollectionsAsync()).filter(function (c) {
  return c.name === EVAL.prefix + ' tokens';
});
cols.forEach(function (c) { c.remove(); });
return { pages: pages.length, collections: cols.length };
