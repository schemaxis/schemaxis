"""Narrow instrumentation and setup for the compact-plan authoring pilot."""
import collections
import hashlib
import json
import math
from pathlib import Path
import shutil

from benchmark_workflows import ROOT, command, save
from run_paraview_ai_pilot import native_command


FILES = ('compact_plan_cli.py', 'compact_plan_evaluator.py', 'compact_plan_experiment.py')
ROUNDS = ('initial', 'repeat', 'revision')


def arm_method(arm):
    model, variant = arm.split('-')
    return model, 'native' if variant == 'native' else 'schemaxis'


def configure_product(product):
    target = product / 'experiment'
    target.mkdir()
    shutil.copyfile(ROOT / 'tools/compact_plan_cli.py', target / 'plan_cli.py')


def prefix_environment(prefix, arm):
    variant = arm.split('-')[1]
    if variant == 'native':
        return prefix
    result = list(prefix)
    index = result.index('--')
    result[index:index] = ['--setenv', 'SCHEMAXIS_PLAN_PRESENTATION', variant]
    return result


def introduction(text, method):
    if method == 'native':
        return text
    return text.replace('`python3 -m schemaxis plan`',
                        '`python3 /opt/schemaxis/experiment/plan_cli.py plan INPUT.json`') + """
Use that experimental entry point for planning. It calls the unchanged production
planner and retains complete responses under /work/plan-evidence. Its presentation
mode is configured by the coordinator. Production execution and schemas are unchanged.
For retained details use `python3 /opt/schemaxis/experiment/plan_cli.py inspect FILE
--pointer /PATH --revision OBSERVATION_REVISION`. The revision is the existing
observation digest, not the pipeline digest or raw-file SHA256. Planning does not
execute native applications or verify publications. Keep the retained plan files.
"""


def metadata(models, seconds, cost_limit):
    from model_pilot_codex import PRICES
    return {'treatment': 'Plan presentation only; identical broad-schema onboarding in both Schemaxis arms.',
        'replication': 'One fresh conversation per cell; related initial/repeat/revision observations.',
        'plannedTurns': 18, 'maximumModelWallSeconds': 18 * seconds,
        'indicativeImprovementTarget': .20, 'automaticShippingDecision': False,
        'estimatedListPriceRangeUSD': [6, 12],
        'estimateBasis': 'Historical 2026-09-29 authoring costs plus repeat turns; not a billing guarantee.',
        'betweenInvocationStopUSD': cost_limit,
        'costLimitScope': 'Soft stop before the next invocation; an in-flight turn can exceed it. No Codex CLI dollar cap.',
        'accountingGate': 'Stop on unresolved final metering or pricing; partial usage is retained as known evidence, never a complete total.',
        'observationGate': 'Stop on missing or malformed required telemetry, diagnostic capture or grading.',
        'priceDate': '2026-09-29', 'priceBasis': 'Frozen historical API list rates, not subscription charges or freshly verified prices.',
        'priceCategoryOrder': ['ordinaryInput', 'cacheRead', 'cacheWrite', 'output'],
        'pricesUSDPerMillion': {m: PRICES[m] for m in models.values()},
        'qualityConclusion': 'Bounded evaluator acceptance only; procedure/claim audits required. No unqualified quality-preserved claim.',
        'telemetryScope': 'Recorded model-facing tool content after tool truncation, not a capture of complete provider request bodies; usage-record request counts exclude unrecorded failed requests.'}


def grade(task_path, submission, reference, pvbatch, logs):
    logs.mkdir(parents=True, exist_ok=False)
    output = logs / 'grade.json'
    command(native_command(pvbatch, ROOT/'tools/compact_plan_evaluator.py',
                           task_path, submission, reference, output), logs, 'grader', 180)
    result = json.loads(output.read_text())
    task = json.loads(task_path.read_text())
    expected = {c['id'] for c in task['cases']}
    actual = {p.name for p in submission.iterdir() if p.is_dir()} if submission.is_dir() else set()
    result['caseSetMatches'] = actual == expected
    result['passed'] = result['passed'] and result['caseSetMatches']
    save(output, result)
    return result


