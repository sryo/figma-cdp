# API: Styling (fills, strokes, effects, images, prototype)

Load for any task touching colors, shadows, blurs, images, or prototype reactions. See `references/building.md` → Effects / Gradient fills / Image fills for end-to-end patterns.

Cross-refs: `references/api-reference.md` for base mixins and `figma.util` color helpers; `references/api-layout.md` for shape nodes that use these mixins; `references/api-components.md` for PaintStyle / EffectStyle objects.

## GeometryMixin (fills, strokes)

```
fills: Paint[]|mixed                             // READONLY array — reassign, don't push!
fillStyleId: string|mixed
strokes: Paint[]
strokeStyleId: string
strokeWeight: number|mixed
strokeAlign: 'CENTER'|'INSIDE'|'OUTSIDE'
strokeCap: StrokeCap|mixed
strokeJoin: StrokeJoin|mixed
strokeMiterLimit: number
dashPattern: number[]
fillGeometry/strokeGeometry: VectorPaths [ro]
outlineStroke(): VectorNode|null
setFillStyleIdAsync(id)/setStrokeStyleIdAsync(id): P<void>
setFillsAsync(paints)/setStrokesAsync(strokes): P<void>
```

## BlendMixin (effects, opacity, blend mode, masks)

```
opacity: number                                  // 0-1
blendMode: BlendMode
isMask: boolean
maskType: 'ALPHA'|'VECTOR'|'LUMINANCE'
effects: Effect[]                                // READONLY array — clone before mutating
effectStyleId: string
setEffectStyleIdAsync(id): P<void>
```

## ReactionMixin (prototype interactions)

```
reactions: Reaction[] [ro]
setReactionsAsync(reactions): P<void>
```

## Paint types

```
SolidPaint: {type:'SOLID', color:{r,g,b}, opacity?, visible?, blendMode?}
GradientPaint: {type:'GRADIENT_LINEAR'|'GRADIENT_RADIAL'|'GRADIENT_ANGULAR'|'GRADIENT_DIAMOND',
                gradientStops:[{position:0-1, color:{r,g,b,a}}], gradientTransform}
ImagePaint: {type:'IMAGE', scaleMode:'FILL'|'FIT'|'CROP'|'TILE', imageHash,
             imageTransform?, filters?}
VideoPaint: {type:'VIDEO', scaleMode, videoHash}
```

Hex → SolidPaint: `figma.util.solidPaint('#6366f1')` (see `api-reference.md` → Utility).

## Effect types

```
DropShadowEffect: {type:'DROP_SHADOW', color:RGBA, offset:{x,y}, radius, spread?,
                   visible, blendMode, showShadowBehindNode?}
InnerShadowEffect: {type:'INNER_SHADOW', color:RGBA, offset:{x,y}, radius, spread?,
                    visible, blendMode}
BlurEffect: {type:'LAYER_BLUR'|'BACKGROUND_BLUR', radius, visible}
  // Progressive variant (Beta): {blurType:'PROGRESSIVE', startRadius,
  //   startOffset:Vector, endOffset:Vector}
  // offsets normalized (0,0)=top-left, (1,1)=bottom-right

// Beta effects (rare): NoiseEffect, TextureEffect, GlassEffect — see plugin-typings
```

## Images and video

```
figma.createImage(data: Uint8Array): Image
figma.createImageAsync(url: string): P<Image>    // CORS may block — fall back to bytes
figma.getImageByHash(hash): Image|null
figma.createVideoAsync(data: Uint8Array): P<Video>
figma.base64Encode(data: Uint8Array): string
figma.base64Decode(data: string): Uint8Array

// Image: {hash [ro], getBytesAsync(): P<Uint8Array>, getSizeAsync(): P<{width, height}>}
// Video: {hash [ro]}
// Image format limits: PNG/JPG/GIF, max 4096×4096
```

## Prototype types

```
Reaction: {trigger, action?, actions?}
Trigger: 'ON_CLICK'|'ON_HOVER'|'ON_PRESS'|'ON_DRAG'
       | {type:'AFTER_TIMEOUT', timeout}
       | {type:'MOUSE_*', delay}
       | {type:'ON_KEY_DOWN', device, keyCodes}
       | {type:'ON_MEDIA_*'}
Action: 'BACK'|'CLOSE'
      | {type:'URL', url}
      | {type:'NODE', destinationId, navigation, transition, ...}
      | {type:'SET_VARIABLE'|'SET_VARIABLE_MODE'|'CONDITIONAL'|'UPDATE_MEDIA_RUNTIME', ...}
Navigation: 'NAVIGATE'|'SWAP'|'OVERLAY'|'SCROLL_TO'|'CHANGE_TO'
Transition: {type:'DISSOLVE'|'SMART_ANIMATE'|'MOVE_IN'|'MOVE_OUT'|'PUSH'|'SLIDE_IN'|'SLIDE_OUT',
             easing, duration, direction?}
Easing: {type:'EASE_IN|OUT|IN_AND_OUT'|'LINEAR'|'GENTLE'|'QUICK'|'BOUNCY'|'SLOW'
            |'CUSTOM_CUBIC_BEZIER'|'CUSTOM_SPRING', ...}
```

## Enums

```
BlendMode: 'NORMAL'|'MULTIPLY'|'SCREEN'|'OVERLAY'|'DARKEN'|'LIGHTEN'|... (16 total)
StrokeCap: 'NONE'|'ROUND'|'SQUARE'|'ARROW_LINES'|'ARROW_EQUILATERAL'|
           'DIAMOND_FILLED'|'TRIANGLE_FILLED'|'CIRCLE_FILLED'
StrokeJoin: 'MITER'|'BEVEL'|'ROUND'
```
