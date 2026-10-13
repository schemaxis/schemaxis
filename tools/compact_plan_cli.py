"""Experimental plan presentation; production CLI and canonical plans are unchanged.

SCHEMAXIS_PLAN_PRESENTATION selects full (control) or compact. Both use the
production CLI planner exactly once and retain its complete JSON response.
No native execution or model calls take place here.
"""
import argparse
import copy
import hashlib
import json
import os
from pathlib import Path
import sys
import time

from schemaxis.capabilities import digest, response_bytes
from schemaxis.core.faults import Fault, SchemaxisError
from schemaxis.observations import bounded


def encoded(value):
    return (json.dumps(value, indent=2, allow_nan=False) + '\n').encode()


def retain(value, directory, suffix):
    """Store exactly the existing CLI encoding, without modifying the value."""
    payload = encoded(value)
    sha = hashlib.sha256(payload).hexdigest()
    directory = Path(directory).resolve()
    directory.mkdir(parents=True, exist_ok=True)
    path = directory / (sha + '.' + suffix + '.json')
    try:
        with path.open('xb') as stream:
            stream.write(payload)
    except FileExistsError:
        if path.read_bytes() != payload:
            raise ValueError('retained artifact differs from its content-addressed name')
    return {'file': str(path), 'fileSHA256': sha, 'bytes': len(payload),
            'observationRevision': digest(value)}


def diagnostic_members(value, pointer=''):
    """Retain reported diagnostics verbatim; absence is not a no-warning claim."""
    found = []
    if isinstance(value, dict):
        for key, child in value.items():
            if key in ('declarations', 'document', 'options'):
                continue
            path = pointer + '/' + key.replace('~', '~0').replace('/', '~1')
            if key in ('warnings', 'errors', 'diagnostics', 'fault', 'artifactResolution'):
                found.append({'canonicalPointer': path, 'reported': copy.deepcopy(child)})
            elif key == 'status' and child in ('deferred', 'unavailable', 'unsupported', 'failed'):
                found.append({'canonicalPointer': pointer, 'reported': copy.deepcopy(value)})
            else:
                found.extend(diagnostic_members(child, path))
    elif isinstance(value, list):
        for index, child in enumerate(value):
            found.extend(diagnostic_members(child, pointer + '/' + str(index)))
    return found


def projection(plan):
    """A ParaView plan view, with an explicit generic fallback for other shapes."""
    diagnostics = diagnostic_members(plan)
    result = {'reportedDiagnostics': diagnostics,
              'diagnosticAvailability': 'reported' if diagnostics else 'not-reported',
              'deferredChecks': ['native property acceptance and source contents',
                                 'runtime-derived values', 'publication and image correctness']}
    pipeline, scenes = plan.get('pipeline'), plan.get('scenes')
    if not isinstance(pipeline, dict) or not isinstance(scenes, list):
        result.update(viewScope='Generic plan navigation; no task-specific count interpretation.',
                      plan=bounded(plan, 'canonical-plan'))
        return result
    active = {node for scene in scenes for node in scene['selection']['order']}
    nodes = []
    for index, node in enumerate(pipeline['nodes']):
        if node['id'] not in active:
            continue
        item = {key: copy.deepcopy(node[key]) for key in
                ('id', 'filter', 'inputs', 'dependencies', 'options', 'onVisit') if key in node}
        item['canonicalPointer'] = '/pipeline/nodes/' + str(index)
        item['contractPointer'] = '/pipeline/declarations/' + node['filter'].replace('~', '~0').replace('/', '~1')
        nodes.append(item)
    result.update(viewScope='Selected ParaView work; options include defaults and unevaluated runtime expressions.',
                  counts={'declaredNodes': len(pipeline['nodes']), 'selectedNodes': len(nodes),
                          'sceneStateVisits': sum(scene['selection']['states'] for scene in scenes),
                          'expectedPublications': plan['expectedPublications']},
                  nodes=nodes, times=copy.deepcopy(pipeline['times']),
                  axes=copy.deepcopy(pipeline['axes']), scenes=copy.deepcopy(scenes))
    return result


