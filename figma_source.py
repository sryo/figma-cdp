#!/usr/bin/env python3
"""Extract a source manifest: what the implementation says the design is, every entry cited.

  python3 figma_source.py <file-or-dir>... [-o manifest.json]

Reads style sheets, markup, UI code and JSON token or string files (plus the local sheets a page links
or a sheet @imports), and writes JSON with:
  tokens        [{name, value, kind, src}]   custom properties, theme constants, JSON tokens
  colors        [{value, token?, src}]       every literal color, as #rrggbb
  spacing, radii, fontSizes, fontWeights     [{value, token?, src}]  numbers in px
  fontFamilies  [{value, token?, src}]
  copy          [{text, src}]                user-visible strings: markup text, copy attributes,
                                             prose string literals, string tables
  variants      [{component, prop, values, src}]  prop unions, enums, boolean props, class modifiers
  states        [{component, state, src}]    pseudo-classes, state-named props and modifiers
  components    [{component, uses, nests, src, css?, fill?}]  style blocks with a paint or type rule and
                                             capitalized code tags, with how often the markup uses each
                                             and the components used directly inside it, most used
                                             first; a style block's css is its rules (modifiers and
                                             elements too) as {selector: declarations}, about 1.6 KB;
                                             fill: the usages a column flex parent stretches across
src is `file:line` relative to the inputs' common directory. Without -o the JSON goes to
stdout; with -o a one-line summary does. figma_fidelity.py diffs a Figma subtree against it.
"""
import argparse, bisect, colorsys, html, json, os, re, sys

SKIP_DIRS = {'node_modules', '.git', 'dist', 'build', 'out', '.next', '.nuxt', 'vendor', 'Pods', 'DerivedData',
             'coverage', '__pycache__', '.venv', 'venv', '.gradle', 'target', '.turbo', '.cache'}
SKIP_EXT = {'.png', '.jpg', '.jpeg', '.gif', '.webp', '.ico', '.svg', '.pdf', '.woff', '.woff2', '.ttf', '.otf',
            '.eot', '.mp3', '.mp4', '.mov', '.zip', '.gz', '.lock', '.map', '.md', '.txt', '.rst', '.log', '.pyc'}
SKIP_FILES = {'package.json', 'package-lock.json', 'tsconfig.json', 'jsconfig.json', 'composer.json', 'manifest.json'}
# Test code: its strings and values are fixtures, not the UI.
TEST_NAME = re.compile(r'^(?i:tests?|__tests__|specs?|__mocks__|e2e)$|[a-z0-9]Tests?(\.\w+)?$|[._-](test|spec)s?(\.\w+)?$|^test_')
STYLE_EXT = {'.css', '.scss', '.sass', '.less', '.styl', '.pcss'}
MAX_BYTES = 512 * 1024

STATE_WORDS = {'hover', 'hovered', 'focus', 'focused', 'active', 'pressed', 'disabled', 'enabled', 'loading',
               'selected', 'checked', 'error', 'invalid', 'empty', 'open', 'expanded', 'visited', 'busy'}
WEIGHTS = {'thin': 100, 'hairline': 100, 'extralight': 200, 'ultralight': 200, 'light': 300, 'normal': 400,
           'regular': 400, 'medium': 500, 'semibold': 600, 'demibold': 600, 'bold': 700, 'extrabold': 800,
           'ultrabold': 800, 'black': 900, 'heavy': 900}
# Keys whose string values are code, not copy.
CODE_KEYS = re.compile(r'(class|style|href|src|path|url|^id$|^key$|^name$|type|kind|role|variant|icon|testid|^for$|'
                       r'font|family|color|colour|size|weight|radius|padding|margin|gap|background|border|shadow|'
                       r'^lang$|^d$|^points$|viewbox|transform|charset|^rel$|target|method|action|^title$|^alt$|^as$|^to$|mode|format|align|'
                       r'direction|^aria-|^data-|locale|event|^on[A-Z])', re.I)

HEX = re.compile(r'(?<![&\w#])#([0-9a-fA-F]{8}|[0-9a-fA-F]{6}|[0-9a-fA-F]{3,4})(?![\w-])')
RGB = re.compile(r'\brgba?\(\s*(\d+(?:\.\d+)?)[\s,]+(\d+(?:\.\d+)?)[\s,]+(\d+(?:\.\d+)?)')
HSL = re.compile(r'\bhsla?\(\s*(\d+(?:\.\d+)?)(?:deg)?[\s,]+(\d+(?:\.\d+)?)%[\s,]+(\d+(?:\.\d+)?)%')
HEX0X = re.compile(r'\b0x([0-9a-fA-F]{8}|[0-9a-fA-F]{6})\b')
URL_ATTR = re.compile(r'(?:href|src|to|action|id|for|name|target|xlink:href)\s*=\s*["\']?$', re.I)
NUM = re.compile(r'(?<![\w#.$-])(-?\d*\.?\d+)(px|pt|dp|sp|rem|em)?(?![\w%.])')
VAR = re.compile(r'var\(\s*(--[\w-]+)[^()]*(?:\([^()]*\)[^()]*)*\)')
SIGIL_DEF = re.compile(r'(?<![\w-])((?:--|\$|@)[A-Za-z_][\w-]*)\s*:\s*([^;}\n]+)')
IDENT_DEF = re.compile(r'(?<![\w.$-])([A-Za-z_]\w*)\s*[:=]\s*([^;\n]+)')
COLOR_START = re.compile(r'(?:[\w.]+\(\s*(?:hex:\s*)?)?["\']?\s*(?=#|rgb|hsl|0x)')
DECL_USE = re.compile(r'(?<![\w$@-])([A-Za-z][\w-]*)\s*([:=(])(?=\s*([^;{}\n]*))')
DECL_NAME = re.compile(r'\b(?:function|class|struct|interface|type|enum|const|let|var|val|fun|func|def|object|'
                       r'component|protocol|record)\s+([A-Z]\w*)')
