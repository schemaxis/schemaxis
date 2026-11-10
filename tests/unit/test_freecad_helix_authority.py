"""Fresh authority binds publications and detects changes after admission."""
import copy
from pathlib import Path
import tempfile
import unittest

from schemaxis.adaptors.freecad.export_payloads import capture
from schemaxis.adaptors.freecad.helix_authority import Admission, verify_observations
from schemaxis.core.faults import SchemaxisError


class HelixPublicationAuthority(unittest.TestCase):
    def records(self):
        common={'definition':{'output':'coil'},'measurementObservations':{'coil':{'volume':23.}},
                'selections':{'rim':[1,2]},'importObservations':{},
                'exportEvidence':{'precision':{'runtime':{'freecad':['1','1','4'],'occ':'7.8.1'}}}}
        built={**copy.deepcopy(common),'shape':{'volume':23.}}
        reopened={**copy.deepcopy(common),'native':{'volume':23.},'step':{'volume':23.},
                  'mesh':{'volume':22.9},'runtime':['1','1','4'],'units':'mm',
                  'freshProcess':True,'status':'succeeded'}
        trusted={'built':copy.deepcopy(built),'reopened':copy.deepcopy(reopened)}
        return built,reopened,trusted

    def refused(self, function, code='VERIFICATION_FAILED'):
        with self.assertRaises(SchemaxisError) as raised:function()
        self.assertEqual(raised.exception.fault.code,code)

    def test_coforged_observations_never_replace_fresh_reference(self):
        built,reopened,trusted=self.records()
        verify_observations({},built,reopened,trusted)
        for key in ('measurementObservations','selections','importObservations','definition'):
            with self.subTest(key=key):
                first,second=copy.deepcopy(built),copy.deepcopy(reopened)
                first[key]=second[key]={'forged':2.}
                self.refused(lambda:verify_observations({},first,second,trusted))
        for key in ('native','step','mesh','runtime','units','freshProcess','status'):
            with self.subTest(key=key):
                altered=copy.deepcopy(reopened);altered[key]={'forged':2.}
                self.refused(lambda:verify_observations({},built,altered,trusted))

    def test_exact_membership_types_and_runtime_change(self):
        built,reopened,trusted=self.records()
        reopened['freshProcess']=1
        self.refused(lambda:verify_observations({},built,reopened,trusted))
        reopened=copy.deepcopy(trusted['reopened']);del reopened['selections']
        self.refused(lambda:verify_observations({},built,reopened,trusted))
        reopened=copy.deepcopy(trusted['reopened'])
        reopened['exportEvidence']['precision']['runtime']['occ']='7.9'
        self.refused(lambda:verify_observations({},built,reopened,trusted),'RERUN_REQUIRED')

    def test_snapshot_and_metadata_final_recheck(self):
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory)
            (root/'model.step').write_bytes(b'original geometry')
            (root/'built.json').write_bytes(b'original observations')
            geometry=capture(root/'model.step');metadata=capture(root/'built.json')
            admitted=Admission(root,root,{}, {}, {}, {'model.step':geometry},
                               {'built.json':metadata,'verification.json':None},{})
            admitted.check_current({}, {})
            for filename,original in (('model.step',geometry.data),('built.json',metadata.data)):
                with self.subTest(filename=filename):
                    (root/filename).write_bytes(b'changed')
                    self.refused(lambda:admitted.check_current({}, {}))
                    (root/filename).write_bytes(original)
            (root/'verification.json').write_bytes(b'late evidence')
            self.refused(lambda:admitted.check_current({}, {}))
            (root/'verification.json').unlink()
            self.refused(lambda:admitted.check_current({'changed':True}, {}))
            admitted.check_current({}, {})


if __name__=='__main__':unittest.main()
