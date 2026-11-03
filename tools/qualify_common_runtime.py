#!/usr/bin/env python3
# Copyright (C) 2026 David L F Gaden
"""Qualify two changing common input states against each route's independent fixtures."""
import argparse
import copy
import json
from pathlib import Path
import sys

from schemaxis.adaptors import registry
from schemaxis.adaptor_delivery import route_materials, case_document, source_digest
from schemaxis.adaptor_conformance import assertions
from schemaxis.adaptor_runtime import InputProgram
from schemaxis.documents import resolve_document
from schemaxis.artifacts import atomic_json


def study_for(version, root):
    _, route, entry = route_materials(version)
    cases = entry['development']['cases'][:2]
    documents = []
    for case in cases:
        document = case_document(entry, case, root)
        document, _ = resolve_document(document)
        document = next(InputProgram(document, route).visits())['document']
        for key in ('dimensions','definitions','settings'): document.pop(key, None)
        documents.append(document)
    if set(documents[0]) != set(documents[1]):
        raise ValueError('fixture root fields differ; supply a paired study for '+version)
    if documents[0] == documents[1]:
        raise ValueError('qualification requires two different effective input states for '+version)
    study = {'version': version, 'definitions': {'case': {
        '$analytic': {'type': 'values', 'values': documents, 'sync': 'fixture'}}}}
    for key in documents[0]:
        if key != 'version':
            study[key] = {'$expr': {'op': 'get', 'args': [{'$document': '/definitions/case'}, key]}}
    return study, cases


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--config', type=Path, required=True)
    parser.add_argument('--output-directory', type=Path, required=True)
    parser.add_argument('--version', action='append')
    parser.add_argument('--timeout', type=float, default=180)
    args = parser.parse_args()
    root = Path(__file__).resolve().parents[1]
    output = args.output_directory.absolute(); output.mkdir(parents=True, exist_ok=False)
    locations = json.loads(args.config.read_text())['locations']
    report = {'verified': False, 'scope': 'Two common input states per selected route, native execution, independent existing fixture assertions, aggregate verification and corruption rejection. Serial only.', 'routes': []}
    for version in args.version or registry.routes():
        provider, route = registry.resolve({'version': version})
        record = {'version': version, 'provider': provider, 'verified': False, 'sourceDigest': source_digest(provider)}
        report['routes'].append(record)
        try:
            document, cases = study_for(version, root)
            target = output/route.get('referenceName', route.get('schemaName', provider))
            plan = registry.plan(document)
            if plan['states'] != 2: raise ValueError('expected exactly two visits')
            registry.run(document, target, locations=locations, timeout=args.timeout)
            record['verification'] = registry.verify(target)
            record['cases'] = [assertions(target/('state-'+str(index).zfill(5)), case['checks']) for index, case in enumerate(cases)]
            # Challenge the shared state evidence independently of each native verifier.
            receipt_path = target/'verification.json'
            original = receipt_path.read_bytes()
            try:
                altered = json.loads(original); altered['states'][1]['indices'] = {'wrong': 1}
                atomic_json(receipt_path, altered)
                try: registry.verify(target)
                except Exception as error:
                    from schemaxis.core.faults import SchemaxisError
                    if not isinstance(error, SchemaxisError): raise
                    record['corruptionFault'] = error.fault.code
                else: raise ValueError('altered state indices were accepted')
            finally:
                receipt_path.write_bytes(original)
            registry.verify(target)
            if source_digest(provider) != record['sourceDigest']: raise ValueError('source changed during qualification')
            record['verified'] = True
        except Exception as error:
            record['fault'] = error.to_dict() if hasattr(error, 'to_dict') else {'message': str(error)}
        atomic_json(output/'report.json', report)
        print(version, 'PASS' if record['verified'] else 'FAILED: '+str(record.get('fault')), flush=True)
    report['verified'] = all(record['verified'] for record in report['routes'])
    atomic_json(output/'report.json', report)
    return 0 if report['verified'] else 1


if __name__ == '__main__':
    sys.exit(main())
