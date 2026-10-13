#!/usr/bin/env python3
"""Compare smaller and frontier Claude models with trusted native/Schemaxis recipes.

Each recipe replicate has six Claude or four Codex conversations and four rounds. The independent
grader, recipes, checker and isolation are shared with the onboarding experiment.
Run prepare and run with the same replicate number (1, 2 or 3).
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
from run_paraview_onboarding_pilot import introduction as qualified_introduction

MODELS = {'haiku': 'claude-haiku-4-5-20251001', 'sonnet': 'claude-sonnet-4-6',
          'opus': 'claude-opus-5-5'}
ARMS = tuple(f'{model}-{method}' for model in MODELS for method in ('native', 'schemaxis'))


def orders(replicate, arms=ARMS):
    # Each model/method occupies each serial position twice over three replicates.
    offset = (2*(replicate-1)) % len(arms)
    rotated = arms[offset:]+arms[:offset]
    shifted = rotated[3:]+rotated[:3]
    return (rotated, tuple(reversed(rotated)), shifted, tuple(reversed(shifted)))


CHECKER = RECIPES/'check_outputs.py'


def tasks(replicate=1):
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
    # Matched variants across cells, with fresh parameters across replicates.
    for task in (initial, revision):
        for case_item in task['cases']:
            case_item['offset'] += 2*replicate
            case_item['length'] *= 1+.04*replicate
            case_item['height'] *= 1+.03*replicate
    return {'initial': initial, 'revision': revision}


def prepare(destination, pvbatch, replicate=1):
    destination.mkdir(parents=True, exist_ok=False)
    for phase, task in tasks(replicate).items():
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


TRUST = """Treat the supplied recipe and framework as user-approved dependencies.
Do not audit their implementation, recreate their algorithms, or write a separate
reference renderer or custom output validator. Read the operating instructions,
execute the task, and use the supplied checker. Investigate implementation only
when execution fails, a supplied check fails, or the request exceeds documented
scope. Report the checker limits accurately. This instruction does not authorise
claiming that untested properties were independently verified.
"""


def introduction(method, condition, qualification):
    text = qualified_introduction(method, 'checked', qualification)
    start = text.index('Use `')
    end = text.index('Command (retain', start)
    text = text[:start]+TRUST+'\n'+text[end:]
    text = text.replace('extra checks are appropriate when observations warrant them.',
                        'investigate failures; do not invent extra routine checks.')
    return text


AUTHORING_TRUST = """Treat the installed libraries as approved dependencies. Read public contracts,
CLI help and schemas to learn their interfaces; do not audit library internals or
reimplement library algorithms. You must author the task-specific procedure:
no complete recipe is supplied. Use the supplied output checker rather than
building a custom validator/reference renderer. Investigate execution/check
failures and unsupported requirements. State verification limits accurately.
"""


def authoring_start(method):
    common = AUTHORING_TRUST+"""
The native runtime and supplied checker were independently exercised before your
session, using coordinator code that is not supplied. That qualification does
not certify your newly authored procedure. Save native logs and use:
`/opt/paraview/bin/pvbatch --force-offscreen-rendering /work/check_outputs.py /work/task.json /work/submission --record /work/checked.json > check.log 2>&1`
Inspect its exit status and report. The checker verifies analytic geometry and
fields, image dimensions/nonblank content, and optional baseline hashes. It DOES
NOT independently certify image camera, colour mapping or image time. The hidden
evaluator checks those properties. Report that distinction honestly.
"""
    if method == 'native':
        return common+"""
Author ordinary ParaView Python and run it with:
`/opt/paraview/bin/pvbatch --force-offscreen-rendering YOUR_SCRIPT.py`
Use the public paraview.simple API; native Python help is available in pvbatch.
"""
    return common+"""