UNION = re.compile(r'([A-Za-z_]\w*)\??\s*[:=]\s*((?:["\'][^"\'\n|]+["\']\s*\|\s*)+["\'][^"\'\n|]+["\'])')
BOOL_UNION = re.compile(r'([A-Za-z_]\w*)\??\s*:\s*(?:true\s*\|\s*false|false\s*\|\s*true)\b')
BOOL_TYPED = re.compile(r'([A-Za-z_]\w*)\??\s*:\s*(?:boolean|bool|Bool|Boolean)\b')
BOOL_DEFAULT = re.compile(r'([A-Za-z_]\w*)\s*=\s*(?:true|false)\b')
ENUM = re.compile(r'\benum\s+(?:class\s+)?([A-Za-z_]\w*)[^{\n]*\{([^}]*)\}')
MODIFIER = re.compile(r'\.((?:[A-Za-z0-9_]|-(?!-))+)--([A-Za-z0-9_]+(?:-[A-Za-z0-9_]+)*)')
PSEUDO = re.compile(r'\.((?:[A-Za-z0-9_]|-(?!-))+)(?:--[\w-]+)?[^\s{},]*?:(hover|focus-visible|focus-within|focus|'
                    r'active|disabled|checked|invalid|visited)\b')
UTILITY_STATE = re.compile(r'(?<![\w-])(hover|focus|active|disabled|checked|selected|pressed):[\w\[-]')
TAG = re.compile(r'<[A-Za-z][^<>]*>')
COPY_ATTR = re.compile(r'(?<![\w-])(placeholder|label|text|value|caption|heading|subtitle|description|hint|message|cta)'
                       r'\s*=\s*\{?\s*(["\'])([^"\'\n{}]+)\2')
LITERAL = re.compile(r'"((?:[^"\\\n]|\\.)*)"|\'((?:[^\'\\\n]|\\.)*)\'|`([^`$\n]*)`')
# Properties that make a style block look like something: it is a component, not layout scaffolding.
VISUAL = re.compile(r'(?<![\w-])(?:background(?:-color|-image)?|border(?:-(?:top|right|bottom|left))?(?:-color|-width|-style)?|'
                    r'color|box-shadow|font(?:-size|-weight|-family)?|outline|fill|stroke|text-decoration)\s*:', re.I)
RULE = re.compile(r'([^{}]+)\{([^{}]*)\}')
CSS_CAP = 1600  # bytes of rules per component in the manifest
FILL_CAP = 8     # stretched usages listed per component
COMPOUND = re.compile(r'^(?:\.-?[A-Za-z_][\w-]*)+$')
STYLE_ATTR = re.compile(r'(?<![\w-])style\s*=\s*(?:"([^"]*)"|\'([^\']*)\')')
TAG_OR_CLOSE = re.compile(r'<(/?)([A-Za-z][\w.:-]*)((?:\{(?:[^{}]|\{[^{}]*\})*\}|"[^"]*"|\'[^\']*\'|[^<>{}"\'])*)>')
CLASS_ATTR = re.compile(r'(?<![\w-])class(?:Name)?\s*=\s*(?:"([^"]*)"|\'([^\']*)\'|\{((?:[^{}]|\{[^{}]*\})*)\})')
VOID = {'area', 'base', 'br', 'col', 'embed', 'hr', 'img', 'input', 'link', 'meta', 'param', 'source', 'track', 'wbr'}
BLANK_BLOCKS = re.compile(r'<script\b[\s\S]*?</script>|<style\b[\s\S]*?</style>|<title\b[\s\S]*?</title>|<!--[\s\S]*?-->|'
                          r'\{/\*[\s\S]*?\*/\}', re.I)


def norm_component(s):
    return re.sub(r'[^a-z0-9_]', '', str(s).lower())


def hex6(r, g, b):
    return '#%02x%02x%02x' % tuple(max(0, min(255, round(float(v)))) for v in (r, g, b))


def colors_in(text, line=''):
    """[(offset, #rrggbb)] for every literal color in text."""
    out = []
    for m in HEX.finditer(text):
        if URL_ATTR.search(text[:m.start()][-40:]):
            continue
        h = m.group(1)
        if len(h) in (3, 4):
            h = ''.join(c * 2 for c in h[:3])
        out.append((m.start(), '#' + h[:6].lower()))
    for m in RGB.finditer(text):
        out.append((m.start(), hex6(*m.groups())))
    for m in HSL.finditer(text):
        h, s, l = float(m.group(1)) / 360, float(m.group(2)) / 100, float(m.group(3)) / 100
        r, g, b = colorsys.hls_to_rgb(h % 1, l, s)
        out.append((m.start(), hex6(r * 255, g * 255, b * 255)))
    if re.search(r'colou?r', line or text, re.I):
        for m in HEX0X.finditer(text):
            h = m.group(1)
            out.append((m.start(), '#' + (h[2:] if len(h) == 8 else h).lower()))
    return sorted(out)


