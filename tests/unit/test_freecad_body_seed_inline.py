"""The no-Sketch seed-only envelope is exactly empty, with complete literal maps."""
import copy
import unittest
from types import SimpleNamespace
from unittest.mock import patch
from xml.etree import ElementTree as E

from schemaxis.adaptors.freecad.adaptor import _native_plan
from schemaxis.adaptors.freecad.part_reconstruction import literal_maps
from schemaxis.adaptors.freecad.source_bridge import inline_seed_history
from schemaxis.adaptors.freecad.history_copy_verify import compare_ordered
from schemaxis.adaptors.freecad.assembly_sources_native import ordered_record
from schemaxis.core.faults import SchemaxisError


def graph():
    return _native_plan({'version':'schemaxis.freecad/1','nodes':[
        {'id':'stock','filter':'importMesh','options':{'file':'examples/schemaxis/freecad-body-stock.stl','units':'mm','refine':True}},
        {'id':'part','filter':'body'},
        {'id':'seed','filter':'bodySeed','inputs':{'body':'part','source':'stock'}}],'output':'seed'})


def document():
    return E.fromstring('<Document><StringHasher saveall="0" threshold="0" count="0"/></Document>')


class InlineSeed(unittest.TestCase):
    def test_current_ordered_material_volume_counts_solids_without_clamping(self):
        for solids,expected in (([],0),([125],125),([100,25],125),([-125],-125)):
            native=SimpleNamespace(Solids=[SimpleNamespace(Volume=value) for value in solids],Orientation='Forward')
            old={'volume':1e9,'area':17,'vertices':[[1,2,3]]}
            with patch('schemaxis.adaptors.freecad.assembly_sources_native.history_record',return_value=copy.deepcopy(old)):
                record=ordered_record(native)
            self.assertEqual(record['volume'],expected)
            self.assertEqual(record['orientation'],'Forward')
            self.assertEqual(record['area'],17);self.assertEqual(record['vertices'],old['vertices'])
            self.assertEqual(old['volume'],1e9)

    def test_current_ordered_comparison_keeps_orientation_and_geometry(self):
        element={'type':'Face','valid':True,'vertices':[[0,0,0],[10,0,0],[10,10,0],[0,10,0]],
                 'faces':[['Plane',100]],'edges':[['Line',10]]*4,'counts':[0,0,1,1,4,4],
                 'volume':0,'area':100,'length':40,'bounds':[0,10,0,10,0,0],'centreOfMass':None,'orientation':'Forward'}
        source={'shapes':{'N0.Shape':{'faces':[element],'edges':[],'vertices':[]}},'references':{}}
        compare_ordered(source,copy.deepcopy(source))
        for change in ('orientation','area','vertex','nonzero-volume','missing-orientation'):
            modified=copy.deepcopy(source);target=modified['shapes']['N0.Shape']['faces'][0]
            if change=='orientation':target['orientation']='Reversed'
            elif change=='area':target['area']+=1
            elif change=='vertex':target['vertices'][0][0]+=1
            elif change=='nonzero-volume':target['volume']=1
            else:target.pop('orientation')
            with self.subTest(change=change),self.assertRaises(SchemaxisError):compare_ordered(source,modified)

    def test_empty_native_table_requires_exact_state_and_known_seed_only_graph(self):
        prepared=graph();self.assertTrue(inline_seed_history(prepared,document(),'seed','UNSUPPORTED_SOURCE'))
        for change in ('count','saveall','threshold','extra-attribute','child','text','whitespace','tail','table','duplicate'):
            root=document();hasher=root.find('StringHasher')
            if change in ('count','saveall','threshold'):hasher.set(change,'1')
            elif change=='extra-attribute':hasher.set('new','0')
            elif change=='child':E.SubElement(hasher,'String',value='inert')
            elif change in ('text','whitespace'):hasher.text='payload' if change=='text' else ' '
            elif change=='tail':hasher.tail='unbound'
            elif change=='table':E.SubElement(root,'StringHasher2',file='extra.SID')
            else:root.append(copy.deepcopy(hasher))
            with self.subTest(change=change),self.assertRaises(SchemaxisError):
                inline_seed_history(prepared,root,'seed','UNSUPPORTED_SOURCE')
        for change in ('no-seed','sketch','other-output'):
            modified=copy.deepcopy(prepared)
            if change=='no-seed':modified['partDesign']['seeds']={}
            elif change=='sketch':modified['nodes'].append({'id':'later','filter':'circle'})
            else:modified['output']='stock'
            with self.subTest(change=change),self.assertRaises(SchemaxisError):
                inline_seed_history(modified,document(),'seed','UNSUPPORTED_SOURCE')

    def test_literal_maps_bind_unused_dictionary_owner_ids_aliases_and_shadows(self):
        root=E.fromstring('<Document><ObjectData><Object name="A"><Properties>'
            '<Property name="Shape"><ElementMap2 file="a"/></Property>'
            '<Property name="Other"><ElementMap2 file="b"/><Sub shadow=";:H7,E"/></Property>'
            '</Properties></Object></ObjectData></Document>')
        def payload(unused='unused',row=';;:H7,E.0 0'):
            return ('BeginElementMap v1\n1 PostfixCount 1\n'+unused+'\n\nMapCount 1\n\n'
                    'ElementMap 1 1 1\n\nEdge\n\nChildCount 0\n\nNameCount 1\n'+row+'\n\nEndMap\n').encode()
        original={'a':payload(),'b':payload()};expected=literal_maps(original,root,{7:7})
        self.assertNotEqual(expected,literal_maps({k:payload('changed') for k in original},root,{7:7}))
        renamed=copy.deepcopy(root);renamed.find('.//Sub').set('shadow',';:H9,E')
        self.assertEqual(expected,literal_maps({k:payload(row=';;:H9,E.0 0') for k in original},renamed,{9:7}))
        for members in ({**original,'b':payload(row=';;:H7,F.0 0')},
                        {k:payload(row='$#1.0 0') for k in original},
                        {k:payload(row=';;:H8,E.0 0') for k in original},
                        {k:payload(unused='#1') for k in original}):
            with self.subTest(members=members),self.assertRaises(ValueError):literal_maps(members,root,{7:7})


if __name__=='__main__':unittest.main()
