#!/usr/bin/env python3
"""Run the common kit for selected installed adaptors, retaining all failures.

Host checks are the default. Native qualification is opt-in and must be limited
to configured runtimes. No unavailable runtime is counted as a successful skip.
"""
import argparse
import json
import os
from pathlib import Path
from schemaxis.adaptors import registry
from schemaxis.adaptor_conformance import qualify, register
from schemaxis.artifacts import atomic_json
from schemaxis.core.faults import SchemaxisError


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output-directory', type=Path, required=True)
    parser.add_argument('--app', action='append', choices=sorted(registry.ADAPTORS))
    parser.add_argument('--native', action='store_true')
    parser.add_argument('--record', action='store_true')
    parser.add_argument('--config', type=Path)
    args = parser.parse_args()
    if args.record and not args.native:
        parser.error('--record requires --native')
    if args.config:
        os.environ['SCHEMAXIS_CONFIG'] = str(args.config.resolve())
    root = args.output_directory.resolve()
    root.mkdir(parents=True, exist_ok=False)
    report = {'verified': False, 'mode': 'native' if args.native else 'host', 'routes': []}
    for version, (provider, _) in registry.routes().items():
        if args.app and provider not in args.app:
            continue
        directory = root/version.replace('/', '-')
        row = {'provider': provider, 'version': version, 'receipt': str(directory/'qualification.json'), 'verified': False}
        try:
            result = qualify(version, directory, native=args.native)
            row['verified'] = result['verified']
            if args.record:
                row['registration'] = register(directory/'qualification.json')
        except Exception as error:
            row['fault'] = error.to_dict() if isinstance(error, SchemaxisError) else {'type': type(error).__name__, 'message': str(error)}
        report['routes'].append(row)
        atomic_json(root/'report.json', report)
        print(json.dumps(row), flush=True)
    report['verified'] = bool(report['routes']) and all(row['verified'] for row in report['routes'])
    atomic_json(root/'report.json', report)
    return 0 if report['verified'] else 1


if __name__ == '__main__':
    raise SystemExit(main())
