# Copyright (C) 2026 David L F Gaden
"""Native time discovery is metadata-driven, with explicit unavailable states."""
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
from schemaxis.adaptors.paraview.native_inspect import inspect_time_source


class TimeInspectionTests(unittest.TestCase):
    def inspect(self, available):
        class Proxy:
            TimestepValues=[0,0.5,1]
            def ListProperties(self):return ['TimestepValues'] if available else []
            def UpdatePipelineInformation(self):pass
        class Backend:
            deleted=False
            def create(self,*args):return Proxy()
            def configure(self,*args):pass
            def delete(self,*args):self.deleted=True
        backend=Backend()
        document={'version':'schemaxis/1','nodes':[{'id':'clock','filter':'pvTimeSource'}]}
        with tempfile.TemporaryDirectory() as directory:
            with patch('schemaxis.adaptors.paraview.native_inspect.ParaViewBackend',return_value=backend):
                inspect_time_source(document,'clock',directory)
            result=json.loads((Path(directory)/'inspection.json').read_text())
        self.assertTrue(backend.deleted)
        return result

    def test_generated_sources_do_not_require_openfoam_properties(self):
        result=self.inspect(True)
        self.assertEqual(result['times'],[0,0.5,1])
        self.assertEqual(result['operation'],'pvTimeSource')
        self.assertNotIn('regions',result)

    def test_absent_time_metadata_is_a_structured_fault(self):
        self.assertEqual(self.inspect(False)['fault']['code'],'UNAVAILABLE_TIMES')
