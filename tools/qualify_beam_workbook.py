#!/usr/bin/env python3
# Copyright (C) 2026 David L F Gaden
"""Qualify a measured cantilever stress table and its independent workbook checks."""
import argparse
import copy
import csv
import json
import math
from pathlib import Path
from xml.etree import ElementTree as ET
from zipfile import ZipFile

from schemaxis import workflow
from schemaxis.adaptor_delivery import source_digest
from schemaxis.artifacts import atomic_json, file_digest
from schemaxis.core.faults import SchemaxisError

ROOT = Path(__file__).resolve().parents[1]


def rejected(call, expected):
    try:
        call()
    except SchemaxisError as error:
        assert error.fault.code == expected, error.fault.to_dict()
        return error.fault.to_dict()
    raise AssertionError('expected rejection: ' + expected)


def workbook_cells(directory):
    """Read literal native caches without the adaptor's workbook/check helpers."""
    with ZipFile(directory/'analysis.xlsx') as archive:
        xml = ET.fromstring(archive.read('xl/worksheets/sheet2.xml'))
    ns = {'s': 'http://schemas.openxmlformats.org/spreadsheetml/2006/main'}
    xlsx = {cell.get('r'): float(cell.findtext('s:v', namespaces=ns))
            for cell in xml.findall('.//s:c', ns)
            if cell.get('r') in ('B7', 'E7', 'F7')}
    with ZipFile(directory/'analysis.ods') as archive:
        xml = ET.fromstring(archive.read('content.xml'))
    ns = {'t': 'urn:oasis:names:tc:opendocument:xmlns:table:1.0',
          'o': 'urn:oasis:names:tc:opendocument:xmlns:office:1.0'}
    sheet = next(item for item in xml.findall('.//t:table', ns)
                 if item.get('{'+ns['t']+'}name') == 'Summary')
    row = sheet.findall('t:table-row', ns)[6]
    cells = row.findall('t:table-cell', ns)
    ods = {address: float(cells[column].get('{'+ns['o']+'}value'))
           for address, column in (('B7', 1), ('E7', 4), ('F7', 5))}
    return {'xlsx': xlsx, 'ods': ods}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--config', type=Path, required=True)
    parser.add_argument('--output-directory', type=Path, required=True)
    args = parser.parse_args()
    locations = json.loads(args.config.read_text())['locations']
    output = args.output_directory.resolve()
    output.mkdir(parents=True, exist_ok=False)
    example = ROOT/'examples/schemaxis/calculix-to-calc.json'
    document = json.loads(example.read_text())
    report = {'version': 'schemaxis.beam-workbook-qualification/1',
              'verified': False, 'checks': {}, 'recipeSHA256': file_digest(__file__),
              'documentSHA256': file_digest(example),
              'sourceDigests': {app: source_digest(app) for app in ('calculix', 'calc')}}
    try:
        target = output/'workflow'
        result = workflow.execute(document, target, locations=locations, timeout=180)
        workflow.verify(target)
        jobs = {job['operation']: job for job in result['jobs']}
        assert len(result['jobs']) == 2 and set(jobs) == {'beam', 'workbook'}
        assert all(job['status'] == 'succeeded' for job in jobs.values())
        beam_directory = Path(jobs['beam']['directory'])
        calc_directory = Path(jobs['workbook']['directory'])
        assessment = json.loads((beam_directory/'beam-assessment.json').read_text())
        observed = assessment['native']['fine']
        # Literal independent geometry/load oracle for this particular fixture.
        inertia = .02*.02**3/12
        expected_tip = -100*.4**3/(3*210e9*inertia)
        assert math.isclose(observed['tipAreaMeanDisplacement_m'][2], expected_tip, rel_tol=.006)
        assert math.isclose(observed['rootReaction_N'][2], 100, rel_tol=1e-4)
        assert math.isclose(observed['rootMomentAboutClampCentre_Nm'][1], -40, rel_tol=1e-4)
        with (beam_directory/'interior-stress.csv').open(newline='') as stream:
            rows = list(csv.DictReader(stream))
        assert len(rows) == 1280
        assert all(.12 <= float(row['x_m']) <= .28 for row in rows)
        stresses = [float(row['sxx_Pa']) for row in rows]
        minimum, maximum = min(stresses), max(stresses)
        assert -20e6 <= minimum <= -10e6 and 10e6 <= maximum <= 20e6
        assert abs(minimum+maximum) <= 10
        caches = workbook_cells(calc_directory)
        for values in caches.values():
            assert values == {'B7': 1280, 'E7': minimum, 'F7': maximum}, values
        assert (beam_directory/'interior-stress.csv').read_bytes() == (calc_directory/'source.csv').read_bytes()
        requirements = json.loads((calc_directory/'requirements.json').read_text())
        assert requirements['passed'] and len(requirements['requirements']) == 4
        report['checks']['nativeValues'] = {'areaMeanTipUz_m': observed['tipAreaMeanDisplacement_m'][2],
            'theoryTip_m': expected_tip, 'interiorSamples': len(rows), 'workbookCaches': caches}
        report['runtimes'] = {
            'calculix': json.loads((beam_directory/'verification.json').read_text())['runtime'],
            'calc': json.loads((calc_directory/'runtime.json').read_text())['runtime']}

        resumed = workflow.execute(document, target, locations=locations, timeout=180, resume=True)
        assert len(resumed['jobs']) == 2
        assert {job['operation'] for job in resumed['jobs']} == set(jobs)
        assert all(job['status'] == 'succeeded' and job['reused'] for job in resumed['jobs'])
        workflow.verify(target)
        report['checks']['reusedJobs'] = 2

        bad_beam = copy.deepcopy(document)
        bad_beam['operations'][0]['document']['requirements'][0]['maximum'] = .0007
        rejected_target = output/'unmet-beam'
        report['checks']['unmetBeam'] = rejected(lambda: workflow.execute(
            bad_beam, rejected_target, locations=locations, timeout=180), 'PERFORMANCE_NOT_MET')
        failed = json.loads((rejected_target/'result.json').read_text())
        assert failed['status'] == 'failed' and not failed['verified']
        assert {job['operation'] for job in failed['jobs']} == {'beam'}
        assert failed['jobs'][0]['status'] == 'failed'
        assert not (rejected_target/'workbook').exists()
        report['checks']['unmetBeamBlocksWorkbook'] = True

        bad_workbook = copy.deepcopy(document)
        bound = bad_workbook['operations'][1]['document']['requirements'][2]
        bound['minimum'], bound['maximum'] = 0, 10e6
        rejected_target = output/'unmet-workbook'
        report['checks']['unmetWorkbook'] = rejected(lambda: workflow.execute(
            bad_workbook, rejected_target, locations=locations, timeout=180), 'REQUIREMENTS_UNMET')
        failed = json.loads((rejected_target/'result.json').read_text())
        failed_jobs = {job['operation']: job for job in failed['jobs']}
        assert failed['status'] == 'failed' and not failed['verified']
        assert set(failed_jobs) == {'beam', 'workbook'}
        assert failed_jobs['beam']['status'] == 'succeeded'
        assert failed_jobs['workbook']['status'] == 'failed'
        report['checks']['consumerAcceptanceIndependent'] = True
        report['verified'] = True
    finally:
        atomic_json(output/'qualification.json', report)
    print(json.dumps(report, indent=2))


if __name__ == '__main__':
    main()
