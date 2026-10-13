"""Check the Studio starter's design, exact case identity and live parameter bindings.

Run from the repository root with PYTHONPATH=src. No native application starts.
"""
import json
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch

from schemaxis import output_naming, workflow, workflow_design, workflow_templates


ROOT = Path(__file__).resolve().parent / 'sequence-study'


def read(path):
    return json.loads(path.read_text(encoding='utf-8'))


def main():
    with patch('subprocess.Popen', side_effect=AssertionError('host check must not start native applications')):
        design = read(ROOT / 'design.json')
        workflow_design.validate(design)
        projection = workflow_design.project(design)
        assert len(projection['connections']) == 1
        assert not projection['loops']
        bundle = workflow_templates.load_template(ROOT / 'template.json')
        assert workflow_design.compile(design) == bundle['workflow']
        assert set(bundle['template']['parameters']) == {'stop', 'count', 'factor'}
        for filename in ('example.json', 'dense.json'):
            case = read(ROOT / 'cases' / filename)
            prepared = workflow_templates.prepare_template(ROOT / 'template.json', case, planning=True)
            operations = workflow.validate(prepared['document'])
            source = operations[0]['document']['nodes'][0]['options']
            factor = operations[1]['document']['nodes'][1]['options']['factor']
            assert source['stop'] == case['values']['stop']
            assert source['count'] == case['values']['count']
            assert factor == case['values']['factor']
            names = output_naming.preview(case['run']['naming']['pattern'], [
                {'operation': spec['operation'], 'output': alias, 'artifact': spec['artifact'],
                 'ext': '.csv' if spec['kind'] == 'table' else '.json', 'parameters': prepared['values']}
                for alias, spec in bundle['template']['outputs'].items()
            ], index_width=case['run']['naming']['indexWidth'])
            assert not names['collisions']
            assert len(names['names']) == 4
            print(filename + ': exact identity bound; stop, count and factor reach their operations; plan accepted')
        with TemporaryDirectory() as directory:
            exported = workflow_design.export_template(design, Path(directory) / 'export',
                template_id=bundle['template']['id'], title=bundle['template']['title'],
                revision=bundle['template']['revision'])
            assert exported['digest'] == bundle['digest']
        print('Design export reproduces the checked-in template digest; output names are collision-free.')


if __name__ == '__main__':
    main()
