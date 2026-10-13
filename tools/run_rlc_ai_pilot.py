#!/usr/bin/env python3
"""Run one bounded, filesystem-isolated Claude pair on the RLC benchmark.

Requires Linux bubblewrap, an already authenticated Claude CLI and configured
ngspice/Calc. Credentials are mounted from the existing account, never copied.
The coordinator retains frozen inputs, transcripts and independent grades outside
the contestant namespaces. This is a pilot, not a statistical evaluation.
"""
import argparse
import json
import os
from pathlib import Path
import shutil
import signal
import subprocess
import time
import uuid

from benchmark_workflows import ROOT, grade, locations, prepare, save, stage, task_digest


TASK = """Implement a reusable multi-case RLC-to-workbook procedure in /work.
Read /work/task.json and process every case into /work/submission/CASE-ID/.
Use native ngspice for a linear AC sweep of source--R--L--output--C--ground
with one grounded ideal voltage source, using the specified SI parameters.
Publish circuit.cir, results.csv and editable results.ods for every case.
CSV and workbook data headers must be frequency_Hz,out_real_V,out_imag_V,
out_magnitude_V,out_phase_deg. Use exp(+j*omega*t) phasors and degrees.
Preserve the full numeric table, including a negative source amplitude when given.
An independent evaluator compares every numeric value to analytic expectations
with relative/absolute tolerance 1e-7; producer success flags are insufficient.
Use LibreOffice Calc to create the workbook. Retain native logs, your reusable
procedure and brief rerun instructions. Do not hardcode expected results or case IDs.
Later turns will request an unchanged repeat, then revised parameters and a new
case; reuse your own code/artifacts where appropriate. Initial example templates,
if supplied, are not automatically regenerated for revisions.

Runtime locations are in /work/runtime.json. Python 3 and ordinary system tools
are available. Work locally and serially; no installs, cluster jobs, purchases,
external communications or unrelated data access. Native manuals/help and public
documentation are allowed. Do not seek benchmark reference solutions or graders.
You have 300 seconds for this turn. Execute the task, rather than only describing
an approach. Report failures honestly. Keep all project files under /work.
"""


def runtime_configuration():
    return {'version': 1, 'locations': {'ngspice': '/opt/ngspice/bin/ngspice',
                                       'calc': '/opt/libreoffice/program/soffice'}}


# HOME inside the isolated sandbox, bound to a fresh per-run directory.
SANDBOX_HOME = '/sandbox/home'


def sandbox(home, work, runtime, claude, credentials, product=None):
    args = ['bwrap', '--ro-bind', '/usr', '/usr']
    for alias in ('bin', 'sbin', 'lib', 'lib64'):
        args += ['--symlink', 'usr/'+alias, '/'+alias]
    args += ['--ro-bind', '/etc', '/etc', '--ro-bind', '/run/systemd/resolve', '/run/systemd/resolve',
             '--proc', '/proc', '--dev', '/dev', '--tmpfs', '/tmp',
             '--bind', str(home), SANDBOX_HOME, '--dir', SANDBOX_HOME+'/.claude',
             '--ro-bind', str(credentials), SANDBOX_HOME+'/.claude/.credentials.json',
             '--ro-bind', str(claude), '/opt/claude', '--bind', str(work), '/work',
             '--ro-bind', str(runtime['ngspice']), '/opt/ngspice',
             '--ro-bind', str(runtime['calc']), '/opt/libreoffice',
             '--chdir', '/work', '--clearenv', '--setenv', 'HOME', SANDBOX_HOME,
             '--setenv', 'PATH', '/usr/bin:/bin', '--setenv', 'LANG', 'C.UTF-8',
             '--setenv', 'QT_QPA_PLATFORM', 'offscreen', '--setenv', 'OMP_NUM_THREADS', '1',
             '--setenv', 'SCHEMAXIS_CONFIG', '/work/runtime.json',
             '--unshare-pid', '--die-with-parent']
    if product:
        args += ['--ro-bind', str(product), '/opt/schemaxis', '--setenv', 'PYTHONPATH', '/opt/schemaxis/src']
    return args+['--']


