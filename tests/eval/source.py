#!/usr/bin/env python3
"""What a fixture app's screens contain, read from its HTML and CSS, for the scorers.

A task with "fixture": "<dir>" gets EVAL.expect from load(fixtures/<dir>) instead of
fixtures/expect.json (the hand-kept picture of fixtures/app), and {FIXTURE} in its prompt is
that dir. The scorer's picture of the source comes from the same files the session reads, so
the two cannot drift:

  colors   every --color-<name>: #hex in the tokens.css beside the stylesheet the screens link
  screens  per *.html screen (components.html, the catalog, is not a screen): its <h1> title,
           every visible string in order (text, input values and placeholders), the <p>
           paragraphs, and the tree of component usages and layout roles in it
  axes, sizing, slots, roles  how the scorers read that tree (below)

A usage is an element whose class list names a component block (`badge`, `list-item`...) or a
layout role (`toolbar`, `sidebar`...); `block--modifier` classes are its variant values. Each
usage records its own strings (`anchors`, the ones no nested usage owns), every string inside it
(`texts`), its nested usages (`kids`) and, for builders, its content in order (`items`: strings
and kid indexes). `key` is the string that identifies it on a screen: its first own string, or
its first string at all when it has none of its own (Tabs, layout roles); icons have none.

  python3 tests/eval/source.py harbor      # dump what the scorers see
"""
import json, os, re, sys
from html.parser import HTMLParser

HERE = os.path.dirname(os.path.abspath(__file__))

COMPONENTS = {'app-header': 'AppHeader', 'avatar': 'Avatar', 'badge': 'Badge', 'button': 'Button', 'card': 'Card',
              'icon': 'Icon', 'input': 'Input', 'list-item': 'ListItem', 'stat-card': 'StatCard', 'tabs': 'Tabs',
              'tab': 'Tab'}
ROLE_CLASSES = {'layout': 'container', 'toolbar': 'toolbar', 'columns': 'columns', 'main': 'main',
                'sidebar': 'sidebar', 'tag-list': 'tagRow', 'tag': 'tag', 'fab': 'fab'}

