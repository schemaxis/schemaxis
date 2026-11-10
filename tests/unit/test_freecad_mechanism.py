"""Motion intent admission and independent connector-transform controls."""
import copy
import math
from pathlib import Path
import tempfile
import threading
from xml.etree import ElementTree as ET
from zipfile import ZipFile, BadZipFile
import unittest
from unittest.mock import patch

from schemaxis.adaptors.freecad import assembly,mechanism
from schemaxis.core.faults import SchemaxisError


class MechanismTests(unittest.TestCase):
    def source(self):
        authored={'version':assembly.VERSION,'parts':[{'id':'block','type':'box','options':{'length':10,'width':10,'height':10}}],
            'components':[{'id':'base','part':'block','position':[2,3,4],'rotation':90},{'id':'arm','part':'block'}],
            'grounded':'base','joints':[{'id':'hinge','type':'fixed','parent':{'component':'base','face':'top'},
                'child':{'component':'arm','face':'bottom'},'offset':[3,4,5]}]}
        return {'assembly':assembly._native_plan(authored),'native':{'components':{'base':'Component0','arm':'Component1'},
            'joints':{'hinge':'Joint0'}},'file':'source.FCStd','sha256':'a','run':'source','receiptSha256':'b'}

    def prepared(self,motion=None,**options):
        d={'version':mechanism.VERSION,'source':'source.FCStd','motions':[motion or {'joint':'hinge','kind':'rotation','end':90}],**options}
        with patch.object(mechanism,'source_record',return_value=self.source()):return mechanism._native_plan(d)

    def assertVector(self,actual,wanted):
        for a,b in zip(actual,wanted):self.assertAlmostEqual(a,b,places=8)

    def test_rotated_root_and_offset_hinge_compose_about_the_connector(self):
        p=self.prepared();pose=mechanism.poses(p,1)['arm']
        self.assertVector([pose[i] for i in (3,7,11)],[-2,16,19])
        self.assertVector([pose[i] for i in (0,5,10)],[-1,-1,1])
        self.assertAlmostEqual(float(p['motions'][0]['formula'].split('*')[0]),math.pi/2)

    def test_slider_uses_connector_z_and_millimetres(self):
        p=self.prepared({'joint':'hinge','kind':'translation','end':12.5})
        pose=mechanism.poses(p,1)['arm']
        self.assertVector([pose[i] for i in (3,7,11)],[-2,6,31.5])
        self.assertEqual(p['motions'][0]['formula'],'12.5*time')

    def test_tilted_source_mount_moves_in_its_local_axis(self):
        from schemaxis.adaptors.freecad.assembly_sources import _axes
        p=self.prepared({'joint':'hinge','kind':'translation','end':7})
        a=p['source']['assembly'];a['sourced']=True
        _,_,rotation=_axes({'z':'+X','x':'+Y'},'mount')
        a['parts']=[{'id':'block','mounts':[{'id':'hinge','value':[10,20,30],'rotation':rotation},
            {'id':'other','value':[2,3,4],'rotation':[[1,0,0],[0,1,0],[0,0,1]]}]}]
        a['components'][0].update(position=[0,0,0],rotation=0)
        a['joints'][0].update(parent={'component':'base','mount':'hinge'},child={'component':'arm','mount':'other'},offset=[0,0,0],clocking=0)
        pose=mechanism.poses(p,1)['arm']
        self.assertVector([pose[i] for i in (3,7,11)],[13,18,27])

    def test_unknown_duplicate_formula_zero_and_underresolved_motion_are_refused(self):
        cases=[{'joint':'absent','kind':'rotation','end':90},
            {'joint':'hinge','kind':'rotation','end':90,'formula':'arbitrary(time)'},
            {'joint':'hinge','kind':'rotation','end':0},
            {'joint':'hinge','kind':'rotation','end':361}]
        for motion in cases:
            with self.subTest(motion=motion),self.assertRaises(SchemaxisError):self.prepared(motion)
        with self.assertRaises(SchemaxisError):self.prepared(intervals=2)
        d={'version':mechanism.VERSION,'source':'source.FCStd','motions':[{'joint':'hinge','kind':'rotation','end':90}]*2}
        with patch.object(mechanism,'source_record',return_value=self.source()),self.assertRaises(SchemaxisError):mechanism._native_plan(d)

    def test_configuration_uses_location_keys_without_treating_gui_as_a_provider(self):
        with patch('schemaxis.configuration.locations',return_value={'freecad_gui':'/private/freecad'}):
            self.assertEqual(mechanism.gui_location(),'/private/freecad')


