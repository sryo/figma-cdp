// Removes the rep's pages and its "<prefix> tokens" variable collection. A run's page may be
// the current one, and Figma refuses to remove that, so another page is shown first.
var pages = evalPages();
if (belongs(figma.currentPage.name)) {
  var keep = figma.root.children.filter(function (p) { return !belongs(p.name); })[0];
  await figma.setCurrentPageAsync(keep || figma.createPage());
}
pages.forEach(function (p) { p.remove(); });
var cols = (await figma.variables.getLocalVariableCollectionsAsync()).filter(function (c) {
  return c.name === EVAL.prefix + ' tokens';
});
cols.forEach(function (c) { c.remove(); });
return { pages: pages.length, collections: cols.length };