TRUE = ['true', 'yes', 'on', 'selected', 'active', 'current', 'checked']
FALSE = ['false', 'no', 'off', 'default', 'inactive', 'unselected', 'rest', 'normal', 'idle', 'none']
# Variant axes per component: the default value (no modifier), and per value the option names a
# Figma variant may use for it (compared lowercase, letters and digits only).
AXES = {
    'Avatar': {'size': {'default': 'sm', 'values': {
        'sm': ['sm', 'small', 's', 'xs', 'default', 'regular', '24', '28', '32', '36'],
        'lg': ['lg', 'large', 'l', 'xl', '48', '56', '64']}}},
    'Badge': {'tone': {'default': 'neutral', 'values': {
        'neutral': ['neutral', 'default', 'gray', 'grey', 'info', 'muted', 'subtle', 'secondary', 'base'],
        'success': ['success', 'positive', 'green', 'good', 'ok'],
        'warning': ['warning', 'warn', 'caution', 'amber', 'yellow', 'attention', 'pending'],
        'danger': ['danger', 'error', 'critical', 'negative', 'red', 'destructive', 'alert']}}},
    'Button': {'variant': {'default': 'primary', 'values': {
        'primary': ['primary', 'filled', 'solid', 'main', 'cta', 'brand'],
        'secondary': ['secondary', 'outline', 'outlined', 'ghost', 'neutral', 'subtle', 'bordered']}}},
    'Input': {'state': {'default': 'default', 'values': {
        'default': ['default', 'rest', 'normal', 'idle', 'enabled', 'filled', 'empty', 'base', 'placeholder'],
        'focus': ['focus', 'focused', 'active', 'focusvisible'],
        'error': ['error', 'invalid', 'danger', 'errored', 'negative'],
        'disabled': ['disabled', 'readonly', 'inactive', 'locked']}}},
    'Tab': {'selected': {'default': 'false', 'boolean': True, 'values': {'false': FALSE, 'true': TRUE}}},
    'ListItem': {'selected': {'default': 'false', 'boolean': True, 'values': {'false': FALSE, 'true': TRUE}}},
    'Icon': {'name': {'default': None, 'values': {
        'bell': ['bell', 'notification', 'notifications', 'alert'],
        'plus': ['plus', 'add', 'new', 'create'],
        'search': ['search', 'magnifier', 'magnifyingglass', 'find', 'lookup']}}},
}
# What the CSS says each component's box does inside its parent, per axis, as Figma sizing.
SIZING = {
    'AppHeader': {'h': 'FILL'}, 'Tabs': {'h': 'FILL'}, 'StatCard': {'h': 'FILL'}, 'ListItem': {'h': 'FILL'},
    'Input': {'h': 'FILL'}, 'Badge': {'h': 'HUG', 'v': 'HUG'}, 'Button': {'h': 'HUG', 'v': 'HUG'},
    'Tab': {'h': 'HUG', 'v': 'HUG'}, 'Avatar': {'h': 'FIXED', 'v': 'FIXED'},
}
# Column flex boxes with no align-items (harbor/components.css): a child with no width of its
# own (AUTO_WIDTH) stretches across one, so a usage straight inside it expects FILL across.
# .stat-card is not one: `.stat-card .badge { align-self: flex-start }`.
STRETCH = {'card', 'page', 'list', 'fields', 'pairs', 'screen'}
AUTO_WIDTH = {'Badge', 'Button', 'Tab'}
# Components whose content differs per usage (a card holds anything): an instance of one only
# has to carry its own strings, not its nested usages.
SLOTS = ['Card']
# harbor-pages/notes.html's layout roles, as Figma properties (the CSS in its <style> block).
ROLES = {
    'container': {'h': 'FILL', 'maxWidth': 1120},
    'toolbar': {'h': 'FILL', 'v': 'HUG', 'justify': 'SPACE_BETWEEN'},
    'columns': {'h': 'FILL', 'v': 'HUG'},
    'main': {'h': 'FILL', 'v': 'HUG'},
    'sidebar': {'h': 'FIXED', 'v': 'HUG', 'width': 280},
    'tagRow': {'h': 'FILL', 'v': 'HUG', 'wrap': 'WRAP'},
    'tag': {'h': 'HUG', 'v': 'HUG'},
    'fab': {'h': 'HUG', 'v': 'HUG', 'pin': ['MAX', 'MAX']},
    'paragraph': {'h': 'FILL', 'textAutoResize': 'HEIGHT'},
}
VOID = {'input', 'br', 'img', 'meta', 'link', 'hr', 'use', 'path', 'circle'}
SKIP = {'head', 'title', 'style', 'script', 'svg'}


def ws(s):
    return re.sub(r'\s+', ' ', s).strip()


def modifier_values(c, mods):
    props = {}
    for axis, spec in AXES.get(c, {}).items():
        props[axis] = spec['default']
        for m in mods:
            if m in spec['values'] or (spec.get('boolean') and m == axis):
                props[axis] = 'true' if spec.get('boolean') else m
    return props


