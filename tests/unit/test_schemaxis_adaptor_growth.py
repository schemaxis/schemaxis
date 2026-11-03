# Copyright (C) 2026 David L F Gaden
"""Expanded CAD and mesh bridges: typed inputs, loss contracts and tamper checks."""
import copy
import json
from pathlib import Path
import struct
import tempfile
import unittest
from unittest.mock import patch
from schemaxis.core.faults import SchemaxisError
from schemaxis.adaptors.freecad.adaptor import plan as cad_plan
from schemaxis.adaptors.blender.adaptor import plan as blender_plan
from schemaxis.adaptors.blender.stl import triangle,digest,file_snapshot
from schemaxis.adaptors.blender.resources import capture,verify as verify_sources
from schemaxis.workflow import inspect_plan
from schemaxis.adaptors.registry import query


def cad(nodes,output='out'):
    return {'version':'schemaxis.freecad/1','nodes':nodes,'output':output}


def blender(nodes,meshes=None):
    return {'version':'schemaxis.blender/1','nodes':nodes,'scenes':[{'id':'main','visible':['out'],
        'meshes':meshes or [],'prepareOnly':True,'images':[{'id':'view','size':[64,64],'cameras':[{'direction':[1,-2,1]}]}]}]}


class GrowthTests(unittest.TestCase):
    def test_camera_clipping_scales_with_small_cad_geometry(self):
        from schemaxis.adaptors.blender.settings import clipping
        for diagonal in (0.001,0.043,1,1000):
            near,far=clipping(diagonal,diagonal*2)
            self.assertLess(near,diagonal*1.5)
            self.assertGreater(far,diagonal*2.5)
        self.assertGreater(clipping(1,10000)[1],10000)

    def test_cad_document_parameters_resolve_before_typed_validation(self):
        d=cad([{'id':'out','filter':'box','options':{'height':{'$document':'/dimensions/height'}}}])
        d['dimensions']={'height':24}
        self.assertEqual(cad_plan(d)['nodes'][0]['options']['height'],24)
        d['dimensions']['height']=-1
        with self.assertRaises(SchemaxisError):cad_plan(d)

    def test_polygon_rejects_crossings_duplicate_vertices_and_zero_area(self):
        for points in ([[0,0],[1,1],[0,1],[1,0]],[[0,0],[1,0],[2,0]],[[0,0],[1,0],[0,1],[0,0]],
                       [[0,0],[3,0],[3,3],[1,0],[0,3]]):
            d=cad([{'id':'p','filter':'polygon','options':{'points':points}}, {'id':'out','filter':'extrude','inputs':{'profile':'p'}}])
            with self.subTest(points=points),self.assertRaises(SchemaxisError):cad_plan(d)

    def test_cad_kinds_prevent_solid_profile_confusion(self):
        box={'id':'b','filter':'box'}
        for operation in ('extrude','revolve'):
            with self.assertRaises(SchemaxisError):cad_plan(cad([box,{'id':'out','filter':operation,'inputs':{'profile':'b'}}]))
        with self.assertRaises(SchemaxisError):cad_plan(cad([{'id':'out','filter':'polygon','options':{'points':[[0,0],[1,0],[0,1]]}}]))
        with self.assertRaises(SchemaxisError):cad_plan(cad([{'id':'out','filter':'torus','options':{'majorRadius':2,'minorRadius':3}}]))

    def test_edges_and_extrusion_require_bounded_valid_values(self):
        for operation,options in [('fillet',{'edges':[0]}),('chamfer',{'edges':[1,1]}),('fillet',{'radius':0}),('revolve',{'angle':361}),('revolve',{'axis':[0,0,0]})]:
            n={'id':'out','filter':operation,'options':options,'inputs':{'base':'b'} if operation in ('fillet','chamfer') else {'profile':'b'}}
            with self.subTest(operation=operation,options=options),self.assertRaises(SchemaxisError):cad_plan(cad([{'id':'b','filter':'box'},n]))

    def test_cross_application_examples_plan_and_discover_all_requirements(self):
        for name in ('cad-direct-to-blender','blender-mesh-workshop','blender-to-paraview'):
            d=json.loads(Path('examples/schemaxis/expanded/'+name+'.json').read_text())
            self.assertTrue(inspect_plan(d)['jobs'])
            self.assertTrue(query(d)['supported'])

    def test_blender_mesh_publications_are_counted_and_must_be_unique_meshes(self):
        nodes=[{'id':'paint','filter':'material'},{'id':'out','filter':'cube','inputs':{'material':'paint'}}]
        d=blender(nodes,['out'])
        self.assertEqual(blender_plan(d)[2]['expectedPublications'],2)
        for meshes in (['paint'],['out','out'],['missing'],[{}]):
            d['scenes'][0]['meshes']=meshes
            with self.assertRaises(SchemaxisError):blender_plan(d)

    def test_new_modifier_settings_reject_invalid_enums_ranges_and_inputs(self):
        base=[{'id':'paint','filter':'material'},{'id':'box','filter':'cube','inputs':{'material':'paint'}}]
        for operation,options in [('subdivision',{'method':'UNKNOWN'}),('voxelRemesh',{'voxelSize':0}),('weld',{'distance':-1}),('bend',{'angle':20}),('twist',{'axis':'Q'}),('weightedNormal',{'weight':101}),('shadeSmooth',{'enabled':1})]:
            d=blender(base+[{'id':'out','filter':operation,'options':options,'inputs':{'input':'box'}}])
            with self.subTest(operation=operation),self.assertRaises(SchemaxisError):blender_plan(d)
        with self.assertRaises(SchemaxisError):blender_plan(blender(base+[{'id':'out','filter':'join','inputs':{'inputs':[]}}]))
        with self.assertRaises(SchemaxisError):blender_plan(blender(base+[{'id':'out','filter':'shrinkwrap','inputs':{'input':'box'}}]))

    def test_stl_comparison_preserves_winding_but_ignores_triangle_order(self):
        p=[(0,0,0),(1,0,0),(0,1,0)]
        self.assertEqual(triangle(p),triangle(p[1:]+p[:1]))
        self.assertNotEqual(triangle(p),triangle(list(reversed(p))))
        q=[(0,0,1),(1,0,1),(0,1,1)]
        self.assertEqual(digest([triangle(p),triangle(q)]),digest([triangle(q),triangle(p)]))
        with self.assertRaises(SchemaxisError):triangle([(float('nan'),0,0),p[1],p[2]])

    def test_binary_stl_is_checked_independently_of_native_receipt(self):
        with tempfile.TemporaryDirectory() as tmp:
            p=Path(tmp)/'mesh.stl';p.write_bytes(bytes(80)+struct.pack('<I',1)+struct.pack('<12fH',0,0,1,0,0,0,1,0,0,0,1,0,0))
            self.assertEqual(file_snapshot(p),digest([triangle([(0,0,0),(1,0,0),(0,1,0)])]))
            p.write_bytes(p.read_bytes()+b'garbage')
            with self.assertRaises(SchemaxisError):file_snapshot(p)
            p.write_bytes(bytes(80)+struct.pack('<I',1000001))
            with self.assertRaises(SchemaxisError):file_snapshot(p)

    def test_native_import_scale_bounds_are_checked_before_dispatch(self):
        for scale in (0,1e-9,1e7,True):
            with self.subTest(scale=scale),self.assertRaises(SchemaxisError):
                blender_plan(blender([{'id':'out','filter':'readSTL','options':{'file':'mesh.stl','scale':scale}}]))

    def test_mesh_input_capture_detects_mutation_and_manifest_escape(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);source=root/'source.stl';source.write_bytes(b'original')
            target=root/'run';target.mkdir()
            master,selection,_=blender_plan(blender([{'id':'out','filter':'readSTL','options':{'file':str(source),'scale':0.001}}]))
            capture(master,selection,target);verify_sources(master,selection,target)
            source.write_bytes(b'changed')
            with self.assertRaises(SchemaxisError):verify_sources(master,selection,target)
            source.write_bytes(b'original')
            manifest=json.loads((target/'sources.json').read_text());manifest['out']['retained']=str(source)
            (target/'sources.json').write_text(json.dumps(manifest))
            with self.assertRaises(SchemaxisError):verify_sources(master,selection,target)
