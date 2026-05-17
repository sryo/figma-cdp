# API: Text + fonts

Load for copy edits, text creation, font-related work. See `references/copy.md` for the workflow patterns (extract, update, font loading caching, find-and-replace, surgical edits).

Cross-refs: `references/api-reference.md` for `figma` global, base mixins; `references/api-styling.md` for fills on text.

## Create a text node

```
figma.createText(): TextNode
figma.createTextPath(vectorNode, startSegment, startPosition): TextPathNode
```

## Fonts (top-level)

```
figma.loadFontAsync({family, style}): P<void>
figma.listAvailableFontsAsync(): P<Font[]>
// Font: {fontName: {family, style}}
// MUST loadFontAsync before mutating any layout-affecting text property
```

## TextNode

```
type: 'TEXT' [ro]
// REQUIRE font loaded before mutating: characters, fontSize, fontName, textStyleId,
//   textCase, textDecoration, letterSpacing, lineHeight
// NO font needed: fills, strokes, strokeWeight, opacity, blendMode, visible

characters: string
fontSize: number|mixed
fontName: {family, style}|mixed
fontWeight: number|mixed [ro]
textAlignHorizontal: 'LEFT'|'CENTER'|'RIGHT'|'JUSTIFIED'
textAlignVertical: 'TOP'|'CENTER'|'BOTTOM'
textAutoResize: 'NONE'|'WIDTH_AND_HEIGHT'|'HEIGHT'|'TRUNCATE'
textTruncation: 'DISABLED'|'ENDING'
maxLines: number|null
letterSpacing: {value, unit:'PIXELS'|'PERCENT'}|mixed
lineHeight: {value, unit}|{unit:'AUTO'}|mixed
leadingTrim: 'CAP_HEIGHT'|'NONE'|mixed
textCase: 'ORIGINAL'|'UPPER'|'LOWER'|'TITLE'|'SMALL_CAPS'|'SMALL_CAPS_FORCED'|mixed
textDecoration: 'NONE'|'UNDERLINE'|'STRIKETHROUGH'|mixed
paragraphSpacing/paragraphIndent/listSpacing: number
hangingPunctuation/hangingList: boolean
hyperlink: HyperlinkTarget|null|mixed            // {type:'URL'|'NODE', value}
autoRename: boolean
textStyleId: string|mixed
setTextStyleIdAsync(id): P<void>
hasMissingFont: boolean [ro]
openTypeFeatures: {[feature]: boolean}|mixed [ro]
```

## Range methods (per-character formatting)

Start inclusive, end exclusive. All `set*` variants require fonts in the range to be loaded first.

```
get/setRangeFontSize(start, end, value?)
get/setRangeFontName(start, end, value?)
get/setRangeFills(start, end, value?)
get/setRangeTextDecoration(start, end, value?)
get/setRangeTextCase(start, end, value?)
get/setRangeLetterSpacing(start, end, value?)
get/setRangeLineHeight(start, end, value?)
get/setRangeListOptions(start, end, value?)
get/setRangeIndentation(start, end, value?)
get/setRangeHyperlink(start, end, value?)
setRangeBoundVariable(start, end, field, variable|null)
setRangeTextStyleIdAsync(start, end, styleId)
setRangeFillStyleIdAsync(start, end, styleId)

insertCharacters(start, chars, useStyle?: 'BEFORE'|'AFTER')
deleteCharacters(start, end)

getStyledTextSegments(fields, start?, end?): StyledTextSegment[]
getRangeAllFontNames(start, end): FontName[]
```

## Data types

```
HyperlinkTarget: {type:'URL'|'NODE', value: string}
TextListOptions: {type:'ORDERED'|'UNORDERED'|'NONE'}
FontName: {family, style}
```

## Notes

- `figma.mixed` appears when a property has different values across ranges (e.g. a node with two fonts). Check `node.fontName !== figma.mixed` before single-font operations; use `getRangeAllFontNames` for mixed.
- `figma.util.rgb(hex)` and `figma.util.solidPaint(hex)` (in `api-reference.md` → Utility) work for text fills.