class Screen(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.stack = []      # (tag, usage or None, skip, classes)
        self.root = {'c': 'Screen', 'anchors': [], 'texts': [], 'kids': [], 'items': []}
        self.title = None
        self.paragraphs = []
        self.para = None
        self.h1 = False

    def owner(self):
        for _, u, _, _ in reversed(self.stack):
            if u is not None:
                return u
        return self.root

    def chain(self):
        return [self.root] + [u for _, u, _, _ in self.stack if u is not None]

    def skipping(self):
        return any(s for _, _, s, _ in self.stack)

    def add_text(self, s):
        s = ws(s)
        if not s or self.skipping():
            return
        own = self.owner()
        own['anchors'].append(s)
        own['items'].append({'s': s})
        for u in self.chain():
            u['texts'].append(s)
        if self.h1 and self.title is None:
            self.title = s
        if self.para is not None:
            self.para.append(s)

    def handle_starttag(self, tag, attrs):
        a = dict(attrs)
        classes = (a.get('class') or '').split()
        usage = None
        for cls in classes:
            if cls in COMPONENTS or cls in ROLE_CLASSES:
                c = COMPONENTS.get(cls) or ROLE_CLASSES[cls]
                mods = [m[len(cls) + 2:] for m in classes if m.startswith(cls + '--')]
                usage = {'c': c, 'props': modifier_values(c, mods), 'anchors': [], 'texts': [], 'kids': [], 'items': []}
                if c in AUTO_WIDTH and self.stack and STRETCH & set(self.stack[-1][3]):
                    usage['sizing'] = {'h': 'FILL'}
                parent = self.owner()
                parent['items'].append({'k': len(parent['kids'])})
                parent['kids'].append(usage)
                break
        if tag == 'input':
            if usage is None:
                self.add_text(a.get('value') or a.get('placeholder') or '')
            return
        if tag in VOID:
            return
        self.stack.append((tag, usage, tag in SKIP, classes))
        if tag == 'h1':
            self.h1 = True
        if tag == 'p':
            self.para = []

    def handle_startendtag(self, tag, attrs):
        if tag == 'input':
            self.handle_starttag(tag, attrs)
        # anything else self-closed (<use/>, <path/>) holds no text

    def handle_endtag(self, tag):
        if tag in VOID:
            return
        while self.stack:
            t, _, _, _ = self.stack.pop()
            if t == tag:
                break
        if tag == 'h1':
            self.h1 = False
        if tag == 'p' and self.para is not None:
            self.paragraphs.append(' '.join(self.para))
            self.para = None

    def handle_data(self, data):
        self.add_text(data)


def finish(u):
    own = u['anchors']
    u['key'] = own[0] if own else (u['texts'][0] if u['texts'] and u['c'] != 'Icon' else None)
    for k in u['kids']:
        finish(k)
    return u


def parse_screen(path):
    p = Screen()
    with open(path) as f:
        p.feed(f.read())
    root = p.root
    for k in root['kids']:
        finish(k)
    return {'file': os.path.basename(path), 'title': p.title, 'strings': root['texts'], 'paragraphs': p.paragraphs,
            'items': root['items'], 'usages': root['kids']}


def colors(path):
    with open(path) as f:
        return {k: v.lower() for k, v in re.findall(r'--color-([a-z0-9-]+):\s*(#[0-9a-fA-F]{6});', f.read())}


def tokens_path(d, screen):
    with open(os.path.join(d, screen)) as f:
        css = re.search(r'<link rel="stylesheet" href="([^"]+)"', f.read())
    return os.path.join(os.path.dirname(os.path.normpath(os.path.join(d, css.group(1)))), 'tokens.css')


def load(name):
    d = os.path.join(HERE, 'fixtures', name)
    files = sorted(f for f in os.listdir(d) if f.endswith('.html') and f != 'components.html')
    screens = {f[:-5]: parse_screen(os.path.join(d, f)) for f in files}
    return {'fixture': name, 'colors': colors(tokens_path(d, files[0])), 'screens': screens, 'axes': AXES,
            'sizing': SIZING, 'slots': SLOTS, 'roles': ROLES}


def expect_for(task):
    """EVAL.expect for a task: its fixture's derived picture, or fixtures/expect.json."""
    if task.get('fixture', 'app') != 'app':
        return load(task['fixture'])
    with open(os.path.join(HERE, 'fixtures', 'expect.json')) as f:
        return json.load(f)


if __name__ == '__main__':
    json.dump(load(sys.argv[1] if len(sys.argv) > 1 else 'harbor'), sys.stdout, indent=1)
    print()
