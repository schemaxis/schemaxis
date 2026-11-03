#!/usr/bin/env python3
# Copyright (C) 2026 David L F Gaden
"""Compare baseline, qualified introduction and packaged checking for two recipes.

Six fresh conversations, four turns each. The hidden grader and native isolation
are shared with the earlier pilot. Qualification is reported only after preflight.
"""
import argparse
import copy
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import time
import uuid

from benchmark_workflows import ROOT, command, save
from run_paraview_ai_pilot import (NATIVE, RECIPES, TASK, case, challenge, damage,
    digest, grade, native_command, prove, runtime_configuration, sandbox, tree_digest)
from run_rlc_ai_pilot import invoke
from summarise_ai_pilot import summarise

ARMS = ('native-baseline', 'schemaxis-baseline', 'schemaxis-brief',
        'native-brief', 'native-checked', 'schemaxis-checked')
ORDERS = (ARMS, tuple(reversed(ARMS)), ARMS[3:]+ARMS[:3], tuple(reversed(ARMS[3:]+ARMS[:3])))
CHECKER = RECIPES/'check_outputs.py'


def tasks():
    initial = {'inputs': '/work/inputs', 'imageSize': [192, 160],
        'appearances': [{'field': ['POINTS', 'T'], 'range': [0, 65], 'preset': 'Grayscale'},
                        {'field': ['CELLS', 'T'], 'range': [65, 140], 'preset': 'Grayscale'}],
        'cases': [case('field-a', 2.4, 1.2, .75, 6, fractions=[.2, .7]),
                  case('field-b', 2.8, 1.1, .9, 15, fractions=[.2, .7])]}
    revision = copy.deepcopy(initial)
    revision['cases'][0] = case('field-a', 2.4, 1.2, .75, 6, axis=1,
                                fractions=[.3, .6, .8], times=[0, 2])
    revision['cases'].append(case('field-c', 1.8, 1.3, .65, 9, fractions=[.2, .7], times=[0, 2]))
    revision['appearances'][0]['range'] = [0, 55]
    return {'initial': initial, 'revision': revision}


def prepare(destination, pvbatch):
    destination.mkdir(parents=True, exist_ok=False)
    for phase, task in tasks().items():
        root = destination/phase; root.mkdir(); save(root/'task.json', task)
        command(native_command(pvbatch, NATIVE, 'fixture', root/'task.json', root/'inputs'), root, 'fixtures')
        host = {**task, 'inputs': str(root/'inputs')}; save(root/'host-task.json', host)
        command(native_command(pvbatch, RECIPES/'native_recipe.py', root/'host-task.json', root/'reference'), root, 'reference')
        if not grade(root/'host-task.json', root/'reference', root/'reference', pvbatch, root/'reference-grade')['passed']:
            raise RuntimeError('analytic reference failed')


def recipe(method):
    return 'schemaxis_recipe.py' if method == 'schemaxis' else 'native_recipe.py'


def launch(method, output):
    script = '/work/'+recipe(method)
    return (['python3', script, '/work/task.json', output] if method == 'schemaxis'
            else native_command('/opt/paraview/bin/pvbatch', script, '/work/task.json', output))


