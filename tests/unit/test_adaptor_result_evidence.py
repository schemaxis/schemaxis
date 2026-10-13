"""Malformed saved result envelopes must fail with structured verification faults."""
import importlib
import json
from pathlib import Path
import tempfile
import unittest

from schemaxis.core.faults import SchemaxisError

ROOT=Path(__file__).resolve().parents[2]


class ResultEvidenceTests(unittest.TestCase):
    def test_non_object_result_evidence_is_structured(self):
        for provider in ('gmsh','cantera','ngspice'):
            module=importlib.import_module('schemaxis.adaptors.'+provider+'.adaptor')
            document=json.loads((ROOT/f'examples/schemaxis/{provider}-minimal.json').read_text())
            for invalid in ([],None,True,'succeeded'):
                with self.subTest(provider=provider,invalid=invalid),tempfile.TemporaryDirectory() as temp:
                    directory=Path(temp)
                    # The verifier validates result shape after the authored plan
                    # and file-presence checks, before trusting any native payload.
                    for name in [n for n,_ in module.FILES]+list(module.EVIDENCE)+['verification.json']:
                        (directory/name).write_text('{}')
                    (directory/'authored.json').write_text(json.dumps(document))
                    (directory/'plan.json').write_text(json.dumps(module.plan(document)))
                    (directory/'result.json').write_text(json.dumps(invalid))
                    with self.assertRaises(SchemaxisError) as caught:module.verify(directory)
                    self.assertEqual(caught.exception.fault.code,'VERIFICATION_FAILED')


if __name__=='__main__':unittest.main()