class MechanismSavedTests(unittest.TestCase):
    def archive(self,directory,*,gui_doctype=False,extra_string=False,owner=1):
        directory.mkdir();path=directory/'model.FCStd'
        document=('<Document><StringHasher2 file="strings.txt"/><Properties/>'
            '<Objects><Object name="Block" type="Part::Feature" id="'+str(owner)+'"/></Objects>'
            '<ObjectData><Object name="Block"><Properties/></Object></ObjectData></Document>')
        gui=('<!DOCTYPE GuiDocument>' if gui_doctype else '')+'<GuiDocument><ViewProviderData><ViewProvider name="Block"/></ViewProviderData></GuiDocument>'
        table='StringTableStart v1 '+('2' if extra_string else '1')+'\n1.0 ;:H'+format(owner,'x')+',F\n'
        if extra_string:table+='2.0 unused-but-persisted\n'
        with ZipFile(path,'w') as archive:
            for name,data in [('Document.xml',document),('GuiDocument.xml',gui),('strings.txt',table)]:archive.writestr(name,data)
        return path

    def test_complete_string_inventory_allows_owner_id_bijection_and_refuses_unused_addition(self):
        with tempfile.TemporaryDirectory() as temporary:
            root=Path(temporary);expected=self.archive(root/'expected');actual=self.archive(root/'actual',owner=42)
            mechanism.compare_saved(actual,expected)
            extra=self.archive(root/'extra',owner=42,extra_string=True)
            with self.assertRaisesRegex(ValueError,'complete string inventory'):
                mechanism.compare_saved(extra,expected)

    def test_gui_payload_file_allocation_is_normalised_but_owner_bytes_are_bound(self):
        def material(path,swapped=False,forged=False):
            with ZipFile(path) as archive:members={n:archive.read(n) for n in archive.namelist()}
            root=ET.fromstring(members['GuiDocument.xml']);providers=root.find('ViewProviderData')
            providers.clear()
            for index,name in enumerate(('Block','Other')):
                provider=ET.SubElement(providers,'ViewProvider',name=name)
                props=ET.SubElement(provider,'Properties')
                prop=ET.SubElement(props,'Property',name='ShapeAppearance',type='App::PropertyMaterialList')
                file='Material'+str(1-index if swapped else index)
                ET.SubElement(prop,'MaterialList',file=file,version='3')
                members[file]=(b'forged' if forged and index==0 else name.encode())
            members['GuiDocument.xml']=ET.tostring(root)
            with ZipFile(path,'w') as archive:
                for name,data in members.items():archive.writestr(name,data)
        with tempfile.TemporaryDirectory() as temporary:
            root=Path(temporary);expected=self.archive(root/'expected');actual=self.archive(root/'actual')
            material(expected);material(actual,swapped=True)
            mechanism.compare_saved(actual,expected)
            material(actual,swapped=True,forged=True)
            with self.assertRaisesRegex(ValueError,'owned GUI payload'):
                mechanism.compare_saved(actual,expected)

    def test_fresh_constructor_gui_rank_follows_owner_id_bijection(self):
        def rank(path,value):
            with ZipFile(path) as archive:members={n:archive.read(n) for n in archive.namelist()}
            xml=ET.fromstring(members['GuiDocument.xml']);xml.find('./ViewProviderData/ViewProvider').set('treeRank',str(value))
            members['GuiDocument.xml']=ET.tostring(xml)
            with ZipFile(path,'w') as archive:
                for name,data in members.items():archive.writestr(name,data)
        with tempfile.TemporaryDirectory() as temporary:
            root=Path(temporary);expected=self.archive(root/'expected');actual=self.archive(root/'actual',owner=42)
            rank(expected,1);rank(actual,42)
            mechanism.compare_saved(actual,expected,fresh_document=True)
            with self.assertRaisesRegex(ValueError,'view properties'):
                mechanism.compare_saved(actual,expected)
            rank(actual,41)
            with self.assertRaisesRegex(ValueError,'native owner allocation'):
                mechanism.compare_saved(actual,expected,fresh_document=True)
            rank(expected,-1);rank(actual,-1)
            mechanism.compare_saved(actual,expected,fresh_document=True)

    def test_gui_prolog_is_checked_before_native_xml_signature(self):
        with tempfile.TemporaryDirectory() as temporary:
            root=Path(temporary);expected=self.archive(root/'expected');actual=self.archive(root/'actual',gui_doctype=True)
            with self.assertRaisesRegex(ValueError,'DOCTYPE'):
                mechanism.compare_saved(actual,expected)

    def test_corrupt_archive_is_a_structured_verification_fault(self):
        with patch.object(mechanism,'_verify',side_effect=BadZipFile('truncated member')):
            with self.assertRaises(SchemaxisError) as caught:mechanism.verify('damaged')
        self.assertEqual(caught.exception.fault.code,'VERIFICATION_FAILED')
        self.assertEqual(caught.exception.fault.observed['detail'],'truncated member')

    def test_host_physics_comparison_obeys_cooperative_cancellation(self):
        from schemaxis.dispatch import allocation
        cancel=threading.Event();cancel.set()
        with allocation({},cancel):
            with self.assertRaises(SchemaxisError) as caught:mechanism.check_observation({}, {})
        self.assertEqual(caught.exception.fault.code,'RUNNER_CANCELLED')

    def test_gui_transport_accepts_only_installed_family_stages(self):
        from schemaxis.adaptors.freecad import gui_process,assembly
        for family,stage in (('authored.module','build'),('assembly','build'),('mechanism','gui_finish')):
            with self.subTest(family=family,stage=stage),self.assertRaises(ValueError):
                gui_process.run('/unused','/bin/true',stage,family=family)
        with patch.object(gui_process,'run',return_value={'nativeJointEditors':True}) as private:
            assembly.gui_stage('/bin/true',Path('/unused'),10,stage='gui_reopen')
            private.assert_called_once_with(Path('/unused'),'/bin/true','gui_reopen',timeout=10,family='assembly')

    def test_cancel_after_xvfb_readiness_prevents_gui_spawn_and_private_profile_is_valid(self):
        from schemaxis.adaptors.freecad import gui_process
        from schemaxis.dispatch import allocation
        cancel=threading.Event();launches=[];terminated=[]
        class Display:
            pid=123
            def __init__(self,command,**options):
                launches.append(command)
                # The profile is produced before either process, in a private folder.
                config=next(Path(temporary).glob('schemaxis-freecad-gui-*/user.cfg'))
                root=ET.fromstring(config.read_text())
                prefs=root.find('./FCParamGroup/FCParamGroup[@Name="BaseApp"]/FCParamGroup[@Name="Preferences"]/FCParamGroup[@Name="Mod"]/FCParamGroup[@Name="CAM"]/FCParamGroup[@Name="Migration"]/FCText[@Name="OfferedToMigrateCAMAssets"]')
                self.assert_profile=prefs.text
                if prefs.text!='v1-1':raise AssertionError('migration preference differs')
            def poll(self):return None
        def ready(*args):cancel.set();return ([1],[],[])
        with tempfile.TemporaryDirectory() as temporary:
            (Path(temporary)/'run').mkdir()
            with allocation({},cancel),patch('tempfile.tempdir',temporary),patch.object(gui_process.shutil,'which',return_value='/bin/true'),patch.object(gui_process.subprocess,'Popen',Display),patch.object(gui_process.select,'select',side_effect=ready),patch.object(gui_process.os,'read',return_value=b'9\n'),patch('schemaxis.dispatch.terminate_tree',side_effect=lambda p,k:terminated.append(p.pid)):
                with self.assertRaises(SchemaxisError) as caught:gui_process.run(Path(temporary)/'run','/bin/true','build')
        self.assertEqual(caught.exception.fault.code,'RUNNER_CANCELLED')
        self.assertEqual(len(launches),1)
        self.assertEqual(terminated,[123])

    def test_total_deadline_crossing_inside_display_wait_is_a_timeout_not_display_failure(self):
        from schemaxis.adaptors.freecad import gui_process
        now=[0.0];launches=[];terminated=[]
        class Display:
            pid=123
            def __init__(self,command,**options):launches.append(command)
            def poll(self):return None
        def waited(*args):now[0]=2.0;return ([],[],[])
        with tempfile.TemporaryDirectory() as temporary:
            with patch.object(gui_process.time,'monotonic',side_effect=lambda:now[0]), \
                 patch.object(gui_process.shutil,'which',return_value='/bin/true'), \
                 patch.object(gui_process.subprocess,'Popen',Display), \
                 patch.object(gui_process.select,'select',side_effect=waited), \
                 patch('schemaxis.dispatch.terminate_tree',side_effect=lambda p,k:terminated.append(p.pid)):
                with self.assertRaises(SchemaxisError) as caught:
                    gui_process.run(temporary,'/bin/true','inspect',family='sourceAssembly',timeout=1)
        self.assertEqual(caught.exception.fault.code,'RUNNER_TIMED_OUT')
        self.assertEqual(len(launches),1);self.assertEqual(terminated,[123])


if __name__=='__main__':unittest.main()