def decl_dict(decls):
    """'a: b; c: d' as {a: b, c: d}, properties lowercased, !important dropped."""
    out = {}
    for d in decls.split(';'):
        k, sep, v = d.partition(':')
        if sep and k.strip():
            out[k.strip().lower()] = ' '.join(v.replace('!important', '').split())
    return out


def kind_of(name):
    """What a token or property name says its number is: spacing, radius, fontSize, fontWeight, or None."""
    n = name.lower().lstrip('-$@')
    flat = re.sub(r'[^a-z0-9]', '', n)
    if 'weight' in flat:
        return 'fontWeight'
    if re.search(r'lineheight|letter|tracking|leading|opacity|zindex|duration|delay|shadow|blur|border(?!radius)', flat):
        return None
    if re.search(r'radius|radii|rounded|corner', flat):
        return 'radius'
    if re.search(r'spac|gap|gutter|padding|margin|inset', flat):
        return 'spacing'
    if re.search(r'fontsize|textsize', flat) or re.match(r'(text|font|type|typo)', n) or re.search(r'typescale', flat):
        return 'fontSize'
    return None


def is_family_name(name):
    flat = re.sub(r'[^a-z]', '', name.lower())
    return bool(re.search(r'family|typeface', flat)) or flat in ('font', 'fontfamily') or flat.endswith('font')


def numbers(value, kind):
    """px numbers in a declaration value (rem/em × 16); font weights also by name."""
    out = []
    for m in NUM.finditer(value):
        v = float(m.group(1))
        if m.group(2) in ('rem', 'em'):
            v *= 16
        out.append(v)
    if kind == 'fontWeight':
        for w in re.findall(r'[A-Za-z]+', value):
            if w.lower() in WEIGHTS:
                out.append(float(WEIGHTS[w.lower()]))
    return [int(v) if v == int(v) else round(v, 2) for v in out]


def families(value):
    out = []
    for part in value.split(','):
        p = part.strip().strip('"\'').strip()
        if p and re.match(r'^[A-Za-z][\w .-]*$', p) and 'var(' not in p:
            out.append(p)
    return out


def prose(s):
    """A string a user would read, not code: words, not identifiers, class lists, paths or values."""
    s = s.strip()
    if not s or len(s) > 300 or not re.search(r'[^\W\d_]', s):
        return False
    if re.search(r'[{}<>=;\\]|\$\{|://|^[./#@,]|\w\(', s) or colors_in(s):
        return False
    if re.fullmatch(r'-?\d*\.?\d+(px|pt|dp|sp|rem|em|%)?', s):
        return False
    words = s.split()
    if len(words) == 1:
        return bool(re.fullmatch(r'[A-Z][a-z]+[!?.]?|[A-Z][a-z]+(?:[\'’][a-z]+)?', s))
    if all(re.fullmatch(r'[a-z0-9:_./\[\]-]+', w) for w in words) and any(re.search(r'[-_:/\[]', w) for w in words):
        return False
    return True


def text_node(s):
    """Markup text with each {expression} as a placeholder ({name.path}, else {…}), or '' when the
    text around the expressions is code or empty."""
    held = []

    def hold(m):
        inner = m.group(0)[1:-1].strip()
        held.append('{' + inner + '}' if re.fullmatch(r'[A-Za-z_$][\w$.]*', inner) else '{…}')
        return f'\0{len(held) - 1}\0'

    prev = None
    while prev != s:
        prev, s = s, re.sub(r'\{[^{}]*\}', hold, s)
    s = html.unescape(re.sub(r'\s+', ' ', s)).strip()
    bare = re.sub(r'\0\d+\0', ' ', s)
    if not re.search(r'\w', bare) or re.search(r'[;=(){}\[\]]|=>|&&|\|\|', bare):
        return ''
    # A held expression may contain earlier placeholders; restore innermost last.
    while re.search(r'\0\d+\0', s):
        s = re.sub(r'\0(\d+)\0', lambda m: held[int(m.group(1))], s)
    return s


