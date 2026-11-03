# Copyright (C) 2026 David L F Gaden
"""Named quantity validation, independent dimensions and publication integrity."""
import copy
import json
from pathlib import Path
import unittest
from schemaxis.core.faults import SchemaxisError
from schemaxis.adaptors.freecad import measurements as m
from schemaxis.adaptors.freecad.adaptor import plan,output_files
from test_freecad_selections import box_edges


def document():
    return {'version':'schemaxis.freecad/1','nodes':[{'id':'blank','filter':'box'}],'output':'blank',
        'measurements':[{'id':'v','node':'blank','quantity':'volume'}]}


def observations():
    return {'blank':{'shape':{'valid':True,'solids':1,'volume':1000.,'area':700.,'bounds':[0,10,0,20,0,5]},
                     'centreMM':[5,10,2.5]}}


class MeasurementTests(unittest.TestCase):
    def test_units_scalar_vector_and_selected_edge_aggregates(self):
        doc=document();doc['measurements']=[{'id':q,'quantity':q,'node':'blank'} for q in m.QUANTITIES if q not in m.EDGE_QUANTITIES]
        for q in m.EDGE_QUANTITIES:
            doc['measurements'].append({'id':q,'quantity':q,'node':'blank','edges':{'where':{'parallelTo':[0,0,1]},'expect':4}})
        prepared=plan(doc);observed=observations();observed['blank']['edges']=box_edges()
        values=m.evaluate(prepared,observed)['measurements']
        for q,value,unit in [('volume',1000,'mm^3'),('surfaceArea',700,'mm^2'),('extentX',10,'mm'),
                             ('extentY',20,'mm'),('extentZ',5,'mm'),('centreOfMass',[5,10,2.5],'mm'),
                             ('totalEdgeLength',20,'mm'),('edgeCount',4,'count')]:
            self.assertEqual(values[q]['value'],value);self.assertEqual(values[q]['units'],unit)
        self.assertEqual(prepared['expectedPublications'],4)
        self.assertEqual(output_files(prepared)[3],('measurements.json','text'))

    def test_replay_rejects_altered_values_units_membership_and_readback(self):
        prepared=plan(document());observed=observations();publication=m.evaluate(prepared,observed)
        m.verify(prepared,observed,copy.deepcopy(observed),publication)
        for key,value in [('value',999),('units','kg'),('node','elsewhere'),('quantity','surfaceArea')]:
            bad=copy.deepcopy(publication);bad['measurements']['v'][key]=value
            with self.assertRaises(SchemaxisError):m.verify(prepared,observed,copy.deepcopy(observed),bad)
        altered=copy.deepcopy(observed);altered['blank']['shape']['volume']=999
        with self.assertRaises(SchemaxisError):m.verify(prepared,observed,altered,publication)
        with self.assertRaises(SchemaxisError):m.evaluate(prepared,{})
        altered=copy.deepcopy(observed);altered['blank']['centreMM'][0]=100
        with self.assertRaises(SchemaxisError):m.evaluate(prepared,altered)

    def test_invalid_measurement_intent_is_rejected_before_native_execution(self):
        for value in ([],[{'id':'v','node':'absent','quantity':'volume'}],
            [{'id':'v','node':'blank','quantity':'mass'}],
            [{'id':'v','node':'blank','quantity':'edgeCount'}],
            [{'id':'v','node':'blank','quantity':'volume','edges':[1]}],
            [{'id':'v','node':'blank','quantity':'volume'}]*2,
            [{'id':'v'+str(i),'node':'blank','quantity':'volume'} for i in range(33)]):
            doc=document();doc['measurements']=value
            with self.subTest(value=value),self.assertRaises(SchemaxisError):plan(doc)
        doc=document();doc['nodes'].insert(0,{'id':'profile','filter':'rectangle'});doc['measurements'][0]['node']='profile'
        with self.assertRaises(SchemaxisError):plan(doc)

    def test_unrequested_measurements_preserve_existing_artifact_order(self):
        doc=document();doc.pop('measurements');prepared=plan(doc)
        self.assertEqual(prepared['expectedPublications'],3)
        self.assertEqual([name for name,_ in output_files(prepared)],['model.step','model.stl','model.FCStd'])
        self.assertEqual(m.evaluate(prepared,{})['measurements'],{})
