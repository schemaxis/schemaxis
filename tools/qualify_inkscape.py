#!/usr/bin/env python3
# Copyright (C) 2026 David L F Gaden
"""Fresh bounded diagram qualification plus flow intent, native recovery, analytics and concurrency."""
import argparse
from concurrent.futures import ThreadPoolExecutor
import copy
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT/'src'))
from schemaxis.adaptors.inkscape.adaptor import plan, run, verify
from schemaxis.adaptor_conformance import qualify
from schemaxis.artifacts import atomic_json, file_digest
from schemaxis.core.faults import SchemaxisError


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output-directory', required=True, type=Path)
    parser.add_argument('--executable', type=Path)
    parser.add_argument('--timeout', type=float, default=120)
    args = parser.parse_args()
    directory = args.output_directory.resolve(); directory.mkdir(parents=True, exist_ok=False)
    locations = {'inkscape': str(args.executable.resolve())} if args.executable else {}
    report = {'verified': False, 'scope': 'Explicit and ranked DAG diagrams, measured text/geometry, semantic SVG tamper rejection, lifecycle/recovery, common native analytics and twelve distinct concurrently executed native jobs.'}
    try:
        report['conformance'] = qualify('schemaxis.inkscape/1', directory/'native', native=True, locations=locations, timeout=args.timeout)
        if not report['conformance']['verified']: raise AssertionError('native conformance did not pass')
        document = json.loads((ROOT/'examples/schemaxis/inkscape-diagram.json').read_text())
        overflow = copy.deepcopy(document); overflow['boxes'][0]['label'] = 'W' * 80
        plan(overflow)  # Geometry valid; acceptance depends on native text measurement.
        try:
            run(overflow, directory/'label-overflow', executable=locations.get('inkscape'), timeout=args.timeout)
        except SchemaxisError as error:
            if error.fault.code != 'LABEL_OVERFLOW': raise
            report['overflow'] = error.fault.to_dict()
        else: raise AssertionError('native label overflow was accepted')
        recovered = copy.deepcopy(overflow); recovered['boxes'][0]['label'] = 'Input'
        run(recovered, directory/'label-recovered', executable=locations.get('inkscape'), timeout=args.timeout)
        report['recovery'] = verify(directory/'label-recovered')
        # Stronger than an unchanged manifest: alter native SVG geometry and
        # refresh its declared hash. Semantic reconstruction must still reject it.
        recovered_directory = directory/'label-recovered'
        svg_path = recovered_directory/'diagram.svg'; receipt_path = recovered_directory/'verification.json'
        original_svg = svg_path.read_bytes(); original_receipt = receipt_path.read_bytes()
        try:
            svg_path.write_bytes(original_svg.replace(b'width="30"', b'width="31"', 1))
            altered = json.loads(original_receipt)
            altered['artifacts'][0]['sha256'] = file_digest(svg_path)
            atomic_json(receipt_path, altered)
            try: verify(recovered_directory)
            except SchemaxisError as error:
                if error.fault.code != 'VERIFICATION_FAILED': raise
                report['semanticTamper'] = error.fault.to_dict()
            else: raise AssertionError('SVG with refreshed publication hash was accepted')
        finally:
            svg_path.write_bytes(original_svg); receipt_path.write_bytes(original_receipt)
        verify(recovered_directory)
        flow = json.loads((ROOT/'examples/schemaxis/inkscape-flow.json').read_text())
        flow_overflow = copy.deepcopy(flow); flow_overflow['boxes'][0]['label'] = 'W' * 80
        plan(flow_overflow)
        try: run(flow_overflow, directory/'flow-label-overflow', executable=locations.get('inkscape'), timeout=args.timeout)
        except SchemaxisError as error:
            if error.fault.code != 'LABEL_OVERFLOW': raise
            report['flowOverflow'] = error.fault.to_dict()
        else: raise AssertionError('native flow label overflow was accepted')
        run(flow, directory/'flow-recovered', executable=locations.get('inkscape'), timeout=args.timeout)
        report['flowRecovery'] = verify(directory/'flow-recovered')
        flow_directory = directory/'flow-recovered'
        svg_path = flow_directory/'diagram.svg'; receipt_path = flow_directory/'verification.json'
        original_svg = svg_path.read_bytes(); original_receipt = receipt_path.read_bytes()
        try:
            svg_path.write_bytes(original_svg.replace(b'width="26"', b'width="27"', 1))
            altered = json.loads(original_receipt); altered['artifacts'][0]['sha256'] = file_digest(svg_path)
            atomic_json(receipt_path, altered)
            try: verify(flow_directory)
            except SchemaxisError as error:
                if error.fault.code != 'VERIFICATION_FAILED': raise
                report['flowSemanticTamper'] = error.fault.to_dict()
            else: raise AssertionError('derived flow layout with refreshed hash was accepted')
        finally:
            svg_path.write_bytes(original_svg); receipt_path.write_bytes(original_receipt)
        verify(flow_directory)
        analytic = copy.deepcopy(flow)
        analytic['dimensions'] = {'cardWidth': {'$analytic': {'type': 'values', 'values': [26, 28]}}}
        analytic['boxWidth'] = {'$document': '/dimensions/cardWidth'}
        analytic['fontSize'] = {'$expr': {'op': 'divide', 'args': [6, 2]}}
        run(analytic, directory/'flow-analytic', executable=locations.get('inkscape'), timeout=args.timeout)
        report['analytic'] = verify(directory/'flow-analytic')
        if report['analytic'].get('states') != 2: raise AssertionError('common native analytic state count differs')
        for index, expected in enumerate((109.2, 115.2)):
            measured = json.loads((directory/'flow-analytic'/f'state-{index:05d}'/'verification.json').read_text())
            if abs(measured['native']['layout']['requiredSize'][0] - expected) > 1e-10:
                raise AssertionError('native analytic card budget differs')
        report['concurrent'] = []
        for round_index in range(3):
            jobs = []
            with ThreadPoolExecutor(max_workers=4) as pool:
                for index in range(4):
                    candidate = copy.deepcopy(document if index % 2 == 0 else flow)
                    candidate['boxes'][0]['label'] = 'Step' + str(index)
                    target = directory/'concurrent'/f'round-{round_index:02d}'/f'job-{index:02d}'
                    jobs.append((target, pool.submit(run, candidate, target, executable=locations.get('inkscape'), timeout=args.timeout)))
                for target, future in jobs:
                    future.result(); check = verify(target)
                    report['concurrent'].append({'directory': str(target), 'verified': check['verified'], 'runtime': check['runtime']})
        report['verified'] = True
    finally:
        atomic_json(directory/'qualification.json', report)
    print(json.dumps({'verified': report['verified'], 'directory': str(directory)}, indent=2))


if __name__ == '__main__': main()