def session_telemetry(path, directory, offset=0):
    """Separate UI execution output, tool response content, and model usage.

Use an event-line offset for tools and reconcile response IDs against the whole
retained prefix for requests. Conflicting repeats make the observation incomplete.
"""
    directory.mkdir(parents=True, exist_ok=True)
    lines = Path(path).read_text().splitlines()
    if offset > len(lines):
        raise ValueError('session log shrank')
    calls, responses, requests, messages = [], [], {}, []
    seen, conflicts, duplicates = {}, [], 0
    malformed = 0
    for index, line in enumerate(lines):
        try:
            event = json.loads(line)
            if not isinstance(event, dict) or not isinstance(event.get('payload', {}), dict):
                raise ValueError('Invalid event shape')
        except ValueError:
            malformed += 1
            continue
        value = event.get('payload', {})
        if event.get('type') == 'token_usage_record' and value.get('response_id'):
            identity = value['response_id']
            usage = value.get('usage')
            if not isinstance(identity, str) or not isinstance(usage, dict) or not usage or not all(
                    isinstance(v, int) and not isinstance(v, bool) and v >= 0 for v in usage.values()):
                malformed += 1
                continue
            if identity in seen:
                if seen[identity] != value:
                    conflicts.append({'responseId': identity, 'line': index})
                if index >= offset:
                    duplicates += 1
            else:
                seen[identity] = value
                if index >= offset:
                    requests[identity] = value
        if index < offset:
            continue
        if event.get('type') != 'response_item':
            continue
        entry = {'line': index, 'timestamp': event.get('timestamp'), 'payload': value}
        if value.get('type') in ('custom_tool_call', 'function_call'):
            calls.append(entry)
        elif value.get('type') in ('custom_tool_call_output', 'function_call_output'):
            responses.append(entry)
        elif value.get('type') == 'message':
            messages.append(entry)
    for name, values in [('tool-calls', calls), ('model-visible-tool-responses', responses),
                         ('model-usage-records', list(requests.values())), ('messages', messages)]:
        (directory/(name+'.jsonl')).write_text(''.join(json.dumps(v, ensure_ascii=False)+'\n' for v in values))
    def text_bytes(entry):
        value = entry['payload'].get('output', '')
        if isinstance(value, list):
            return sum(len(v.get('text', '').encode()) for v in value if isinstance(v, dict))
        return len(str(value).encode())
    return {'sessionLog': str(path), 'nextLineOffset': len(lines), 'malformedLines': malformed,
        'complete': not malformed and not conflicts, 'duplicateUsageRecords': duplicates,
        'conflictingResponseIds': conflicts,
        'recordedModelRequests': len(requests) if requests else None,
        'requestCountScope': 'New response IDs reconciled against the retained session prefix; excludes unrecorded failed requests.',
        'modelToolCalls': len(calls), 'modelToolResponses': len(responses),
        'recordedToolResponseTextBytes': sum(map(text_bytes, responses)),
        'usageCategories': dict(sum((collections.Counter(r.get('usage', {})) for r in requests.values()), collections.Counter()))}


def capture_round(home, session, directory, offset=0):
    paths = list((home/'.codex/sessions').rglob('*'+session+'*.jsonl'))
    if len(paths) != 1:
        save(directory/'telemetry.json', {'available': False, 'complete': False, 'reason': 'Unique session log unavailable'})
        return offset
    info = session_telemetry(paths[0], directory/'telemetry', offset)
    # CLI stream output can retain far more than the model-facing tool response.
    commands = []
    for line in (directory/'transcript.jsonl').read_text().splitlines():
        try:
            event = json.loads(line)
        except json.JSONDecodeError:
            continue
        item = event.get('item', {})
        if event.get('type') == 'item.completed' and item.get('type') == 'command_execution':
            commands.append({'command': item.get('command'), 'exitCode': item.get('exit_code'),
                'retainedStreamOutputBytes': len(item.get('aggregated_output', '').encode())})
    info.update(available=True, localCommandCalls=len(commands), localCommands=commands,
                complete=info['complete'] and info['recordedModelRequests'] is not None)
    save(directory/'telemetry.json', info)
    save(directory/'procedure-audit.json', {'status': 'requires-review',
        'reusableProcedure': None, 'evidenceRetained': None, 'verificationClaimsAccurate': None,
        'repairAttempts': None, 'planPresentationCompliance': None,
        'evidence': 'Review tool calls, messages, workspace and presentation-events.jsonl; command exit codes alone miss swallowed failures.'})
    return info['nextLineOffset']


def spent(report):
    """Known cumulative estimates and explicit coverage; never price unknown as zero."""
    latest, unresolved = {}, []
    for run in report['runs']:
        cost = run.get('listPriceCostUSD')
        valid = isinstance(cost, (int, float)) and not isinstance(cost, bool) and math.isfinite(cost) and cost >= latest.get(run['arm'], 0)
        if valid:
            latest[run['arm']] = cost
        if not valid or run.get('accounting', {}).get('complete') is not True:
            unresolved.append({'arm': run['arm'], 'round': run.get('round')})
    return {'knownListPriceCostUSD': sum(latest.values()), 'complete': not unresolved,
            'unresolvedInvocations': unresolved,
            'basis': 'Latest recorded cumulative estimate per conversation at frozen API list prices; not subscription charges.'}


