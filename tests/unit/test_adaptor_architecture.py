# Copyright (C) 2026 David L F Gaden
"""App folders are independently discoverable and cannot own shared dependencies."""
import ast
import copy
import importlib.util
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import unittest

from schemaxis.core.faults import SchemaxisError
from schemaxis.adaptors.registry import load_registry

ROOT = Path(__file__).resolve().parents[2]
SOURCE = ROOT/'src'


class AdaptorArchitectureTests(unittest.TestCase):
    def test_framework_and_adaptor_import_boundaries(self):
        adaptors = {p.parent.name for p in (SOURCE/'schemaxis/adaptors').glob('*/adaptor.json')}
        aliases = {'native', 'native_run', 'native_inspect', 'job', 'filters', 'more_filters',
                   'extra_filters', 'publication', 'blender_adaptor', 'blender_native',
                   'blender_meshes', 'blender_operations', 'blender_settings'}
        native = {'bpy', 'paraview', 'vtk', 'vtkmodules', 'FreeCAD', 'FreeCADGui', 'Part', 'Mesh', 'Sketcher', 'PySide', 'PySide2', 'schemaxis.adaptors.paraview.mvp'}
        paths = list((SOURCE/'schemaxis').rglob('*.py'))
        for path in paths:
            parts = path.relative_to(SOURCE).with_suffix('').parts
            package = '.'.join(parts[:-1])
            owner = parts[2] if len(parts) > 3 and parts[1] == 'adaptors' and parts[2] in adaptors else None
            if len(parts) == 2 and parts[-1] in aliases: continue
            tree = ast.parse(path.read_text())
            # Only compatibility exports may refer from framework to old app APIs.
            tree.body = [n for n in tree.body if not isinstance(n, ast.FunctionDef) or n.name != '__getattr__']
            for node in ast.walk(tree):
                if owner is None and isinstance(node, ast.Compare):
                    # Compatibility location keyword strings are allowed; app-specific
                    # dispatch comparisons in the framework are not.
                    values = [node.left, *node.comparators]
                    literals = {v.value for value in values for v in ast.walk(value)
                                if isinstance(v, ast.Constant) and isinstance(v.value, str)}
                    self.assertFalse(literals & adaptors, f'app-name branch in {path}')
                if isinstance(node, ast.ImportFrom):
                    imports = [importlib.util.resolve_name('.'*node.level + (node.module or ''), package) if node.level else (node.module or '')]
                elif isinstance(node, ast.Import): imports = [a.name for a in node.names]
                else: continue
                for module in imports:
                    with self.subTest(file=str(path.relative_to(ROOT)), module=module):
                        target = module.split('.')
                        if len(target) >= 3 and target[:2] == ['schemaxis', 'adaptors'] and target[2] in adaptors:
                            self.assertEqual(owner, target[2], 'framework/app or app/app dependency')
                        if owner is None:
                            self.assertNotIn(target[0], native, 'native application import in shared framework')
                            self.assertNotIn(module, {'schemaxis.' + name for name in aliases}, 'shared code uses an app compatibility alias')

    def test_duplicate_versions_and_invalid_manifests_fail_before_imports(self):
        fixture = json.loads((ROOT/'tests/fixtures/adaptor_plugin/adaptor.json').read_text())
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            for name in ('one', 'two'):
                item = copy.deepcopy(fixture)
                item['id'] = name
                # Match all binding paths to the synthetic folder.
                item = json.loads(json.dumps(item).replace('schemaxis.adaptors.fixtureapp.', 'schemaxis.adaptors.' + name + '.'))
                (root/name).mkdir()
                (root/name/'adaptor.json').write_text(json.dumps(item))
            with self.assertRaises(SchemaxisError) as caught: load_registry(root)
            self.assertEqual(caught.exception.fault.code, 'INVALID_ADAPTOR')
            (root/'two/adaptor.json').write_text('{broken')
            with self.assertRaises(SchemaxisError) as caught: load_registry(root)
            self.assertEqual(caught.exception.fault.code, 'INVALID_ADAPTOR')

    def test_new_folder_routes_everywhere_without_framework_edits(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            for package in ('schemaxis',):
                shutil.copytree(SOURCE/package, root/package, ignore=shutil.ignore_patterns('__pycache__', 'console_ui'))
            shutil.copytree(ROOT/'tests/fixtures/adaptor_plugin', root/'schemaxis/adaptors/fixtureapp')
            # All routing is exercised in a fresh process, exactly as after installation.
            script = r'''
import importlib.abc, json, sys
from pathlib import Path
class NoNative(importlib.abc.MetaPathFinder):
    def find_spec(self, fullname, *args):
        if fullname.split('.')[0] in {'bpy', 'paraview', 'vtk', 'vtkmodules', 'FreeCAD', 'FreeCADGui'}:
            raise AssertionError('host tried importing native app: ' + fullname)
sys.meta_path.insert(0, NoNative())
from schemaxis.adaptors import registry
from schemaxis.__main__ import main
from schemaxis.schema import export_schema
from schemaxis.schema_authoring import version_schema, umbrella_schema
from schemaxis.console_session import AdaptorConsoleSession
from schemaxis.workflow import execute, inspect_plan, verify
from schemaxis.core.faults import SchemaxisError
root = Path(sys.argv[1])
def cli(*args):
    sys.argv = ['schemaxis', *args]
    return main()
doc = {'version': 'fixtureapp/1', 'nodes': [{'id': 'hello', 'filter': 'emit', 'options': {'text': 'hello'}}]}
source = root/'input.json'; source.write_text(json.dumps(doc))
assert 'fixtureapp' in {p['id'] for p in cli('discover')['providers']}
readiness = cli('readiness', '--app', 'fixtureapp')
assert readiness['routes'][0]['documentVersion'] == 'fixtureapp/1'
assert readiness['routes'][0]['structural'] == 'incomplete'
assert readiness['routes'][0]['nativeQualification'] == 'unknown'
assert cli('describe', '--provider', 'fixtureapp')['emit']['id'] == 'emit'
assert cli('capabilities', 'browse', 'app/fixtureapp')['items'][0]['id'] == 'operation/fixtureapp/emit'
assert cli('capabilities', 'describe', 'operation/fixtureapp/emit')['sections']['declaration']['id'] == 'emit'
assert cli('plan', str(source)) == doc
assert cli('schema', '--provider', 'fixtureapp')['properties']['version']['const'] == 'fixtureapp/1'
assert cli('schema', '--version', 'fixtureapp/1')['properties']['version']['const'] == 'fixtureapp/1'
assert registry.query(doc)['adaptors'][0]['adaptor'] == 'fixtureapp'
assert any(s['properties']['version']['const'] == 'fixtureapp/1' for s in umbrella_schema()['$defs'].values())
result = cli('run', str(source), '--output-directory', str(root/'standalone'), '--executable', 'test-launcher')
assert result['executable'] == 'test-launcher'
assert cli('verify', str(root/'standalone'))['verified']
with AdaptorConsoleSession(root/'console', provider='fixtureapp') as session:
    session.add('hello', 'emit', {'text': 'hello'})
    assert session.preview()['status'] == 'planned'
workflow = {'version': 'schemaxis.workflow/1', 'operations': [{'id': 'first', 'document': doc}, {'id': 'second', 'document': doc}]}
assert len(inspect_plan(workflow)['jobs']) == 2
result = execute(workflow, root/'workflow', locations={'fixtureapp': 'workflow-launcher'})
assert result['verified'] and all(j['result']['executable'] == 'workflow-launcher' for j in result['jobs'])
assert verify(root/'workflow')['artifacts'] == 2
resumed = execute(workflow, root/'workflow', resume=True)
assert all(j['reused'] for j in resumed['jobs'])
(root/'standalone/output.txt').write_text('corrupted')
try: cli('verify', str(root/'standalone'))
except SchemaxisError as error: assert error.fault.code == 'VERIFICATION_FAILED'
else: raise AssertionError('corruption accepted')
try: registry.plan({'version': 'not-registered/1'})
except SchemaxisError as error: assert error.fault.code == 'UNSUPPORTED_VERSION'
else: raise AssertionError('unknown app fell through to a different app')
'''
            result = subprocess.run([sys.executable, '-c', script, str(root)], cwd=root,
                                    env={**os.environ, 'PYTHONPATH': str(root)}, text=True, capture_output=True, timeout=60)
            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)

            # Remove every built-in adaptor from this isolated installation.
            # The new app must still work: no implicit dependency on the first app.
            for folder in (root/'schemaxis/adaptors').iterdir():
                if folder.is_dir() and folder.name != 'fixtureapp' and (folder/'adaptor.json').is_file():
                    shutil.rmtree(folder)
            isolated = subprocess.run([sys.executable, '-c', """
import json
from pathlib import Path
from schemaxis.adaptors import registry
from schemaxis.schema import export_schema
from schemaxis.console_session import AdaptorConsoleSession
assert list(registry.ADAPTORS) == ['fixtureapp']
from schemaxis.capabilities import CapabilityCatalogue
catalogue = CapabilityCatalogue()
assert [i['id'] for i in catalogue.browse()['items']] == ['app/fixtureapp']
assert catalogue.search('emit')['items'][0]['id'] == 'operation/fixtureapp/emit'
assert registry.discover()['providers'][0]['id'] == 'fixtureapp'
assert export_schema()['properties']['version']['const'] == 'fixtureapp/1'
doc = json.loads(Path('input.json').read_text())
assert registry.plan(doc) == doc
assert registry.query(doc)['supported']
with AdaptorConsoleSession('only-app-console') as session:
    session.add('hello', 'emit')
    assert session.preview()['status'] == 'planned'
"""], cwd=root, env={**os.environ, 'PYTHONPATH': str(root)}, text=True, capture_output=True, timeout=30)
            self.assertEqual(isolated.returncode, 0, isolated.stdout + isolated.stderr)