class Source:
    def __init__(self, base):
        self.base = base
        self.files = []
        self.token_raw = {}  # name -> (raw value, src)
        self.tokens = {}     # name -> entry
        self.usage_kind = {}
        self.colors, self.copy, self.states = {}, {}, {}
        self.nums = {'spacing': {}, 'radius': {}, 'fontSize': {}, 'fontWeight': {}}
        self.fams = {}
        self.variants = []
        self.blocks = {}  # style block -> [src, visual]
        self.rules = {}   # style block -> [(selector, declarations, file)]
        self.sheet = []   # [(compounds, combinators, specificity, order, {property: value})] for class-only selectors
        self.comps = {}   # component -> {component, uses, nests, src}

    # ---- reading

    def add_file(self, path):
        try:
            if os.path.getsize(path) > MAX_BYTES:
                return
            with open(path, 'rb') as f:
                data = f.read()
        except OSError:
            return
        if b'\0' in data[:8192]:
            return
        text = data.decode('utf-8', errors='replace')
        rel = os.path.relpath(path, self.base)
        starts = [0] + [m.end() for m in re.finditer('\n', text)]
        self.files.append((rel, os.path.splitext(path)[1].lower(), text, starts))

    def src(self, f, offset):
        return f'{f[0]}:{bisect.bisect_right(f[3], offset)}'

    # ---- tokens

    def collect_tokens(self):
        for f in self.files:
            rel, ext, text, _ = f
            if ext == '.json':
                self.json_file(f)
                continue
            for m in SIGIL_DEF.finditer(text):
                self.token_raw.setdefault(m.group(1), (m.group(2).strip(), self.src(f, m.start(1))))
            if ext in STYLE_EXT:
                continue
            for m in IDENT_DEF.finditer(text):
                name, raw = m.group(1), m.group(2)
                end = text.find('\n', m.end())
                lead = COLOR_START.match(raw)
                found = colors_in(raw[lead.end():] if lead else '', text[text.rfind('\n', 0, m.start()) + 1:end if end >= 0 else len(text)])
                if found and found[0][0] == 0 and not URL_ATTR.match(name + '=') and not re.search(r'colou?r$|background|fill|stroke|border|tint|foreground|shadow|outline',
                                                     name, re.I):
                    self.token_raw.setdefault(name, (found[0][1], self.src(f, m.start(1))))
        for name in self.token_raw:
            self.resolve(name, set())

    def resolve(self, name, seen):
        if name in self.tokens:
            return self.tokens[name]
        if name not in self.token_raw or name in seen:
            return None
        seen.add(name)
        raw, src = self.token_raw[name]
        if isinstance(raw, (int, float)):
            value = raw
        else:
            value = VAR.sub(lambda m: str((self.resolve(m.group(1), seen) or {}).get('value', '')), raw)
            value = re.sub(r'\{([\w.-]+)\}', lambda m: str((self.resolve(m.group(1), seen) or {}).get('value', m.group(0))), value)
            value = re.sub(r'(?<![\w-])(\$[\w-]+)', lambda m: str((self.resolve(m.group(1), seen) or {}).get('value', m.group(0))), value)
        entry = {'name': name, 'value': value, 'kind': None, 'src': src}
        self.tokens[name] = entry
        found = colors_in(str(value))
        if found and (len(found) == 1 or not isinstance(value, str) or str(value).strip().startswith(('#', 'rgb', 'hsl'))):
            entry.update(value=found[0][1], kind='color')
            return entry
        kind = kind_of(name)
        if is_family_name(name) and isinstance(value, str) and not NUM.fullmatch(value.strip()):
            entry.update(value=value.strip(), kind='fontFamily')
            return entry
        nums = numbers(str(value), kind)
        if kind and len(nums) == 1:
            entry.update(value=nums[0], kind=kind)
        elif len(nums) == 1 and re.fullmatch(r'\s*-?\d*\.?\d+(px|pt|dp|sp|rem|em)?\s*', str(value)):
            entry['value'] = nums[0]
        return entry

    def json_file(self, f):
        rel, _, text, _ = f
        if os.path.basename(rel) in SKIP_FILES:
            return
        try:
            data = json.loads(text, object_pairs_hook=list)
        except ValueError:
            return
        cursor = [0]

        def find_key(k):
            i = text.find(json.dumps(k), cursor[0])
            if i >= 0:
                cursor[0] = i + 1
            return max(i, 0)

        def walk(node, path):
            if not isinstance(node, list) or (node and not isinstance(node[0], tuple)):
                return
            keys = {k for k, _ in node}
            for k, v in node:
                if k.startswith('$') or (keys & {'$value', 'value'} and k in ('type', 'description', 'comment')):
                    continue
                at = find_key(k)
                p = path + [k]
                if isinstance(v, list) and v and isinstance(v[0], tuple):
                    inner = dict(v)
                    leaf = inner.get('$value', inner.get('value'))
                    if leaf is not None and not isinstance(leaf, list):
                        self.token_raw.setdefault('.'.join(p), (leaf, self.src(f, at)))
                        continue
                    walk(v, p)
                elif isinstance(v, bool) or v is None:
                    continue
                elif isinstance(v, (int, float)):
                    self.token_raw.setdefault('.'.join(p), (v, self.src(f, at)))
                elif isinstance(v, str):
                    if colors_in(v) or re.fullmatch(r'-?\d*\.?\d+(px|pt|dp|sp|rem|em)?', v.strip()) or is_family_name('.'.join(p)):
                        self.token_raw.setdefault('.'.join(p), (v, self.src(f, at)))
                    elif prose(v):
                        self.add_copy(v, self.src(f, at))

        walk(data, [])

    # ---- usages

    def add_num(self, kind, value, src, token=None):
        if value is None or value <= 0:
            return
        e = self.nums[kind].get(value)
        if e is None or (token and 'token' not in e):
            self.nums[kind][value] = {'value': value, **({'token': token} if token else {}), 'src': src}

    def add_family(self, value, src, token=None):
        for fam in families(value):
            if fam not in self.fams or (token and 'token' not in self.fams[fam]):
                self.fams[fam] = {'value': fam, **({'token': token} if token else {}), 'src': src}

    def add_color(self, hexv, src, token=None):
        e = self.colors.get(hexv)
        if e is None or (token and 'token' not in e):
            self.colors[hexv] = {'value': hexv, **({'token': token} if token else {}), 'src': src}

    def add_copy(self, text, src):
        text = re.sub(r'\s+', ' ', text).strip()
        if text and text not in self.copy:
            self.copy[text] = {'text': text, 'src': src}

    def add_state(self, component, state, src):
        state = state.lower().split('-')[0]
        key = (norm_component(component), state, src.rsplit(':', 1)[0])
        if key[0] and key not in self.states:
            self.states[key] = {'component': key[0], 'state': state, 'src': src}

    def add_variant(self, component, prop, values, src):
        values = [v.lower() for v in dict.fromkeys(values)]
        comp = norm_component(component)
        if comp and values:
            self.variants.append({'component': comp, 'prop': prop, 'values': values, 'src': src})

    def collect_usages(self):
        for t in self.tokens.values():
            if t['kind'] == 'color':
                self.add_color(t['value'], t['src'], t['name'])
            elif t['kind'] == 'fontFamily':
                self.add_family(t['value'], t['src'], t['name'])
            elif t['kind'] in self.nums and isinstance(t['value'], (int, float)):
                self.add_num(t['kind'], t['value'], t['src'], t['name'])
        for f in self.files:
            rel, ext, text, _ = f
            if ext == '.json':
                continue
            for start, line in zip(f[3], text.split('\n')):
                for off, hexv in colors_in(line, line):
                    self.add_color(hexv, self.src(f, start + off))
            self.declarations(f)
            if ext in STYLE_EXT:
                self.style_variants(f)
                self.style_blocks(f)
            else:
                self.code_variants(f)
                self.copy_from(f)
        for f in self.files:
            if f[1] not in STYLE_EXT and f[1] != '.json':
                self.component_uses(f)

    def declarations(self, f):
        rel, ext, text, _ = f
        style = ext in STYLE_EXT
        for m in DECL_USE.finditer(text):
            name, sep, value = m.groups()
            if name.startswith('-'):
                continue
            kind = kind_of(name)
            fam = re.sub(r'[^a-z]', '', name.lower()) in ('fontfamily', 'typeface', 'family')
            if not kind and not fam:
                continue
            refs = []

            def sub(v):
                t = self.resolve(v.group(1), set())
                if t is None:
                    return ' '
                refs.append(t)
                return f' \0{len(refs) - 1}\0 '

            value = VAR.sub(sub, value)
            if sep == '(' or not style:
                value = re.split(r'[),]', value)[0] if not fam or not style else value.split(')')[0]
            src = self.src(f, m.start(1))
            if fam:
                for i, t in enumerate(refs):
                    self.add_family(str(t['value']), src, t['name'])
                self.add_family(re.sub(r'\0\d+\0', '', value), src)
                continue
            for i in map(int, re.findall(r'\0(\d+)\0', value)):
                t = refs[i]
                if t['kind'] in (None, kind) and isinstance(t['value'], (int, float)):
                    if t['kind'] is None:
                        t['kind'] = kind
                    self.add_num(kind, t['value'], t['src'], t['name'])
            for v in numbers(re.sub(r'\0\d+\0', ' ', value), kind):
                self.add_num(kind, v, src)

    def style_variants(self, f):
        rel, _, text, _ = f
        groups = {}
        for m in MODIFIER.finditer(text):
            block, mod = m.group(1), m.group(2)
            if mod.lower() in STATE_WORDS:
                self.add_state(block, mod, self.src(f, m.start()))
            else:
                g = groups.setdefault(block, [[], self.src(f, m.start())])
                if mod not in g[0]:
                    g[0].append(mod)
        for block, (vals, src) in groups.items():
            self.add_variant(block, None, vals, src)
        for m in PSEUDO.finditer(text):
            self.add_state(m.group(1), m.group(2), self.src(f, m.start()))

    def style_blocks(self, f):
        text = re.sub(r'/\*[\s\S]*?\*/', lambda m: re.sub(r'[^\n]', ' ', m.group(0)), f[2])
        for m in RULE.finditer(text):
            visual = bool(VISUAL.search(m.group(2)))
            rule = (re.sub(r'\s*,\s*', ', ', ' '.join(m.group(1).split())), ' '.join(m.group(2).split()).rstrip(';') + ';', f[0])
            self.add_sheet_rule(rule[0], rule[1])
            for c in re.finditer(r'\.(-?[A-Za-z_][\w-]*)', m.group(1)):
                block = re.split(r'__|--', c.group(1))[0]
                rules = self.rules.setdefault(block, [])
                if rule not in rules and rule[1] != ';':
                    rules.append(rule)
                b = self.blocks.setdefault(block, [self.src(f, m.start(1) + len(m.group(1)) - len(m.group(1).lstrip())), False])
                b[1] = b[1] or visual

    def add_sheet_rule(self, selectors, decls):
        props = decl_dict(decls)
        for part in selectors.split(', '):
            chain, kinds = [], []
            for t in re.sub(r'\s*>\s*', ' > ', part).split():
                if t == '>' and kinds:
                    kinds[-1] = '>'
                elif COMPOUND.match(t):
                    chain.append(set(t[1:].split('.')))
                    kinds.append(' ')
                else:
                    chain = None
                    break
            if chain:
                self.sheet.append((chain, kinds, sum(map(len, chain)), len(self.sheet), props))

    def style_of(self, classes, inline, ancestors):
        """An element's declared properties from class-only rules and its style attribute; ancestors nearest first."""
        def matches(chain, kinds):
            if not chain[-1] <= set(classes):
                return False
            i, ups = len(chain) - 2, 0
            while i >= 0:
                child = kinds[i] == '>'
                while ups < len(ancestors) and not chain[i] <= set(ancestors[ups]):
                    if child:
                        return False
                    ups += 1
                if ups == len(ancestors):
                    return False
                ups += 1
                i -= 1
            return True
        out = {}
        for chain, kinds, spec, order, props in sorted(self.sheet, key=lambda r: (r[2], r[3])):
            if matches(chain, kinds):
                out.update(props)
        out.update(inline)
        return out

    def stretches(self, parent, child):
        """Whether a column flex parent stretches this child across: no align-items or align-self, no width."""
        direction = parent.get('flex-direction') or next((w for w in parent.get('flex-flow', '').split() if 'row' in w or 'column' in w), '')
        return (parent.get('display') in ('flex', 'inline-flex') and direction.startswith('column')
                and parent.get('align-items', 'stretch') in ('stretch', 'normal')
                and child.get('align-self', 'auto') in ('auto', 'stretch', 'normal')
                and child.get('width', 'auto') == 'auto' and child.get('inline-size', 'auto') == 'auto'
                and child.get('position', 'static') not in ('absolute', 'fixed'))

    def component_uses(self, f):
        rel, ext, text, _ = f
        work = BLANK_BLOCKS.sub(lambda m: re.sub(r'[^\n]', ' ', m.group(0)), text)
        markup = ext in ('.html', '.htm', '.xml', '.xhtml')
        stack = []  # [(tag, components, classes, inline style)]
        for m in TAG_OR_CLOSE.finditer(work):
            closing, tag, attrs = m.groups()
            if not markup and not closing and m.start() and re.match(r'[\w$.]', work[m.start() - 1]):
                continue  # a type argument such as List<Item>
            if closing:
                for i in range(len(stack) - 1, -1, -1):
                    if stack[i][0] == tag.lower():
                        del stack[i:]
                        break
                continue
            found, classes = [], []
            for a in CLASS_ATTR.finditer(attrs):
                raw = a.group(1) if a.group(1) is not None else a.group(2) if a.group(2) is not None else \
                    ' '.join(next(g for g in q.groups() if g is not None) for q in LITERAL.finditer(a.group(3)))
                for cls in re.sub(r'\$\{[^{}]*\}', ' ', raw).split():
                    if cls not in classes:
                        classes.append(cls)
                    if '__' in cls:
                        continue
                    block = cls.split('--')[0]
                    if self.blocks.get(block, [None, False])[1] and block not in found:
                        found.append(block)
            if not markup and tag[0].isupper() and '.' not in tag and tag != 'Fragment':
                found.append(tag)
            parent = next((s for t, s, _, _ in reversed(stack) if s), [])
            st = STYLE_ATTR.search(attrs)
            inline = decl_dict(next(g for g in st.groups() if g is not None)) if st else {}
            found = list({norm_component(n): n for n in reversed(found)}.values())[::-1]
            for name in found:
                key = norm_component(name)
                e = self.comps.setdefault(key, {'component': name, 'uses': 0, 'nests': [],
                                                'src': self.blocks[name][0] if name in self.blocks else self.src(f, m.start())})
                e['uses'] += 1
                if stack and markup and name in self.blocks:
                    ups = [c for _, _, c, _ in reversed(stack)]
                    pstyle = self.style_of(ups[0], stack[-1][3], ups[1:])
                    if self.stretches(pstyle, self.style_of(classes, inline, ups)):
                        where = ''.join('.' + c for c in ups[0]) or stack[-1][0]
                        e.setdefault('fill', []).append(f'{self.src(f, m.start())} in {where}')
                for p in parent:
                    nest = self.comps[norm_component(p)]['nests']
                    if norm_component(p) != key and key not in map(norm_component, nest):
                        nest.append(e['component'])
            if not attrs.rstrip().endswith('/') and tag.lower() not in VOID:
                stack.append((tag.lower(), found, classes, inline))

    def enclosing(self, text, offset):
        last = None
        for m in DECL_NAME.finditer(text, 0, offset + 200):
            if m.start() > offset and text.rfind('\n', 0, m.start()) >= text.rfind('\n', 0, offset):
                break
            last = m.group(1)
        return last

    def code_variants(self, f):
        rel, _, text, _ = f
        seen = set()
        for m in UNION.finditer(text):
            comp = self.enclosing(text, m.start()) or m.group(1)
            vals = re.findall(r'["\']([^"\'\n|]+)["\']', m.group(2))
            self.add_variant(comp, m.group(1), vals, self.src(f, m.start(1)))
        for m in ENUM.finditer(text):
            vals = []
            body = m.group(2)
            # An enum with `case` lines may also hold members; only the cases are values.
            items = ([i for c in re.findall(r'\bcase\s+([^\n;:{]+)', body) for i in c.split(',')]
                     if re.search(r'\bcase\b', body) else re.split(r'[,;\n]', body))
            for item in items:
                w = re.match(r'\s*\.?([A-Za-z_]\w*)', item)
                if w:
                    vals.append(w.group(1))
            self.add_variant(self.enclosing(text, m.start()) or m.group(1), m.group(1), vals, self.src(f, m.start(1)))
        bools = list(BOOL_UNION.finditer(text)) + list(BOOL_TYPED.finditer(text))
        for d in DECL_NAME.finditer(text):
            line_end = text.find('\n', d.end())
            bools += [b for b in BOOL_DEFAULT.finditer(text, d.end(), line_end if line_end >= 0 else len(text))]
        for b in sorted(bools, key=lambda b: b.start()):
            comp = self.enclosing(text, b.start())
            prop = b.group(1)
            if not comp or (comp, prop) in seen:
                continue
            seen.add((comp, prop))
            if prop.lower() in STATE_WORDS or re.sub(r'^(is|has)', '', prop).lower() in STATE_WORDS:
                self.add_state(comp, re.sub(r'^(is|has)(?=[A-Z])', '', prop), self.src(f, b.start(1)))
            else:
                self.add_variant(comp, prop, ['true', 'false'], self.src(f, b.start(1)))
        for m in UTILITY_STATE.finditer(text):
            comp = self.enclosing(text, m.start())
            if comp:
                self.add_state(comp, m.group(1), self.src(f, m.start()))
        for tag in TAG.finditer(text):
            t = tag.group(0)
            if re.search(r'\s(?:disabled|aria-disabled=["\']?true)(?=[\s>=/])', t):
                cls = re.search(r'class(?:Name)?\s*=\s*[{"\'`]+\s*([A-Za-z][\w-]*)', t)
                if cls:
                    self.add_state(re.split(r'--', cls.group(1))[0], 'disabled', self.src(f, tag.start()))

    def copy_from(self, f):
        rel, ext, text, _ = f
        work = BLANK_BLOCKS.sub(lambda m: re.sub(r'[^\n]', ' ', m.group(0)), text)
        markup = '</' in work or '/>' in work
        if markup:
            spans = []
            # Text between a tag and the next tag; `>` from an arrow or comparison is not a tag.
            for m in re.finditer(r'(?:<[A-Za-z/][^<>]*|/)>([^<>]+)(?=<[A-Za-z/])', work):
                s = text_node(m.group(1))
                if s:
                    lead = len(m.group(1)) - len(m.group(1).lstrip())
                    self.add_copy(s, self.src(f, m.start(1) + lead))
                    spans.append(m.span(1))
            for m in COPY_ATTR.finditer(work):
                if prose(m.group(3)) or re.search(r'[A-Za-z]', m.group(3)) and m.group(1) == 'placeholder':
                    self.add_copy(m.group(3), self.src(f, m.start(3)))
            for a, b in reversed(spans):
                work = work[:a] + re.sub(r'[^\n]', ' ', work[a:b]) + work[b:]
        if ext in ('.html', '.htm', '.xml', '.xhtml', '.svg'):
            return
        # Comments go first, so their quotes and words never read as literals.
        work = re.sub(r'/\*[\s\S]*?\*/', lambda m: re.sub(r'[^\n]', ' ', m.group(0)), work)
        work = re.sub(r'(?m)(^|[^:"\'\\])//[^\n]*', lambda m: m.group(1) + ' ' * (len(m.group(0)) - len(m.group(1))), work)
        work = re.sub(r'(?m)^\s*#(?![0-9a-fA-F]{3}).*$', lambda m: ' ' * len(m.group(0)), work)
        for m in LITERAL.finditer(work):
            s = next(g for g in m.groups() if g is not None)
            line_start = work.rfind('\n', 0, m.start()) + 1
            line = work[line_start:m.start()]
            if re.match(r'\s*(import|export\s.*\sfrom|from\s|require|#include|using|package|console\.|throw\b|logger?\.)', line):
                continue
            key = re.search(r'([\w:-]+)\s*(?::|=(?!=))\s*\{?\s*$', line)
            if key and CODE_KEYS.search(key.group(1)):
                continue
            if re.search(r'\b(require|import|querySelector\w*|getElementById|addEventListener|t|i18n\.t)\(\s*$', line):
                continue
            if prose(s):
                self.add_copy(s, self.src(f, m.start() + 1))

    # ---- output

    def merged_variants(self):
        out = []
        for g in self.variants:
            for h in out:
                if h['component'] == g['component'] and set(h['values']) & set(g['values']):
                    h['values'] += [v for v in g['values'] if v not in h['values']]
                    if h['prop'] is None:
                        h['prop'] = g['prop']
                    break
            else:
                out.append(dict(g, values=list(g['values'])))
        return out

    def component_css(self, name):
        """A style component's rules as {selector: declarations}, about CSS_CAP bytes at most."""
        css, left = {}, []
        for sel, decls, rel in self.rules.get(name, []):
            if left or len(json.dumps(css)) + len(sel) + len(decls) + 8 > CSS_CAP - 60:
                left.append(rel)
            else:
                css[sel] = decls
        if left:
            css['…'] = f"{len(left)} more rules in {', '.join(dict.fromkeys(left))}"
        return css

    def capped(self, e):
        if len(e.get('fill', [])) > FILL_CAP:
            e = dict(e, fill=e['fill'][:FILL_CAP] + [f"{len(e['fill']) - FILL_CAP} more"])
        return e

    def manifest(self):
        def by_value(d):
            return sorted(d.values(), key=lambda e: e['value'])
        tokens = [t for t in self.tokens.values() if t['kind']]
        return {
            'files': [f[0] for f in self.files],
            'tokens': tokens,
            'colors': by_value(self.colors),
            'spacing': by_value(self.nums['spacing']),
            'radii': by_value(self.nums['radius']),
            'fontSizes': by_value(self.nums['fontSize']),
            'fontWeights': by_value(self.nums['fontWeight']),
            'fontFamilies': list(self.fams.values()),
            'copy': list(self.copy.values()),
            'variants': self.merged_variants(),
            'states': list(self.states.values()),
            'components': [dict(self.capped(e), css=self.component_css(e['component'])) if self.rules.get(e['component'])
                           else self.capped(e) for e in sorted(self.comps.values(), key=lambda e: -e['uses'])],
        }


