// Fresh page for one task rep: removes leftovers of an earlier run with this prefix (pages and
// the "<prefix> tokens" variable collection), then creates the page "<prefix>".
// Returns {pageId, pageName, cleared}.
var stale = evalPages();
if (stale.length && belongs(figma.currentPage.name)) {
  var keep = figma.root.children.filter(function (p) { return !belongs(p.name); })[0];
  await figma.setCurrentPageAsync(keep || figma.createPage());
}
stale.forEach(function (p) { p.remove(); });
(await figma.variables.getLocalVariableCollectionsAsync()).forEach(function (c) {
  if (c.name === EVAL.prefix + ' tokens') c.remove();
});
var page = figma.createPage();
page.name = EVAL.prefix;
return { pageId: page.id, pageName: page.name, cleared: stale.length };
