#!/usr/bin/env python3
"""Stands in for `claude -p ... --output-format stream-json` in offline_test.py: checks the
arguments run.py passes, then prints a transcript with a main-session tool call, a failed
one, a subagent's tool call and a result event that bills two models. A recon prompt gets
a correct answer; nothing touches Figma."""
import json, os, sys

args = sys.argv[1:]
prompt = args[args.index('-p') + 1]
assert prompt.startswith('/figma-eval:figma-cdp '), prompt
for flag in ('--plugin-dir', '--setting-sources', '--strict-mcp-config', '--allowedTools'):
    assert flag in args, flag
plugin = args[args.index('--plugin-dir') + 1]
assert os.path.isfile(os.path.join(plugin, 'skills', 'figma-cdp', 'SKILL.md')), plugin
assert 'CLAUDECODE' not in os.environ

answer = 'Done.'
if 'top-level frames' in prompt:
    answer = ('Onboarding / Step 1: 375×812, 3 text layers. Onboarding / Step 2: 375×812, 2 text layers. '
              'Paywall: 390×844, 4 text layers.')
events = [
    {'type': 'system', 'subtype': 'init', 'skills': ['figma-eval:figma-cdp'], 'tools': ['Bash']},
    {'type': 'assistant', 'parent_tool_use_id': None, 'message': {'content': [
        {'type': 'text', 'text': 'Reading the page.'},
        {'type': 'tool_use', 'id': 't1', 'name': 'Bash', 'input': {}}]}},
    {'type': 'user', 'message': {'content': [{'type': 'tool_result', 'tool_use_id': 't1', 'is_error': True, 'content': 'x'}]}},
    {'type': 'assistant', 'parent_tool_use_id': None, 'message': {'content': [
        {'type': 'tool_use', 'id': 't2', 'name': 'Agent', 'input': {}}]}},
    {'type': 'assistant', 'parent_tool_use_id': 't2', 'message': {'content': [
        {'type': 'tool_use', 'id': 't3', 'name': 'Read', 'input': {}}]}},
    {'type': 'user', 'parent_tool_use_id': 't2', 'message': {'content': [{'type': 'tool_result', 'tool_use_id': 't3', 'content': 'ok'}]}},
    {'type': 'result', 'subtype': 'success', 'is_error': False, 'num_turns': 4, 'result': answer,
     'total_cost_usd': 0.5, 'usage': {'input_tokens': 1},
     'modelUsage': {'opus': {'inputTokens': 100, 'outputTokens': 50, 'cacheReadInputTokens': 1000, 'cacheCreationInputTokens': 200},
                    'haiku': {'inputTokens': 10, 'outputTokens': 5, 'cacheReadInputTokens': 0, 'cacheCreationInputTokens': 0}}},
]
for e in events:
    print(json.dumps(e))
