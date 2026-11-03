# Copyright (C) 2026 David L F Gaden
"""Codex CLI transport for the isolated ParaView model comparison.

Uses the existing account through a read-only auth mount. No user configuration,
other task history, coordinator files or reference results enter the namespace.
"""
import json
from pathlib import Path

from run_paraview_ai_pilot import SANDBOX_HOME, sandbox as claude_sandbox
from run_rlc_ai_pilot import invoke as capture

# Standard API list prices checked against official model pages 2026-09-29.
# Not a representation of Codex subscription billing.
PRICES = {'gpt-5.6-luna': (.2, .02, .25, 1.2), 'gpt-6-astra': (10, 1, 12.5, 50)}


def accounting(current, previous, model):
    """Codex turn.completed reports session-cumulative usage, including cache."""
    keys = ('input_tokens', 'cached_input_tokens', 'cache_write_input_tokens', 'output_tokens')
    if not all(k in current for k in keys):
        raise ValueError('Missing token categories; cannot estimate cost accurately')
    delta = {k: current[k]-previous.get(k, 0) for k in keys}
    if min(delta.values()) < 0:
        raise ValueError('Cumulative usage decreased')
    uncached = delta['input_tokens']-delta['cached_input_tokens']-delta['cache_write_input_tokens']
    if uncached < 0:
        raise ValueError('Cache token categories exceed input tokens')
    a, b, c, d = PRICES[model]
    cumulative_cost = ((current['input_tokens']-current['cached_input_tokens']-current['cache_write_input_tokens'])*a
                       +current['cached_input_tokens']*b+current['cache_write_input_tokens']*c
                       +current['output_tokens']*d)/1e6
    return {'input_tokens': uncached, 'cache_read_input_tokens': delta['cached_input_tokens'],
            'cache_creation_input_tokens': delta['cache_write_input_tokens'],
            'output_tokens': delta['output_tokens']}, cumulative_cost


def session_context(home, session):
    """Read model and token evidence, never account credential contents."""
    paths = list((home/'.codex/sessions').rglob('*'+session+'*.jsonl'))
    if len(paths) != 1:
        raise ValueError('Expected exactly one retained Codex session')
    models, max_input = set(), 0
    for line in paths[0].read_text().splitlines():
        event = json.loads(line); payload = event.get('payload', {})
        if event.get('type') == 'turn_context':
            models.add(payload.get('model'))
        if event.get('type') == 'event_msg' and payload.get('type') == 'token_count':
            info = payload.get('info') or {}
            max_input = max(max_input, info.get('last_token_usage', {}).get('input_tokens', 0))
    return {'models': sorted(models), 'maxRequestInputTokens': max_input,
            'sessionLog': str(paths[0])}


def sandbox(home, work, inputs, pvroot, executable, credentials, product=None):
    args = claude_sandbox(home, work, inputs, pvroot, executable, credentials, product)
    args = [str(arg).replace(SANDBOX_HOME+'/.claude/.credentials.json', SANDBOX_HOME+'/.codex/auth.json')
            .replace(SANDBOX_HOME+'/.claude', SANDBOX_HOME+'/.codex')
            .replace('/opt/claude', '/opt/codex') for arg in args]
    # Code-mode tool execution resolves this companion beside the CLI binary.
    index = args.index('--')
    args[index:index] = ['--ro-bind', str(Path(executable).parent/'codex-code-mode-host'),
                        '/opt/codex-code-mode-host']
    return args


def command(model, effort='high', session=None):
    args = ['/opt/codex', 'exec']
    if session:
        args += ['resume']
    args += ['--ignore-user-config', '--skip-git-repo-check', '--json',
             '--dangerously-bypass-approvals-and-sandbox', '--model', model,
             '-c', 'model_reasoning_effort="'+effort+'"',
             '-c', 'features.multi_agent=false', '-c', 'web_search="disabled"']
    if session:
        args += [session]
    return args+['-']


def invoke(args, prompt, logs, seconds):
    result = capture(args, prompt, logs, seconds)
    events = []
    for line in (logs/'transcript.jsonl').read_text().splitlines():
        try:
            events.append(json.loads(line))
        except json.JSONDecodeError:
            # A wall-time kill may leave an incomplete final transport line.
            continue
    completed = [e for e in events if e.get('type') == 'turn.completed']
    started = [e for e in events if e.get('type') == 'thread.started']
    errors = [e for e in events if e.get('type') in ('error', 'turn.failed')]
    items = [e.get('item', {}) for e in events if e.get('type') == 'item.completed']
    infrastructure_errors = [i for i in items if i.get('type') == 'error'
                             and 'codex-code-mode-host' in json.dumps(i)]
    usage = completed[-1].get('usage', {}) if completed else {}
    result.update(sessionId=started[0].get('thread_id') if started else None,
                  resultType='success' if completed and result['exitCode'] == 0 else 'error',
                  isError=not (completed and result['exitCode'] == 0),
                  terminalReason=('completed' if completed else 'timeout' if result['timedOut'] else 'api_error'),
                  usage=usage, modelUsage=None, listPriceCostUSD=None,
                  toolCalls=sum(i.get('type') not in ('reasoning', 'agent_message') for i in items),
                  toolErrors=sum(i.get('type') == 'command_execution' and i.get('exit_code') not in (0, None) for i in items),
                  providerMessage=json.dumps(errors) if errors else None)
    if infrastructure_errors:
        result.update(isError=True, terminalReason='infrastructure_error',
                      providerMessage=json.dumps(infrastructure_errors))
    return result
