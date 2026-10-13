"""Host-only architecture probes, not a production template loader or native test."""
import copy
import datetime
import hashlib
import json
from pathlib import Path
import sys
from unittest.mock import patch

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[2]
sys.path.insert(0, str(ROOT / 'src'))

from schemaxis.adaptor_runtime import InputProgram
from schemaxis.core.faults import SchemaxisError
from schemaxis.storage import digest, load
from schemaxis.workflow import inspect_plan, validate


def check():
    directory = HERE / 'examples/reentrant'
    template = load((directory / 'template.json').read_text())
    body = load((directory / 'workflow.json').read_text())
    bundle_digest = digest({'template': template, 'workflow': body})
    findings = []
    with patch('subprocess.Popen', side_effect=AssertionError('Native launch prohibited')) as launch:
        for name in ('values-small.json', 'values-tall.json'):
            case = load((directory / name).read_text())
            assert case['template'] == {
                'id': template['id'], 'revision': template['revision'], 'digest': bundle_digest}
            # Explicit materialisation for this example only. This is not a
            # schema-complete validator, parameter binder or public template API.
            effective = copy.deepcopy(body)
            for parameter, value in case['values'].items():
                metadata = template['parameters'][parameter]
                assert metadata['target'] == {
                    'scope': 'workflow', 'pointer': '/dimensions/' + parameter}
                assert type(value) in (int, float)
                assert metadata['constraints']['minimum'] <= value <= metadata['constraints']['maximum']
                effective['dimensions'][parameter] = value
            planned = inspect_plan(effective)
            assert planned['version'] == 'schemaxis.workflow.plan/2'
            ids = [operation['id'] for operation in planned['operations']]
            assert ids == ['design', 'mesh', 'table', 'revise']
            dependencies = [job['dependencies'] for job in planned['jobs']]
            assert dependencies == [[], ['design'], ['mesh'], ['table']]
            prepared = validate(effective)
            options = prepared[0]['document']['nodes'][0]['options']
            assert options['height'] == case['values']['height']
            assert options['length'] == case['values']['length']
            assert prepared[0]['document']['version'] == prepared[-1]['document']['version']
            deferred = [op['id'] for op in planned['operations']
                        if op['provisionalPlan'].get('status') == 'deferred']
            assert deferred == ['mesh', 'table', 'revise']
            findings.append({'check': name, 'passed': True, 'operationOrder': ids,
                             'dependencies': dependencies, 'deferredNativePlans': deferred,
                             'resolvedInitialDimensions': options})

        sweep = copy.deepcopy(body)
        sweep['dimensions']['height'] = {'$analytic': {'type': 'values', 'values': [5, 7]}}
        program = InputProgram(sweep, workflow=True)
        heights = [v['document']['operations'][0]['document']['nodes'][0]['options']['height']
                   for v in program.visits()]
        assert program.count == 2 and heights == [5, 7]
        findings.append({'check': 'workflow-wide finite sweep', 'passed': True,
                         'states': program.count, 'resolvedHeights': heights})

        for name, change, code in (
            ('duplicate operation ID', lambda b: b['operations'][-1].update(id='design'), 'DUPLICATE_OPERATION'),
            ('forward reference', lambda b: b['operations'][0]['document']['nodes'][0]['options'].update(
                height={'$value': 'revise', 'artifact': 3, 'path': '/height'}), 'UNAVAILABLE_OPERATION')):
            invalid = copy.deepcopy(body)
            change(invalid)
            try:
                validate(invalid)
            except SchemaxisError as error:
                assert error.fault.code == code
                findings.append({'check': name, 'passed': True, 'expectedFault': code})
            else:
                raise AssertionError('Invalid dependency structure was accepted')

        # Preserve a current limitation found during review, rather than hide it
        # behind the deferred scalar-value path used by the main example.
        artifact_only = copy.deepcopy(body)
        artifact_only['operations'][1]['document']['nodes'][1]['options']['size'] = 2
        try:
            inspect_plan(artifact_only)
        except SchemaxisError as error:
            assert error.fault.code == 'INVALID_RESOURCE'
            limitation = {'check': 'artifact-only STEP input with literal mesh size',
                          'status': 'existing-host-planner-limitation',
                          'fault': error.to_dict(),
                          'reason': 'Workflow placeholder lacks a STEP extension; Gmsh rejects it. '
                                    'Deferred typed artifact planning needs correction during D0/D1.'}
        else:
            limitation = {'check': 'artifact-only STEP input with literal mesh size',
                          'status': 'no-longer-reproduced; review source revision'}
        assert launch.call_count == 0

    native_modules = [name for name in sys.modules
                      if name.split('.')[0] in {'paraview', 'FreeCAD', 'gmsh', 'bpy'}]
    assert not native_modules
    return {
        'kind': 'architecture-host-probes', 'dateUTC': datetime.datetime.now(datetime.timezone.utc).isoformat(),
        'sourceBaseline': '4487292', 'command': 'python3 docs/design/workflow-templates/check_examples.py',
        'checks': findings, 'knownLimitations': [limitation],
        'nativeProcesses': 0, 'nativeModules': native_modules, 'modelInvocations': 0,
        'scope': 'Current workflow engine only; explicit example binding, not a new template loader. '
                 'Downstream plans remain deferred. No native or GUI acceptance claimed.',
        'exampleSHA256': {str(p.relative_to(HERE)): hashlib.sha256(p.read_bytes()).hexdigest()
                          for p in sorted(directory.glob('*.json'))},
        'probeSHA256': hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
        'sourceSHA256': {name: hashlib.sha256((ROOT / name).read_bytes()).hexdigest()
                         for name in ['src/schemaxis/workflow.py',
                                      'src/schemaxis/adaptor_runtime.py',
                                      'src/schemaxis/parallel.py',
                                      'src/schemaxis/adaptors/registry.py',
                                      'src/schemaxis/adaptors/gmsh/adaptor.py']},
    }


if __name__ == '__main__':
    result = check()
    (HERE / 'design-checks.json').write_text(json.dumps(result, indent=2) + '\n')
    print(json.dumps({'checksPassed': len(result['checks']),
                      'knownLimitations': len(result['knownLimitations']),
                      'nativeProcesses': 0, 'modelInvocations': 0}))
