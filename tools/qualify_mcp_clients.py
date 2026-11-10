#!/usr/bin/env python3
"""Model-free installed-client qualification; no provider inference request.

Run with an optional SDK environment, leaving the core dependency-free. Full
transcripts are local evidence, not public release material. Client workspaces
use self-cleaning temporary directories, separate from retained transcripts.
Native application execution is separately opt-in via --native; no agent/model
loop is invoked. A transcript preserves captured verification responses, not a
workspace for later native reverification.
"""
import argparse
import asyncio
from datetime import datetime, timezone
from importlib.metadata import PackageNotFoundError, version
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import time

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT/'src'))
DOCUMENT = {'version': 'schemaxis.sympy/1', 'operation': 'isolateRealRoots',
            'coefficients': ['1', '0', '-2'], 'maximumIntervalWidth': '1/1000'}


def versions():
    result = {}
    for package in ('mcp', 'openai-agents', 'claude-agent-sdk'):
        try:
            result[package] = version(package)
        except PackageNotFoundError:
            result[package] = None
    return result


def plain(value):
    return value.model_dump(mode='json', by_alias=True, exclude_none=True) if hasattr(value, 'model_dump') else value


def carrier(result):
    data = plain(result)
    value = data.get('structuredContent', data.get('structured_content'))
    if value is None:
        value = json.loads(next(block['text'] for block in data['content'] if block.get('type') == 'text'))
    return value


def parameters(args, workspace):
    environment = {'PYTHONPATH': str(ROOT/'src'), 'OPENAI_AGENTS_DISABLE_TRACING': '1'}
    if args.config is not None:
        environment['SCHEMAXIS_CONFIG'] = str(args.config.resolve())
    command = ['-m', 'schemaxis', 'mcp', '--workspace', str(workspace)]
    if args.isolation_config is not None:
        command.extend(('--isolation-config', str(args.isolation_config.resolve())))
    return {'command': args.server_python, 'args': command,
            'env': environment, 'cwd': str(ROOT)}


def complete_tools(names, *, isolated=False):
    """Discover the current shared service contract, including local inputs."""
    from schemaxis.service_contracts import METHODS
    expected = {'methods', *(name.replace('.', '_') for name in METHODS)}
    if isolated:
        expected.update(('inputs_list', 'input_from_resource'))
    return len(names) == len(set(names)) and set(names) == expected


async def exercise(call, record, *, native=False, timeout=120):
    transcript = record.setdefault('transcript', [])
    async def invoke(name, arguments):
        started = time.monotonic()
        result = await call(name, arguments)
        value = carrier(result)
        transcript.append({'tool': name, 'arguments': arguments, 'response': plain(result),
                           'elapsedSeconds': time.monotonic()-started})
        return value

    search = await invoke('capabilities_search', {'query': 'real root', 'scope': 'app/sympy'})
    if not search.get('ok') or not search['result']['items']:
        raise RuntimeError('capability search failed')
    task = await invoke('create_task', {'objective': 'Qualify exact-root MCP lifecycle',
        'allowed_providers': ['sympy'], 'budget': {'maxAttempts': 2, 'maxElapsedSeconds': timeout,
                                                'timeoutPerStageSeconds': min(60, timeout)}})
    if not task.get('ok'):
        raise RuntimeError('task creation failed')
    task = task['result']
    refused = await invoke('plan', {'task_id': task['id'], 'expected_revision': 0,
                                   'document': {**DOCUMENT, 'file': '/outside/forbidden'}})
    if refused.get('ok') or refused.get('fault', {}).get('code') != 'MCP_POLICY_DENIED':
        raise RuntimeError('hostile unknown file option was not refused')
    plan = await invoke('plan', {'task_id': task['id'], 'expected_revision': 0, 'document': DOCUMENT})
    if not plan.get('ok'):
        raise RuntimeError('host plan failed')
    plan = plan['result']
    observed = await invoke('observe', {'plan_id': plan['id'], 'section': 'plan'})
    if not observed.get('ok'):
        raise RuntimeError('captured plan observation failed')
    record.update(task=task['id'], plan=plan['id'], hostPlan=True, scopeRefusal=True,
                  nativeExecuted=False, modelCalls=0)
    if native:
        job = await invoke('execute', {'plan_id': plan['id'], 'expected_revision': plan['revision']})
        if not job.get('ok'):
            raise RuntimeError('native execution admission failed')
        job = job['result']
        until = time.monotonic()+timeout
        while True:
            status = await invoke('job', {'job_id': job['id']})
            if not status.get('ok'):
                raise RuntimeError('job polling failed')
            status = status['result']
            if status['status'] in {'succeeded', 'failed', 'cancelled', 'interrupted'}:
                break
            if time.monotonic() >= until:
                await invoke('cancel', {'job_id': job['id']})
                raise RuntimeError('native client qualification timed out')
            await asyncio.sleep(.2)
        record['nativeExecuted'] = True
        record['job'] = job['id']
        record['status'] = status
        observed = await invoke('observe', {'job_id': job['id'], 'section': 'verification'})
        verified = await invoke('verify', {'job_id': job['id']})
        if status.get('verified') is not True or not observed.get('ok') or not verified.get('ok'):
            raise RuntimeError('native execution/reverification was not established')
        resources = await invoke('observe', {'job_id': job['id'], 'section': 'resources'})
        if not resources.get('ok') or not resources['result'].get('value'):
            raise RuntimeError('native publications were not retained')
        for resource in resources['result']['value']:
            inspected = await invoke('inspect_resource', {'resource_id': resource['id']})
            if not inspected.get('ok'):
                raise RuntimeError('native publication inspection failed')
        record['publicationsCaptured'] = len(resources['result']['value'])
        record['nativeVerified'] = True
    return record