def introduction(method, condition, qualification):
    if qualification.get('passed') is not True:
        raise ValueError('cannot advertise an unsuccessful preflight')
    execution = ' '.join(launch(method, '/work/submission'))
    text = f'''# Start here

Use `{recipe(method)}` as the supplied operating procedure. This is a user-approved
local recipe; ordinary use does not require a source-code audit. Start by running
it with the current task. Inspect or modify implementation when a check fails,
requirements exceed its scope, or an observation gives a reason to investigate.

Command (retain the exit status and log):
`{execution} > run.log 2>&1`

Edit task.json to select cases, times, slice axis/fractions, appearances and cameras.
The recipe handles time updates, first-render camera reset, fixed colour ranges,
point/cell association and publication naming. It regenerates all requested files;
it does not promise automatic selective repair. Outputs are in submission/CASE-ID.

The coordinator independently tested this exact recipe with the initial task in
this isolated environment before the conversation. All {qualification['artifactChecks']}
initial geometry/image checks passed, including decoded camera/colour comparisons.
qualification.json identifies the tested task, inputs, recipe, product and native
binary. This is local evidence, not a security signature or proof for arbitrary
changes. Qualification is scoped to those initial inputs and runtime. Revisions
need current output checks. Do not treat an old success or file existence as proof.

For a quick freshness check, `sha256sum task.json {recipe(method)}` must match
qualification.json's taskFileSHA256 and recipeSHA256 respectively. Those hash raw
file bytes. canonicalTaskSHA256 instead hashes normalized JSON: do not compare it
to sha256sum of the file. The digestFormats object defines all tree/JSON digests.
The statement remains the INITIAL qualification on later turns; an expected task
change then requires current output checks, not a claim that the original failed.
'''
    if condition == 'checked':
        text += '''
A supplied checker avoids writing routine geometry/image-structure/hash validators:
`/opt/paraview/bin/pvbatch --force-offscreen-rendering /work/check_outputs.py /work/task.json /work/submission --record /work/checked.json > check.log 2>&1`
Read its exit status and compact report. After a successful check, unchanged reuse
can be checked with `--baseline /work/checked.json` instead of `--record`. A baseline
mismatch requires investigation or regeneration, not overwriting the saved evidence
to call it valid. After a revision/regeneration, check and record a new manifest.
The checker covers analytic geometry/fields, PNG dimensions/nonblank content, and
optional byte integrity. It DOES NOT independently certify image camera, colour
mapping or image time. The hidden evaluator still checks those properties. State
the scope accurately; extra checks are appropriate when observations warrant them.
'''
    return text


