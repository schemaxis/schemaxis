"""Generated node and non-node adaptors enter the registry without framework edits."""
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import unittest

from schemaxis.adaptor_scaffold import scaffold
from schemaxis.core.faults import SchemaxisError

ROOT = Path(__file__).resolve().parents[2]


class ScaffoldTests(unittest.TestCase):
    def test_invalid_names_models_and_existing_directories_do_not_write(self):
        with tempfile.TemporaryDirectory() as tmp:
            target = Path(tmp)/'new'
            for name in ('../escape', 'FreeCAD', 'class', 'octave', 'with-dash'):
                with self.assertRaises(SchemaxisError):
                    scaffold(name, target)
                self.assertFalse(target.exists())
            with self.assertRaises(SchemaxisError):
                scaffold('testnew', target, model='arbitrary-code')
            scaffold('testnew', target)
            marker = target/'DEVELOPMENT.md'
            original = marker.read_bytes()
            with self.assertRaises(SchemaxisError):
                scaffold('anothernew', target)
            self.assertEqual(marker.read_bytes(), original)

    def test_both_generated_models_are_host_safe_and_remain_unqualified(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            source = root/'source'
            shutil.copytree(ROOT/'src/schemaxis', source/'schemaxis', ignore=shutil.ignore_patterns('__pycache__', 'console_ui'))
            for provider, model in (('scaffnode', 'nodes'), ('scaffdoc', 'document')):
                overlay = root/provider
                result = scaffold(provider, overlay, model=model)
                self.assertFalse(result['installed'])
                self.assertEqual(result['qualification'], 'unknown')
                shutil.copytree(overlay/'src/schemaxis/adaptors'/provider, source/'schemaxis/adaptors'/provider)
            script = r'''
import importlib.abc, json, sys, unittest
from pathlib import Path
attempts = []
class Guard(importlib.abc.MetaPathFinder):
    def find_spec(self, fullname, *args):
        if fullname.endswith('.native') or fullname.split('.')[0] in {'bpy','paraview','FreeCAD','Part'}:
            attempts.append(fullname)
            raise AssertionError(fullname)
sys.meta_path.insert(0, Guard())
from schemaxis.__main__ import main
from schemaxis.core.faults import SchemaxisError
from schemaxis.adaptors import registry
from schemaxis.adaptor_delivery import qualification_status
from schemaxis.execution_service import ExecutionService
root = Path(sys.argv[1])
def cli(*args):
    sys.argv = ['schemaxis', *args]
    return main()
for provider, model in [('scaffnode', 'nodes'), ('scaffdoc', 'document')]:
    document = json.loads((root/provider/'examples/schemaxis'/f'{provider}-minimal.json').read_text())
    assert provider in {p['id'] for p in cli('discover')['providers']}
    assert registry.plan(document)['value'] == 3
    assert registry.query(document)['adaptors'][0]['adaptor'] == provider
    assert cli('schema', '--version', document['version'])['properties']['version']['const'] == document['version']
    assert cli('capabilities', 'describe', 'operation/'+provider+'/exampleOperation')['sections']['declaration']['native'] == 'NOT_IMPLEMENTED'
    assert qualification_status(document['version'])['status'] == 'unknown'
    report = cli('readiness', '--app', provider, '--admission', '--repository-root', str(root/provider))
    assert not report['structurallyComplete']
    assert any(c['code']=='delivery.development' and c['status']=='fail' for c in report['routes'][0]['checks'])
    from schemaxis.studio_guidance import audit, load
    from schemaxis.studio_catalogue import catalogue
    from schemaxis.studio_library import load_library
    guidance = audit(provider)
    assert guidance['counts']['pending'] > 0 and not guidance['stale'], guidance
    assert not guidance['complete']
    assert all(r['status']=='pending' for r in load(provider)['operations'].values())
    assert load_library(provider)['templates']
    additions = catalogue(provider)['items']
    assert {i['operation'] for i in additions if i.get('operation')} == {'exampleOperation'}
    assert 'adaptor-completion.md' in (root/provider/'DEVELOPMENT.md').read_text()
    with ExecutionService(root/(provider+'-session')) as service:
        draft = service.create_draft(provider)
        draft = service.edit_draft(draft['document'], draft['revision'], json.dumps(document))
        value_path = '/nodes/0/options/value' if model == 'nodes' else '/value'
        draft = service.patch_draft(draft['document'], draft['revision'],
                                   [{'op':'replace','path':value_path,'value':4}])
        assert draft['valid'], draft
        task = service.create_task('Verify generated authoring contract', [provider])
        plan = service.plan_draft(task['id'], 0, draft['document'], draft['revision'])
        assert service.observe(plan_id=plan['id'], section='plan')['value']['value'] == 4
    suite = unittest.TestLoader().discover(str(root/provider/'tests/unit'), pattern=f'test_{provider}_admission.py')
    result = unittest.TextTestRunner().run(suite)
    assert result.wasSuccessful() and result.testsRun == 2
    try: registry.run(document, root/'unused')
    except SchemaxisError as error: assert error.fault.code == 'ADAPTOR_NOT_IMPLEMENTED'
    else: raise AssertionError('scaffold claimed native success')
assert not attempts, attempts
# A broken newly installed runner that ignores its timeout must not hang admission.
source = root/'source/schemaxis/adaptors/scaffnode/adaptor.py'
stub = "fail('ADAPTOR_NOT_IMPLEMENTED', 'Replace this scaffold with a bounded native runner')"
assert stub in source.read_text()
source.write_text(source.read_text().replace(stub, "__import__('time').sleep(30)"))
from schemaxis.adaptor_conformance import _bounded_native
document = json.loads((root/'scaffnode/examples/schemaxis/scaffnode-minimal.json').read_text())
try:
    _bounded_native({'action':'timeout', 'document':document, 'run':str(root/'untrusted-timeout'),
                     'locations':None, 'timeout':1e-9}, root/'watchdog', .25)
except SchemaxisError as error:
    assert error.fault.code == 'CONFORMANCE_WATCHDOG', error.to_dict()
else:
    raise AssertionError('ignored runner timeout was admitted')
assert list((root/'watchdog').glob('*.metrics.json'))
'''
            result = subprocess.run([sys.executable, '-c', script, str(root)], cwd=root,
                                    env={**os.environ, 'PYTHONPATH': str(source)}, text=True, capture_output=True, timeout=60)
            self.assertEqual(result.returncode, 0, result.stdout+result.stderr)


if __name__ == '__main__':
    unittest.main()
