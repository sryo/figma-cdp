#!/usr/bin/env python3
"""Headless Claude Code sessions pinned to one copy of the skill.

A session loads the skill under test, not ~/.claude/skills/figma-cdp, by:
  --plugin-dir <wrapper>        a generated plugin "figma-eval" whose skills/figma-cdp is a
                                symlink to the copy (a git worktree of this repo)
  --setting-sources project     user settings and ~/.claude/skills stay unloaded, so the user's
                                own figma-cdp (and figma-text, which competes for Figma URLs)
                                never appears; the session's cwd is an empty temp dir, so
                                "project" adds nothing either
  --strict-mcp-config           no MCP servers: the skill reaches Figma through its helpers
The prompt starts with /figma-eval:figma-cdp so the skill loads on every run (triggering is
not what the eval measures). Auth is the user's own CLI login (`claude auth login`, or
CLAUDE_CODE_OAUTH_TOKEN / ANTHROPIC_API_KEY in the environment); env vars a host Claude Code
session sets for its own children are dropped.

  python3 tests/eval/session.py probe [--skill-dir <dir>]

runs the mechanism against a local fake Messages API (no auth, no cost): the fake answers the
first turn by calling the Skill tool and records the skill body the CLI sends back, then
checks it carries a marker planted in a temp copy of the skill.
"""
import argparse, http.server, json, os, shutil, subprocess, sys, tempfile, threading, time

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
PLUGIN = 'figma-eval'
SKILL = f'{PLUGIN}:figma-cdp'
TOOLS = 'Bash,Read,Write,Edit,Glob,Grep,Agent,Task,Skill,TodoWrite'
HOST_ENV = ('CLAUDECODE', 'CLAUDE_PID', 'CLAUDE_EFFORT', 'AI_AGENT', 'BAGGAGE', 'CLAUDE_PREVIEW_CLASSIFIER_FLOOR')


def make_plugin(skill_dir, parent):
    """A plugin dir under parent exposing skill_dir as figma-eval:figma-cdp."""
    root = os.path.join(parent, 'plugin')
    os.makedirs(os.path.join(root, '.claude-plugin'), exist_ok=True)
    os.makedirs(os.path.join(root, 'skills'), exist_ok=True)
    with open(os.path.join(root, '.claude-plugin', 'plugin.json'), 'w') as f:
        json.dump({'name': PLUGIN, 'version': '0.0.0', 'description': 'figma-cdp under evaluation'}, f)
    link = os.path.join(root, 'skills', 'figma-cdp')
    if os.path.lexists(link):
        os.unlink(link)
    os.symlink(os.path.realpath(skill_dir), link)
    return root


def clean_env(extra=None):
    """The caller's env minus what a host Claude Code session sets for its children."""
    e = {k: v for k, v in os.environ.items()
         if k not in HOST_ENV and not (k.startswith('CLAUDE_CODE_') and k != 'CLAUDE_CODE_OAUTH_TOKEN')}
    if os.environ.get('CLAUDE_CODE_SDK_HAS_HOST_AUTH_REFRESH'):
        e.pop('ANTHROPIC_BASE_URL', None)
    e.update(extra or {})
    return e


def command(claude, plugin, prompt, model=None, add_dirs=(), budget=None, slash=True):
    cmd = [claude, '-p', f'/{SKILL} {prompt}' if slash else prompt, '--output-format', 'stream-json', '--verbose',
           '--no-session-persistence', '--setting-sources', 'project', '--strict-mcp-config', '--no-chrome',
           '--plugin-dir', plugin, '--permission-mode', 'dontAsk', '--allowedTools', TOOLS]
    for d in add_dirs:
        cmd += ['--add-dir', d]
    if model:
        cmd += ['--model', model]
    if budget:
        cmd += ['--max-budget-usd', str(budget)]
    return cmd


