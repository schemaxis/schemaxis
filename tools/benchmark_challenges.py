#!/usr/bin/env python3
"""Falsify copies of passing reference outputs and require common-grader rejection."""
import argparse
import json
from pathlib import Path
import shutil
import zipfile
import xml.etree.ElementTree as ET

from benchmark_workflows import csv_read, csv_write, grade, grade_case, locations, require, save


def challenge(package, proof, config, output):
    require(json.loads((proof/'report.json').read_text()).get('passed') is True,
            'start from a passing proof')
    output.mkdir(parents=True, exist_ok=False)
    loc = locations(config)
    rows = []
    for arm in ('ordinary', 'schemaxis'):
        task = json.loads((package/'initial'/arm/'task.json').read_text())
        for family in ('rlc', 'mesh', 'cfd', 'table'):
            case = next(c for c in task['cases'] if c['family'] == family)
            directory = output/arm/family
            shutil.copytree(proof/arm/'initial/submission'/case['id'], directory)
            if family == 'rlc':
                columns, values = csv_read(directory/'results.csv')
                values[0][2] *= -1
                csv_write(directory/'results.csv', columns, values)
                mutation = 'wrong complex voltage sign'
            elif family == 'mesh':
                path = directory/'mesh.msh'
                source = path.read_text()
                require('"fixed"' in source, 'expected named face')
                path.write_text(source.replace('"fixed"', '"wrong"'))
                mutation = 'wrong physical face name'
            elif family == 'cfd':
                shutil.copyfile(directory/'slice-1-0.vtp', directory/'slice-0-0.vtp')
                mutation = 'later-time field substituted for earlier time'
            else:
                path = directory/'results.ods'
                with zipfile.ZipFile(path) as archive:
                    entries = [(info, archive.read(info)) for info in archive.infolist()]
                changed = False
                with zipfile.ZipFile(path, 'w') as archive:
                    for info, data in entries:
                        if info.filename == 'content.xml':
                            root = ET.fromstring(data)
                            attribute = '{urn:oasis:names:tc:opendocument:xmlns:office:1.0}value'
                            cell = next(node for node in root.iter() if attribute in node.attrib)
                            cell.set(attribute, str(float(cell.get(attribute))+100))
                            changed = True
                            data = ET.tostring(root)
                        archive.writestr(info, data)
                require(changed, 'expected workbook value for challenge')
                mutation = 'wrong workbook value while CSV remains correct'
            save(directory/'claimed-result.json', {'verified': True})
            try:
                grade_case(case, directory, loc, output/arm/(family+'-grade'))
                rejected, reason = False, 'incorrectly accepted'
            except ValueError as error:
                rejected, reason = True, str(error)
            rows.append({'arm': arm, 'family': family, 'mutation': mutation,
                         'rejected': rejected, 'reason': reason})
        # Case-set checking must reject an absent case even without a producer fault.
        small_task = {**task, 'cases': [next(c for c in task['cases'] if c['family'] == 'table')]}
        report = grade(small_task, output/arm/'absent-submission', loc, output/arm/'absent-grade')
        rows.append({'arm': arm, 'mutation': 'missing case',
                     'rejected': not report['passed'] and not report['caseSetMatches']})
    result = {'kind': 'benchmark-artifact-challenges', 'passed': all(r['rejected'] for r in rows),
              'checks': rows, 'autonomousAIComparison': False}
    save(output/'report.json', result)
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ('package', 'proof', 'config', 'output-directory'):
        parser.add_argument('--'+name, type=Path, required=True)
    args = parser.parse_args()
    report = challenge(args.package.resolve(), args.proof.resolve(), args.config.resolve(), args.output_directory.resolve())
    print(json.dumps(report, indent=2))
    return 0 if report['passed'] else 1


if __name__ == '__main__':
    raise SystemExit(main())
