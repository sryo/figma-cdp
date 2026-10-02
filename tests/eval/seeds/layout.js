// A library page with the Button set and a ProductCard component built from it, plus the
// color tokens as variables. The store screen should place Card instances in its grid.
await loadFonts();
var tokens = seedTokens();
var v = tokens.vars;
var lib = await libraryPage();
var buttons = buildButtonSet(lib, v);
var card = mkFrame(lib, 'Product card', 'VERTICAL', { component: true, gap: 12, pad: [16, 16, 16, 16], radius: 10,
  fill: 'surface', stroke: 'border', width: 240, vars: v });
card.y = 200;
var img = figma.createRectangle();
img.name = 'Image';
card.appendChild(img);
img.resize(208, 160);
img.cornerRadius = 6;
img.fills = [paintOf('background', v)];
img.layoutSizingHorizontal = 'FILL';
var title = mkText(card, 'Product name', { style: 'Medium', size: 16, name: 'Title', vars: v });
var price = mkText(card, '$0', { size: 14, color: 'text-muted', name: 'Price', vars: v });
var primary = buttons.children.filter(function (c) { return c.name === 'Variant=Primary, State=Default'; })[0];
var cta = primary.createInstance();
card.appendChild(cta);
cta.layoutSizingHorizontal = 'FILL';
title.componentPropertyReferences = { characters: card.addComponentProperty('Title', 'TEXT', 'Product name') };
price.componentPropertyReferences = { characters: card.addComponentProperty('Price', 'TEXT', '$0') };
return { buttonSetId: buttons.id, cardId: card.id, variables: tokens.ids };
