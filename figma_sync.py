#!/usr/bin/env python3
"""Design sync between a repo's DESIGN.md and a Figma file's variables: report drift, propose a change.
The repo owns the tokens; nothing here applies itself.

  python3 figma_sync.py report [--repo <dir>] [--design <DESIGN.md>] [--file <figma-url>] [<code>...]
  python3 figma_sync.py propose --to code|figma [--repo <dir>] [--design <DESIGN.md>] [--file <figma-url>]
                        [--base <branch>] [--date YYYY-MM-DD] [<code>...]

report      figma_source.py's DESIGN.md read (broken refs), figma_source.py --check against the code
            (<code>, default the repo), and figma_fidelity.py --variables against the file (--file or
            FIGMA_FILE; without one that part is skipped). One read-only eval; no git, no writes.
propose --to code    Figma → DESIGN.md. The variables that differ from the base branch's DESIGN.md
            (and ones only Figma has, in colors, rounded and spacing) become a DESIGN.md edit on its own
            branch design-sync/<date>, from origin/<base> (--base, else origin/HEAD) in a temporary
            worktree, so the checkout is untouched. It stages DESIGN.md by path, pushes only that
            branch and runs gh pr create. With a design-sync PR already open it commits on that PR's
            branch instead, pushes it and updates the PR (gh pr edit). Never the base, never --force.
propose --to figma   DESIGN.md → Figma. After figma.saveVersionHistoryAsync, the variables Figma lacks
            or holds another value for go in new collections "Proposed <date>/<collection>" with a page
            "Proposed <date>" listing them; the live collections are not touched. Then one REST
            comment on that page (FIGMA_TOKEN; FIGMA_API_URL overrides https://api.figma.com).

Exit 0 when clean or proposed, 1 when report found drift, 2 when it could not run, 3 when Figma needs
a person first (signed out of a room, plugin system not ready): the fix is the stderr line `fix: ...`.
"""
import argparse, datetime, json, os, re, subprocess, sys, tempfile, urllib.request

HERE = os.path.dirname(os.path.realpath(__file__))
sys.path.insert(0, HERE)
import figma_fidelity as fidelity
import figma_source as source

SIMPLE_GROUPS = ('colors', 'rounded', 'spacing')


class Blocked(Exception):
    def __init__(self, code, message, fix=None):
        super().__init__(message)
        self.code, self.fix = code, fix


def fail(e):
    print(f'figma_sync.py: {e}', file=sys.stderr)
    if e.fix:
        print(f'fix: {e.fix}', file=sys.stderr)
    sys.exit(e.code)


# ---- Figma

def figma_eval(a, script, lib=False):
    cmd = [sys.executable, os.path.join(HERE, 'figma_run.py'), *(['--lib'] if lib else []), '--file', a.file,
           *(['--timeout', a.timeout] if a.timeout else []), '-e', script]
    r = subprocess.run(cmd, capture_output=True, text=True)
    if r.returncode != 0:
        err = (r.stderr or r.stdout).strip()
        if 'signed_out' in err:
            m = re.search(r'rooms signin (\S+) (\S+?)[,;]?(?:\s|$)', err)
            raise Blocked(3, err[:600], (f'rooms signin {m.group(1)} {m.group(2)}' if m else 'rooms signin <room> https://www.figma.com/login')
                          + ', sign in, then rerun')
        if 'figma is undefined' in err:
            raise Blocked(3, err[:600], "open and close any Figma plugin once in the file's tab (Figma's Tools menu), then rerun")
        raise Blocked(2, err[:600])
    try:
        return json.loads(r.stdout)
    except ValueError:
        raise Blocked(2, f'unreadable eval output: {r.stdout.strip()[:300]}')


def figma_vars(a):
    out = figma_eval(a, fidelity.INVENTORY_VARS, lib=True)
    if out.get('truncated'):
        print('figma_sync.py: the inventory was truncated; some variables were not read', file=sys.stderr)
    return fidelity.parse_vars(out.get('text', ''))


def file_key(url):
    m = re.search(r'/(?:file|design|proto|board)/([A-Za-z0-9]+)', url)
    return m.group(1) if m else url


# ---- report

