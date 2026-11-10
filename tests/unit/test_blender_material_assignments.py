"""Surface region and ownership intent independent of native Blender."""
import copy
import json
import unittest
from schemaxis.errors import SchemaxisError
from schemaxis.adaptors.blender.production import validate,schema
from schemaxis.adaptors.blender.material_assignments import indices,verify,selection_work
from schemaxis.adaptors.blender.mesh_edits import mesh

MESH={'id':'panel','kind':'mesh','vertices':[[0,0,0],[1,0,0],[1,1,0],[0,1,0],[2,0,0],[2,1,0]],'faces':[[0,1,2,3],[1,4,5,2]]}
LAYOUT={'kind':'layout','id':'finish','object':'panel','slots':[{'id':'body','material':'red'},{'id':'label','material':'blue'}],'defaultSlot':'body','regions':[{'slot':'label','selection':{'kind':'faceIndices','indices':[1]}}]}
GRAPH={'red':{'filter':'material'},'blue':{'filter':'material'}}


def planned(layout=LAYOUT,objects=None,extra=()):return validate({'objects':objects or [MESH],'materialAssignments':[layout,*extra]},GRAPH)['materialAssignments']


class Materials(unittest.TestCase):
    def test_disjoint_regions_default_and_face_geometry(self):
        g=mesh(MESH['vertices'],MESH['faces'])
        for selection in [{'kind':'faceIndices','indices':[1]},{'kind':'faceBox','minimum':[1.1,-1,-1],'maximum':[3,2,1]}]:
            layout=copy.deepcopy(LAYOUT);layout['regions'][0]['selection']=selection
            self.assertEqual(indices(planned(layout)[0],'FACE',2,g),[0,1])
        layout=copy.deepcopy(LAYOUT);layout['regions'][0]['selection']={'kind':'faceNormal','direction':[0,0,1]}
        self.assertEqual(indices(planned(layout)[0],'FACE',2,g),[1,1])

    def test_empty_outside_overlap_and_wrong_domain_refuse(self):
        for selection in [{'kind':'faceIndices','indices':[2]},{'kind':'faceBox','minimum':[5,5,5],'maximum':[6,6,6]},{'kind':'characters','start':0,'end':1}]:
            layout=copy.deepcopy(LAYOUT);layout['regions'][0]['selection']=selection
            with self.subTest(selection=selection),self.assertRaises(SchemaxisError):planned(layout)
        layout=copy.deepcopy(LAYOUT);layout['regions']*=2
        with self.assertRaises(SchemaxisError):planned(layout)

    def test_text_unicode_character_range_and_type(self):
        layout=copy.deepcopy(LAYOUT);layout['regions'][0]['selection']={'kind':'characters','start':1,'end':3}
        found=planned(layout,[{'id':'panel','kind':'text','body':'Aé中Z'}])[0]
        self.assertEqual(indices(found,'CHARACTER',4),[0,1,1,0])
        for start,end in [(3,3),(4,5),(0,True)]:
            layout['regions'][0]['selection'].update(start=start,end=end)
            with self.assertRaises(SchemaxisError):planned(layout,[{'id':'panel','kind':'text','body':'Aé中Z'}])

    def test_palette_override_logical_ids_and_complete_mapping(self):
        override={'kind':'override','id':'second','object':'other','layout':'finish','slots':[{'id':'label','material':'red'},{'id':'body','material':'blue'}]}
        objects=[MESH,{'id':'other','kind':'instance','source':'panel'}]
        found=planned(objects=objects,extra=[override]);self.assertEqual(found[1]['slots'],override['slots'])
        for change in [{'layout':'absent'},{'slots':override['slots'][:1]},{'slots':[override['slots'][0]]*2}]:
            with self.subTest(change=change),self.assertRaises(SchemaxisError):planned(objects=objects,extra=[{**override,**change}])

    def test_no_raw_properties_and_roundtrip(self):
        found=validate({'objects':[MESH],'materialAssignments':[LAYOUT]},GRAPH)
        self.assertEqual(validate(found,GRAPH),found);json.dumps(schema())
        for change in [{'nativePath':'data.materials'},{'slots':[{'id':'body','material':'missing'}]},{'sourceObject':'other'}]:
            with self.subTest(change=change),self.assertRaises(SchemaxisError):planned({**LAYOUT,**change})

    def test_typed_readback_rejects_boolean_indices(self):
        spec=planned();record={'id':'finish','kind':'layout','object':'panel','sourceObject':'','nativeObject':'panel','domain':'FACE','owners':['panel'],'slots':LAYOUT['slots'],'logicalSlots':['body','label'],'links':['DATA','DATA'],'dataMaterials':['red','blue'],'indices':[0,1]}
        verify(spec,[record])
        for change in [{'indices':[False,1]},{'logicalSlots':['label','body']},{'links':['OBJECT','DATA']},{'dataMaterials':['blue','red']}]:
            with self.subTest(change=change),self.assertRaises(SchemaxisError):verify(spec,[{**record,**change}])

    def test_repeated_geometry_scan_refuses_before_selector_geometry_is_read(self):
        layout=copy.deepcopy(LAYOUT);layout['regions']=[{'slot':'label','selection':{'kind':'faceNormal','direction':[0,0,1],'angle':0,'invert':False}}]*10
        with self.assertRaises(SchemaxisError) as error:indices(layout,'FACE',100000,geometry=None)
        self.assertEqual(error.exception.fault.code,'RESOURCE_BUDGET_EXCEEDED')
        # Sparse regions charge their actual selected indices, rather than an
        # unnecessary full-domain scan; this is a meaningful allowed control.
        layout['regions']=[{'slot':'label','selection':{'kind':'faceIndices','indices':[i]}} for i in range(256)]
        self.assertEqual(selection_work(layout,100000),100256)
        values=indices(layout,'FACE',100000);self.assertEqual(values[:256],[1]*256);self.assertEqual(values[256:],[0]*(100000-256))
