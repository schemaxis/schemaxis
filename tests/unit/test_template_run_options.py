# Copyright (C) 2026 David L F Gaden
"""Case run options are validated and returned, but never enter the template digest."""
import copy
from pathlib import Path
import tempfile
import unittest

from schemaxis import storage
from schemaxis.core.faults import SchemaxisError
from schemaxis.workflow_authoring import example
from schemaxis.workflow_templates import bind_values, load_template


class TemplateRunOptionTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        directory = Path(temporary.name)
        body = example()
        body['settings'] = {'factor': 2}
        body['operations'][1]['document']['nodes'][1]['options']['factor'] = {
            '$document': '/settings/factor', 'scope': 'workflow'}
        manifest = {'version': 'schemaxis.workflow-template/1', 'id': 'scale', 'revision': 1, 'title': 'Scale',
                    'workflow': 'workflow.json', 'outputs': {},
                    'parameters': {'factor': {'label': 'Factor', 'kind': 'number', 'default': 2,
                                              'target': {'scope': 'workflow', 'pointer': '/settings/factor'}}}}
        (directory / 'template.json').write_bytes(storage.encoded(manifest))
        (directory / 'workflow.json').write_bytes(storage.encoded(body))
        self.bundle = load_template(directory / 'template.json')

    def case(self, **extra):
        return {'version': 'schemaxis.workflow-values/1', 'values': {'factor': 3},
                'template': {'id': 'scale', 'revision': 1, 'digest': self.bundle['digest']}, **extra}

    def test_run_options_are_returned_without_changing_the_binding(self):
        run = {'outputDirectory': 'runs/case-1', 'workers': 4,
               'naming': {'pattern': '{index}-{operation}{ext}', 'indexWidth': 4}}
        case = self.case(run=run)
        frozen = copy.deepcopy(case)
        result = bind_values(self.bundle, case)
        self.assertEqual(result['run'], run)
        self.assertEqual(case, frozen)
        plain = bind_values(self.bundle, self.case())
        self.assertEqual(plain['run'], {})
        self.assertEqual(plain['digest'], result['digest'])
        self.assertEqual(plain['template'], result['template'])

    def test_invalid_run_options_fail_with_locations(self):
        cases = [({'workers': 0}, 'INVALID_RUN_OPTIONS', '$.case.run.workers'),
                 ({'workers': 65}, 'INVALID_RUN_OPTIONS', '$.case.run.workers'),
                 ({'workers': True}, 'INVALID_RUN_OPTIONS', '$.case.run.workers'),
                 ({'outputDirectory': ' '}, 'INVALID_RUN_OPTIONS', '$.case.run.outputDirectory'),
                 ({'naming': {'pattern': '../x{index}'}}, 'INVALID_NAMING', '$.case.run.naming.pattern'),
                 ({'naming': {'indexWidth': 0}}, 'INVALID_NAMING', '$.case.run.naming.indexWidth'),
                 ({'naming': {'style': 'x'}}, 'UNKNOWN_ARGUMENT', '$.case.run.naming'),
                 ({'imageSize': 512}, 'UNKNOWN_ARGUMENT', '$.case.run'),
                 ([], 'INVALID_DOCUMENT', '$.case.run')]
        for run, code, location in cases:
            with self.subTest(run=run):
                with self.assertRaises(SchemaxisError) as caught:
                    bind_values(self.bundle, self.case(run=run))
                self.assertEqual((caught.exception.fault.code, caught.exception.fault.location), (code, location))


if __name__ == '__main__':
    unittest.main()