def report(a):
    m = source.build([a.design])
    if not m.get('design'):
        raise Blocked(2, f'{a.design} has no DESIGN.md tokens')
    drift = False
    rep = source.check(a.design, a.code)
    print(source.render_check(rep))
    drift |= bool(rep['findings'])
    if not a.file:
        print('figma: skipped (no --file or FIGMA_FILE)')
    else:
        vrep = fidelity.variable_drift(m, figma_vars(a))
        print(fidelity.render_variables(vrep, m['design']['src']))
        drift |= bool(vrep['findings'])
    return 1 if drift else 0


# ---- propose --to code: DESIGN.md edits from Figma's values

def yaml_value(v, old=None, group=None, prop=None):
    """v written as a DESIGN.md value, in the old value's unit and quoting when there is one."""
    if isinstance(v, str) and re.fullmatch(r'#[0-9a-f]{6,8}', v):
        q = "'" if old and old.strip().startswith("'") else '"'
        return f'{q}{v}{q}'
    if isinstance(v, (int, float)) and not isinstance(v, bool):
        unit = re.search(r'\d(px|rem|em)\b', old or '')
        if unit and unit.group(1) in ('rem', 'em'):
            return f'{v / 16:g}{unit.group(1)}'
        if unit or (old is None and (group in ('rounded', 'spacing') or prop in ('fontSize', 'letterSpacing'))):
            return f'{v:g}px'
        return f'{v:g}'
    s = str(v)
    return s if re.fullmatch(r'[A-Za-z][\w .-]*', s) else json.dumps(s)


def set_line_value(line, value):
    m = re.match(r'^(\s*(?:"[^"]*"|\'[^\']*\'|[^:#]+?)\s*:\s*)(.*?)(\s+#.*)?$', line)
    return m.group(1) + value + (m.group(3) or '') if m else line


def group_end(lines, group):
    """(index of the last line in a top-level group's mapping, its children's indent), or None."""
    for i, l in enumerate(lines):
        if re.match(rf'^{group}\s*:\s*(#.*)?$', l):
            last, indent = i, None
            for j in range(i + 1, len(lines)):
                s = source.uncomment(lines[j])
                if not s.strip():
                    continue
                ind = len(s) - len(s.lstrip())
                if ind == 0 or lines[j].strip() in ('---', '```'):
                    break
                indent = indent if indent is not None else ind
                last = j
            return last, ' ' * (indent or 2)
    return None


def code_edits(text, design_rel, fvars):
    """(new DESIGN.md text, [change lines]) for the Figma values the text doesn't hold yet."""
    changes, notes = [], []
    for phase in ('base', 'themes'):
        with tempfile.TemporaryDirectory() as tmp:
            path = os.path.join(tmp, os.path.basename(design_rel))
            with open(path, 'w') as f:
                f.write(text)
            m = source.build([path])
        d = m.get('design')
        if not d:
            return text, [], ['no DESIGN.md tokens']
        exp = fidelity.expected_variables(m)
        base_theme = d['themes'][0] if d['themes'] else None
        colls = d['collections'][:1] if phase == 'base' else d['collections'][1:]
        lines = text.split('\n')
        ops = []  # (line index, 'set'|'after', text)
        by_var = {t['variable']: t for t in m['tokens'] if t.get('variable') and t.get('theme') in (None, base_theme)}
        for coll in colls:
            theme = d['themes'][d['collections'].index(coll)] if d['themes'] else None
            have = fvars.get(coll, {})
            for (c, var), t in exp.items():
                if c != coll or var not in have or fidelity.same_value(t, have[var]):
                    continue
                n = int(t['src'].rsplit(':', 1)[1]) - 1
                raw = source.uncomment(lines[n]).split(':', 1)[1].strip()
                if '{' in raw:
                    notes.append(f"{t['name']} is a ref ({raw}); Figma {coll} has {have[var]}: edit by hand")
                    continue
                parts = var.split('/')
                if t.get('theme') in (None, base_theme) and theme not in (None, base_theme):
                    if parts[0] not in SIMPLE_GROUPS or len(parts) != 2:
                        notes.append(f'{coll} {var} = {have[var]} differs from the base; add a -{theme} override by hand')
                        continue
                    indent = re.match(r'^\s*', lines[n]).group(0)
                    ops.append((n, 'after', f'{indent}{parts[1]}-{theme}: {yaml_value(have[var], raw, parts[0])}'))
                    changes.append(f"{parts[0]}.{parts[1]}-{theme}: new, {have[var]} (Figma {coll})")
                else:
                    ops.append((n, 'set', set_line_value(lines[n], yaml_value(have[var], raw, parts[0], parts[-1]))))
                    changes.append(f"{t['name']}: {t['value']} → {have[var]} (Figma {coll})")
            if phase == 'base':
                for var, v in have.items():
                    parts = var.split('/')
                    if (coll, var) in exp:
                        continue
                    if parts[0] not in SIMPLE_GROUPS or len(parts) != 2 or not re.fullmatch(r'[\w-]+', parts[1]) or var in by_var:
                        notes.append(f'{coll} {var} = {v} is only in Figma; add it by hand')
                        continue
                    end = group_end(lines, parts[0])
                    if end is None:
                        notes.append(f'{coll} {var} = {v} is only in Figma and DESIGN.md has no {parts[0]} group; add it by hand')
                        continue
                    ops.append((end[0], 'after', f'{end[1]}{parts[1]}: {yaml_value(v, None, parts[0])}'))
                    changes.append(f'{parts[0]}.{parts[1]}: new, {v} (Figma {coll})')
        for n, op, s in sorted(ops, key=lambda o: o[0], reverse=True):
            if op == 'set':
                lines[n] = s
            else:
                lines.insert(n + 1, s)
        text = '\n'.join(lines)
    return text, changes, notes