def gather(paths):
    files = []
    for p in paths:
        if os.path.isdir(p):
            for d, dirs, names in os.walk(p):
                dirs[:] = sorted(x for x in dirs if x not in SKIP_DIRS and not x.startswith('.') and not TEST_NAME.search(x))
                for n in sorted(names):
                    if os.path.splitext(n)[1].lower() not in SKIP_EXT and not n.endswith('.min.js') and not TEST_NAME.search(n):
                        files.append(os.path.join(d, n))
        else:
            files.append(p)
    return files


STYLE_LINK = re.compile(r'<link\b(?=[^>]*\brel\s*=\s*["\']?stylesheet)[^>]*\bhref\s*=\s*["\']([^"\']+)["\']', re.I)
STYLE_IMPORT = re.compile(r'@import\s+(?:url\(\s*)?["\']?([^"\')\s;]+)', re.I)


def with_style_sheets(files):
    """files plus the local style sheets they pull in: a page's <link rel=stylesheet>, a sheet's @import."""
    seen, out, i = {os.path.realpath(f) for f in files}, list(files), 0
    while i < len(out):
        f, i = out[i], i + 1
        ext = os.path.splitext(f)[1].lower()
        pattern = STYLE_IMPORT if ext in STYLE_EXT else STYLE_LINK if ext in ('.html', '.htm') else None
        if not pattern:
            continue
        try:
            with open(f, encoding='utf-8', errors='replace') as fh:
                text = fh.read(MAX_BYTES)
        except OSError:
            continue
        for ref in pattern.findall(text):
            if re.match(r'(?i)[a-z][a-z0-9+.-]*:|//', ref):
                continue
            p = os.path.normpath(os.path.join(os.path.dirname(f), ref.split('?')[0].split('#')[0]))
            if os.path.isfile(p) and os.path.realpath(p) not in seen:
                seen.add(os.path.realpath(p))
                out.append(p)
    return out