def invoke(args, prompt, logs, seconds):
    logs.mkdir(parents=True)
    (logs/'prompt.txt').write_text(prompt)
    started = time.monotonic()
    timed_out = False
    with (logs/'transcript.jsonl').open('w') as output, (logs/'stderr.log').open('w') as error:
        process = subprocess.Popen(args, stdin=subprocess.PIPE, stdout=output, stderr=error,
                                   start_new_session=True, text=True)
        try:
            process.communicate(prompt, timeout=seconds)
        except subprocess.TimeoutExpired:
            timed_out = True
            os.killpg(process.pid, signal.SIGTERM)
            try:
                process.wait(timeout=5)
            except subprocess.TimeoutExpired:
                os.killpg(process.pid, signal.SIGKILL)
                process.wait(timeout=5)
    elapsed = time.monotonic()-started
    events = []
    for line in (logs/'transcript.jsonl').read_text().splitlines():
        try:
            events.append(json.loads(line))
        except json.JSONDecodeError:
            pass
    results = [e for e in events if e.get('type') == 'result']
    result = results[-1] if results else {}
    tool_calls, tool_errors = [], 0
    for event in events:
        for block in event.get('message', {}).get('content', []) or []:
            if not isinstance(block, dict):
                continue
            if block.get('type') == 'tool_use':
                tool_calls.append(block.get('name'))
            if block.get('type') == 'tool_result' and block.get('is_error'):
                tool_errors += 1
    return {'exitCode': process.returncode, 'timedOut': timed_out, 'wallSeconds': elapsed,
            'sessionId': result.get('session_id'), 'resultType': result.get('subtype'),
            'isError': result.get('is_error'), 'usage': result.get('usage'),
            'terminalReason': result.get('terminal_reason'), 'apiErrorStatus': result.get('api_error_status'),
            'providerMessage': result.get('result') if result.get('is_error') else None,
            'modelUsage': result.get('modelUsage'), 'listPriceCostUSD': result.get('total_cost_usd'),
            'agentTurns': result.get('num_turns'), 'toolCalls': len(tool_calls),
            'toolErrors': tool_errors, 'permissionDenials': result.get('permission_denials'),
            'transcript': str(logs/'transcript.jsonl'), 'humanInterventions': 0}


