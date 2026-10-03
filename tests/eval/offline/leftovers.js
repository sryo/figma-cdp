// What an earlier session may leave behind: its own page, a top-level frame and a variable collection.
var p = figma.createPage();
p.name = 'Library';
figma.root.children[0].appendChild(figma.createFrame());
var c = figma.variables.createVariableCollection('Agent tokens');
figma.variables.createVariable('x', c, 'COLOR');
return {ok: true};
