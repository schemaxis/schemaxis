"""Reduced native tool admission, identity and executable bundle closure."""
import copy
from pathlib import Path
import sys
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch
from zipfile import ZipFile,ZIP_DEFLATED

import jsonschema
from schemaxis.adaptors.freecad import cam,cam_publication,cam_reduced
from schemaxis.core.faults import SchemaxisError
from test_freecad_cam_physical import physical


class ReducedTool(unittest.TestCase):
    def test_explicit_native_reduced_profile_changes_typed_identity(self):
        d=physical();standard=cam.plan(d);d['tools'][1]['shankDiameter']=1
        reduced=cam.plan(d);jsonschema.validate(d,cam.schema())
        self.assertNotEqual(standard['tools'][1]['nativeId'],reduced['tools'][1]['nativeId'])
        self.assertEqual(reduced['tools'][1]['shankDiameter'],1)
        self.assertTrue(cam_reduced.needed(reduced));self.assertFalse(cam_reduced.needed(standard))
        for diameter in (0,True,3,3.1):
            bad=copy.deepcopy(d);bad['tools'][1]['shankDiameter']=diameter
            with self.subTest(diameter=diameter),self.assertRaises(SchemaxisError):cam.plan(bad)
        bad=copy.deepcopy(d);bad['tools'][1]['module']='foreign.py'
        with self.assertRaises(SchemaxisError):cam.plan(bad)

    def test_foreign_loaded_class_refused_before_native_import(self):
        with patch.dict(sys.modules,{cam_reduced.MODULE:SimpleNamespace(__file__='/foreign/tool.py')}):
            with self.assertRaisesRegex(ValueError,'foreign'):cam_reduced.native_module()

    def test_complete_bundle_matches_installed_code_before_any_native_use(self):
        p={'version':'schemaxis.freecad.cam.plan/3','tools':[{'kind':'drill','shankDiameter':1}]}
        with tempfile.TemporaryDirectory() as temporary:
            root=Path(temporary)
            for name in ('machining.FCStd','program.ngc','remaining.brep'):(root/name).write_bytes(b'bounded host fixture')
            cam_publication.publish(root,'1.1.4',p)
            self.assertEqual(cam_publication.verify(root,p),cam_publication.artifacts(root))
            with ZipFile(root/'cam-project.zip') as archive:
                original={name:archive.read(name) for name in archive.namelist()}
            self.assertEqual(original[cam_reduced.FILENAME],cam_reduced.module_bytes())
            self.assertIn(b'open-cam.FCMacro',original['README.txt'])
            mutations=[]
            for name in (cam_reduced.FILENAME,cam_reduced.LAUNCHER_NAME):
                replaced=dict(original);replaced[name]+=b'\nraise RuntimeError("replaced")\n';mutations.append(replaced)
                missing=dict(original);del missing[name];mutations.append(missing)
            extra=dict(original);extra['foreign.py']=b'raise RuntimeError()';mutations.append(extra)
            for changed in mutations:
                with ZipFile(root/'cam-project.zip','w',ZIP_DEFLATED) as archive:
                    for name,data in changed.items():archive.writestr(name,data)
                with self.assertRaises(SchemaxisError):cam_publication.verify(root,p)
            # Legacy plans retain their exact original four-member format.
            cam_publication.publish(root,'1.1.4')
            cam_publication.verify(root)
            with ZipFile(root/'cam-project.zip') as archive:self.assertEqual(tuple(archive.namelist()),cam_publication.MEMBERS)
            with self.assertRaises(SchemaxisError):cam_publication.verify(root,p)


if __name__=='__main__':unittest.main()