def git(repo, *args, check=True):
    r = subprocess.run(['git', '-C', repo, *args], capture_output=True, text=True)
    if check and r.returncode != 0:
        raise Blocked(2, f"git {' '.join(args)}: {(r.stderr or r.stdout).strip()[:400]}")
    return r.stdout.strip()


def gh(repo, *args):
    r = subprocess.run(['gh', *args], capture_output=True, text=True, cwd=repo)
    if r.returncode != 0:
        raise Blocked(2, f"gh {' '.join(args[:2])}: {(r.stderr or r.stdout).strip()[:400]}")
    return r.stdout.strip()


def pr_body(date, changes, notes):
    body = [f'DESIGN.md tokens from the Figma variables, {date} (`figma_sync.py propose --to code`).', '', '## Changes', '']
    body += [f'- {c}' for c in changes]
    if notes:
        body += ['', '## Not proposed', ''] + [f'- {n}' for n in notes]
    return '\n'.join(body) + '\n'


def propose_code(a):
    repo = a.repo
    rel = os.path.relpath(os.path.abspath(a.design), repo)
    base = a.base or git(repo, 'symbolic-ref', '--short', 'refs/remotes/origin/HEAD', check=False).removeprefix('origin/') or 'main'
    fvars = figma_vars(a)
    git(repo, 'fetch', '-q', 'origin', base)
    text = git(repo, 'show', f'origin/{base}:{rel}') + '\n'
    new, changes, notes = code_edits(text, rel, fvars)
    if not changes:
        print(f'nothing to propose: origin/{base}:{rel} holds every Figma value it can')
        for n in notes:
            print(f'not proposed: {n}')
        return 0
    prs = [p for p in json.loads(gh(repo, 'pr', 'list', '--state', 'open', '--json', 'number,headRefName,baseRefName,url', '--limit', '100') or '[]')
           if p['headRefName'].startswith('design-sync/')]
    pr = prs[0] if prs else None
    if pr:
        branch = pr['headRefName']
        git(repo, 'fetch', '-q', 'origin', branch)
        text = git(repo, 'show', f'origin/{branch}:{rel}') + '\n'
        new, changes, notes = code_edits(text, rel, fvars)
        if not changes:
            print(f"nothing to propose: the open PR {pr['url']} holds every Figma value it can")
            return 0
    else:
        branch, k = f'design-sync/{a.date}', 2
        while git(repo, 'rev-parse', '--verify', '--quiet', f'refs/heads/{branch}', check=False) or \
                git(repo, 'ls-remote', '--heads', 'origin', branch, check=False):
            branch, k = f'design-sync/{a.date}-{k}', k + 1
    tmp = tempfile.mkdtemp(prefix='figma-sync-')
    wt = os.path.join(tmp, 'wt')
    try:
        if pr:
            git(repo, 'worktree', 'add', '-q', '--detach', wt, f'origin/{branch}')
        else:
            git(repo, 'worktree', 'add', '-q', '-b', branch, wt, f'origin/{base}')
        with open(os.path.join(wt, rel), 'w') as f:
            f.write(new.rstrip('\n') + '\n')
        git(wt, 'add', '--', rel)
        git(wt, 'commit', '-q', '-m', f'DESIGN.md: tokens from Figma {a.date}', '-m', '\n'.join(f'- {c}' for c in changes))
        git(wt, 'push', '-q', 'origin', f'HEAD:refs/heads/{branch}' if pr else branch)
    finally:
        git(repo, 'worktree', 'remove', '--force', wt, check=False)
        os.rmdir(tmp) if os.path.isdir(tmp) and not os.listdir(tmp) else None
    body = pr_body(a.date, changes, notes)
    if pr:
        gh(repo, 'pr', 'edit', str(pr['number']), '--body', body)
        url = pr['url']
        print(f'updated {url} ({branch}): {len(changes)} change(s)')
    else:
        url = gh(repo, 'pr', 'create', '--base', base, '--head', branch, '--title', f'Design sync {a.date}: DESIGN.md tokens from Figma',
                 '--body', body).splitlines()[-1]
        print(f'opened {url} ({branch} → {base}): {len(changes)} change(s)')
    for c in changes:
        print(f'  {c}')
    for n in notes:
        print(f'not proposed: {n}')
    return 0