def parse_stream(lines):
    """Metrics from a stream-json transcript: the result event's totals (subagents included,
    via modelUsage) plus tool calls counted on every assistant message, subagents' too."""
    init, result, calls, failed, skill_seen, text = None, None, 0, 0, False, ''
    for line in lines:
        try:
            ev = json.loads(line)
        except ValueError:
            continue
        t = ev.get('type')
        if t == 'system' and ev.get('subtype') == 'init':
            init = ev
        elif t == 'assistant':
            for c in ev.get('message', {}).get('content', []):
                if c.get('type') == 'tool_use':
                    calls += 1
        elif t == 'user':
            content = ev.get('message', {}).get('content', [])
            for c in content if isinstance(content, list) else []:
                if c.get('type') == 'tool_result' and c.get('is_error'):
                    failed += 1
                if c.get('type') == 'text' and 'Base directory for this skill' in c.get('text', ''):
                    skill_seen = True
        elif t == 'result':
            result = ev
    m = {'tool_calls': calls, 'failed_tool_calls': failed}
    if init:
        m['skill_listed'] = SKILL in (init.get('skills') or [])
    if result:
        mu = result.get('modelUsage') or {}
        tok = {'input_tokens': 'inputTokens', 'output_tokens': 'outputTokens',
               'cache_read_tokens': 'cacheReadInputTokens', 'cache_write_tokens': 'cacheCreationInputTokens'}
        for k, src in tok.items():
            m[k] = sum(int(u.get(src) or 0) for u in mu.values())
        if not mu:
            u = result.get('usage') or {}
            m.update(input_tokens=u.get('input_tokens', 0), output_tokens=u.get('output_tokens', 0),
                     cache_read_tokens=u.get('cache_read_input_tokens', 0),
                     cache_write_tokens=u.get('cache_creation_input_tokens', 0))
        m['tokens_total'] = m['input_tokens'] + m['output_tokens'] + m['cache_read_tokens'] + m['cache_write_tokens']
        m['cost_usd'] = float(result.get('total_cost_usd') or 0)
        m['turns'] = int(result.get('num_turns') or 0)
        m['session_error'] = bool(result.get('is_error'))
        text = result.get('result') or ''
    else:
        m['session_error'] = True
    return m, text


# ---- probe ------------------------------------------------------------------

def sse(events):
    return ''.join(f'event: {e["type"]}\ndata: {json.dumps(e)}\n\n' for e in events).encode()


def reply(blocks, stop):
    msg = {'id': 'msg_probe', 'type': 'message', 'role': 'assistant', 'model': 'probe', 'content': [],
           'stop_reason': None, 'stop_sequence': None, 'usage': {'input_tokens': 1, 'output_tokens': 1}}
    ev = [{'type': 'message_start', 'message': msg}]
    for i, b in enumerate(blocks):
        if b['type'] == 'tool_use':
            ev.append({'type': 'content_block_start', 'index': i, 'content_block': {**b, 'input': {}}})
            ev.append({'type': 'content_block_delta', 'index': i,
                       'delta': {'type': 'input_json_delta', 'partial_json': json.dumps(b['input'])}})
        else:
            ev.append({'type': 'content_block_start', 'index': i, 'content_block': {'type': 'text', 'text': ''}})
            ev.append({'type': 'content_block_delta', 'index': i, 'delta': {'type': 'text_delta', 'text': b['text']}})
        ev.append({'type': 'content_block_stop', 'index': i})
    ev.append({'type': 'message_delta', 'delta': {'stop_reason': stop, 'stop_sequence': None}, 'usage': {'output_tokens': 1}})
    ev.append({'type': 'message_stop'})
    return sse(ev)


