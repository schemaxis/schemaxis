"""Portable demo and authored-input regressions; no native application launch."""
import copy
import importlib.util
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

from schemaxis.core.faults import SchemaxisError
from schemaxis.adaptors.registry import plan, routes
from schemaxis.documents import resolve_document
from schemaxis.schema import expand_input

ROOT = Path(__file__).resolve().parents[2]
DEMO = ROOT / 'examples/demos'


def authored_files():
    """Authored demo inputs whose route is registered."""
    return [name for name in ('site.input.json',) if (DEMO / name).is_file()
            and json.loads((DEMO / name).read_text()).get('version') in routes()]


class AuthoredCaseTests(unittest.TestCase):
    def test_authored_and_literal_plans_match_without_mutation(self):
        for filename in authored_files():
            with self.subTest(filename=filename):
                authored = json.loads((DEMO / filename).read_text())
                before = copy.deepcopy(authored)
                literal, _ = resolve_document(authored)
                for key in ('dimensions', 'settings', 'definitions'):
                    literal.pop(key, None)
                self.assertEqual(plan(authored), plan(literal))
                self.assertEqual(plan(expand_input(authored)), plan(literal))
                self.assertEqual(authored, before)

    def test_invalid_resolved_values_references_and_unknown_options_fail(self):
        for filename, field, bad_value in (
            ('site.input.json', 'bufferDistance', 'sixty'),
        ):
            if filename not in authored_files():
                continue
            for mutation in ('type', 'missing', 'cycle', 'option', 'root'):
                with self.subTest(filename=filename, field=field, mutation=mutation):
                    authored = json.loads((DEMO / filename).read_text())
                    section = 'dimensions' if field == 'bufferDistance' else 'settings'
                    if mutation == 'type': authored[section][field] = bad_value
                    if mutation == 'missing': del authored[section][field]
                    if mutation == 'cycle': authored[section][field] = {'$document': '/' + section + '/' + field}
                    if mutation == 'option': authored['nodes'][0]['options']['runSolver'] = True
                    if mutation == 'root': authored['script'] = 'unsupported'
                    with self.assertRaises(SchemaxisError): plan(authored)

    def test_normal_cli_plans_authored_files_from_unrelated_directory(self):
        with tempfile.TemporaryDirectory() as directory:
            for filename in authored_files():
                result = subprocess.run([sys.executable, '-m', 'schemaxis', 'plan', str(DEMO / filename)],
                    cwd=directory, env={**os.environ, 'PYTHONPATH': str(ROOT / 'src')},
                    capture_output=True, text=True)
                self.assertEqual(result.returncode, 0, result.stderr)
                self.assertNotIn('$document', result.stdout)


class PortableDemoTests(unittest.TestCase):
    def setUp(self):
        spec = importlib.util.spec_from_file_location('cfd_demo', DEMO / 'demo.py')
        self.demo = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(self.demo)

    def test_case_override_reaches_standalone_and_workflow_without_editing_source(self):
        original = (DEMO / 'vehicle.input.json').read_bytes()
        self.demo.CASE = '/a different installation/case.foam'
        for name in ('vehicle', 'region', 'cfd-render'):
            document = self.demo.build(name)
            if name == 'cfd-render': document = document['operations'][0]['document']
            expanded, _ = resolve_document(document)
            self.assertEqual(expanded['settings']['case'], self.demo.CASE)
            self.assertIn(self.demo.CASE, json.dumps(expanded['nodes']))
        self.assertEqual((DEMO / 'vehicle.input.json').read_bytes(), original)

    def test_helper_keeps_authoring_and_resolves_its_own_site_asset(self):
        site = self.demo.build('site')['operations'][0]['document']
        self.assertEqual(site['settings']['source'], str(DEMO / 'sites.geojson'))
        self.assertEqual(plan(site)['nodes'][0]['options']['file'], str(DEMO / 'sites.geojson'))

    def test_selected_doctor_and_environment_override_need_no_other_runtimes(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / 'bin').mkdir()
            executable = root / 'bin/pvbatch'
            executable.write_text('#!/bin/sh\nexit 99\n')
            executable.chmod(0o755)  # doctor must not execute this file
            case = root / 'case.foam'
            case.touch()
            with patch.dict(os.environ, {'SCHEMAXIS_DEMO_PARAVIEW_ROOT': directory,
                                        'SCHEMAXIS_DEMO_CASE': str(case)}, clear=True), \
                 patch.object(sys, 'argv', ['demo.py', 'doctor', 'vehicle']), \
                 patch.object(self.demo, 'RUNS', root / 'runs'):
                with self.assertRaises(SystemExit) as result:
                    self.demo.main()
            self.assertEqual(result.exception.code, 0)
            self.assertEqual(self.demo.CASE, str(case))
            self.assertEqual(self.demo.APPS, {'paraview-root': directory})