Author Schemaxis ParaView pipeline documents (version schemaxis/1).
Start with /opt/schemaxis/docs/json-input.md and paraview-catalogue.md.
Public discovery and planning are available through `python3 -m schemaxis --help`,
`python3 -m schemaxis schema --provider paraview --authored`, and `python3 -m schemaxis plan`.
Execute with `python3 -m schemaxis run INPUT.json --output-directory RUN_DIRECTORY`.
Retained verification.json artifacts include file paths and identities that can
be used to copy publications into the required submission names. Ordinary Python
may build documents and organise outputs; use Schemaxis for slicing and rendering.
"""


def run(args, pvroot):
    started = time.monotonic()
    provider = getattr(args, 'provider', 'claude')
    authoring = getattr(args, 'task_mode', 'recipe') == 'authoring'
    compact_pilot = getattr(args, 'compact_plan', False)
    evaluate = grade
    if compact_pilot:
        import compact_plan_experiment as experiment
        if provider != 'codex' or not authoring or getattr(args, 'omit_arm', []):
            raise ValueError('Compact-plan pilot requires Codex authoring and all six arms')
        evaluate = experiment.grade
    models = MODELS if provider == 'claude' else {'luna': 'gpt-5.6-luna', 'astra': 'gpt-6-astra'}
    variants = ('native', 'full', 'compact') if compact_pilot else ('native', 'schemaxis')
    arms = tuple(f'{model}-{method}' for model in models for method in variants)
    omitted = getattr(args, 'omit_arm', [])
    if any(arm not in arms for arm in omitted):
        raise ValueError('Unknown omitted arm')
    arms = tuple(arm for arm in arms if arm not in omitted)
    run_orders = orders(args.replicate, arms)
    if provider == 'codex':
        import model_pilot_codex as codex
        isolate = codex.sandbox
    else:
        isolate = sandbox
    destination = args.output_directory; destination.mkdir(parents=True, exist_ok=False)
    package = args.package.resolve(); product = destination/'product'
    for phase, expected_task in tasks(args.replicate).items():
        if json.loads((package/phase/'task.json').read_text()) != expected_task:
            raise ValueError('Package does not match the declared replicate')
    shutil.copytree(ROOT/'src', product/'src', ignore=shutil.ignore_patterns('__pycache__', '*.pyc'))
    (product/'docs').mkdir()
    for name in ('getting-started.md', 'workflow-authoring.md', 'json-input.md', 'schema-guide.md', 'capability-discovery.md'):
        shutil.copyfile(ROOT/'docs'/name, product/'docs'/name)
    if authoring:
        shutil.copyfile(ROOT/'docs/paraview-catalogue.md', product/'docs/paraview-catalogue.md')
    if compact_pilot:
        experiment.configure_product(product)
    source = subprocess.check_output(['git', '-C', str(ROOT), 'rev-parse', 'HEAD'], text=True).strip()
    native_version = subprocess.check_output([str(pvroot/'bin/pvbatch'), '--version'], text=True).strip()
    native_digest = hashlib.sha256((pvroot/'bin/pvbatch').read_bytes()).hexdigest()
    report = {'kind': 'autonomous-ai-model-capability-pilot', 'taskMode': 'authoring' if authoring else 'recipe', 'family': 'paraview', 'replicates': 1,
        'model': provider+' model matrix', 'provider': provider, 'models': models, 'replicate': args.replicate, 'effort': args.effort, 'schemaxisMode': 'required', 'status': 'preflight', 'runs': [],
        'sourceCommit': source, 'productSourceDigest': tree_digest(product/'src'),
        'recipeDigest': tree_digest(RECIPES), 'checkerDigest': hashlib.sha256(CHECKER.read_bytes()).hexdigest(),
        'orders': run_orders, 'preflights': [],
        'omittedArms': omitted,
        'limits': {'wallSecondsPerInvocation': args.seconds, 'claudeMaxBudgetUSDFlag': args.budget_usd if provider == 'claude' else None},
        'conditions': {arm: {'model': models[arm.split('-')[0]], 'method': arm.split('-')[1], 'introduction': 'trusted'} for arm in arms},
        'scope': ('Fresh two-round authoring conversations; no complete recipe; exploratory, not independently replicated'
                  if authoring else 'One exploratory OpenAI replicate; four model/method cells; trusted qualified recipes'
                  if provider == 'codex' else 'One of three independent Claude replicates; six model/method cells; trusted qualified recipes; network available; no claim of general model equivalence')}
    if compact_pilot:
        report.update(kind='compact-plan-presentation-pilot', scope='Six fresh authoring conversations; initial, unchanged repeat and revision; no statistical equivalence claim.',
                      experiment=experiment.metadata(models, args.seconds, args.pilot_cost_limit),
                      experimentDigest=tree_digest(product/'experiment'))
    save(destination/'report.json', report)
    frozen = destination/'harness'; frozen.mkdir()
    for name in ('run_paraview_model_pilot.py', 'run_paraview_onboarding_pilot.py',
                 'run_paraview_ai_pilot.py', 'run_rlc_ai_pilot.py', 'paraview_benchmark_native.py',
                 'summarise_ai_pilot.py', 'benchmark_workflows.py', 'model_pilot_codex.py',
                 *(experiment.FILES if compact_pilot else ())):
        shutil.copyfile(ROOT/'tools'/name, frozen/name)
    report['harnessDigest'] = tree_digest(frozen)
    report['cliVersion'] = subprocess.check_output([str(args.claude), '--version'], text=True).strip()
    report['trustInstruction'] = AUTHORING_TRUST if authoring else TRUST
    sessions = {}; previous_usage = {}; telemetry_offsets = {}; local_evidence_state = {}
    for arm in arms:
        model_name, method = experiment.arm_method(arm) if compact_pilot else arm.split('-')
        condition = 'checked'; base = destination/arm
        work = base/'work'; work.mkdir(parents=True); home = base/'home'; home.mkdir()
        (work/'inputs').mkdir(); save(work/'runtime.json', runtime_configuration())
        shutil.copyfile(RECIPES/recipe(method), work/recipe(method))
        extra = ('\nUse Schemaxis for all slicing and rendering. Ordinary Python may prepare inputs, inspect results and collect publications.\n'
                 'A complete reusable procedure is supplied: schemaxis_recipe.py. Run with Python 3. Source/docs: /opt/schemaxis.\n'
                 if method == 'schemaxis' else '\nUse ordinary ParaView Python; Schemaxis is unavailable and prohibited.\n'
                 'A complete reusable starting procedure is supplied: native_recipe.py. Follow START.md.\n')
        if condition != 'baseline': extra += '\nRead START.md for the invocation, qualification evidence and operating guidance.\n'
        (work/'TASK.md').write_text(TASK+extra+'\n'+TRUST+f'\nTime allowance: {args.seconds} seconds per turn.\n')
        sessions[arm] = str(uuid.uuid4())
        save(work/'task.json', json.loads((package/'initial/task.json').read_text()))
        prefix = isolate(home, work, package/'initial/inputs', pvroot, args.claude, args.credentials,
                         product if method == 'schemaxis' else None)
        if compact_pilot:
            prefix = experiment.prefix_environment(prefix, arm)
        before = time.monotonic()
        probe = subprocess.run(prefix+launch(method, '/work/.preflight-output'), text=True, capture_output=True, timeout=240)
        (base/'native-preflight.log').write_text(probe.stdout+probe.stderr)
        if probe.returncode: raise RuntimeError('native namespace preflight failed: '+arm)
        if compact_pilot and method == 'schemaxis':
            planned_probe = subprocess.run(prefix+['python3', '/opt/schemaxis/experiment/plan_cli.py', 'plan',
                '/work/.preflight-output/field-a/pipeline.json', '--retain', '/work/.plan-preflight'],
                text=True, capture_output=True, timeout=30)
            (base/'plan-preflight.json').write_text(planned_probe.stdout)
            (base/'plan-preflight.stderr.log').write_text(planned_probe.stderr)
            if planned_probe.returncode:
                raise RuntimeError('plan presentation preflight failed: '+arm)
            shutil.move(work/'.plan-preflight', base/'plan-preflight-evidence')
        checker_result = None
        if condition == 'checked':
            shutil.copyfile(CHECKER, work/'check_outputs.py')
            checked_probe = subprocess.run(prefix+native_command('/opt/paraview/bin/pvbatch', '/work/check_outputs.py',
                '/work/task.json', '/work/.preflight-output'), text=True, capture_output=True, timeout=90)
            (base/'checker-preflight.log').write_text(checked_probe.stdout+checked_probe.stderr)
            if checked_probe.returncode: raise RuntimeError('public checker preflight failed: '+arm)
            checker_result = json.loads(checked_probe.stdout)
        shutil.move(work/'.preflight-output', base/'native-preflight-output')
        checked = evaluate(package/'initial/task.json', base/'native-preflight-output', package/'initial/reference',
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
        if authoring:
            (work/recipe(method)).unlink()
            (work/'qualification.json').unlink()
            start_text = authoring_start(method)
            if compact_pilot:
                start_text = experiment.introduction(start_text, method)
            (work/'START.md').write_text(start_text)
            method_rule = ('Use Schemaxis for all slicing and rendering. Public source/docs: /opt/schemaxis.'
                           if method == 'schemaxis' else 'Use ordinary ParaView Python; Schemaxis is unavailable and prohibited.')
            (work/'TASK.md').write_text(TASK+'\n'+method_rule+'\nRead START.md.\n'+AUTHORING_TRUST+
                                       f'\nTime allowance: {args.seconds} seconds per turn.\n')
        save(destination/'report.json', report)
        print(json.dumps({'event': 'preflight-passed', 'arm': arm}), flush=True)
    if getattr(args, 'stage_only', False):
        report.update(status='staged-no-model-runs', preparationSeconds=time.monotonic()-started)
        save(destination/'report.json', report)
        return report
    report.update(status='running', preparationSeconds=time.monotonic()-started)
    save(destination/'report.json', report)
    round_labels = experiment.ROUNDS if compact_pilot else ('initial', 'revision') if authoring else ('initial', 'repeat', 'revision', 'repair')
    unavailable_arms = set()
    for index, label in enumerate(round_labels):
        phase = 'initial' if label in ('initial', 'repeat') else 'revision'
        for arm in run_orders[index]:
            if arm in unavailable_arms:
                continue
            model_name, method = experiment.arm_method(arm) if compact_pilot else arm.split('-')
            condition = 'checked'; base = destination/arm; work = base/'work'; home = base/'home'
            if compact_pilot:
                spending = experiment.spent(report)
                report['spending'] = spending
                if not spending['complete'] or spending['knownListPriceCostUSD'] >= args.pilot_cost_limit:
                    report.update(status='budget-stopped' if spending['complete'] else 'unresolved-accounting')
                    save(destination/'report.json', report)
                    experiment.save_measurements(report, destination)
                    return report
            task = json.loads((package/phase/'task.json').read_text()); save(work/'task.json', task)
            mutations = damage(work) if label == 'repair' else []
            prefix = isolate(home, work, package/phase/'inputs', pvroot, args.claude, args.credentials,
                             product if method == 'schemaxis' else None)
            if compact_pilot:
                prefix = experiment.prefix_environment(prefix, arm)
            if provider == 'claude':
                command_args = prefix+['/opt/claude', '-p', '--safe-mode', '--strict-mcp-config', '--mcp-config', '{"mcpServers":{}}',
                    '--tools', 'Bash,Read,Write,Edit,Glob,Grep', '--allowedTools', 'Bash', 'Read', 'Write', 'Edit', 'Glob', 'Grep',
                    '--permission-mode', 'dontAsk', '--model', models[model_name], '--effort', args.effort,
                    '--max-budget-usd', str(args.budget_usd), '--output-format', 'stream-json', '--verbose']
                command_args += ['--session-id', sessions[arm]] if label == 'initial' else ['--resume', sessions[arm]]
            else:
                command_args = prefix+codex.command(models[model_name], args.effort,
                                                   sessions[arm] if label != 'initial' else None)
            prompts = {'initial': 'Read TASK.md and task.json. Implement or use the reusable procedure and execute all cases now.',
                'repeat': 'Repeat the unchanged task using your existing procedure. Validate any reused publications; regeneration is allowed. Execute now and report what reran or reused.',
                'revision': 'task.json and read-only inputs now contain revised parameters and a new case. Read them and execute all requested outputs using or adapting your procedure. Starting recipes were not regenerated.',
                'repair': 'Some published files have been deleted or replaced with incorrect outputs. task.json and inputs are unchanged. Check and repair the complete submission using your procedure, retaining evidence. Do not trust file existence alone.'}
            if authoring:
                prompts['initial'] = 'Read TASK.md, START.md and task.json. Author a reusable procedure and execute all cases now.'
                prompts['revision'] = 'task.json and read-only inputs contain revised parameters and a new case. Adapt your procedure and execute all requested outputs. Use the supplied checker and report verification limits.'
            print(json.dumps({'event': 'start', 'arm': arm, 'round': label}), flush=True)
            # Preserve the actual invocation separately from its public response.
            save(base/(label+'-invocation.json'), {'argv': command_args, 'prompt': prompts[label]})
            record = (invoke if provider == 'claude' else codex.invoke)(command_args, prompts[label], base/label, args.seconds)
            save(base/label/'invocation-result.json', record)
            if provider == 'codex' and record.get('sessionId'):
                sessions[arm] = record['sessionId']
            if compact_pilot:
                record.update(arm=arm, model=models[model_name], replicate=args.replicate, round=label,
                              taskDigest=digest(task), inputDigest=tree_digest(package/phase/'inputs'), mutations=mutations)
                previous_usage[arm], telemetry_offsets[arm], local_evidence_state[arm] = experiment.finish_invocation(
                    record, report, base, label, home, sessions[arm], work, previous_usage.get(arm, {}),
                    telemetry_offsets.get(arm, 0), local_evidence_state.get(arm), package/phase/'task.json',
                    package/phase/'reference', pvroot/'bin/pvbatch', evaluate)
                print(json.dumps({'event': 'finish', 'arm': arm, 'round': label, 'seconds': record['wallSeconds'],
                                  'passed': record['grade']['passed'], 'status': report['status']}), flush=True)
                if report['status'] != 'running':
                    return report
                continue
            if provider == 'codex' and not record['isError']:
                sessions[arm] = record['sessionId']
                cumulative = record['usage']
                record['codexCumulativeUsage'] = cumulative
                record['usage'], record['listPriceCostUSD'] = codex.accounting(
                    cumulative, previous_usage.get(arm, {}), models[model_name])
                previous_usage[arm] = cumulative
                context = codex.session_context(home, sessions[arm]); record['codexContext'] = context
                if context['models'] != [models[model_name]] or context['maxRequestInputTokens'] > 272000:
                    raise RuntimeError('Unexpected model or long-context pricing; adjudicate retained evidence')
                record['modelUsage'] = {models[model_name]: {'provider': 'OpenAI', 'costBasis': 'API list-price estimate'}}
            record.update(arm=arm, model=models[model_name], replicate=args.replicate, round=label, taskDigest=digest(task), inputDigest=tree_digest(package/phase/'inputs'), mutations=mutations)
            save(base/label/'normalised-result.json', record)
            observed_models = set((record.get('modelUsage') or {}).keys())
            record['requestedModelObserved'] = models[model_name] in observed_models
            if observed_models and observed_models != {models[model_name]}:
                # Never call a substituted-model result a requested-model result.
                # Preserve and grade its artifacts diagnostically, then stop this
                # conversation without trying to override provider safeguards.
                record['eligibleForModelComparison'] = False
                record['observedModels'] = sorted(observed_models)
                record['exclusionReason'] = 'Provider substituted or added an unrequested model'
                shutil.copytree(work, base/label/'workspace', symlinks=True)
                record['diagnosticGrade'] = evaluate(package/phase/'task.json', base/label/'workspace/submission',
                    package/phase/'reference', pvroot/'bin/pvbatch', base/label/'diagnostic-grade')
                record['grade'] = {'passed': None, 'cases': [], 'status': 'not-scored-model-substitution'}
                report['runs'].append(record)
                report.setdefault('unavailableArms', {})[arm] = record['exclusionReason']
                unavailable_arms.add(arm)
                save(destination/'report.json', report)
                continue
            if record['terminalReason'] in ('api_error', 'infrastructure_error') or record['apiErrorStatus'] is not None:
                record['grade'] = {'passed': None, 'cases': [], 'status': 'not-scored'}
                report['runs'].append(record); report.update(status='blocked', blockedReason=record['providerMessage'] or 'Provider failure')
                save(destination/'report.json', report)
                return report
            # A timeout/budget exhaustion is an outcome, not a provider exclusion.
            # Grade whatever was actually produced and retain the failed invocation.
            shutil.copytree(work, base/label/'workspace', symlinks=True)
            record['grade'] = evaluate(package/phase/'task.json', base/label/'workspace/submission',
                package/phase/'reference', pvroot/'bin/pvbatch', base/label/'grade')
            report['runs'].append(record); save(destination/'report.json', report)
            measured = summarise(report); measured['scope'] = report['scope']; save(destination/'measurements.json', measured)
            print(json.dumps({'event': 'finish', 'arm': arm, 'round': label, 'seconds': record['wallSeconds'],
                              'passed': record['grade']['passed']}), flush=True)
    report.update(status='complete', allArtifactsPassed=all(r['grade']['passed'] for r in report['runs']))
    save(destination/'report.json', report)
    if compact_pilot:
        experiment.save_measurements(report, destination)
    else:
        measured = summarise(report); measured['scope'] = report['scope']; save(destination/'measurements.json', measured)
    return report


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('action', choices=('prepare', 'prove', 'challenge', 'stage', 'run'))
    parser.add_argument('--config', type=Path, required=True); parser.add_argument('--package', type=Path)
    parser.add_argument('--output-directory', type=Path, required=True)
    parser.add_argument('--task-mode', choices=('recipe', 'authoring'), default='recipe')
    parser.add_argument('--omit-arm', action='append', default=[], help='Explicitly omit a documented unavailable comparison cell')
    parser.add_argument('--provider', choices=('claude', 'codex'), default='claude')
    parser.add_argument('--replicate', type=int, choices=(1, 2, 3), default=1)
    parser.add_argument('--effort', default='high')
    parser.add_argument('--compact-plan', action='store_true', help='experimental six-arm Codex authoring comparison; production CLI unchanged')
    parser.add_argument('--pilot-cost-limit', type=float, default=20, help='compact pilot soft list-price stop between invocations, not an in-flight cap')
    parser.add_argument('--seconds', type=int, default=600); parser.add_argument('--budget-usd', type=float, default=6)
    parser.add_argument('--claude', type=Path, default=Path.home()/'.local/bin/claude')
    parser.add_argument('--credentials', type=Path, default=Path.home()/'.claude/.credentials.json')
    args = parser.parse_args(); args.output_directory = args.output_directory.resolve()
    args.stage_only = args.action == 'stage'
    if args.seconds <= 0 or args.pilot_cost_limit <= 0:
        parser.error('time and cost bounds must be positive')
    if args.provider == 'codex':
        args.claude = Path.home()/'.local/bin/codex'
        args.credentials = Path.home()/'.codex/auth.json'
    args.claude = args.claude.resolve(); args.credentials = args.credentials.resolve()
    config = args.config.resolve(); os.environ['SCHEMAXIS_CONFIG'] = str(config)
    pvroot = Path(json.loads(config.read_text())['locations']['roots'][0]).resolve()
    if args.action == 'prepare': prepare(args.output_directory, pvroot/'bin/pvbatch', args.replicate)
    elif args.action == 'prove': prove(args.package.resolve(), args.output_directory, pvroot/'bin/pvbatch', config)
    elif args.action == 'challenge': challenge(args.package.resolve(), args.output_directory, pvroot/'bin/pvbatch')
    else:
        try:
            report = run(args, pvroot)
        except BaseException as error:
            report_path = args.output_directory/'report.json'
            if report_path.exists():
                interrupted = json.loads(report_path.read_text())
                interrupted.update(status='interrupted', interruption=type(error).__name__+': '+str(error))
                save(report_path, interrupted)
            raise
        if report['status'] == 'staged-no-model-runs':
            return 0
        return 2 if report['status'] in ('blocked', 'budget-stopped', 'unresolved-accounting', 'incomplete-observation') else 0 if report['allArtifactsPassed'] else 1
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
