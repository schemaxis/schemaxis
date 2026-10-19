"""Bounded PrusaSlicer acceptance: shared conformance plus native negative probes.

Host mode runs schema/planner conformance only. ``--native`` additionally runs
the readiness cases, lifecycle probes and adaptor-specific rejections against a
configured console executable. Nothing is sent to a printer.
"""
import argparse
import hashlib
import json
from pathlib import Path
import re

from schemaxis.adaptor_conformance import qualify
from schemaxis.adaptors import registry
from schemaxis.adaptors.prusaslicer import adaptor
from schemaxis.artifacts import atomic_json
from schemaxis.core.faults import SchemaxisError

ROOT = Path(__file__).resolve().parents[1]
VERSION = 'schemaxis.prusaslicer/1'


def document(name, model):
    value = json.loads((ROOT/f'examples/schemaxis/prusaslicer-{name}.json').read_text())
    value['model']['file'] = str(ROOT/'examples/schemaxis'/model)
    return value


def rejected(action, codes, label):
    try:
        action()
    except SchemaxisError as error:
        if error.fault.code not in codes:
            raise SystemExit(f'{label}: wrong fault {error.fault.to_dict()}')
        return {'check': label, 'fault': error.fault.code, 'message': error.fault.message, 'verified': True}
    raise SystemExit(label + ': incorrectly accepted')


def forged(directory, old, new, expected):
    """Alter G-code semantics in place, recompute publication digests, then restore.

    Verification must reject the forgery. Because the fresh reload is bound to
    the published bytes, that rejection can come from evidence binding; the
    independent replay alone (``checked``) must also reject it for the named
    semantic reason, so digest bookkeeping is never the only defence.
    """
    path, receipt_path = directory/'model.gcode', directory/'verification.json'
    original, original_receipt = path.read_bytes(), receipt_path.read_bytes()
    pattern = re.compile(old, re.M)
    if not pattern.search(original):
        raise SystemExit('forgery anchor absent: ' + old.decode())
    try:
        path.write_bytes(pattern.sub(new, original, count=1))
        receipt = json.loads(original_receipt)
        for artifact in receipt['artifacts']:
            artifact['sha256'] = hashlib.sha256(Path(artifact['file']).read_bytes()).hexdigest()
        atomic_json(receipt_path, receipt)
        verified = rejected(lambda: adaptor.verify(directory, require_result=False), {'VERIFICATION_FAILED'}, 'verify')
        prepared = adaptor.plan(json.loads((directory/'authored.json').read_text()))
        replay = rejected(lambda: adaptor.checked(directory, prepared), {'VERIFICATION_FAILED'}, 'replay')
        if expected not in replay['message']:
            raise SystemExit(f'independent replay rejected the forgery for an unexpected reason: {replay["message"]}')
        return {'fault': verified['fault'], 'verifyMessage': verified['message'],
                'replayMessage': replay['message'], 'verified': True}
    finally:
        path.write_bytes(original)
        receipt_path.write_bytes(original_receipt)


def probes(directory, executable, timeout):
    results = []
    limited = document('petg', 'prusaslicer-box.stl')
    limited['requirements'] = [{'name': 'tight_time', 'quantity': 'printTime_s', 'maximum': 1}]
    run = directory/'unmet-limit'
    results.append(rejected(lambda: adaptor.run(limited, run, executable=executable, timeout=timeout),
                            {'PERFORMANCE_NOT_MET'}, 'named estimate limit rejects a verified slice'))
    summary = json.loads((run/'slice-summary.json').read_text())
    margin = summary['requirements'][0]['margin']
    if not margin < 0 or json.loads((run/'result.json').read_text())['status'] != 'failed':
        raise SystemExit('unmet limit must retain a negative margin and a failed result')
    results.append(rejected(lambda: adaptor.verify(run), {'INCOMPLETE_EXECUTION', 'PERFORMANCE_NOT_MET'},
                            'unmet attempt is not reusable'))
    results[-2]['observedMargin_s'] = margin
    good = directory/'baseline'
    adaptor.run(document('pla', 'prusaslicer-box.stl'), good, executable=executable, timeout=timeout)
    adaptor.verify(good)
    for label, old, new, expected in (
            ('forged later-layer nozzle setpoint', rb'^M104 S210\b', b'M104 S230', 'temperature setpoint'),
            ('forged layer height', rb'^G1 Z\.4 ', b'G1 Z.45 ', 'layer-height grid'),
            ('forged native time estimate', rb'^; estimated printing time \(normal mode\) = .*$',
             b'; estimated printing time (normal mode) = 1m 0s', 'kinematic bounds')):
        result = forged(good, old, new, expected)
        result['check'] = label + ' with recomputed digests'
        results.append(result)
    adaptor.verify(good)
    outside = document('pla', 'prusaslicer-box.stl')
    outside['placement'] = {'centre_mm': [10, 105]}
    target = directory/'off-bed'
    results.append(rejected(lambda: adaptor.run(outside, target, executable=executable, timeout=timeout),
                            {'MODEL_OUT_OF_BOUNDS'}, 'footprint outside bed rejected before launch'))
    if target.exists():
        raise SystemExit('pre-launch rejection created an attempt directory')
    return results


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output-directory', required=True, type=Path)
    parser.add_argument('--native', action='store_true')
    parser.add_argument('--executable', help='absolute PrusaSlicer 2.9.6 console executable')
    parser.add_argument('--timeout', type=float, default=300)
    parser.add_argument('--wall-timeout', type=float, default=600)
    args = parser.parse_args()
    locations = {'prusaslicer': args.executable} if args.executable else None
    report = qualify(VERSION, args.output_directory/'conformance', native=args.native, locations=locations,
                     timeout=args.timeout, wall_timeout=args.wall_timeout)
    result = {'conformance': {'verified': report['verified'], 'mode': report['mode'], 'sourceDigest': report['sourceDigest'],
                              'cases': [{'id': c['id'], 'runtime': c['runtime']} for c in report['cases']]}}
    if args.native:
        from schemaxis.configuration import locations as configured
        executable = configured(locations or {}).get('prusaslicer')
        if not executable:
            raise SystemExit('native probes need --executable or a configured prusaslicer location')
        result['probes'] = probes(args.output_directory/'probes', executable, args.timeout)
    atomic_json(args.output_directory/'prusaslicer-acceptance.json', result)
    print(json.dumps(result, indent=2))


if __name__ == '__main__':
    main()