def build(paths):
    paths = [os.path.abspath(p) for p in paths]
    files = with_style_sheets(gather(paths))
    base = os.path.commonpath([p if os.path.isdir(p) else os.path.dirname(p) for p in paths]
                              + [os.path.dirname(f) for f in files])
    s = Source(base)
    for path in files:
        s.add_file(path)
    s.collect_tokens()
    s.collect_usages()
    return s.manifest()


def summary(m):
    return (f"{len(m['copy'])} copy, {len(m['colors'])} colors ({sum(t['kind'] == 'color' for t in m['tokens'])} tokens), "
            f"{len(m['spacing'])} spacing, {len(m['radii'])} radii, {len(m['fontSizes'])} font sizes, "
            f"{len(m['variants'])} variant groups, {len(m['states'])} states")


def main():
    ap = argparse.ArgumentParser(prog='figma_source.py', description='Extract a cited source manifest for figma_fidelity.py')
    ap.add_argument('paths', nargs='+', help='source files or directories')
    ap.add_argument('-o', '--out', help='write the manifest here and print a one-line summary')
    a = ap.parse_args()
    missing = [p for p in a.paths if not os.path.exists(p)]
    if missing:
        print(f"figma_source.py: no such file or directory: {', '.join(missing)}", file=sys.stderr)
        sys.exit(2)
    m = build(a.paths)
    if a.out:
        with open(a.out, 'w') as f:
            json.dump(m, f, indent=1, ensure_ascii=False)
        print(f'manifest: {summary(m)} → {a.out}')
        if m['components']:
            print('components: ' + ' · '.join(f"{c['component']} ×{c['uses']}" + (f" ({', '.join(c['nests'])})" if c['nests'] else '')
                                              for c in m['components']))
        groups = {}
        for v in m['variants']:
            groups.setdefault(v['component'], []).extend(v['values'])
        if groups:
            print('variants: ' + ' · '.join(f"{c}({', '.join(vs)})" for c, vs in groups.items()))
        groups = {}
        for st in m['states']:
            groups.setdefault(st['component'], []).append(st['state'])
        if groups:
            print('states: ' + ' · '.join(f"{c}({', '.join(sts)})" for c, sts in groups.items()))
        scales = [(label, m[key]) for label, key in (('spacing', 'spacing'), ('radii', 'radii'), ('font sizes', 'fontSizes'),
                                                     ('weights', 'fontWeights')) if m[key]]
        line = ' · '.join(f"{label} {' '.join(str(v['value']) for v in vs)}" for label, vs in scales)
        if m['fontFamilies']:
            line += (' · ' if line else '') + 'families ' + ', '.join(dict.fromkeys(f['value'] for f in m['fontFamilies']))
        if line:
            print('scales: ' + line)
    else:
        print(json.dumps(m, indent=1, ensure_ascii=False))


if __name__ == '__main__':
    main()
