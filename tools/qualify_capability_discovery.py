#!/usr/bin/env python3
"""Reproducible M1 host acceptance and optional two-attempt serial FreeCAD proof.

Run from the repository root with PYTHONPATH=src. Bulk responses stay in the
chosen fresh output directory; report.json contains byte counts and actual scope.
"""
import argparse
import copy
import json
import math
from pathlib import Path
import sys
import time

from schemaxis.__main__ import main as cli_main
from schemaxis.adaptors import registry
from schemaxis.capabilities import CapabilityCatalogue, response_bytes
from schemaxis.core.faults import SchemaxisError


def cli(*args):
    original = sys.argv
    try:
        sys.argv = ['schemaxis', *args]
        return cli_main()
    finally:
        sys.argv = original


def write(path, value):
    path.write_text(json.dumps(value, indent=2, allow_nan=False) + '\n')


def qualify(directory, *, native=False):
    directory.mkdir(parents=True, exist_ok=False)
    catalogue = CapabilityCatalogue()
    responses = {}
    def retain(name, response):
        responses[name] = response
        write(directory/(name + '.json'), response)
        return response

    retain('root', catalogue.browse())
    retain('geometry', catalogue.browse('domain/geometry'))
    retain('solids', catalogue.browse('group/freecad/solids'))
    box = retain('box', catalogue.describe('operation/freecad/box'))
    assert box == catalogue.describe(next(i['id'] for i in responses['solids']['items'] if i['label'] == 'box'))
    retain('search', catalogue.search('extrusion', scope='domain/geometry', input_kind='profile'))
    retain('data-analysis', catalogue.browse('domain/data-analysis'))
    retain('sampling', catalogue.browse('group/paraview/sampling'))
    sliced = retain('slice', catalogue.describe('operation/paraview/slice'))
    for name, detail in [('box', box), ('slice', sliced)]:
        command = detail['sections']['schema']['authoredDocument']['command']
        retain(name + '-document-schema', cli(*command[1:]))
    for name, detail in [('box', box), ('slice', sliced)]:
        identity = detail['capability']['id']
        retain(name + '-schema-root', catalogue.schema(identity))
        retain(name + '-document-required', catalogue.schema(identity, pointer='/required'))
        pointer = detail['sections']['schema']['authoredDocument']['nodePointer']
        retain(name + '-node-schema', catalogue.schema(identity, pointer=pointer))
    retain('flat-discover', cli('discover'))
    retain('flat-box-declaration', cli('describe', 'box', '--provider', 'freecad'))
    retain('flat-box-options', cli('schema', '--provider', 'freecad', '--operation', 'box'))
    retain('flat-slice-declaration', cli('describe', 'slice', '--provider', 'paraview'))
    retain('flat-slice-options', cli('schema', '--provider', 'paraview', '--operation', 'slice'))

    sections = box['sections']
    options = {key: copy.deepcopy(value['value']['default'])
               for key, value in sections['declaration']['options'].items() if 'default' in value['value']}
    options.update(length=20, width=10, height=5)
    document = {'version': sections['requirements']['documentVersion'],
                'nodes': [{'id': 'body', 'filter': sections['provenance']['operationKey'], 'options': options}],
                'output': 'body'}
    retain('authored-box', document)
    retain('box-plan', registry.plan(document))
    pv_document = copy.deepcopy(sliced['sections']['examples']['items'][0]['document'])
    # Deliberate case variant of the returned example, still using declared options.
    pv_document['nodes'][1]['options']['origin'] = [1, 0, 0]
    retain('authored-slice', pv_document)
    retain('slice-plan', registry.plan(pv_document))

    def path(names):
        return {'responses': names, 'steps': len(names),
                'bytes': sum(response_bytes(responses[n]) for n in names)}
    report = {
        'version': 'schemaxis.capability-acceptance/1',
        'catalogueRevision': catalogue.revision,
        'budgets': {'summaryBytes': 8192, 'summaryItems': 12,
                    'detailPolicy': 'Complete selected sections, no truncation or hard byte cap; document schema fetched separately.'},
        'responseBytes': {k: response_bytes(v) for k, v in responses.items()},
        'paths': {
            'geometryContractNavigation': path(['root', 'geometry', 'solids', 'box']),
            'analysisContractNavigation': path(['root', 'data-analysis', 'sampling', 'slice']),
            'geometrySchemaFragments': path(['box-schema-root', 'box-document-required', 'box-node-schema']),
            'analysisSchemaFragments': path(['slice-schema-root', 'slice-document-required', 'slice-node-schema']),
            'geometryBreadcrumb': path(['root', 'geometry', 'solids', 'box', 'box-document-schema']),
            'geometryDirect': path(['box', 'box-document-schema']),
            'geometryFlat': path(['flat-discover', 'flat-box-declaration', 'flat-box-options', 'box-document-schema']),
            'analysisBreadcrumb': path(['root', 'data-analysis', 'sampling', 'slice', 'slice-document-schema']),
            'analysisDirect': path(['slice', 'slice-document-schema']),
            'analysisFlat': path(['flat-discover', 'flat-slice-declaration', 'flat-slice-options', 'slice-document-schema'])},
        'hostPlanning': {'constructedBox': True, 'returnedSliceExampleVariant': True},
        'measurementScope': 'UTF-8 bytes of CLI-style indented JSON including newline, not model tokens. '
                            'Breadcrumb, Direct and Flat paths include the same complete declaration, literal option schema and authored document schema. '
                            'Progressive detail additionally carries requirements, examples, provenance and status. '
                            'ContractNavigation excludes the optional whole document schema; SchemaFragments measures selected structural guidance only, with local $refs still retrievable from the root. '
                            'Flat comparison assumes the operation is already known. This is not an AI success evaluation.',
        'native': {'requested': native, 'executed': False}}
    write(directory/'report.json', report)
    if native:
        # This is a bounded client of existing run/verify, not a new execution engine.
        # The target and two-attempt budget are fixed, and any failed verification stops.
        started = time.monotonic()
        report['native'] = {'requested': True, 'executed': False, 'maxAttempts': 2,
                            'timeoutPerNativeStageSeconds': 120, 'targetVolumeMM3': 1500,
                            'attempts': [], 'scope': 'Serial FreeCAD boxes only; no MPI or exhaustive qualification.'}
        try:
            for attempt in range(2):
                run_dir = directory/('native-' + str(attempt + 1))
                planned = registry.plan(document)
                registry.run(document, run_dir, timeout=120)
                observed = registry.verify(run_dir)
                report['native']['executed'] = True
                volume = observed['volumeMM3']
                expected = math.prod(document['nodes'][0]['options'][key] for key in ('length', 'width', 'height'))
                if not math.isclose(volume, expected, rel_tol=1e-8):
                    raise AssertionError('native volume disagrees with independent analytic expectation')
                report['native']['attempts'].append({'directory': run_dir.name, 'observed': observed,
                    'analyticVolumeMM3': expected, 'planOutput': planned['output'],
                    'authoredHeightMM': document['nodes'][0]['options']['height']})
                if attempt == 0:
                    document['nodes'][0]['options']['height'] *= 1500 / volume
                elif not math.isclose(volume, 1500, rel_tol=1e-8):
                    raise AssertionError('refined box did not reach the target volume')
            report['native']['verified'] = True
            report['native']['refinement'] = 'Changed height from returned volume; retained both authored requests and verified artifacts.'
        except SchemaxisError as error:
            report['native']['failure'] = error.to_dict()
            raise
        except Exception as error:
            report['native']['failure'] = {'type': type(error).__name__, 'message': str(error)}
            raise
        finally:
            report['native']['elapsedSeconds'] = round(time.monotonic()-started, 3)
            write(directory/'report.json', report)
    return report


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output-directory', type=Path, required=True)
    parser.add_argument('--native', action='store_true', help='also execute and verify two serial FreeCAD boxes using configured locations')
    args = parser.parse_args()
    result = qualify(args.output_directory.resolve(), native=args.native)
    print(json.dumps({'report': str(args.output_directory/'report.json'),
                      'paths': result['paths'], 'native': result['native']}, indent=2))


if __name__ == '__main__':
    main()
