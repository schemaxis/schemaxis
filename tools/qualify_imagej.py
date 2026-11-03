#!/usr/bin/env python3
# Copyright (C) 2026 David L F Gaden
"""Native ImageJ particle kit, tamper probes, Calc handoff/reuse and public agent reuse.

Requires a Java 11+ runtime with jdk.compiler and ImageJ 1.54 ij.jar. The Calc
handoff runs only when a Calc location is supplied; otherwise it is reported as
unavailable (unqualified), never as a skipped success.
"""
import argparse
import copy
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys

from schemaxis.adaptor_conformance import qualify
from schemaxis.adaptor_delivery import case_document, route_materials
from schemaxis.adaptors import registry
from schemaxis.artifacts import file_digest
from schemaxis.core.faults import SchemaxisError
from schemaxis.tabular import close, read_csv
from schemaxis import workflow

ROOT = Path(__file__).resolve().parents[1]
VERSION = 'schemaxis.imagej/1'
FIXTURE = ROOT/'examples/schemaxis/fixtures/imagej/particles-8bit.pgm'


def rejected(action, code):
    try: action()
    except SchemaxisError as error:
        assert error.fault.code == code, error.fault.to_dict()
        return error.fault.code
    raise AssertionError('accepted invalid evidence or input')


def tamper(target, report):
    """A refreshed digest cannot hide a changed label or measurement."""
    receipt_path = target/'verification.json'; saved_receipt = receipt_path.read_bytes()
    for name, old, new in (('count-mask.pgm', None, None), ('native-particles.csv', b'27.0,', b'27.5,'),
                           ('reopen-particles.csv', b'160.0', b'159.0')):
        path = target/name; saved = path.read_bytes()
        try:
            changed = bytearray(saved)
            if old is None: changed[-1] ^= 1
            else: changed = saved.replace(old, new, 1); assert changed != saved
            path.write_bytes(bytes(changed))
            receipt = json.loads(saved_receipt); receipt['evidence'][name] = file_digest(path)
            receipt_path.write_text(json.dumps(receipt))
            report['negative'].append({name+'WithRefreshedDigest': rejected(lambda: registry.verify(target), 'VERIFICATION_FAILED')})
        finally:
            path.write_bytes(saved); receipt_path.write_bytes(saved_receipt)
    assert registry.verify(target)['verified']


def handoff(directory, locations, report):
    original = json.loads((ROOT/'examples/schemaxis/imagej-to-calc.json').read_text())
    image = directory/'handoff-input.pgm'; shutil.copyfile(FIXTURE, image)
    for unit, size, total in (('um', 0.5, 86.75), ('mm', 0.25, 21.6875)):
        document = copy.deepcopy(original)
        particles = document['operations'][0]['document']
        particles.update(image=str(image), calibration={'pixelWidth': size, 'pixelHeight': size, 'unit': unit})
        target = directory/('handoff-'+unit)
        result = workflow.execute(document, target, locations=locations, timeout=180)
        assert workflow.verify(target)['verified']
        jobs = {job['operation']: job for job in result['jobs']}
        table = read_csv(Path(jobs['particles']['directory'])/'particles.csv')
        workbook = read_csv(Path(jobs['workbook']['directory'])/'data.csv')
        assert table['columns'] == workbook['columns'] and close(table, workbook)
        assert table['columns'][2] == 'area_'+unit+'2' and abs(sum(row[2] for row in table['rows'])-total) < 1e-9
        resumed = workflow.execute(document, target, locations=locations, timeout=180, resume=True)
        assert all(job['reused'] for job in resumed['jobs'])
        report['workflows'].append({'unit': unit, 'pixelSize': size, 'totalArea': total,
                                    'workbookColumns': workbook['columns'][:4], 'allReused': True})
    # A changed image with the same path must not reuse the earlier measurement.
    data = bytearray(image.read_bytes()); data[-1] = 200; image.write_bytes(bytes(data))
    resumed = workflow.execute(document, target, locations=locations, timeout=180, resume=True)
    reused = {job['operation']: job['reused'] for job in resumed['jobs']}
    assert reused['particles'] is False, reused
    report['workflows'].append({'changedImageReuse': reused})


