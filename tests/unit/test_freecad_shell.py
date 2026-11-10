"""Uniform wall intent, exact opening selectors and native history constraints."""
import copy
import unittest
from schemaxis.adaptors.freecad import adaptor,shell
from schemaxis.core.faults import SchemaxisError


def design(options=None):
    return {'version':'schemaxis.freecad/1','nodes':[
        {'id':'body','filter':'body'},
        {'id':'outline','filter':'rectangle','options':{'width':40,'height':30},'inputs':{'body':'body'}},
        {'id':'stock','filter':'pad','options':{'length':20},'inputs':{'body':'body','profile':'outline'}},
        {'id':'housing','filter':'shell','options':{'openings':[{'face':'top'}],**(options or {})},'inputs':{'base':'stock'}}],
        'output':'housing'}


class UniformWalls(unittest.TestCase):
    def fault(self,d,code):
        with self.assertRaises(SchemaxisError) as error:adaptor.plan(d)
        self.assertEqual(error.exception.fault.code,code)

    def test_wall_defaults_and_current_body_history_are_explicit(self):
        d=design();before=copy.deepcopy(d);p=adaptor.plan(d);self.assertEqual(d,before)
        self.assertEqual(p['nodes'][-1]['options'],{'openings':[{'face':'top','position':'outermost'}],'thickness':2,'side':'inward','corners':'sharp','intersectionHandling':False})
        self.assertEqual(p['partDesign']['bodies']['body']['tip'],'housing');self.assertEqual(p['partDesign']['owners']['housing'],'body')

    def test_duplicates_and_attachment_only_fields_are_rejected(self):
        self.fault(design({'openings':[{'face':'top'},{'face':'top'}]}),'INVALID_SHELL_OPENINGS')
        self.fault(design({'openings':[{'face':'top','offset':3}]}),'UNKNOWN_ARGUMENT')
        self.fault(design({'openings':[]}),'INVALID_ARGUMENT')

    def test_dimension_and_native_property_escape_refused(self):
        self.fault(design({'thickness':0}),'INVALID_ARGUMENT')
        self.fault(design({'nativeType':'PartDesign::Thickness'}),'UNKNOWN_ARGUMENT')
        self.fault(design({'mode':'Pipe'}),'UNKNOWN_ARGUMENT')

    def test_shared_wall_driver_lowers_to_native_value(self):
        d=design();d['parameters']={'wall':{'kind':'length','value':3,'minimum':2,'maximum':4}}
        d['nodes'][-1]['drive']={'thickness':{'terms':{'wall':1}}};p=adaptor.plan(d)
        self.assertEqual(p['nodes'][-1]['options']['thickness'],3)
        from schemaxis.adaptors.freecad.parameters import expected_expressions
        self.assertEqual(expected_expressions(p['nodes'][-1]),{'Value':{'terms':{'wall':1},'offset':0}})

    def test_openings_resolve_unique_extreme_faces_without_index_input(self):
        inventory=[{'index':1,'planar':True,'normal':[0,0,1],'centre':[0,0,20],'area':1200},
            {'index':2,'planar':True,'normal':[0,0,-1],'centre':[0,0,0],'area':1200}]
        p=adaptor.plan(design({'openings':[{'face':'top'},{'face':'bottom'}]}));self.assertEqual(shell.selected(p['nodes'][-1]['options'],inventory,'housing'),['Face1','Face2'])
        inventory.append({'index':3,'planar':True,'normal':[0,0,1],'centre':[5,0,20],'area':20})
        with self.assertRaises(SchemaxisError) as error:shell.selected(p['nodes'][-1]['options'],inventory,'housing')
        self.assertEqual(error.exception.fault.code,'AMBIGUOUS_SELECTION')


if __name__=='__main__':unittest.main()
