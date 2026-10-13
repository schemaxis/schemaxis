"""Execute the file-driven MVP and material failures; retain every CLI report."""
import argparse
from copy import deepcopy
import json
from pathlib import Path
import subprocess
import sys

from schemaxis.core.documents import load_document, resolve_document
from schemaxis.adaptors.paraview.mvp.foam_export import verify_complete


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--case-file', action='append', required=True)
    parser.add_argument('--output-directory', type=Path, required=True)
    parser.add_argument('--failures', action='store_true')
    args = parser.parse_args()
    root = args.output_directory.expanduser().absolute()
    root.mkdir(exist_ok=False)
    template = Path(__file__).with_name('mvp.json')
    authored = load_document(template.read_text())
    resolved, _ = resolve_document(authored)
    summary = {'verified': False, 'status': 'running', 'runs': [], 'failures': []}

    def publish():
        (root/'acceptance.json').write_text(json.dumps(summary, indent=2)+'\n')

    def run(name, case, document=None, destination=None):
        path = root/(name+'-input.json')
        path.write_text(json.dumps(document if document is not None else authored, indent=2)+'\n')
        command = [sys.executable, '-m', 'schemaxis.adaptors.paraview.mvp', 'run', str(path), '--case-file', str(Path(case).expanduser()),
                   '--output-directory', str(destination or root/name)]
        completed = subprocess.run(command, capture_output=True, text=True)
        (root/(name+'-report.json')).write_text(completed.stdout)
        (root/(name+'-submission.json')).write_text(json.dumps({'command': command, 'exitCode': completed.returncode,
                                                              'stderr': completed.stderr}, indent=2)+'\n')
        report = json.loads(completed.stdout)
        return completed.returncode, report

    publish()
    try:
        for index, case in enumerate(args.case_file):
            name = 'case-%02d' % index
            status, report = run(name, case)
            assert status == 0, report
            execution = report['execution']
            assert execution['state'] == 'succeeded', execution
            evidence = execution['steps'][0]['observations']['verification']
            verify_complete(evidence)
            assert len(evidence['states']) == 6 and len(evidence['images']) == 48
            assert [v['coordinates'] for v in evidence['visits']] == [
                {'time': time, 'position': position} for time in [0.8, 1.0] for position in [0.25, 0.5, 0.75]]
            assert evidence['visits'][3]['changed'] == ['time', 'position']
            assert len({image['pixelSha256'] for image in evidence['images']}) == 48
            for field in ['U', 'p']:
                assert evidence['states'][0]['live']['fields'][field]['sha256'] != evidence['states'][3]['live']['fields'][field]['sha256']
            summary['runs'].append({'case': str(Path(case).expanduser()), 'directory': name,
                                    'geometry': 6, 'images': 48, 'verified': True,
                                    'cells': evidence['inspection']['selectedStates'][0]['cells']})
            publish()
        if args.failures:
            case = args.case_file[0]
            failure_specs = [('missing-field', 'MISSING_FIELD'), ('empty-slice', 'EMPTY_GEOMETRY'),
                             ('time-mismatch', 'TIME_OUT_OF_TOLERANCE'), ('expansion', 'EXPANSION_TOO_LARGE'),
                             ('existing-output', 'OUTPUT_EXISTS'), ('interrupted', 'RUNNER_TIMED_OUT'),
                             ('invalid-expression', 'INVALID_EXPRESSION'), ('cycle', 'DOCUMENT_CYCLE')]
            for name, expected in failure_specs:
                document = deepcopy(resolved)
                options = document['steps'][0]['arguments']
                options['case']['writers'] = []
                options['case']['times'] = {'values': [0.8], 'tolerance': 0}
                if name == 'missing-field':
                    options['case']['requiredFields'] = ['U', 'p', 'schemaxis_missing_field']
                elif name == 'empty-slice':
                    options['case']['fractions'] = [0.5, 2]
                elif name == 'time-mismatch':
                    options['case']['times'] = {'values': [0.7], 'tolerance': 0}
                elif name == 'expansion':
                    options['case']['maxPublications'] = 1
                elif name == 'interrupted':
                    options['timeout'] = 1
                elif name == 'invalid-expression':
                    options['case']['fractions'] = {'$expr': {'op': 'divide', 'args': [1, 0]}}
                elif name == 'cycle':
                    options['case']['fractions'] = {'$document': '/steps/0/arguments/case/fractions'}
                destination = root/'case-00' if name == 'existing-output' else None
                status, report = run(name, case, document, destination)
                fault = report.get('fault') or report['execution']['faults'][0]
                assert status != 0 and fault['code'] == expected, report
                receipt = root/name/'verification.json'
                if receipt.is_file():
                    evidence = json.loads(receipt.read_text())
                    assert evidence.get('verified') is not True
                    if name == 'empty-slice':
                        assert len(evidence['states']) == 1
                        assert (root/name/evidence['states'][0]['file']).is_file()
                summary['failures'].append({'name': name, 'expected': expected, 'observed': fault['code'], 'verified': True})
                publish()
        summary.update(verified=True, status='succeeded')
    except Exception as error:
        summary.update(status='failed', error=str(error))
        raise
    finally:
        publish()
    print(json.dumps(summary, indent=2))


if __name__ == '__main__':
    main()
