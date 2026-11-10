"""Retained-evidence boundary for Graphviz verification.

A stand-in ``dot`` replays the checked-in baseline plain/SVG fixtures so the host
run/verify lifecycle can be exercised without Graphviz. It is not native
qualification and says nothing about real Graphviz output.
"""
import json
from pathlib import Path
import stat
import sys
import tempfile
import unittest

from schemaxis.adaptors.graphviz import adaptor as a
from schemaxis.core.faults import SchemaxisError
ROOT=Path(__file__).resolve().parents[2]
NESTING=100000


def stand_in(directory,version='16.1.0 (20260904.0139)'):
    fixtures=ROOT/'tests/fixtures'
    script=Path(directory)/'dot'
    script.write_text(f'''#!{sys.executable}
import shutil,sys
args=sys.argv[1:]
if args==['-V']:
    sys.stderr.write({('dot - graphviz version '+version+chr(10))!r});sys.exit(0)
outputs=[args[i+1] for i,x in enumerate(args) if x=='-o']
shutil.copy({str(fixtures/'graphviz-baseline.plain')!r},outputs[0])
shutil.copy({str(fixtures/'graphviz-baseline.svg')!r},outputs[1])
''')
    script.chmod(script.stat().st_mode|stat.S_IXUSR)
    return str(script)


class GraphvizRetainedEvidence(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.addCleanup(self.temp.cleanup);self.root=Path(self.temp.name);self.count=0
        self.document=json.loads((ROOT/'examples/schemaxis/graphviz-baseline.json').read_text())
    def run_fresh(self,executable=None):
        self.count+=1;directory=self.root/f'run{self.count}'
        a.run(self.document,directory,executable=executable or stand_in(self.root),timeout=60);return directory
    def fault(self,action,code):
        with self.assertRaises(SchemaxisError) as caught:action()
        self.assertEqual(caught.exception.fault.code,code,caught.exception.fault.to_dict());return caught.exception.fault
    def test_pristine_stand_in_run_reopens(self):
        directory=self.run_fresh();result=a.verify(directory)
        self.assertEqual((result['verified'],result['nodes'],result['edges']),(True,4,4))
    def test_deeply_nested_retained_json_is_a_structured_fault(self):
        nested={'object':'{"a":'*NESTING+'1'+'}'*NESTING,'array':'['*NESTING+']'*NESTING}
        # Include the shared protocol detector before adaptor-specific verification.
        for name in ('verification.json','plan.json','layout.json','layout-submission.json','version-submission.json','result.json'):
            for shape,text in nested.items():
                directory=self.run_fresh();(directory/name).write_text(text)
                with self.subTest(file=name,shape=shape):
                    fault=self.fault(lambda:a.verify(directory),'VERIFICATION_FAILED')
                    self.assertTrue(fault.location.endswith(name),fault.to_dict())
    def test_malformed_identity_is_not_reported_as_unsupported_version(self):
        for text in ('','not a graphviz identity\n','dot - graphviz version 16.1.0\n','dot - graphviz version 16.1.0 (x)\nextra\n'):
            directory=self.run_fresh();(directory/'version.stderr').write_text(text)
            with self.subTest(text=text):self.fault(lambda:a.verify(directory),'VERIFICATION_FAILED')
        directory=self.run_fresh();(directory/'version.stderr').write_bytes(b'\xff')
        self.fault(lambda:a.verify(directory),'VERIFICATION_FAILED')
    def test_single_file_version_tamper_is_verification_failed(self):
        directory=self.run_fresh();(directory/'version.stderr').write_text('dot - graphviz version 15.0.0 (x)\n')
        self.fault(lambda:a.verify(directory),'VERIFICATION_FAILED')
    def test_intact_other_version_stays_unsupported(self):
        directory=self.run_fresh();(directory/'version.stderr').write_text('dot - graphviz version 15.0.0 (20250101.0000)\n')
        receipt=json.loads((directory/'verification.json').read_text())
        receipt['runtime']=(directory/'version.stderr').read_text().strip()
        receipt['evidence']['version.stderr']=a.digest(directory,'version.stderr')
        (directory/'verification.json').write_text(json.dumps(receipt))
        fault=self.fault(lambda:a.verify(directory),'UNSUPPORTED_NATIVE_VERSION')
        self.assertIn('16.1.0',fault.message)
    def test_run_still_rejects_other_executables_before_layout(self):
        for version in ('15.0.0 (20250101.0000)','16.2.0 (20270101.0000)'):
            directory=self.root/('other-'+version[:4])
            self.fault(lambda:a.run(self.document,directory,executable=stand_in(self.root,version),timeout=60),'UNSUPPORTED_NATIVE_VERSION')
            self.assertEqual(json.loads((directory/'result.json').read_text())['status'],'failed')
            self.assertFalse((directory/'layout-launcher.py').exists())


if __name__=='__main__':unittest.main()