async def mcp_client(args, workspace, mode, record):
    from mcp import Client, StdioServerParameters
    record.update(client='official-mcp-'+mode, sdkVersion=version('mcp'))
    params = parameters(args, workspace)
    async with Client(StdioServerParameters(**params), mode=mode) as client:
        record['protocolVersion'] = client.protocol_version
        tools, cursor = [], None
        while True:
            page = await client.list_tools(cursor=cursor)
            tools.extend(tool.name for tool in page.tools)
            cursor = page.next_cursor
            if cursor is None:
                break
        record['tools'] = tools
        if not complete_tools(tools, isolated=args.isolation_config is not None):
            raise RuntimeError('official MCP client did not discover the complete paged tool list')
        await exercise(client.call_tool, record, native=args.native, timeout=args.timeout)
        templates = await client.list_resource_templates()
        uri = next(template.uri_template for template in templates.resource_templates
                   if '/plans/' in template.uri_template)
        base = uri.split('/plans/', 1)[0]
        resource = await client.read_resource(base+'/plans/'+record['plan']+'/observations/document')
        contents = plain(resource)['contents']
        captured = json.loads(contents[0]['text'])
        if captured.get('value') != DOCUMENT:
            raise RuntimeError('MCP resource changed the captured document')
        record['resourceRead'] = True
    record['passed'] = True
    return record


async def openai_client(args, workspace, record):
    from agents import set_tracing_disabled
    from agents.mcp import MCPServerStdio
    set_tracing_disabled(True)
    record.update(client='openai-agents-mcp', sdkVersion=version('openai-agents'),
                  scope='SDK MCP transport wrapper; no Runner or model request')
    async with MCPServerStdio(params=parameters(args, workspace), name='Schemaxis qualification') as server:
        tools = await server.list_tools()
        record['tools'] = [tool.name for tool in tools]
        if not complete_tools(record['tools'], isolated=args.isolation_config is not None):
            raise RuntimeError('Agents SDK did not discover the complete paged tool list')
        await exercise(server.call_tool, record, native=args.native, timeout=args.timeout)
    record['passed'] = True
    return record


