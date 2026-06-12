# Figma Plugin API gotchas

Every rule has a WRONG/CORRECT example.

## 1. FILL sizing MUST be set AFTER appendChild
```js
// WRONG
child.layoutSizingHorizontal = 'FILL';
parent.appendChild(child);  // throws!
// CORRECT
parent.appendChild(child);
child.layoutSizingHorizontal = 'FILL';
```

## 2. Fonts don't persist across evals: load every time
```js
// WRONG: assumes font loaded in previous eval
node.characters = 'Hello';
// CORRECT
await figma.loadFontAsync(node.fontName);
node.characters = 'Hello';
```

## 3. Colors use 0-1 range, not 0-255
```js
// WRONG
{r: 37, g: 99, b: 235}
// CORRECT: divide by 255
{r: 0.145, g: 0.388, b: 0.922}
```

## 4. Paint opacity goes on paint object, not color.a
```js
// WRONG
node.fills = [{type: 'SOLID', color: {r: 0, g: 0, b: 0, a: 0.5}}];
// CORRECT
node.fills = [{type: 'SOLID', color: {r: 0, g: 0, b: 0}, opacity: 0.5}];
```

## 5. Readonly arrays: clone before mutating
```js
// WRONG
node.fills.push(newFill);       // fills is readonly
// CORRECT
var f = node.fills.slice();
f.push(newFill);
node.fills = f;
```

## 6. Optional chaining (`?.`) and nullish coalescing (`??`) aren't supported — Figma's QuickJS sandbox
```js
// WRONG
var name = node?.parent?.name ?? 'none';
// CORRECT
var name = node && node.parent ? node.parent.name: 'none';
```

## 7. Return errors instead of throwing — `throw` crashes the eval and you lose context
```js
// WRONG: throw crashes the eval, you lose context
if (!node) throw new Error('not found');
// CORRECT
if (!node) return {error: 'Node not found'};
```

## 8. commitUndo() is expensive: once per user-visible change
```js
// WRONG: calling per property
node.name = 'X'; figma.commitUndo();
node.fills = [...]; figma.commitUndo();
// CORRECT: once after all mutations
node.name = 'X';
node.fills = [...];
figma.commitUndo();
```

## 9. Don't alternate ComponentNode writes + InstanceNode reads
```js
// WRONG: Figma recalculates instances on every component change
comp.fills = [...]; var x = inst.width;
comp.name = 'Y';   var y = inst.height;
// CORRECT: batch all component writes, then read instances
comp.fills = [...]; comp.name = 'Y';
var x = inst.width; var y = inst.height;
```

## 10. lineHeight/letterSpacing use {unit, value} format
```js
// WRONG
textNode.lineHeight = 24;
// CORRECT
textNode.lineHeight = {unit: 'PIXELS', value: 24};
textNode.letterSpacing = {unit: 'PERCENT', value: 0};
```

## 11. New top-level nodes default to (0,0): position them
```js
// WRONG: overlaps existing content at origin
var frame = figma.createFrame();
// CORRECT
var frame = figma.createFrame();
frame.x = 500; frame.y = 500;
```

## 12. resize() before sizing modes: resize resets to FIXED
```js
// WRONG: resize after sizing mode resets it
child.layoutSizingHorizontal = 'FILL';
child.resize(200, 40);  // resets to FIXED!
// CORRECT
child.resize(200, 40);
child.layoutSizingHorizontal = 'FILL';
```

## 13. Async helpers like `new AsyncFunction(...)` are blocked — wrap code in an async IIFE
QuickJS blocks `new AsyncFunction(...)` and `Function('async ...')()`.
```js
// WRONG
new AsyncFunction('await foo()')();
// CORRECT: async IIFE wrapper
(async function() { await foo(); })();
```

## 14. Verify parent after appendChild: silent reparenting
In long async scripts, `appendChild` can drop a node to page root with no error.
```js
// WRONG: assume it worked
parent.appendChild(child);
// CORRECT
parent.appendChild(child);
if (child.parent.id !== parent.id) return {error: 'reparent failed'};
```

## 15. Append in the same eval that creates: orphan nodes get GC'd
```js
// WRONG: split across evals; the orphan may be gone by step 2
window.__batchState.a = figma.createText();          // step 1
parent.appendChild(window.__batchState.a);           // step 2: .removed === true
// CORRECT: create + append in the same script, pass the ID
var t = figma.createText();
parent.appendChild(t);
window.__batchState.aId = t.id;                      // next eval: getNodeByIdAsync(aId)
```

## 16. Find before create: reuse existing nodes and components
Two failure modes: (a) re-running a worker creates duplicate top-level nodes; (b) building raw structures when a local component or variant already covers the case. Inventory first (see `references/reading.md` → Component inventory), then create only if nothing matches.
```js
// WRONG #1: second worker run leaves two "Hero" frames at page root
var hero = figma.createFrame();
hero.name = 'Hero';
// CORRECT: find first, create only if not present
var hero = figma.currentPage.children.find(function(c) {
  return c.name === 'Hero' && c.type === 'FRAME';
});
if (!hero) {
  hero = figma.createFrame();
  hero.name = 'Hero';
}

// WRONG #2: rebuilding a button as raw frame + text when a Button component exists
var btn = figma.createFrame(); btn.layoutMode = 'HORIZONTAL'; /* ...20 more lines... */
// CORRECT: instantiate the existing component, override props
var buttonComp = figma.root
  .findAllWithCriteria({types: ['COMPONENT', 'COMPONENT_SET']})
  .find(function(c) { return c.name === 'Button' || c.name.indexOf('Button') === 0; });
if (buttonComp) {
  var inst = buttonComp.type === 'COMPONENT_SET'
    ? buttonComp.defaultVariant.createInstance()
    : buttonComp.createInstance();
  // For COMPONENT_SET, switch variant: inst.setProperties({'Style': 'Primary'})
}
```