def present(plan, directory, *, compact=True, max_bytes=8192):
    if type(max_bytes) is not int or not 4096 <= max_bytes <= 65536:
        raise ValueError('max_bytes must be 4096..65536')
    retained = retain(plan, directory, 'plan')
    if not compact:
        return copy.deepcopy(plan), retained
    view = projection(plan)
    view_ref = retain(view, directory, 'view')
    response = {'protocol': 'schemaxis.experimental.plan-view/1',
                'hostPlanning': 'returned-plan; inspect reported diagnostics and deferred checks',
                'nativeExecution': 'not-run', 'outputVerification': 'not-run',
                'retainedPlan': retained, 'retainedView': view_ref,
                'existingPipelineDigest': plan.get('pipeline', {}).get('digest'),
                'reportedDiagnosticCount': len(view['reportedDiagnostics']),
                'inspection': 'inspect FILE --pointer /PATH --revision OBSERVATION_REVISION; canonicalPointer and contractPointer address retainedPlan, page pointers address retainedView.'}
    # The bound covers the entire emitted response, not just its nested page.
    remaining = max_bytes - response_bytes(response) - 64
    if remaining < 2048:
        raise ValueError('retained paths leave insufficient room for bounded observations')
    response['view'] = bounded(view, view_ref['file'], max_bytes=remaining)
    if response_bytes(response) > max_bytes:
        raise ValueError('compact response exceeds requested byte budget')
    return response, retained


def plan_once(filename):
    """Delegate argument/loading/routing behaviour to the production CLI."""
    from schemaxis.__main__ import main
    previous = sys.argv
    try:
        sys.argv = ['schemaxis', 'plan', filename]
        return main()
    finally:
        sys.argv = previous


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    actions = parser.add_subparsers(dest='action', required=True)
    plan = actions.add_parser('plan')
    plan.add_argument('input')
    plan.add_argument('--retain', type=Path, default=Path('plan-evidence'))
    plan.add_argument('--max-bytes', type=int, default=8192)
    inspect = actions.add_parser('inspect')
    inspect.add_argument('file', type=Path)
    inspect.add_argument('--pointer', default='')
    inspect.add_argument('--revision', required=True)
    inspect.add_argument('--offset', type=int, default=0)
    inspect.add_argument('--limit', type=int, default=12)
    inspect.add_argument('--max-bytes', type=int, default=8192)
    args = parser.parse_args(argv)
    started = time.perf_counter()
    mode = os.environ.get('SCHEMAXIS_PLAN_PRESENTATION', 'full')
    if mode not in ('full', 'compact'):
        parser.error('SCHEMAXIS_PLAN_PRESENTATION must be full or compact')
    retained = None
    planning_seconds = None
    status = 0
    try:
        if args.action == 'inspect':
            value = json.loads(args.file.read_text())
            result = bounded(value, str(args.file), pointer=args.pointer, revision=args.revision,
                             offset=args.offset, limit=args.limit, max_bytes=args.max_bytes)
        else:
            plan_value = plan_once(args.input)
            planning_seconds = time.perf_counter() - started
            result, retained = present(plan_value, args.retain, compact=mode == 'compact', max_bytes=args.max_bytes)
    except (SchemaxisError, OSError, ValueError, TypeError, KeyError) as error:
        status = 1
        original = (error.to_dict() if isinstance(error, SchemaxisError) else
                    {'fault': Fault('INVALID_INPUT', str(error), '$', 'input').to_dict()})
        result = original
        if args.action == 'plan':
            retained = retain(original, args.retain, 'fault')
        if mode == 'compact' and args.action == 'plan':
            result = {'hostPlanning': 'failed', 'nativeExecution': 'not-run', 'outputVerification': 'not-run',
                      'faultCode': original['fault']['code'], 'retainedFault': retained,
                      'fault': bounded(original, retained['file'], max_bytes=2048)}
    payload = encoded(result)
    # Symmetric telemetry, kept out of the response and model inference.
    directory = args.retain if args.action == 'plan' else args.file.parent
    directory.mkdir(parents=True, exist_ok=True)
    with (directory / 'presentation-events.jsonl').open('a') as stream:
        stream.write(json.dumps({'action': args.action, 'mode': mode, 'exitCode': status,
            'planningSeconds': planning_seconds, 'totalLocalSeconds': time.perf_counter()-started,
            'stdoutBytes': len(payload), 'retained': retained,
            'pointer': getattr(args, 'pointer', None)}, allow_nan=False) + '\n')
    sys.stdout.write(payload.decode())
    return status


if __name__ == '__main__':
    raise SystemExit(main())