async def claude_client(args, workspace, record):
    # Deliberately no query()/receive_response(): those enter the model loop.
    from claude_agent_sdk import ClaudeAgentOptions, ClaudeSDKClient
    record.update(client='claude-agent-sdk', sdkVersion=version('claude-agent-sdk'),
                  scope='connect/get_mcp_status only; no model loop or direct tool-call claim', modelCalls=0)
    with tempfile.TemporaryDirectory(prefix='schemaxis-claude-settings-') as settings:
        options = ClaudeAgentOptions(mcp_servers={'schemaxis': {'type': 'stdio', **parameters(args, workspace)}},
            setting_sources=[], env={'CLAUDE_CONFIG_DIR': settings, 'DISABLE_TELEMETRY': '1',
                'DISABLE_ERROR_REPORTING': '1', 'CLAUDE_CODE_DISABLE_NONESSENTIAL_TRAFFIC': '1'})
        async with ClaudeSDKClient(options=options) as client:
            until = time.monotonic()+min(args.timeout, 30)
            while True:
                record['mcpStatus'] = plain(await client.get_mcp_status())
                servers = record['mcpStatus'].get('mcpServers', [])
                server = next((item for item in servers if item['name'] == 'schemaxis'), None)
                if server is not None and server.get('status') != 'pending':
                    break
                if time.monotonic() >= until:
                    raise RuntimeError('Claude MCP connection status remained pending')
                await asyncio.sleep(.2)
            if server.get('status') != 'connected':
                raise RuntimeError('Claude SDK did not connect the configured MCP server')
            record['tools'] = [tool['name'] for tool in server.get('tools', [])]
            if not complete_tools(record['tools'], isolated=args.isolation_config is not None):
                raise RuntimeError('Claude SDK did not discover the complete paged tool list')
    record['passed'] = True
    return record


async def qualify(args):
    args.output_directory.mkdir(parents=True, exist_ok=False)
    # No credentials are needed for local MCP transport clients. Disable model
    # credentials and tracing in this process as an additional execution guard.
    for key in ('OPENAI_API_KEY', 'ANTHROPIC_API_KEY', 'CLAUDE_CODE_OAUTH_TOKEN'):
        os.environ.pop(key, None)
    os.environ['OPENAI_AGENTS_DISABLE_TRACING'] = '1'
    source = subprocess.check_output(['git', 'rev-parse', 'HEAD'], cwd=ROOT, text=True).strip()
    report = {'startedAt': datetime.now(timezone.utc).isoformat(), 'sourceCommit': source,
        'sdkVersions': versions(), 'modelCalls': 0, 'nativeRequested': args.native, 'clients': []}
    targets = {'mcp-modern': lambda path, record: mcp_client(args, path, 'auto', record),
               'mcp-legacy': lambda path, record: mcp_client(args, path, 'legacy', record),
               'openai': lambda path, record: openai_client(args, path, record),
               'claude': lambda path, record: claude_client(args, path, record)}
    with tempfile.TemporaryDirectory(prefix='schemaxis-mcp-clients-') as scratch:
        for name in args.clients:
            record = {'client': name, 'modelCalls': 0}
            report['clients'].append(record)
            try:
                await asyncio.wait_for(targets[name](Path(scratch)/name, record), timeout=args.timeout+30)
            except Exception as error:
                record.update(passed=False, errorType=type(error).__name__, error=str(error), errorDetail=repr(error))
            (args.output_directory/'clients.json').write_text(json.dumps(report, indent=2, default=str)+'\n')
    report['passed'] = all(result.get('passed') for result in report['clients'])
    (args.output_directory/'clients.json').write_text(json.dumps(report, indent=2, default=str)+'\n')
    print(json.dumps({'passed': report['passed'], 'clients': [{key: item.get(key)
        for key in ('client', 'passed', 'protocolVersion', 'nativeVerified', 'errorType')} for item in report['clients']],
        'sdkVersions': report['sdkVersions'], 'modelCalls': 0}))
    return 0 if report['passed'] else 1


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output-directory', type=Path, required=True)
    parser.add_argument('--clients', nargs='+', choices=('mcp-modern', 'mcp-legacy', 'openai', 'claude'),
                        default=['mcp-modern', 'mcp-legacy', 'openai', 'claude'])
    parser.add_argument('--server-python', default=sys.executable)
    parser.add_argument('--config', type=Path)
    parser.add_argument('--isolation-config', type=Path, help='trusted operator image/capture configuration')
    parser.add_argument('--native', action='store_true')
    parser.add_argument('--timeout', type=int, default=120)
    args = parser.parse_args()
    if not 1 <= args.timeout <= 600:
        parser.error('timeout must be 1..600 seconds')
    if args.native and args.isolation_config is None:
        parser.error('--native requires --isolation-config with qualified immutable worker images')
    return asyncio.run(qualify(args))


if __name__ == '__main__':
    raise SystemExit(main())