# ---- propose --to figma: a Proposed page and collections, behind a version checkpoint

PROPOSE = r'''
(async function (P) {
  var version = await figma.saveVersionHistoryAsync(P.title);
  var taken = figma.root.children.map(function (p) { return p.name; })
    .concat((await figma.variables.getLocalVariableCollectionsAsync()).map(function (c) { return c.name.split('/')[0]; }));
  var name = P.name, k = 2;
  while (taken.indexOf(name) >= 0) name = P.name + ' (' + k++ + ')';
  var page = figma.createPage();
  page.name = name;
  await figma.loadFontAsync({ family: 'Inter', style: 'Regular' });
  var frame = figma.createFrame();
  page.appendChild(frame);
  frame.name = name;
  frame.layoutMode = 'VERTICAL';
  frame.itemSpacing = 8;
  frame.paddingTop = frame.paddingBottom = frame.paddingLeft = frame.paddingRight = 24;
  frame.primaryAxisSizingMode = 'AUTO';
  frame.counterAxisSizingMode = 'AUTO';
  var n = 0, cols = [];
  for (var i = 0; i < P.collections.length; i++) {
    var g = P.collections[i], c = figma.variables.createVariableCollection(name + '/' + g.name);
    cols.push(c.name);
    for (var j = 0; j < g.rows.length; j++) {
      var r = g.rows[j], v = figma.variables.createVariable(r.variable, c, r.type);
      v.setValueForMode(c.defaultModeId, r.value);
      n++;
      var row = figma.createFrame();
      frame.appendChild(row);
      row.name = g.name + ' ' + r.variable;
      row.layoutMode = 'HORIZONTAL';
      row.itemSpacing = 8;
      row.primaryAxisSizingMode = 'AUTO';
      row.counterAxisSizingMode = 'AUTO';
      row.fills = [];
      if (r.type === 'COLOR') {
        var sw = figma.createRectangle();
        row.appendChild(sw);
        sw.resize(16, 16);
        sw.fills = [figma.variables.setBoundVariableForPaint({ type: 'SOLID', color: { r: 0, g: 0, b: 0 } }, 'color', v)];
      }
      var t = figma.createText();
      row.appendChild(t);
      t.fontName = { family: 'Inter', style: 'Regular' };
      t.characters = r.label;
    }
  }
  return { page: page.id, frame: frame.id, name: name, version: version && version.id, collections: cols, variables: n };
})
'''


def figma_value(t):
    v = t['value']
    if t.get('kind') == 'color' or (isinstance(v, str) and re.fullmatch(r'#[0-9a-f]{6}(?:[0-9a-f]{2})?', v)):
        r, g, b = fidelity.rgb(v)
        return 'COLOR', {'r': r / 255, 'g': g / 255, 'b': b / 255, 'a': int(v[7:9], 16) / 255 if len(v) == 9 else 1}
    if isinstance(v, (int, float)) and not isinstance(v, bool):
        return 'FLOAT', v
    return 'STRING', str(v)