def account_invocation(record, previous, model, home, session):
    """Keep metered failures, but a non-final log total cannot close an in-flight bill."""
    import model_pilot_codex as codex
    raw = record.get('usage') or {}
    record['codexReportedUsage'] = raw
    record['usage'] = {}
    record['listPriceCostUSD'] = None
    state = record['accounting'] = {'complete': False, 'source': 'turn.completed', 'errors': []}
    cumulative = raw
    try:
        if not cumulative:
            state['source'] = 'retained-thread-token-usage; partial'
            paths = list((home/'.codex/sessions').rglob('*'+session+'*.jsonl'))
            if len(paths) != 1:
                raise ValueError('Unique session log unavailable for accounting')
            for line in paths[0].read_text().splitlines():
                try:
                    event = json.loads(line)
                except ValueError:
                    continue  # Truncated logs cannot provide final accounting.
                if isinstance(event, dict) and event.get('type') == 'token_usage_record':
                    payload = event.get('payload')
                    if isinstance(payload, dict) and payload.get('thread_token_usage'):
                        cumulative = payload['thread_token_usage']
        record['codexCumulativeUsage'] = cumulative
        keys = ('input_tokens', 'cached_input_tokens', 'cache_write_input_tokens', 'output_tokens')
        if not isinstance(cumulative, dict) or not all(
                isinstance(cumulative.get(k), int) and not isinstance(cumulative[k], bool) and cumulative[k] >= 0 for k in keys):
            raise ValueError('Missing or invalid token categories')
        record['usage'], record['listPriceCostUSD'] = codex.accounting(cumulative, previous, model)
        context = codex.session_context(home, session)
        record['codexContext'] = context
        if context['models'] != [model] or context['maxRequestInputTokens'] > 272000:
            raise ValueError('Unexpected model or long-context pricing; adjudication required')
        record['modelUsage'] = {model: {'provider': 'OpenAI', 'costBasis': 'Frozen API list-price estimate'}}
        state['complete'] = bool(raw) and record['terminalReason'] == 'completed' and not record['timedOut']
        if not state['complete']:
            state['errors'].append('No final metering boundary; unrecorded in-flight usage remains possible')
    except Exception as error:
        state['errors'].append(type(error).__name__+': '+str(error))
    return cumulative if state['complete'] else previous


def save_measurements(report, destination):
    """Keep existing summary arithmetic, label partial observations explicitly."""
    from summarise_ai_pilot import summarise
    measured = summarise(report)
    for run, row in zip(report['runs'], measured['rounds']):
        row.update(accountingComplete=run['accounting']['complete'],
                   observationComplete=run['observationComplete'])
        if not row['accountingComplete']:
            for key in ('listPriceCostUSDThisInvocation', 'inputTokensIncludingCache', 'outputTokens'):
                row['known'+key[0].upper()+key[1:]] = row[key]
                row[key] = None
            total = measured['totals'][run['arm']]
            for key in ('listPriceCostUSD', 'inputTokensIncludingCache', 'outputTokens'):
                total['known'+key[0].upper()+key[1:]] = total[key]
                total[key] = None
    measured.update(scope=report['scope'], spending=report['spending'],
                    observationsComplete=all(r.get('observationComplete') for r in report['runs']))
    save(destination/'measurements.json', measured)


