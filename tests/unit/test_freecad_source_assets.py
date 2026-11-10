"""Original geometry admission and exact native source-asset roles are authority."""
import copy,tempfile,unittest
from pathlib import Path
from unittest.mock import patch
from xml.etree import ElementTree as ET
from zipfile import ZipFile
from schemaxis.adaptors.freecad.adaptor import _native_plan
from schemaxis.adaptors.freecad.source_assets import descriptors,verify_members,copied_assets,copied_property
from schemaxis.adaptors.freecad.source_bridge import EmbeddedSources,record,definition
from schemaxis.errors import SchemaxisError
from test_freecad_mesh_source import binary,box


class SourceAssets(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.directory=Path(self.temp.name)
        self.data=binary(box(20,12,5));self.path=self.directory/'casting.stl';self.path.write_bytes(self.data)
        self.document={'version':'schemaxis.freecad/1','nodes':[
            {'id':'casting','filter':'importMesh','options':{'file':str(self.path),'units':'inch','orientation':{'z':'+Y','x':'-X'},'placement':{'position':[4,5,6],'clocking':31},'refine':True}},
            {'id':'part','filter':'body'},{'id':'seed','filter':'bodySeed','inputs':{'body':'part','source':'casting'}}], 'output':'seed'}
        self.prepared=_native_plan(self.document);self.assets=descriptors(self.prepared)
        self.root=ET.Element('Document');obj=ET.SubElement(ET.SubElement(self.root,'ObjectData'),'Object',name='N0')
        properties=ET.SubElement(obj,'Properties')
        self.prop=ET.SubElement(properties,'Property',name='SourceAsset',type='App::PropertyFileIncluded',group='Schemaxis',doc='',attr='0',ro='0',hide='0',status='2097153')
        ET.SubElement(self.prop,'FileIncluded',file='source-asset-0.stl')
        self.members={'source-asset-0.stl':self.data}
    def tearDown(self):self.temp.cleanup()

    def test_original_units_frame_facts_and_compiled_refined_output_survive_original_removal(self):
        self.assertEqual(self.prepared['nodes'][2]['seed']['source'],'N0Refined')
        archive=self.directory/'model.FCStd'
        with ZipFile(archive,'w') as z:z.writestr('Document.xml',b'host-only provider fixture');z.writestr('source-asset-0.stl',self.data)
        self.path.unlink()
        # Provider admission and complete typed graph replay do not import or
        # launch FreeCAD and never read the now absent original file.
        with patch('subprocess.Popen',side_effect=AssertionError('native forbidden')):
            replay=_native_plan(self.document,source=EmbeddedSources(archive,self.prepared))
            self.assertEqual(replay,self.prepared)
            self.assertEqual(definition(archive,record(self.document,self.prepared)),self.prepared)
            verify_members(self.members,self.root,self.assets,'fixture')

    def test_native_property_role_member_and_complete_original_bytes_are_exact(self):
        changes=[lambda r,m:r.find('./ObjectData/Object/Properties/Property').set('status','2097152'),
                 lambda r,m:r.find('./ObjectData/Object/Properties/Property').set('status','2097145'),
                 lambda r,m:r.find('./ObjectData/Object/Properties/Property').set('type','App::PropertyFile'),
                 lambda r,m:r.find('./ObjectData/Object/Properties/Property/FileIncluded').set('file','../casting.stl'),
                 lambda r,m:m.update({'source-asset-0.stl':binary(box(21,12,5))}),
                 lambda r,m:m.clear()]
        for index,change in enumerate(changes):
            root=copy.deepcopy(self.root);members=dict(self.members);change(root,members)
            if index==0:verify_members(members,root,self.assets,'fixture')
            else:
                with self.subTest(index=index),self.assertRaises(SchemaxisError):verify_members(members,root,self.assets,'fixture')

    def test_retained_hash_cannot_substitute_for_lexical_and_topological_admission(self):
        import hashlib
        invalid=b'not an STL';assets=copy.deepcopy(self.assets)
        assets['N0']['source'].update(bytes=len(invalid),sha256=hashlib.sha256(invalid).hexdigest())
        with self.assertRaises(SchemaxisError):verify_members({'source-asset-0.stl':invalid},self.root,assets,'fixture')

    def test_copied_members_are_compiled_per_definition_and_property_roles_stay_exact(self):
        part={'source':record(self.document,self.prepared)}
        first,second=copied_assets(part,0),copied_assets(part,1)
        self.assertNotEqual(first['N0']['copiedMember'],second['N0']['copiedMember'])
        self.assertEqual(copied_assets({'source':{'generation':2}},0),{})
        item=second['N0'];prop=copy.deepcopy(self.prop);prop[0].set('file',item['copiedMember'])
        self.assertEqual(copied_property(self.prop,prop,item,'fixture')[0].get('file'),'source-asset-0.stl')
        for change in (lambda p:p[0].set('file',first['N0']['copiedMember']),
                       lambda p:p[0].set('file',item['copiedMember']+'.1'),
                       lambda p:p.set('type','App::PropertyFile'),
                       lambda p:p.set('name','OtherAsset'),
                       lambda p:p.set('status','2097145'),
                       lambda p:p[0].set('extra','unqualified')):
            candidate=copy.deepcopy(prop);change(candidate)
            with self.assertRaises(SchemaxisError):copied_property(self.prop,candidate,item,'fixture')


if __name__=='__main__':unittest.main()
