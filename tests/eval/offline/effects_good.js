var main = await figma.getNodeByIdAsync(EVAL.seed.mainId);
main.effects = main.effects.concat([{ type: 'DROP_SHADOW', color: { r: 0, g: 0, b: 0, a: 0.2 }, offset: { x: 0, y: 4 },
  radius: 12, spread: 0, visible: true, blendMode: 'NORMAL' }]);
return { ok: true };
