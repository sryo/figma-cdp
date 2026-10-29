# Prototyping

Load for prototype wiring: clicks, hovers, keys and timers; navigate, overlays, back and close; flows; interactive components. The raw types (`Reaction`, `Trigger`, `Action`, `Transition`) are in `references/api-styling.md` → Prototype types; this file is what works when a script sets them, and the `__fx` helpers that do it.

## Reactions

`node.reactions` is read-only; write the whole list with `await node.setReactionsAsync([...])`, so read it first to keep what is there. A reaction is `{trigger, actions: [action]}`; a read one carries `action` too and writes back as-is.

`setReactionsAsync` refuses the whole list when a destination doesn't exist, sits on another page, or is a CHANGE_TO variant reached from outside an instance or variant. Removing a node drops every reaction and flow starting point that points at it, silently, so rebuild targets before wiring them.

| Trigger | Shape |
|---------|-------|
| Click | `{type: 'ON_CLICK'}` |
| Hover (reverts on leave) | `{type: 'ON_HOVER'}` |
| Press (reverts on release) | `{type: 'ON_PRESS'}` |
| Key | `{type: 'ON_KEY_DOWN', device: 'KEYBOARD', keyCodes: [27]}`: 27 Esc, 13 Enter, 37-40 arrows |
| Timer | `{type: 'AFTER_TIMEOUT', timeout: 800}`, in ms per the API docs (stored as given) |

| Action | Shape |
|--------|-------|
| Go to a frame | `{type: 'NODE', destinationId, navigation: 'NAVIGATE', transition}` |
| Open an overlay | `navigation: 'OVERLAY'`, the destination a top-level frame |
| Replace the open overlay | `navigation: 'SWAP'` |
| Switch variant (interactive component) | `navigation: 'CHANGE_TO'`, the destination a variant of the same set |
| Scroll to a layer | `navigation: 'SCROLL_TO'`, the destination inside the current frame |
| Back | `{type: 'BACK'}` |
| Close overlay | `{type: 'CLOSE'}` |

Transitions: `{type: 'SMART_ANIMATE', easing: {type: 'EASE_IN_AND_OUT'}, duration: 0.3}` (seconds) for navigation between similar screens, `{type: 'DISSOLVE', easing: {type: 'EASE_OUT'}, duration: 0.2}` for overlays, `null` for instant (the usual CHANGE_TO on hover). Add `preserveScrollPosition: false` to NODE actions; OVERLAY and SWAP also take `resetScrollPosition: true`.

## Helpers

```js
// react(ref, [{on, do}], {append}): on 'click'|'hover'|'press'|{key: 27}|{after: ms};
// do 'back'|'close'|{to, nav: 'navigate'|'overlay'|'swap'|'change'|'scroll', anim: 'smart'|'dissolve'|'instant'|'push-left', ms}
await __fx.react(row, [{ on: 'click', do: { to: detail } }]);                       // smart animate
await __fx.react(menuBtn, [{ on: 'click', do: { to: menu, nav: 'overlay' } }]);     // dissolve
await __fx.react(card, [{ on: 'click', do: { to: next } }], { append: true });      // keeps the hover it has
// A base-sized overlay with the panel at its place in base, a Scrim that closes, Esc that closes.
const menu = await __fx.overlayFrame({ base: home, name: 'Menu overlay', items: [{ node: panel, x: 1180, y: 64 }] });
await __fx.flow(figma.currentPage, home, 'Main');
```

Without `append`, `react` replaces the node's reactions; with it, the triggers it names replace their old reactions and the rest stay. `to` is a node or id. `overlayFrame` replaces a same-named frame on the page, which drops the reactions that opened the old one (wire after), places the overlay 200 px below `base`, and takes `items` as `{node, x, y}` in base coordinates (a bare node keeps its x / y), plus `scrim: false` and `page`. `flow` keeps one starting point per frame and per name.

## Flows

`page.flowStartingPoints = [{nodeId, name}, ...]`, read-only array: assign a new one. `__fx.flow` does it. The start is a top-level frame on that page.

## Interactive components

State lives in the variants: a reaction on a variant with CHANGE_TO another variant of the same set applies to every instance. Hover is ON_HOVER CHANGE_TO the `State=Hover` variant, instant; leaving reverts by itself, so the Hover variant needs no reaction back. Press is ON_PRESS the same way; a toggle is ON_CLICK CHANGE_TO in both directions.

```js
const def = set.children.find(v => v.name === 'State=Default'), hov = set.children.find(v => v.name === 'State=Hover');
await __fx.react(def, [{ on: 'hover', do: { to: hov, nav: 'change' } }]);
```

An instance given its own reaction loses the hover: `references/gotchas.md` #17.

## Verified limits (Plugin API, free plan)

- `overlayPositionType`, `overlayBackground` and `overlayBackgroundInteraction` are read-only; assignments are silently ignored, so an overlay opens CENTER, with no background, and doesn't close on a click outside.
- `overlayRelativePosition` on an OVERLAY action applies only when the position type is MANUAL, which a script can't set.
- SET_VARIABLE and CONDITIONAL actions are refused on the free plan, as is a second variable mode. Model state with variants and CHANGE_TO, or with separate frames.

## Overlay placement

CENTER is the only position, so make the overlay land where it belongs by making it the screen:

1. The overlay frame is the size of the base screen, no fill, clip off, with the panel at its real x / y inside it.
2. A full-size, see-through `Scrim` child behind the panel, ON_CLICK CLOSE, stands in for close-on-click-outside.
3. ON_KEY_DOWN Esc → CLOSE on the overlay frame.
4. Open it with OVERLAY from the screen: centered over a frame its own size, it covers the screen exactly.

`__fx.overlayFrame` builds 1-3. For a dimmed backdrop, give the Scrim a fill.

## Audit

`__fx.audit` counts prototype problems too:
- `danglingReactions`: a reaction whose destination id doesn't resolve. The Plugin API never leaves one (see Reactions), so a nonzero count means state written some other way.
- `lostHover`: an instance whose own reactions (an empty list included) have no ON_HOVER while its main component's do.
- `overlayNotFullSize`: an OVERLAY opened from a screen onto a frame smaller than that screen (it opens centered, not in place).