def local_evidence(work, directory, previous=None):
    """Record changed retained timing evidence; never assume complete coverage.

Hashes distinguish rewrites from reuse. We do not sum potentially overlapping
process and publication times or infer missing native calls from absent receipts.
"""
    directory.mkdir(parents=True, exist_ok=True)
    previous = previous or {}
    current = {}
    records, errors = [], []
    for path in sorted(work.rglob('*.json')):
        if path.name not in ('submission.json', 'verification.json'):
            continue
        relative = str(path.relative_to(work))
        try:
            raw = path.read_bytes()
            sha = hashlib.sha256(raw).hexdigest()
            if previous.get(relative) == sha:
                current[relative] = sha
                continue
            value = json.loads(raw)
            if not isinstance(value, dict):
                raise ValueError('Receipt must be an object')
            if path.name == 'submission.json' and 'seconds' in value:
                seconds = value['seconds']
                if not isinstance(seconds, (float, int)) or isinstance(seconds, bool) or not math.isfinite(seconds) or seconds < 0:
                    raise ValueError('seconds must be a finite nonnegative number')
                records.append({'file': relative, 'fileSHA256': sha, 'nativeProcessSeconds': seconds,
                                'exitCode': value.get('exitCode'), 'command': value.get('command')})
            if path.name == 'verification.json':
                states = value.get('states')
                if not isinstance(states, list) or not all(isinstance(s, dict) for s in states):
                    raise ValueError('states must be a list of objects')
                for index, state in enumerate(states):
                    if 'timings' in state:
                        if not isinstance(state['timings'], dict):
                            raise ValueError('state timings must be an object')
                        records.append({'file': relative, 'state': index, 'timings': state['timings']})
            current[relative] = sha
        except (OSError, ValueError) as error:
            errors.append({'file': relative, 'error': type(error).__name__+': '+str(error)})
    presentation = []
    for path in sorted(work.rglob('presentation-events.jsonl')):
        relative = str(path.relative_to(work))
        try:
            lines = path.read_text().splitlines()
        except (OSError, ValueError) as error:
            errors.append({'file': relative, 'error': type(error).__name__+': '+str(error)})
            continue
        old_count = previous.get(relative, 0)
        if not isinstance(old_count, int) or old_count > len(lines):
            old_count = 0
        current[relative] = len(lines)
        for index, line in enumerate(lines[old_count:], old_count):
            try:
                event = json.loads(line)
                if not isinstance(event, dict):
                    raise ValueError('Presentation event must be an object')
                presentation.append(event)
            except ValueError as error:
                errors.append({'file': relative, 'line': index, 'error': str(error)})
    save(directory/'local-evidence.json', {'nativeTimingRecords': records,
         'presentationEvents': presentation, 'complete': not errors, 'errors': errors,
         'scope': 'Changed retained evidence only; native scripts may not emit these receipts. Missing times are unknown, not zero; overlapping timings are not summed.'})
    return current


def finish_invocation(record, report, base, label, home, session, work, previous_usage,
                      telemetry_offset, local_state, task_path, reference, pvbatch, evaluate):
    """Checkpoint first, then account, enrich and grade one compact-pilot invocation.

Only Exception is caught. Cancellation propagates with the checkpoint intact.
No continuation is allowed while accounting or required observations are unresolved.
"""
    directory = base/label
    destination = base.parent
    record.update(grade={'passed': None, 'cases': [], 'status': 'pending'},
                  accounting={'complete': False, 'errors': ['Accounting pending']},
                  observationComplete=False, diagnosticErrors=[])
    report['runs'].append(record)

    def checkpoint():
        save(directory/'normalised-result.json', record)
        report['spending'] = spent(report)
        save(destination/'report.json', report)

    checkpoint()
    current = account_invocation(record, previous_usage, record['model'], home, session)
    checkpoint()  # Enrichment failures cannot lose identity, terminal state or usage.
    telemetry_complete = local_complete = False
    try:
        telemetry_offset = capture_round(home, session, directory, telemetry_offset)
        telemetry = json.loads((directory/'telemetry.json').read_text())
        telemetry_complete = telemetry.get('complete') is True
        if not telemetry_complete:
            record['diagnosticErrors'].append({'stage': 'telemetry', 'error': 'Required telemetry incomplete; see telemetry.json'})
    except Exception as error:
        record['diagnosticErrors'].append({'stage': 'telemetry', 'error': type(error).__name__+': '+str(error)})
    try:
        local_state = local_evidence(work, directory, local_state)
        local = json.loads((directory/'local-evidence.json').read_text())
        local_complete = local['complete']
        if not local_complete:
            record['diagnosticErrors'].append({'stage': 'local-evidence', 'errors': local['errors']})
    except Exception as error:
        record['diagnosticErrors'].append({'stage': 'local-evidence', 'error': type(error).__name__+': '+str(error)})
    record['observationComplete'] = telemetry_complete and local_complete
    record['requestedModelObserved'] = record['model'] in (record.get('modelUsage') or {})
    checkpoint()
    provider_failure = record['terminalReason'] in ('api_error', 'infrastructure_error') or record['apiErrorStatus'] is not None
    if provider_failure:
        record['grade']['status'] = 'not-scored-provider-failure'
    else:
        try:
            shutil.copytree(work, directory/'workspace', symlinks=True)
            record['grade'] = evaluate(task_path, directory/'workspace/submission', reference, pvbatch, directory/'grade')
        except Exception as error:
            record['grade']['status'] = 'unavailable'
            record['observationComplete'] = False
            record['diagnosticErrors'].append({'stage': 'grade', 'error': type(error).__name__+': '+str(error)})
    if not record['accounting']['complete']:
        report.update(status='unresolved-accounting', blockedReason='Final usage or applicable pricing is unresolved; no further dispatch')
    elif not record['observationComplete']:
        report.update(status='incomplete-observation', blockedReason='Required telemetry, diagnostic capture or grading is incomplete')
    elif provider_failure:
        report.update(status='blocked', blockedReason=record.get('providerMessage') or 'Provider failure')
    checkpoint()
    save_measurements(report, destination)
    return current, telemetry_offset, local_state