def run(config, destination, model, effort, seconds, budget, claude, credentials, schemaxis_mode):
    destination.mkdir(parents=True, exist_ok=False)
    loc = locations(config)
    runtime = {'ngspice': Path(loc['ngspice']).resolve().parent.parent,
               'calc': Path(loc['calc']).absolute().parent.parent}
    spec = json.loads((ROOT/'examples/benchmarks/cases.json').read_text())
    for name in spec['rounds']:
        spec['rounds'][name] = [c for c in spec['rounds'][name] if c['family'] == 'rlc']
    package = prepare(spec, destination/'frozen-package')
    product = destination/'product'
    shutil.copytree(ROOT/'src', product/'src', ignore=shutil.ignore_patterns('__pycache__', '*.pyc'))
    (product/'docs').mkdir()
    for name in ('ngspice.md', 'installation.md', 'getting-started.md', 'workflow-authoring.md', 'json-input.md'):
        shutil.copyfile(ROOT/'docs'/name, product/'docs'/name)
    source_commit = subprocess.check_output(['git', '-C', str(ROOT), 'rev-parse', 'HEAD'], text=True).strip()
    report = {'kind': 'autonomous-ai-paired-pilot', 'family': 'rlc', 'replicates': 1,
              'condition': 'template-assisted Schemaxis versus ordinary native scripting',
              'schemaxisMode': schemaxis_mode,
              'model': model, 'effort': effort, 'sourceCommit': source_commit,
              'limits': {'wallSecondsPerInvocation': seconds, 'claudeMaxBudgetUSDFlag': budget},
              'filesystemIsolation': 'bubblewrap; independent homes/workspaces; coordinator and other arm absent',
              'networkIsolation': False, 'runs': [], 'status': 'running'}
    sessions = {}
    for arm in ('ordinary', 'schemaxis'):
        work = destination/arm/'work'
        stage(package, 'initial', arm, work)
        task = json.loads((work/'task.json').read_text()); task['inputs'] = '/work/inputs'; save(work/'task.json', task)
        home = destination/arm/'home'; home.mkdir()
        save(work/'runtime.json', runtime_configuration())
        extra = ('\nSchemaxis is available via python3 -m schemaxis and Python imports.\n'
                 'Its source and selected product docs are at /opt/schemaxis; initial\n'
                 'workflows are in /work/templates. You may use these and ordinary tools.\n'
                 if arm == 'schemaxis' else
                 '\nUse ordinary scripting/native APIs. Schemaxis is unavailable and prohibited.\n')
        if arm == 'schemaxis' and schemaxis_mode == 'required':
            extra += ('\nFor this comparison you MUST use Schemaxis to execute the ngspice\n'
                      'simulation and Calc workbook handoff. Ordinary scripts may populate\n'
                      'workflow inputs, collect artifacts and check results. Replacing these\n'
                      'core steps with direct native calls does not satisfy this method.\n')
        (work/'TASK.md').write_text(TASK.replace('300 seconds', f'{seconds} seconds')+extra)
        prefix = sandbox(home, work, runtime, claude, credentials, product if arm == 'schemaxis' else None)
        # Fail infrastructure preflight before spending model usage.
        probe = subprocess.run(prefix+['/bin/bash', '-c',
            '/opt/claude auth status && /opt/ngspice/bin/ngspice --version && '
            '/opt/libreoffice/program/soffice --headless --version && '
            'python3 -c "import importlib.util; print(importlib.util.find_spec(\'schemaxis\'))"'],
            text=True, capture_output=True, timeout=30)
        (destination/arm/'preflight.log').write_text(probe.stdout+probe.stderr)
        if probe.returncode:
            raise RuntimeError('runtime/auth preflight failed for '+arm)
        if arm == 'schemaxis':
            # Exercise actual dispatch in ephemeral /tmp before timing a model.
            # Output and the frozen coordinator logs are absent from its workspace.
            check = ('import json; from schemaxis import workflow, configuration; '
                     'doc=json.load(open("/work/templates/rlc-a.json")); '
                     'workflow.execute(doc,"/tmp/native-preflight", '
                     'locations=configuration.load()["locations"],timeout=60); '
                     'print("native workflow preflight passed")')
            probe = subprocess.run(prefix+['python3', '-c', check], text=True,
                                   capture_output=True, timeout=90)
            (destination/arm/'native-preflight.log').write_text(probe.stdout+probe.stderr)
            if probe.returncode:
                raise RuntimeError('Schemaxis config/native dispatch preflight failed')
        sessions[arm] = str(uuid.uuid4())
    save(destination/'report.json', report)
    for label, round_name in [('initial', 'initial'), ('repeat', 'initial'), ('revision', 'revision')]:
        # Fixed, declared order in this exploratory pair; balance order in replication.
        for arm in ('ordinary', 'schemaxis'):
            work = destination/arm/'work'; home = destination/arm/'home'
            task = json.loads((package/round_name/arm/'task.json').read_text())
            if label == 'revision':
                save(work/'task.json', {**task, 'inputs': '/work/inputs'})
            prefix = sandbox(home, work, runtime, claude, credentials, product if arm == 'schemaxis' else None)
            args = prefix+['/opt/claude', '-p', '--safe-mode', '--strict-mcp-config',
                '--mcp-config', '{"mcpServers":{}}', '--tools', 'Bash,Read,Write,Edit,Glob,Grep',
                '--allowedTools', 'Bash', 'Read', 'Write', 'Edit', 'Glob', 'Grep',
                '--permission-mode', 'dontAsk', '--model', model, '--effort', effort,
                '--max-budget-usd', str(budget), '--output-format', 'stream-json', '--verbose']
            args += (['--session-id', sessions[arm]] if label == 'initial' else ['--resume', sessions[arm]])
            prompt = ('Read TASK.md and task.json, implement the reusable procedure, and execute it now.' if label == 'initial' else
                      'Repeat the unchanged task now using your existing procedure. Keep or reuse artifacts if valid; verify outputs still match task.json. Report what reran or reused.' if label == 'repeat' else
                      'The coordinator has replaced task.json with revised parameters and a new case. Read it, reuse or adapt your existing procedure and produce all requested outputs. Initial templates were not regenerated. Execute now.')
            print(json.dumps({'event': 'start', 'arm': arm, 'round': label}), flush=True)
            record = invoke(args, prompt, destination/arm/label, seconds)
            if record['terminalReason'] == 'api_error' or record['apiErrorStatus'] is not None:
                # CLI subtype can be "success" even for HTTP 429. Do not score
                # absent artifacts as model failures or launch later rounds.
                record.update(arm=arm, round=label, taskDigest=task_digest(task),
                              grade={'status': 'not-scored', 'passed': None, 'cases': []})
                report['runs'].append(record)
                report.update(status='blocked', blockedReason=record['providerMessage'], allArtifactsPassed=None)
                save(destination/'report.json', report)
                print(json.dumps({'event': 'provider-blocked', 'arm': arm, 'round': label,
                                  'apiErrorStatus': record['apiErrorStatus']}), flush=True)
                return report
            shutil.copytree(work, destination/arm/label/'workspace', symlinks=True)
            snapshot = destination/arm/label/'submission'
            if (work/'submission').is_dir():
                shutil.copytree(work/'submission', snapshot, symlinks=True)
            else:
                snapshot.mkdir()
            record.update(arm=arm, round=label, taskDigest=task_digest(task))
            record['grade'] = grade(task, snapshot, loc, destination/arm/label/'grade')
            report['runs'].append(record); save(destination/'report.json', report)
            print(json.dumps({'event': 'finish', 'arm': arm, 'round': label,
                              'wallSeconds': record['wallSeconds'], 'passed': record['grade']['passed'],
                              'resultType': record['resultType']}), flush=True)
    report['status'] = 'complete'
    report['allArtifactsPassed'] = all(r['grade']['passed'] for r in report['runs'])
    save(destination/'report.json', report)
    return report


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--config', type=Path, required=True)
    parser.add_argument('--output-directory', type=Path, required=True)
    parser.add_argument('--model', required=True)
    parser.add_argument('--effort', default='high')
    parser.add_argument('--seconds', type=int, default=300)
    parser.add_argument('--budget-usd', type=float, default=3)
    parser.add_argument('--schemaxis-mode', choices=('available', 'required'), default='required')
    parser.add_argument('--claude', type=Path, default=Path.home()/'.local/bin/claude')
    parser.add_argument('--credentials', type=Path, default=Path.home()/'.claude/.credentials.json')
    args = parser.parse_args()
    report = run(args.config.resolve(), args.output_directory.resolve(), args.model, args.effort,
                 args.seconds, args.budget_usd, args.claude.resolve(), args.credentials.resolve(), args.schemaxis_mode)
    return 2 if report['status'] == 'blocked' else 0 if report['allArtifactsPassed'] else 1


if __name__ == '__main__':
    raise SystemExit(main())
