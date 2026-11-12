// The Motion timeline (Beta in typings 1.142.0) on the real Plugin API: manual keyframe tracks,
// the timeline's duration and Figma's animation styles.
//
//   python3 tests/probes/figma_probe.py --file <scratch-url> motion
const frame = figma.createFrame(); frame.resize(200, 200); pg.appendChild(frame);
const rect = figma.createRectangle(); frame.appendChild(rect);
const key = (v, at, easing) => Object.assign({ timelinePosition: at, value: { type: 'FLOAT', value: v } }, easing ? { easing } : {});
const OPACITY = { type: 'PROPERTY', name: 'OPACITY' };

check('nothing animated yet', [{}, {}, []], [rect.manualKeyframeTracks, rect.animations, rect.animationStyles]);
// A node's timeline is its top-level frame's: one id for the frame and everything in it.
const tl = frame.timelines;
check('one timeline, 2 s', [1, 2, true], [tl.length, tl[0].duration, rect.timelines[0].id === tl[0].id]);

try {
  rect.applyManualKeyframeTrack(OPACITY, { keyframes: [key(0, 0, { type: 'LINEAR' }), key(1, 1)] });
  const t = rect.manualKeyframeTracks.OPACITY;
  check('track readback', [1, [0, 1], [0, 1], 'LINEAR', 'CUSTOM_CUBIC_BEZIER'],
    [t.baseValue.value, t.keyframes.map((k) => k.timelinePosition), t.keyframes.map((k) => k.value.value), t.keyframes[0].easing.type, t.keyframes[1].easing.type]);
  check('animations lists the track', 'SET', rect.animations.OPACITY.tracks[0].keyframeOperation);
  check('the node keeps its base value', 1, rect.opacity);
  limit('MotionNodeMixin.applyManualKeyframeTrack', 'works');
} catch (e) { limit('MotionNodeMixin.applyManualKeyframeTrack', 'refused', e); }

// A second apply on the same field replaces the track.
rect.applyManualKeyframeTrack(OPACITY, { keyframes: [key(0.5, 0), key(1, 0.5), key(0, 1.5)] });
check('apply replaces', 3, rect.manualKeyframeTracks.OPACITY.keyframes.length);

// A keyframe past the end doesn't stretch the timeline: set the duration.
rect.applyManualKeyframeTrack({ type: 'PROPERTY', name: 'ROTATION' }, { keyframes: [key(0, 0), key(90, 5)] });
check('a late keyframe leaves the duration', 2, frame.timelines[0].duration);
try {
  frame.setTimelineDuration(tl[0].id, 6);
  limit('MotionNodeMixin.setTimelineDuration', frame.timelines[0].duration === 6 ? 'works' : 'ignored');
} catch (e) { limit('MotionNodeMixin.setTimelineDuration', 'refused', e); }

try {
  frame.applyManualKeyframeTrack({ type: 'INDEXED_ITEM', collection: 'fills', index: 0 },
    { keyframes: [{ timelinePosition: 0, value: { type: 'COLOR', value: { r: 1, g: 0, b: 0, a: 1 } } }, { timelinePosition: 1, value: { type: 'COLOR', value: { r: 0, g: 0, b: 1, a: 1 } } }] });
  limit('KeyframeField.fills', Object.keys(frame.manualKeyframeTracks.fills || {}).length === 1 ? 'works' : 'ignored');
} catch (e) { limit('KeyframeField.fills', 'refused', e); }

try {
  rect.removeManualKeyframeTrack(OPACITY);
  limit('MotionNodeMixin.removeManualKeyframeTrack', 'OPACITY' in rect.manualKeyframeTracks ? 'ignored' : 'works');
} catch (e) { limit('MotionNodeMixin.removeManualKeyframeTrack', 'refused', e); }

// Animation styles go by styleId, not by name.
const styles = figma.motion.figmaAnimationStyles();
note('styles', styles.map((s) => ({ styleId: s.styleId, name: s.name, props: Object.keys(s.props || {}) })));
check('the opacity style', true, styles.some((s) => s.styleId === 'Opacity'));
await refuses('a style name is not its id', () => rect.applyAnimationStyle('motion.preset_name.opacity'), /No Figma animation style found/);
try {
  const id = rect.applyAnimationStyle('Opacity', { duration: 0.5 });
  const applied = rect.animationStyles;
  note('applied', applied);
  // The applied entry's styleId is an internal id: tell styles apart by name.
  check('applied style', [1, 'motion.preset_name.opacity', 'FIGMA', id, 0.5, 'fadeIn'],
    [applied.length, applied[0].name, applied[0].type, applied[0].id, applied[0].duration, applied[0].props.type]);
  note('animations after a style', Object.keys(rect.animations));
  rect.removeAnimationStyle(id);
  check('removed style', 0, rect.animationStyles.length);
  limit('MotionNodeMixin.applyAnimationStyle', 'works');
} catch (e) { limit('MotionNodeMixin.applyAnimationStyle', 'refused', e); }

await refuses('an unknown field name', () => rect.applyManualKeyframeTrack({ type: 'PROPERTY', name: 'X' }, { keyframes: [] }), /Property "field" failed validation/);
check('no playhead without the Motion panel', undefined, figma.motion.playheadPosition);