def run(args, pvroot):
    started = time.monotonic()
    destination = args.output_directory; destination.mkdir(parents=True, exist_ok=False)
    package = args.package.resolve(); product = destination/'product'
    shutil.copytree(ROOT/'src', product/'src', ignore=shutil.ignore_patterns('__pycache__', '*.pyc'))
    (product/'docs').mkdir()
    for name in ('getting-started.md', 'workflow-authoring.md', 'json-input.md', 'schema-guide.md', 'capability-discovery.md'):
        shutil.copyfile(ROOT/'docs'/name, product/'docs'/name)
    source = subprocess.check_output(['git', '-C', str(ROOT), 'rev-parse', 'HEAD'], text=True).strip()
    native_version = subprocess.check_output([str(pvroot/'bin/pvbatch'), '--version'], text=True).strip()
    native_digest = hashlib.sha256((pvroot/'bin/pvbatch').read_bytes()).hexdigest()
    report = {'kind': 'autonomous-ai-onboarding-pilot', 'family': 'paraview', 'replicates': 1,
        'model': args.model, 'effort': args.effort, 'schemaxisMode': 'required', 'status': 'preflight', 'runs': [],
        'sourceCommit': source, 'productSourceDigest': tree_digest(product/'src'),
        'recipeDigest': tree_digest(RECIPES), 'checkerDigest': hashlib.sha256(CHECKER.read_bytes()).hexdigest(),
        'orders': ORDERS, 'preflights': [],
        'limits': {'wallSecondsPerInvocation': args.seconds, 'claudeMaxBudgetUSDFlag': args.budget_usd},
        'conditions': {arm: {'method': arm.split('-')[0], 'introduction': arm.split('-')[1]} for arm in ARMS},
        'scope': 'one fresh conversation per method/introduction cell; no independent replicates; network available'}
    save(destination/'report.json', report)
    sessions = {}
    for arm in ARMS:
        method, condition = arm.split('-'); base = destination/arm
        work = base/'work'; work.mkdir(parents=True); home = base/'home'; home.mkdir()
        (work/'inputs').mkdir(); save(work/'runtime.json', runtime_configuration())
        shutil.copyfile(RECIPES/recipe(method), work/recipe(method))
        extra = ('\nUse Schemaxis for all slicing and rendering. Ordinary Python may prepare inputs, inspect results and collect publications.\n'
                 'A complete reusable procedure is supplied: schemaxis_recipe.py. Run with Python 3. Source/docs: /opt/schemaxis.\n'
                 if method == 'schemaxis' else '\nUse ordinary ParaView Python; Schemaxis is unavailable and prohibited.\n'
                 'A complete reusable starting procedure is supplied: native_recipe.py. You may use, inspect and modify it.\n')
        if condition != 'baseline': extra += '\nRead START.md for the invocation, qualification evidence and operating guidance.\n'
        (work/'TASK.md').write_text(TASK+extra+f'\nTime allowance: {args.seconds} seconds per turn.\n')
        sessions[arm] = str(uuid.uuid4())
        save(work/'task.json', json.loads((package/'initial/task.json').read_text()))
        prefix = sandbox(home, work, package/'initial/inputs', pvroot, args.claude, args.credentials,
                         product if method == 'schemaxis' else None)
        before = time.monotonic()
        probe = subprocess.run(prefix+launch(method, '/work/.preflight-output'), text=True, capture_output=True, timeout=240)
        (base/'native-preflight.log').write_text(probe.stdout+probe.stderr)
        if probe.returncode: raise RuntimeError('native namespace preflight failed: '+arm)
        checker_result = None
        if condition == 'checked':
            shutil.copyfile(CHECKER, work/'check_outputs.py')
            checked_probe = subprocess.run(prefix+native_command('/opt/paraview/bin/pvbatch', '/work/check_outputs.py',
                '/work/task.json', '/work/.preflight-output'), text=True, capture_output=True, timeout=90)
            (base/'checker-preflight.log').write_text(checked_probe.stdout+checked_probe.stderr)
            if checked_probe.returncode: raise RuntimeError('public checker preflight failed: '+arm)
            checker_result = json.loads(checked_probe.stdout)
        shutil.move(work/'.preflight-output', base/'native-preflight-output')
        checked = grade(package/'initial/task.json', base/'native-preflight-output', package/'initial/reference',
                        pvroot/'bin/pvbatch', base/'native-preflight-grade')
        if not checked['passed']: raise RuntimeError('independent namespace preflight failed: '+arm)
        qualification = {'passed': True, 'scope': 'initial task only, serial native processing',
            'artifactChecks': sum(len(c['checks']) for c in checked['cases']),
            'taskFileSHA256': hashlib.sha256((work/'task.json').read_bytes()).hexdigest(),
            'canonicalTaskSHA256': digest(json.loads((work/'task.json').read_text())),
            'inputTreeSHA256': tree_digest(package/'initial/inputs'),
            'recipeSHA256': hashlib.sha256((work/recipe(method)).read_bytes()).hexdigest(),
            'sourceCommit': source, 'productSourceDigest': report['productSourceDigest'] if method == 'schemaxis' else None,
            'nativeVersion': native_version, 'nativeExecutableSHA256': native_digest,
            'digestFormats': {'taskFileSHA256': 'SHA256 of raw task.json bytes',
                'recipeSHA256': 'SHA256 of raw supplied recipe bytes',
                'nativeExecutableSHA256': 'SHA256 of raw pvbatch executable bytes',
                'canonicalTaskSHA256': 'SHA256 of UTF-8 json.dumps(task, sort_keys=True, separators=(comma, colon)), with default ensure_ascii=True',
                'inputTreeSHA256': 'SHA256 of the same canonical JSON encoding of a mapping from each relative file path to its raw-file SHA256',
                'productSourceDigest': 'same tree algorithm for /opt/schemaxis/src; null for native method'},
            'checkerScope': checker_result['scope'] if checker_result else None}
        report['preflights'].append({'arm': arm, 'seconds': time.monotonic()-before, 'qualification': qualification})
        if condition != 'baseline':
            save(work/'qualification.json', qualification)
            (work/'START.md').write_text(introduction(method, condition, qualification))
        save(destination/'report.json', report)
        print(json.dumps({'event': 'preflight-passed', 'arm': arm}), flush=True)
    report.update(status='running', preparationSeconds=time.monotonic()-started)
    save(destination/'report.json', report)
    for index, label in enumerate(('initial', 'repeat', 'revision', 'repair')):
        phase = 'initial' if index < 2 else 'revision'
        for arm in ORDERS[index]:
            method, condition = arm.split('-'); base = destination/arm; work = base/'work'; home = base/'home'
            task = json.loads((package/phase/'task.json').read_text()); save(work/'task.json', task)
            mutations = damage(work) if label == 'repair' else []
            prefix = sandbox(home, work, package/phase/'inputs', pvroot, args.claude, args.credentials,
                             product if method == 'schemaxis' else None)
            command_args = prefix+['/opt/claude', '-p', '--safe-mode', '--strict-mcp-config', '--mcp-config', '{"mcpServers":{}}',
                '--tools', 'Bash,Read,Write,Edit,Glob,Grep', '--allowedTools', 'Bash', 'Read', 'Write', 'Edit', 'Glob', 'Grep',
                '--permission-mode', 'dontAsk', '--model', args.model, '--effort', args.effort,
                '--max-budget-usd', str(args.budget_usd), '--output-format', 'stream-json', '--verbose']
            command_args += ['--session-id', sessions[arm]] if label == 'initial' else ['--resume', sessions[arm]]
            prompts = {'initial': 'Read TASK.md and task.json. Implement or use the reusable procedure and execute all cases now.',
                'repeat': 'Repeat the unchanged task using your existing procedure. Validate any reused publications; regeneration is allowed. Execute now and report what reran or reused.',
                'revision': 'task.json and read-only inputs now contain revised parameters and a new case. Read them and execute all requested outputs using or adapting your procedure. Starting recipes were not regenerated.',
                'repair': 'Some published files have been deleted or replaced with incorrect outputs. task.json and inputs are unchanged. Check and repair the complete submission using your procedure, retaining evidence. Do not trust file existence alone.'}
            print(json.dumps({'event': 'start', 'arm': arm, 'round': label}), flush=True)
            record = invoke(command_args, prompts[label], base/label, args.seconds)
            record.update(arm=arm, round=label, taskDigest=digest(task), inputDigest=tree_digest(package/phase/'inputs'), mutations=mutations)
            if record['terminalReason'] == 'api_error' or record['apiErrorStatus'] is not None or record['isError'] is not False:
                record['grade'] = {'passed': None, 'cases': [], 'status': 'not-scored'}
                report['runs'].append(record); report.update(status='blocked', blockedReason=record['providerMessage'] or 'CLI failed or returned no final result')
                save(destination/'report.json', report)
                return report
            shutil.copytree(work, base/label/'workspace', symlinks=True)
            record['grade'] = grade(package/phase/'task.json', base/label/'workspace/submission',
                package/phase/'reference', pvroot/'bin/pvbatch', base/label/'grade')
            report['runs'].append(record); save(destination/'report.json', report)
            measured = summarise(report); measured['scope'] = report['scope']; save(destination/'measurements.json', measured)
            print(json.dumps({'event': 'finish', 'arm': arm, 'round': label, 'seconds': record['wallSeconds'],
                              'passed': record['grade']['passed']}), flush=True)
    report.update(status='complete', allArtifactsPassed=all(r['grade']['passed'] for r in report['runs']))
    save(destination/'report.json', report)
    measured = summarise(report); measured['scope'] = report['scope']; save(destination/'measurements.json', measured)
    return report


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('action', choices=('prepare', 'prove', 'challenge', 'run'))
    parser.add_argument('--config', type=Path, required=True); parser.add_argument('--package', type=Path)
    parser.add_argument('--output-directory', type=Path, required=True)
    parser.add_argument('--model', default='claude-opus-5-5'); parser.add_argument('--effort', default='high')
    parser.add_argument('--seconds', type=int, default=600); parser.add_argument('--budget-usd', type=float, default=6)
    parser.add_argument('--claude', type=Path, default=Path.home()/'.local/bin/claude')
    parser.add_argument('--credentials', type=Path, default=Path.home()/'.claude/.credentials.json')
    args = parser.parse_args(); args.output_directory = args.output_directory.resolve()
    args.claude = args.claude.resolve(); args.credentials = args.credentials.resolve()
    config = args.config.resolve(); os.environ['SCHEMAXIS_CONFIG'] = str(config)
    pvroot = Path(json.loads(config.read_text())['locations']['roots'][0]).resolve()
    if args.action == 'prepare': prepare(args.output_directory, pvroot/'bin/pvbatch')
    elif args.action == 'prove': prove(args.package.resolve(), args.output_directory, pvroot/'bin/pvbatch', config)
    elif args.action == 'challenge': challenge(args.package.resolve(), args.output_directory, pvroot/'bin/pvbatch')
    else:
        report = run(args, pvroot)
        return 2 if report['status'] == 'blocked' else 0 if report['allArtifactsPassed'] else 1
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
