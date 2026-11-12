# 3D transforms and Motion

Load for a tilted or rotated-in-depth layer, perspective, or keyframe animation on Figma's Motion timeline.

## 3D transforms

Figma's "3D transform" effect and a frame's perspective. The typings (1.142.0) don't have these members yet; the live API does (`tests/probes/transform3d.js`, 2026-11-12, free plan).

```
transform3d: {type:'NONE'}                              // every layer; the default
           | {type:'FIXED_ORDER', translateZ, rotateX, rotateY, rotateZ,   // all four required: px, degrees
              backfaceVisible?, visible?}                                  // both default true
transformOrigin: {x, y}, each {unit:'PERCENT'|'PIXELS', value}             // default 50% 50%
scene3d: null | {perspective, preserve3d, visible?}     // frames, components, instances; both required
```

```js
card.transform3d = { type: 'FIXED_ORDER', translateZ: 0, rotateX: 0, rotateY: 35, rotateZ: 0 };
card.parent.scene3d = { perspective: 800, preserve3d: false };
```

- Figma applies `translateZ() rotateX() rotateY() rotateZ()` about `transformOrigin`, on top of the 2D transform. `rotation`, `relativeTransform`, `x` / `y`, the size and both bounding boxes stay the flat ones, and `rotateZ` is not `rotation`.
- A tilt looks flat until its parent frame has `scene3d`: `perspective` is the viewer's distance in px (smaller is stronger), like CSS `perspective` on the parent. `preserve3d: true` (CSS `transform-style`) keeps the frame's children in one 3D space, so nested tilts compose. Figma's editor then turns off that frame's own clipping, opacity, blend mode and effects; the API leaves those properties reading as they were.
- `backfaceVisible: false` hides a layer turned away from the viewer; `visible: false` turns the effect off and keeps its values.
- Groups take `transform3d` but have no `scene3d`; sections have neither.
- Values read back as float32 (10 → 9.9999997): compare with a tolerance. `getCSSAsync()` returns `transform`, `transform-origin`, `backface-visibility` and, on the frame, `perspective` and `transform-style`; a PNG export renders the result.
- To animate: the Motion fields `TRANSFORM_3D_ROTATION_X|Y|Z`, `TRANSFORM_3D_TRANSLATION_Z` and, on the frame, `SCENE_3D_PERSPECTIVE` (Motion timeline, below).

## Motion timeline

Keyframe animation on a top-level frame's timeline, separate from prototype reactions (`references/prototyping.md`). Beta in the typings; `tests/probes/motion.js` holds what was verified (2026-11-12, free plan). Every layer has these members, and a layer's timeline is its top-level frame's.

```
node.timelines: [{id, duration}] [ro]                 // seconds; 2 until set
node.setTimelineDuration(id, seconds)
node.applyManualKeyframeTrack(field, {keyframes: [{timelinePosition, value, easing?}], baseValue?})
node.removeManualKeyframeTrack(field)
node.manualKeyframeTracks [ro]                        // {OPACITY: {id, baseValue, keyframes}, fills: {0: ...}, effects: {0: {RADIUS: ...}}}
node.animations [ro]                                  // per field: {baseValue, timelineDuration, tracks: [{id, keyframeOperation, keyframes}]}
node.applyAnimationStyle(styleId, {duration?, timelineOffset?, props?}): id
node.removeAnimationStyle(id); node.animationStyles [ro]
figma.motion.figmaAnimationStyles()                   // [{styleId, name, description, props}]
figma.motion.playheadPosition                         // seconds; undefined unless the Motion panel is open

field: {type:'PROPERTY', name}
     | {type:'INDEXED_ITEM', collection:'fills'|'strokes', index}
     | {type:'INDEXED_ITEM', collection:'effects', index, field}    // OFFSET_X|Y, RADIUS, SPREAD, COLOR, EFFECT_OPACITY, ...
name:  OPACITY, ROTATION, TRANSLATION_X|Y|XY, SCALE_X|Y|XY, WIDTH, HEIGHT, CORNER_RADIUS, STROKE_WEIGHT,
       PATH_TRIM_START|END, STACK_SPACING, STACK_PADDING_LEFT|TOP|RIGHT|BOTTOM, GRID_ROW_GAP|COLUMN_GAP,
       TRANSFORM_3D_ROTATION_X|Y|Z, TRANSFORM_3D_TRANSLATION_Z, SCENE_3D_PERSPECTIVE   // the 3D five: not in the typings
value: {type:'FLOAT', value} | {type:'COLOR', value: RGBA} | {type:'VECTOR', value: {x, y}} | {type:'BOOL'|'TEXT_DATA', value}
easing: {type:'LINEAR'|'EASE_IN'|'EASE_OUT'|'EASE_IN_AND_OUT'|'GENTLE'|'QUICK'|'BOUNCY'|'SLOW'|'HOLD'
              |'CUSTOM_CUBIC_BEZIER'|'CUSTOM_SPRING', easingFunctionCubicBezier?: {x1, y1, x2, y2}, easingFunctionSpring?: {bounce}}
```

```js
const key = (at, value, easing) => ({ timelinePosition: at, value: { type: 'FLOAT', value }, easing });
card.applyManualKeyframeTrack({ type: 'PROPERTY', name: 'OPACITY' }, { keyframes: [key(0, 0), key(0.4, 1, { type: 'EASE_OUT' })] });
card.applyManualKeyframeTrack({ type: 'PROPERTY', name: 'TRANSFORM_3D_ROTATION_Y' }, { keyframes: [key(0, -90), key(0.6, 0)] });
```

- A track animates over the layer's own value, which stays as it was (`baseValue`). Applying to a field that has a track replaces it. Rotations are degrees, opacity 0-1, positions seconds.
- A keyframe past the timeline's end doesn't lengthen it: `frame.setTimelineDuration(frame.timelines[0].id, seconds)`.
- A field name the API doesn't know fails with the full list of valid names in the error.
- Animation styles go by `styleId` (`Position`, `Scale`, `Rotation`, `Size`, `Opacity`, `Path`, `TextStagger`), not `name`; each style's `description` documents its `props`. The applied entry reads back with an internal `styleId`: find it by the id `applyAnimationStyle` returned, or by `name`. Its keyframes don't show under `animations`.
