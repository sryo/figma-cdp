// The whole file in brief: page names, top-level node count and variable collections.
var cols = await figma.variables.getLocalVariableCollectionsAsync();
return {
  pages: figma.root.children.map(function (p) { return p.name; }),
  nodes: figma.root.children.reduce(function (n, p) { return n + p.children.length; }, 0),
  collections: cols.length,
};