def public_loop(directory, config, report):
    sys.path.insert(0, str(ROOT/'tools'))
    from qualify_agent_service import Client
    from qualify_adaptor_growth import context, example_document
    client = Client(directory, config=config); records = []
    try:
        provider, stamp = context(client, VERSION, '/provider')
        materials, _ = context(client, VERSION, '/materials', stamp)
        assert materials['development']['authoring']['model'] == 'document'
        _, _, entry = route_materials(VERSION)
        cases = [c for c in materials['development']['cases'] if c['id'] in ('baseline-8bit', 'anisotropic-millimetres')]
        task = client.call('create_task', objective='Measure calibrated particles and refine calibration', allowed_providers=[provider],
                           budget={'maxAttempts': len(cases)+2, 'maxElapsedSeconds': 300})
        draft = client.call('create_draft', provider=provider, name='Particle measurement'); revision = 0
        report['publicCases'] = []
        for case in cases:
            draft = client.call('edit_draft', document_id=draft['document'], expected_revision=draft['revision'],
                                source=json.dumps(case_document(entry, case, ROOT)))
            planned = client.call('plan_draft', task_id=task['id'], expected_revision=revision,
                                  document_id=draft['document'], draft_revision=draft['revision'])
            revision = planned['revision']
            job = client.call('execute', plan_id=planned['id'], expected_revision=planned['revision'])
            assert client.wait(job)['status'] == 'succeeded', client.call('observe', job_id=job['id'], section='fault')
            assert client.call('verify', job_id=job['id'])['value']['verified']
            resources = client.call('observe', job_id=job['id'], section='resources')['value']
            resource = next(r for r in resources if Path(r['file']).name == 'particle-summary.json')
            summary = client.call('inspect_resource', resource_id=resource['id'])['value']
            for check in case['checks']:
                if check['file'] != 'particle-summary.json': continue
                value = summary
                for part in check['pointer'].split('/')[1:]: value = value[part]
                assert close(value, check['expected'], rel=check['relative'], absolute=check['absolute']), (case['id'], check)
            report['publicCases'].append({'case': case['id'], 'particleCount': summary['particleCount'],
                                          'totalArea': summary['totalArea'], 'areaUnit': summary['calibration']['areaUnit']})
        invalid = next(e for e in materials['examples'] if e.get('expect') == 'invalid')
        refused = client.request('plan', task_id=task['id'], expected_revision=revision, document=example_document(invalid, ROOT))
        assert not refused['ok'] and refused['fault']['code'] == invalid['fault']
        report['publicInvalid'] = {'example': invalid['id'], 'fault': invalid['fault']}
    finally:
        records.extend(client.records); client.close()
        report['transport'] = {'requests': len(records), 'responseBytes': sum(r['responseBytes'] for r in records)}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output-directory', type=Path, required=True)
    parser.add_argument('--java', type=Path, help='absolute Java 11+ executable (imagej location)')
    parser.add_argument('--jar', type=Path, help='absolute ImageJ 1.54 ij.jar (imagejJar location)')
    parser.add_argument('--calc', type=Path, help='absolute Calc soffice for the workbook handoff')
    parser.add_argument('--config', type=Path, help='private configuration with imagej/imagejJar(/calc)')
    parser.add_argument('--wall-timeout', type=float, default=300)
    args = parser.parse_args()
    directory = args.output_directory.resolve(); directory.mkdir(parents=True, exist_ok=False)
    if args.config: config = args.config.resolve()
    else:
        locations = {'imagej': str(args.java), 'imagejJar': str(args.jar)}
        if args.calc: locations['calc'] = str(args.calc)
        config = directory/'locations.json'
        config.write_text(json.dumps({'version': 1, 'locations': locations}, indent=2)+'\n'); config.chmod(0o600)
    os.environ['SCHEMAXIS_CONFIG'] = str(config)
    os.environ['PYTHONDONTWRITEBYTECODE'] = '1'
    from schemaxis.configuration import locations as configured
    locations = configured()
    report = {'verified': False, 'workflows': [], 'negative': [], 'calc': 'unavailable'}
    try:
        fixtures = subprocess.run([sys.executable, str(ROOT/'tools/qualify_imagej_fixtures.py'), '--check'],
                                  capture_output=True, text=True, timeout=60)
        assert fixtures.returncode == 0, fixtures.stderr
        receipt = qualify(VERSION, directory/'native', native=True, locations=locations, timeout=120, wall_timeout=args.wall_timeout)
        assert receipt['verified'], receipt
        report['receipt'] = str(directory/'native/qualification.json')
        report['cases'] = [{'id': c['id'], 'runtime': c['runtime'], 'checks': len(c['checks']),
                            'integrityProbes': len(c['integrity'])} for c in receipt['cases']]
        report['lifecycle'] = receipt['lifecycle']
        tamper(directory/'native/baseline-8bit', report)
        if locations.get('calc'):
            handoff(directory, locations, report); report['calc'] = 'qualified'
        public_loop(directory/'public', config, report)
        report['verified'] = True
    finally:
        (directory/'report.json').write_text(json.dumps(report, indent=2)+'\n')
    print(json.dumps({k: v for k, v in report.items() if k != 'transport'}, indent=2))


if __name__ == '__main__':
    main()
