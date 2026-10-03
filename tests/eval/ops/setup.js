// Fresh file for one task rep. The scratch file belongs to the evals, so everything an earlier
// session left is removed: every page, every variable collection and every local style. Without
// this, tokens and components an agent made in one rep show up in the next rep's inventory.
// Then the page "<prefix>" is created and shown. Returns {pageId, pageName, cleared}.
var page = figma.createPage();
page.name = EVAL.prefix;
await figma.setCurrentPageAsync(page);
var old = figma.root.children.filter(function (p) { return p !== page; });
old.forEach(function (p) { p.remove(); });
(await figma.variables.getLocalVariableCollectionsAsync()).forEach(function (c) { c.remove(); });
var styles = [].concat(await figma.getLocalPaintStylesAsync(), await figma.getLocalTextStylesAsync(),
  figma.getLocalEffectStylesAsync ? await figma.getLocalEffectStylesAsync() : [],
  figma.getLocalGridStylesAsync ? await figma.getLocalGridStylesAsync() : []);
styles.forEach(function (s) { s.remove(); });
return { pageId: page.id, pageName: page.name, cleared: old.length };