class FakeAPI(http.server.BaseHTTPRequestHandler):
    bodies = []

    def log_message(self, *a):
        pass

    def do_POST(self):
        body = json.loads(self.rfile.read(int(self.headers.get('content-length') or 0)) or b'{}')
        FakeAPI.bodies.append(body)
        if 'count_tokens' in self.path:
            out, ctype = json.dumps({'input_tokens': 1}).encode(), 'application/json'
        else:
            names = [t.get('name') for t in body.get('tools') or []]
            dump = json.dumps(body.get('messages') or [])
            if 'Skill' in names and 'tool_result' not in dump and f'/{SKILL}' not in dump:
                out = reply([{'type': 'tool_use', 'id': 'toolu_probe', 'name': 'Skill', 'input': {'skill': SKILL}}], 'tool_use')
            else:
                out = reply([{'type': 'text', 'text': 'probe done'}], 'end_turn')
            ctype = 'text/event-stream'
        self.send_response(200)
        self.send_header('content-type', ctype)
        self.send_header('content-length', str(len(out)))
        self.end_headers()
        self.wfile.write(out)


def probe(skill_dir, claude='claude', slash=True):
    """True when a session built by command() loads skill_dir's SKILL.md and no other Figma
    skill. slash=False has the model call the Skill tool instead of the slash command.
    Prints what it saw."""
    marker = f'EVAL-PROBE-{os.getpid()}-{int(time.time())}'
    with tempfile.TemporaryDirectory() as tmp:
        copy = os.path.join(tmp, 'skill')
        shutil.copytree(skill_dir, copy, ignore=shutil.ignore_patterns('.git', 'tests', '__pycache__'))
        with open(os.path.join(copy, 'SKILL.md')) as f:
            src = f.read()
        head, sep, body = src.partition('\n---\n')
        with open(os.path.join(copy, 'SKILL.md'), 'w') as f:
            f.write(head + sep + f'{marker}\n' + body)
        plugin = make_plugin(copy, tmp)
        cwd = os.path.join(tmp, 'cwd')
        os.mkdir(cwd)
        FakeAPI.bodies = []
        srv = http.server.ThreadingHTTPServer(('127.0.0.1', 0), FakeAPI)
        threading.Thread(target=srv.serve_forever, daemon=True).start()
        env = clean_env({'ANTHROPIC_BASE_URL': f'http://127.0.0.1:{srv.server_address[1]}',
                         'ANTHROPIC_API_KEY': 'sk-ant-probe'})
        env.pop('CLAUDE_CODE_OAUTH_TOKEN', None)
        cmd = command(claude, plugin, 'probe', slash=slash)
        try:
            r = subprocess.run(cmd, cwd=cwd, env=env, capture_output=True, text=True, timeout=120)
        finally:
            srv.shutdown()
        init = next((json.loads(l) for l in r.stdout.splitlines() if '"subtype":"init"' in l), {})
        skills = init.get('skills') or []
        figma_skills = [s for s in skills if 'figma' in s]
        sent = json.dumps(FakeAPI.bodies)
        loaded = marker in sent
        user_skill = 'Base directory for this skill: ' + os.path.expanduser('~/.claude/skills/')
        others = [d for d in ('Read, audit, and edit text (copy) in Figma files', user_skill) if d in sent.replace('\\/', '/')]
        base = f'Base directory for this skill: {plugin}/skills/figma-cdp' in sent.replace('\\/', '/')
        print(json.dumps({'figma_skills_listed': figma_skills, 'requests': len(FakeAPI.bodies),
                          'marker_in_skill_body': loaded, 'base_dir_is_wrapper': base,
                          'other_figma_skills_sent': others, 'via': 'slash command' if slash else 'Skill tool'}, indent=1))
        if not FakeAPI.bodies:
            print(r.stderr[-2000:] or r.stdout[-2000:], file=sys.stderr)
        return figma_skills == [SKILL] and loaded and base and not others


if __name__ == '__main__':
    ap = argparse.ArgumentParser(prog='session.py')
    ap.add_argument('op', choices=['probe'])
    ap.add_argument('--skill-dir', default=ROOT)
    ap.add_argument('--claude', default=os.environ.get('CLAUDE_BIN', 'claude'))
    a = ap.parse_args()
    ok = [probe(a.skill_dir, a.claude, slash) for slash in (True, False)]
    sys.exit(0 if all(ok) else 1)
