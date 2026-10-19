"""Completion obligations are objective, offline and independent of runtime support."""
import copy
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

from schemaxis.adaptors import registry
from schemaxis.capabilities import CapabilityCatalogue, operation_id
from schemaxis.core.faults import SchemaxisError
from schemaxis.documentation_links import url_syntax
from schemaxis.readiness import Audit, enforce, report
from schemaxis.search_acceptance import check_cases, validate_cases
from schemaxis.studio_catalogue import catalogue
from schemaxis.studio_guidance import audit_links, validate_record

ROOT = Path(__file__).resolve().parents[2]


class CompletionTests(unittest.TestCase):
    def test_representative_admission_keeps_independent_axes(self):
        with patch('subprocess.Popen', side_effect=AssertionError('offline admission')):
            result = enforce(report(['gmsh', 'ngspice'], admission=True))
        for row in result['routes']:
            self.assertEqual(row['implementation']['entryPoints'], 'present')
            self.assertEqual(row['runtimeAvailability'], 'unknown')
            self.assertEqual(row['nativeQualification'], 'unknown')
            self.assertEqual(row['documentationCompleteness'], {'coverage': 'complete', 'editorialReview': 'unreviewed'})

    def test_review_gaps_do_not_remove_registration_or_execution_entry_points(self):
        result = report(['gmsh'], admission=True)
        from schemaxis.adaptor_delivery import route_materials, example_document
        _, _, entry = route_materials('schemaxis.gmsh/1')
        # The manifest and source metadata still route documents when a new
        # required completion review is absent; the opt-in gate reports the gap.
        with patch('schemaxis.readiness._delivery', return_value={'schemaxis.gmsh/1': {k: v for k, v in entry.items() if k != 'completion'}}):
            result = report(['gmsh'], admission=True)
        self.assertFalse(result['structurallyComplete'])
        with self.assertRaises(SchemaxisError) as caught:
            enforce(result)
        self.assertEqual(caught.exception.fault.code, 'ADAPTOR_NOT_READY')
        document = example_document(entry, entry['examples'][0]['id'], ROOT)
        self.assertEqual(registry.plan(document)['version'], 'schemaxis.gmsh.plan/1')
        self.assertEqual(result['routes'][0]['implementation']['entryPoints'], 'present')

    def test_search_cases_use_real_cli_and_public_agent_service(self):
        from schemaxis.agent_transport import dispatch
        from schemaxis.execution_service import ExecutionService
        c = CapabilityCatalogue()
        with tempfile.TemporaryDirectory() as tmp, ExecutionService(tmp) as service:
            for provider in ('gmsh', 'ngspice'):
                self.assertTrue(check_cases(c, provider)['complete'])
                for case in c._metadata[provider]['searchCases']:
                    request = {'query': case['query'], 'scope': case['scope'], 'limit': 100, 'max_bytes': 65536}
                    agent = dispatch(service, {'id': case['id'], 'method': 'capabilities.search', 'params': request})
                    cli = subprocess.run([sys.executable, '-m', 'schemaxis', 'capabilities', 'search', case['query'],
                        '--scope', case['scope'], '--limit', '100', '--max-bytes', '65536'], cwd=ROOT,
                        capture_output=True, text=True, timeout=30)
                    self.assertEqual(cli.returncode, 0, cli.stderr)
                    self.assertEqual(json.loads(cli.stdout)['items'], agent['items'])
                    observed = {i['id'] for i in agent['items']}
                    self.assertLessEqual(set(case['expected']['capabilities']), observed)
                    self.assertFalse(set(case.get('excluded', {}).get('capabilities', [])) & observed)
                    self.assertEqual([i['id'] for i in agent['items']], sorted(observed))

    def test_scoped_operation_projection_does_not_copy_application_terms(self):
        c = CapabilityCatalogue(['gmsh'])
        self.assertIn('finite element pre-processing', c.application_projection('gmsh')['searchText'])
        self.assertEqual(c.search('pre-processing')['items'], [])
        self.assertIn('cuboid', c.operation_search_text('gmsh', 'box'))
        self.assertNotIn('cuboid', c.operation_search_text('gmsh', 'tetrahedral'))
        for provider in ('gmsh', 'ngspice'):
            c = CapabilityCatalogue([provider])
            entries = catalogue(provider)['items']
            for name in registry.declarations(provider):
                item = next(i for i in entries if i.get('operation') == name)
                self.assertEqual(item['capabilityId'], operation_id(provider, name))
                self.assertEqual(item['searchText'], c.operation_search_text(provider, name))
                self.assertEqual(item['guidance']['status'], 'reviewed')
        self.assertEqual({i['at'] for i in catalogue('ngspice')['items'] if i.get('operation')}, {'/operation'})

    def test_invalid_and_pending_search_cases_cannot_complete(self):
        c = CapabilityCatalogue(['gmsh'])
        cases = copy.deepcopy(c._metadata['gmsh']['searchCases'])
        for mutation in ('unknown-id', 'overlap', 'unknown-surface', 'wrong-type', 'duplicate'):
            bad = copy.deepcopy(cases)
            if mutation == 'unknown-id': bad[0]['expected']['add'] = ['operation/gmsh/invented']
            if mutation == 'overlap': bad[0]['excluded']['add'] = bad[0]['expected']['add']
            if mutation == 'unknown-surface': bad[0]['expected']['magic'] = []
            if mutation == 'wrong-type': bad[0]['expected']['add'] = [None]
            if mutation == 'duplicate': bad.append(bad[0])
            with self.assertRaises(SchemaxisError):
                validate_cases(bad, 'gmsh', registry.declarations('gmsh'))
        c._metadata['gmsh']['searchCases'][0]['status'] = 'pending'
        self.assertFalse(check_cases(c, 'gmsh')['complete'])
        c._metadata['gmsh']['searchCases'][0]['status'] = 'reviewed'
        c._metadata['gmsh']['searchCases'][0]['query'] = 'absent phrase'
        self.assertEqual(check_cases(c, 'gmsh')['failedCases'], ['phrase-1'])

    def test_local_links_anchors_symbols_ranges_and_origins_are_checked_offline(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root/'docs').mkdir()
            (root/'docs/guide.md').write_text('# Guide\n## Repeat\n## Repeat\n```\n## Fake\n```\n')
            (root/'src').mkdir()
            (root/'src/helper.py').write_text('def answer():\n    return 42\n')
            audit = Audit(root)
            for reference in ('docs/guide.md#repeat-1', 'src/helper.py:answer', 'src/helper.py:1-2'):
                self.assertEqual(audit.link(reference, reference), 'pass')
            for reference in ('docs/guide.md#fake', 'src/helper.py:absent', 'src/helper.py:1-9', '../escape.md', 'https://example.invalid/todo'):
                self.assertEqual(audit.link(reference, reference), 'fail')
            guidance = {'operations': {}, 'routes': {'test/1': {'fields': {'': {'status': 'reference',
                'explanation': 'Scoped source.', 'sources': ['docs/guide.md#absent', 'guidance:/missing']}}}}}
            self.assertEqual(len(audit_links(guidance, root)), 2)
            (root/'docs/guide.md').write_text('# Guide\n[Missing](missing.md#field)\n')
            audit.markdown_links('docs/guide.md', 'guide')
            self.assertEqual(audit.checks[-1]['status'], 'fail')
            self.assertTrue(url_syntax('https://gmsh.info/doc/texinfo/gmsh.html'))
            self.assertFalse(url_syntax('https://bad host/page'))
            (root/'src/context.json').write_text(json.dumps({'a/b': [{'value': 7}]}))
            self.assertEqual(audit.link('src/context.json#/a~1b/0/value', 'json'), 'pass')
            self.assertEqual(audit.link('src/context.json#/a~1b/01/value', 'json'), 'fail')
            self.assertEqual(audit.link('src/context.json#/a~1b/0/missing', 'json'), 'fail')
            self.assertEqual(audit.link('src/helper.py:1-1,2-2 (readback)', 'range'), 'pass')

    def test_missing_help_and_add_targets_fail_admission(self):
        from importlib.resources import files
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root/'studio_ui/help').mkdir(parents=True)
            index = json.loads(files('schemaxis').joinpath('studio_ui/help/index.json').read_text())
            index['entries'] = [e for e in index['entries'] if not (e.get('provider') == 'ngspice' and e.get('operation') == 'acSweep')]
            (root/'studio_ui/help/index.json').write_text(json.dumps(index))
            actual_files = files
            with patch('schemaxis.readiness.files', side_effect=lambda package: root if package == 'schemaxis' else actual_files(package)):
                result = report(['ngspice'], admission=True)
            check = next(c for c in result['routes'][0]['checks'] if c['code'] == 'studio.help')
            self.assertEqual(check['status'], 'fail')
            self.assertIn('acSweep', check['missingOperations'])
        with patch('schemaxis.studio_catalogue.catalogue', return_value={'items': []}):
            result = report(['ngspice'], admission=True)
        self.assertEqual(next(c for c in result['routes'][0]['checks'] if c['code'] == 'studio.add')['status'], 'fail')

    def test_paraview_generated_drift_check_does_not_rewrite(self):
        with tempfile.TemporaryDirectory() as tmp:
            docs = Path(tmp)/'docs'
            docs.mkdir()
            for name in ('paraview-operation-reference.md', 'paraview-settings-reference.md'):
                (docs/name).write_bytes((ROOT/'docs'/name).read_bytes())
            command = [sys.executable, str(ROOT/'tools/generate_paraview_guide.py'), '--check']
            env = {**os.environ, 'PYTHONPATH': str(ROOT/'src')}
            good = subprocess.run(command, cwd=tmp, env=env, capture_output=True, text=True, timeout=30)
            self.assertEqual(good.returncode, 0, good.stderr)
            path = docs/'paraview-operation-reference.md'
            path.write_text('stale output')
            stale = subprocess.run(command, cwd=tmp, env=env, capture_output=True, text=True, timeout=30)
            self.assertNotEqual(stale.returncode, 0)
            self.assertIn('Stale generated ParaView reference', stale.stderr)
            self.assertEqual(path.read_text(), 'stale output')

    def test_packaged_help_checks_local_anchors_and_drift_without_rewriting(self):
        import importlib.util
        spec = importlib.util.spec_from_file_location('completion_help_generator', ROOT/'tools/generate_studio_help.py')
        generator = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(generator)
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root/'src/schemaxis/adaptors').mkdir(parents=True)
            docs = root/'docs'
            docs.mkdir()
            for name in ('studio-guide', 'paraview-guide', 'dollar-reference', 'workflow-authoring', 'workflow-design', 'paraview-operation-reference'):
                (docs/(name+'.md')).write_text('# ' + name + '\n\n## Topic\n\nA useful topic.\n')
            dest = root/'src/schemaxis/studio_ui/help'
            dest.mkdir(parents=True)
            with patch.object(generator, 'ROOT', root), patch.object(generator, 'DEST', dest):
                generator.build()
                generator.build(check=True)
                before = {p.name: p.read_bytes() for p in dest.glob('*.json')}
                (docs/'studio-guide.md').write_text('# Studio\n\n[Stale anchor](paraview-guide.md#absent)\n')
                with self.assertRaises(SystemExit) as error:
                    generator.build(check=True)
                self.assertIn('has no such anchor', str(error.exception))
                self.assertEqual(before, {p.name: p.read_bytes() for p in dest.glob('*.json')})
                (docs/'studio-guide.md').write_text('# Updated Studio\n')
                with self.assertRaises(SystemExit) as error:
                    generator.build(check=True)
                self.assertIn('Stale supplied help', str(error.exception))

    def test_receipt_updates_do_not_invalidate_help_or_source_identity(self):
        import importlib.util
        from schemaxis.adaptor_delivery import source_digest
        spec = importlib.util.spec_from_file_location('receipt_help_generator', ROOT/'tools/generate_studio_help.py')
        generator = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(generator)
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            package = root/'src/schemaxis'
            adaptor = package/'adaptors/paraview'
            adaptor.mkdir(parents=True)
            receipt = adaptor/'qualification.json'
            receipt.write_text('{"sourceDigest":"before","recordedAt":"earlier"}')
            example = root/'examples/example.json'
            example.parent.mkdir()
            example.write_text('{"value":42}')
            docs = root/'docs'
            docs.mkdir()
            for name in ('studio-guide', 'paraview-guide', 'dollar-reference', 'workflow-authoring', 'workflow-design', 'paraview-operation-reference'):
                (docs/(name+'.md')).write_text('# ' + name + '\n')
            (docs/'studio-guide.md').write_text(
                '# Studio\n\n[Receipt](../src/schemaxis/adaptors/paraview/qualification.json)\n'
                '[Example](../examples/example.json)\n')
            dest = package/'studio_ui/help'
            dest.mkdir(parents=True)
            with patch.object(generator, 'ROOT', root), patch.object(generator, 'DEST', dest), \
                    patch('schemaxis.adaptor_delivery.files', return_value=package):
                generator.build()
                before = {p.name: p.read_bytes() for p in dest.glob('*.json')}
                identity = source_digest('paraview')
                sources = {entry['source'] for entry in json.loads((dest/'index.json').read_text())['entries']}
                self.assertIn('examples/example.json', sources)
                self.assertNotIn('src/schemaxis/adaptors/paraview/qualification.json', sources)
                receipt.write_text('{"sourceDigest":"after","recordedAt":"later"}')
                generator.build(check=True)
                self.assertEqual(before, {p.name: p.read_bytes() for p in dest.glob('*.json')})
                self.assertEqual(identity, source_digest('paraview'))
                receipt.unlink()
                with self.assertRaises(SystemExit) as caught:
                    generator.build(check=True)
                self.assertIn('qualification.json is missing', str(caught.exception))

    def test_placeholder_prose_is_pending_and_type_text_is_not_proof_of_review(self):
        validate_record({'status': 'pending', 'question': 'What are these units?'})
        with self.assertRaises(ValueError):
            validate_record({'status': 'reviewed', 'explanation': 'TODO explain meaning.'})
        # Arbitrary nonempty text can still be incorrect. Structural admission
        # explicitly leaves editorial/domain review unreviewed.
        validate_record({'status': 'reviewed', 'explanation': 'A number.'})


if __name__ == '__main__':
    unittest.main()