def propose_figma(a):
    m = source.build([a.design])
    if not m.get('design'):
        raise Blocked(2, f'{a.design} has no DESIGN.md tokens')
    vrep = fidelity.variable_drift(m, figma_vars(a))
    rows = [r for r in vrep['findings'] if r['kind'] in ('missing', 'different')]
    if not rows:
        print(f"nothing to propose: Figma holds every DESIGN.md token in {', '.join(vrep['collections'])}")
        return 0
    exp = fidelity.expected_variables(m)
    groups = []
    for coll in m['design']['collections']:
        mine = []
        for r in rows:
            if r['collection'] == coll:
                typ, val = figma_value(exp[(coll, r['variable'])])
                label = f"{coll} {r['variable']}: " + (f"{r['figma']} → {r['source']}" if r['kind'] == 'different' else f"missing, {r['source']}") \
                    + f" ({r['src']})"
                mine.append({'variable': r['variable'], 'type': typ, 'value': val, 'label': label})
        if mine:
            groups.append({'name': coll, 'rows': mine})
    name = f'Proposed {a.date}'
    payload = {'title': f'design-sync: before {name}', 'name': name, 'collections': groups}
    out = figma_eval(a, PROPOSE + f'({json.dumps(payload)})')
    print(f"proposed {out['variables']} variable(s) on page \"{out['name']}\" [{out['page']}] in {', '.join(out['collections'])}; "
          f"version {out['version']} saved before")
    token = os.environ.get('FIGMA_TOKEN')
    if not token:
        print('comment: skipped (no FIGMA_TOKEN)')
        return 0
    api = os.environ.get('FIGMA_API_URL', 'https://api.figma.com').rstrip('/')
    msg = (f"{out['name']}: {out['variables']} variable(s) from DESIGN.md ({m['design']['src']}) that Figma lacks or holds "
           f"differently, in {', '.join(out['collections'])}. Review the page; nothing was applied to the live collections.")
    req = urllib.request.Request(f'{api}/v1/files/{file_key(a.file)}/comments', method='POST',
                                 data=json.dumps({'message': msg, 'client_meta': {'node_id': out['frame'], 'node_offset': {'x': 0, 'y': 0}}}).encode(),
                                 headers={'X-Figma-Token': token, 'Content-Type': 'application/json'})
    try:
        with urllib.request.urlopen(req, timeout=30) as resp:
            cid = json.loads(resp.read() or b'{}').get('id')
        print(f'comment: posted {cid} on {out["frame"]}')
    except (OSError, ValueError) as e:
        print(f'comment: failed ({e}); the page stands', file=sys.stderr)
    return 0


def main():
    ap = argparse.ArgumentParser(prog='figma_sync.py', description='Report or propose design sync between DESIGN.md and Figma variables')
    ap.add_argument('action', choices=('report', 'propose'))
    ap.add_argument('code', nargs='*', help='code files or dirs for the DESIGN.md check (default: the repo)')
    ap.add_argument('--to', choices=('code', 'figma'), help='propose: the side that gets the proposal')
    ap.add_argument('--repo', default='.', help='the repo holding DESIGN.md (default: .)')
    ap.add_argument('--design', help='its DESIGN.md (default: <repo>/DESIGN.md)')
    ap.add_argument('--file', default=os.environ.get('FIGMA_FILE'), help='Figma file URL or key (default: FIGMA_FILE)')
    ap.add_argument('--base', help='propose --to code: the base branch (default: origin/HEAD)')
    ap.add_argument('--date', default=datetime.date.today().isoformat(), help='the date in branch and page names')
    ap.add_argument('--timeout', help='seconds each eval may await (passed to figma_run.py)')
    a = ap.parse_args()
    a.repo = os.path.abspath(a.repo)
    a.design = os.path.abspath(a.design or os.path.join(a.repo, 'DESIGN.md'))
    a.code = a.code or [a.repo]
    if not os.path.exists(a.design):
        fail(Blocked(2, f'no DESIGN.md at {a.design}'))
    if a.action == 'propose' and not a.to:
        ap.error('propose needs --to code or --to figma')
    if a.action == 'propose' and not a.file:
        ap.error('propose needs --file or FIGMA_FILE')
    try:
        sys.exit(report(a) if a.action == 'report' else propose_code(a) if a.to == 'code' else propose_figma(a))
    except Blocked as e:
        fail(e)


if __name__ == '__main__':
    main()
