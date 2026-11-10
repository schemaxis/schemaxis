"""Independent policy cases for the unregistered effective-shading kernel."""
import ast
import importlib.util
from pathlib import Path
import sys
from types import SimpleNamespace as NS
import unittest
from unittest.mock import patch

from schemaxis.errors import SchemaxisError


ROOT = Path(__file__).resolve().parents[2] / 'src/schemaxis/adaptors/blender'


class Material:
    library = None;is_evaluated = False
    bl_rna = NS(identifier='Material')
    def __init__(self, name):self.name = name


class World(Material):
    bl_rna = NS(identifier='World')


class Mesh:
    def __init__(self, fields=(), indices=(0,)):
        self.attributes = [NS(name=n, domain=d, data_type=t) for n, d, t in fields]
        self.polygons = [NS(material_index=i) for i in indices]
    def as_pointer(self):return id(self)


def kernel():
    spec = importlib.util.spec_from_file_location('effective_test', ROOT/'effective_shading_native.py')
    module = importlib.util.module_from_spec(spec)
    with patch.dict(sys.modules, {'bpy': NS(types=NS(Material=Material, World=World, Mesh=Mesh))}):
        spec.loader.exec_module(module)
    return module


def obj(name, owner, fields=(), data=None):
    class Object:
        is_evaluated = False;type = 'MESH'
    value = Object();value.name = name;value.data = data or Mesh(fields)
    value.as_pointer = lambda: id(value)
    value.material_slots = [NS(material=owner)]
    return value


def instance(value, parent=None, persistent=()):
    return NS(object=value, parent=parent, is_instance=parent is not None,
              persistent_id=persistent, show_self=True)


def graph(scene, layer, instances=(), mode='RENDER'):
    return NS(mode=mode, scene=scene, view_layer=layer, object_instances=instances, as_pointer=lambda: id(layer))


class EffectiveShading(unittest.TestCase):
    def setup_plan(self, *, override=None):
        module = kernel();material = Material('finish.001');world = World('sky')
        layer = NS(name='study', material_override=override, world_override=None)
        scene = NS(is_evaluated=False, view_layers={'study': layer}, world=world)
        one = obj('part', material, [('sx_temperature', 'POINT', 'FLOAT')])
        settings = [{'id': 'study', 'enabled': True, 'aovs': ['field']}]
        plan = module.EffectiveShadingPlan(scene, settings, objects={'part': one},
                   materials={'finish': material, **({'override': override} if override else {})},
                   worlds={'sky': world}, original_materials={})
        return module, plan, scene, layer, material, one

    def test_render_graph_and_all_declared_layers_are_required(self):
        _, plan, scene, layer, _, one = self.setup_plan()
        with self.assertRaises(SchemaxisError):plan.observe()
        with self.assertRaises(SchemaxisError):plan.capture_layer(layer, graph(scene, layer, [instance(one)], 'VIEWPORT'))
        plan.capture_layer(layer, graph(scene, layer, [instance(one)]))
        self.assertEqual(set(plan.observe()['owners']), {'material:finish', 'world:sky'})
        self.assertEqual(list(plan.observe()['fieldSchemas'].values()), [{'sx_temperature': ['POINT', 'FLOAT']}])
        with self.assertRaises(SchemaxisError):plan.capture_layer(layer, graph(scene, layer))

    def test_override_is_actual_field_owner_and_logical_name_survives_suffix(self):
        override = Material('clay')
        _, plan, scene, layer, original, one = self.setup_plan(override=override)
        plan.capture_layer(layer, graph(scene, layer, [instance(one)]))
        self.assertNotIn('material:finish', plan.owners)
        writer = {'id': 'tap', 'aov': 'field', 'source': {'kind': 'attribute', 'name': 'sx_temperature', 'channel': 'factor', 'missing': 'error'}}
        plan.require_fields([writer], {'tap': override})
        with self.assertRaises(SchemaxisError):plan.require_fields([writer], {'tap': original})

    def test_shared_geometry_keeps_object_palette_independence(self):
        module, _, scene, layer, first, one = self.setup_plan()
        second = Material('other');two = obj('linked', second, data=one.data)
        plan = module.EffectiveShadingPlan(scene, [{'id': 'study', 'enabled': True, 'aovs': ['field']}],
                   objects={'part': one, 'linked': two}, materials={'first': first, 'second': second},
                   worlds={'sky': scene.world}, original_materials={})
        plan.capture_layer(layer, graph(scene, layer, [instance(one), instance(two)]))
        self.assertEqual(len(plan._geometries), 1)
        self.assertEqual({r['owner'] for r in plan.rows if r['role'] == 'Material'}, {'material:first', 'material:second'})

    def test_out_of_range_face_slot_still_consumes_last_material_field(self):
        module, _, scene, layer, material, one = self.setup_plan()
        missing = obj('missing', material, data=Mesh(indices=(1, 32767)))
        settings = [{'id':'study','enabled':True,'aovs':['field']}]
        def capture():
            plan=module.EffectiveShadingPlan(scene,settings,objects={'part':one,'missing':missing},
                materials={'finish':material},worlds={'sky':scene.world},original_materials={})
            plan.capture_layer(layer,graph(scene,layer,[instance(one),instance(missing)]))
            return plan
        writer={'id':'tap','aov':'field','source':{'kind':'attribute','name':'sx_temperature','channel':'factor','missing':'error'}}
        plan=capture()
        self.assertEqual([(r['slot'],r['used']) for r in plan.rows if r['object']=='object:missing'],[(0,True)])
        with self.assertRaises(SchemaxisError) as caught:plan.require_fields([writer],{'tap':material})
        self.assertEqual(caught.exception.fault.code,'MISSING_AOV_ATTRIBUTE')
        missing.data.attributes=one.data.attributes
        capture().require_fields([writer],{'tap':material})

    def test_converted_objects_with_shared_curve_data_keep_distinct_mesh_fields(self):
        module, _, scene, layer, material, one = self.setup_plan()
        shared=NS(as_pointer=lambda:123)
        first=obj('curveA',material,data=shared);second=obj('curveB',material,data=shared)
        cleared=[]
        for item,fields in ((first,[('sx_temperature','POINT','FLOAT')]),(second,[])):
            item.type='CURVE'
            item.to_mesh=lambda *,preserve_all_data_layers,depsgraph,fields=fields:Mesh(fields)
            item.to_mesh_clear=lambda item=item:cleared.append(item.name)
        plan=module.EffectiveShadingPlan(scene,[{'id':'study','enabled':True,'aovs':['field']}],
            objects={'curveA':first,'curveB':second},materials={'finish':material},
            worlds={'sky':scene.world},original_materials={})
        plan.capture_layer(layer,graph(scene,layer,[instance(first),instance(second)]))
        self.assertEqual(len(plan._geometries),2)
        self.assertEqual(cleared,['curveA','curveB'])
        writer={'id':'tap','aov':'field','source':{'kind':'attribute','name':'sx_temperature','channel':'factor','missing':'error'}}
        with self.assertRaises(SchemaxisError) as caught:plan.require_fields([writer],{'tap':material})
        self.assertEqual(caught.exception.fault.code,'MISSING_AOV_ATTRIBUTE')

    def test_borrowed_dupli_pointer_does_not_alias_distinct_converted_sources(self):
        module, _, scene, layer, material, _ = self.setup_plan()
        shared=NS(as_pointer=lambda:123)
        first=obj('curveA',material,data=shared);second=obj('surfaceB',material,data=shared)
        wrappers=[];conversions=[]
        for source,kind,fields in ((first,'CURVE',[('sx_temperature','POINT','FLOAT')]),
                                   (second,'SURFACE',[])):
            evaluated=obj(source.name,material,data=shared)
            evaluated.is_evaluated=True;evaluated.original=source;evaluated.type=kind
            evaluated.as_pointer=lambda:987  # depsgraph iterator's reused dupli storage
            def converted(*,preserve_all_data_layers,depsgraph,fields=fields,name=source.name):
                conversions.append(name);return Mesh(fields)
            evaluated.to_mesh=converted;evaluated.to_mesh_clear=lambda:None
            item=instance(evaluated);item.is_instance=True;wrappers.append(item)
        plan=module.EffectiveShadingPlan(scene,[{'id':'study','enabled':True,'aovs':['field']}],
            objects={'curveA':first,'surfaceB':second},materials={'finish':material},
            worlds={'sky':scene.world},original_materials={})
        # Repeated occurrences of one source may share its geometry cache;
        # a different original must have an independently converted schema.
        plan.capture_layer(layer,graph(scene,layer,[wrappers[0],wrappers[0],wrappers[1]]))
        self.assertEqual(conversions,['curveA','surfaceB'])
        self.assertEqual(len(plan._geometries),2)
        writer={'id':'tap','aov':'field','source':{'kind':'attribute','name':'sx_temperature','channel':'factor','missing':'error'}}
        with self.assertRaises(SchemaxisError) as caught:plan.require_fields([writer],{'tap':material})
        self.assertEqual(caught.exception.fault.code,'MISSING_AOV_ATTRIBUTE')

    def test_required_field_on_instanced_second_owner_cannot_silently_zero(self):
        module, _, scene, layer, material, one = self.setup_plan()
        missing = obj('source', material);carrier = obj('carrier', None)
        plan = module.EffectiveShadingPlan(scene, [{'id': 'study', 'enabled': True, 'aovs': ['field']}],
                   objects={'part': one, 'source': missing, 'carrier': carrier}, materials={'finish': material},
                   worlds={'sky': scene.world}, original_materials={})
        plan.capture_layer(layer, graph(scene, layer, [instance(one), instance(missing, carrier, [3, 2147483647])]))
        writer = {'id': 'tap', 'aov': 'field', 'source': {'kind': 'attribute', 'name': 'sx_temperature', 'channel': 'factor', 'missing': 'error'}}
        with self.assertRaises(SchemaxisError) as error:plan.require_fields([writer], {'tap': material})
        self.assertEqual(error.exception.fault.code, 'MISSING_AOV_ATTRIBUTE')
        writer['source']['missing'] = 'zero';plan.require_fields([writer], {'tap': material})

    def test_wrong_type_world_and_unknown_owner_refuse(self):
        _, plan, scene, layer, material, one = self.setup_plan()
        one.data.attributes[0].data_type = 'FLOAT_COLOR'
        plan.capture_layer(layer, graph(scene, layer, [instance(one)]))
        writer = {'id': 'tap', 'aov': 'field', 'source': {'kind': 'attribute', 'name': 'sx_temperature', 'channel': 'factor', 'missing': 'error'}}
        for owner in (material, scene.world):
            with self.assertRaises(SchemaxisError):plan.require_fields([writer], {'tap': owner})
        _, plan, scene, layer, _, one = self.setup_plan()
        one.material_slots[0].material = Material('injected')
        with self.assertRaises(SchemaxisError):plan.capture_layer(layer, graph(scene, layer, [instance(one)]))

    def test_instance_budget_precedes_unbounded_rows(self):
        module, plan, scene, layer, _, one = self.setup_plan()
        module.MAX_INSTANCES = 1
        with self.assertRaises(SchemaxisError) as error:
            plan.capture_layer(layer, graph(scene, layer, [instance(one), instance(one)]))
        self.assertEqual(error.exception.fault.code, 'RESOURCE_BUDGET_EXCEEDED')


class RecursiveLayerExclusion(unittest.TestCase):
    def test_recursive_flag_propagation_and_reversed_rules(self):
        tree = ast.parse((ROOT/'render_layers_native.py').read_text())
        selected = [node for node in tree.body if isinstance(node, ast.FunctionDef)
                    and node.name in {'collection_flags', 'apply_collection_rules'}]
        namespace = {};exec(compile(ast.Module(body=selected, type_ignores=[]), 'native-layer-functions', 'exec'), namespace)
        class LC:
            def __init__(self):self.children = [];self._exclude = False;self.holdout = self.indirect_only = False
            @property
            def exclude(self):return self._exclude
            @exclude.setter
            def exclude(self, value):
                self._exclude = value
                for child in self.children:child.exclude = value
        parent, child, grandchild = LC(), LC(), LC();parent.children = [child];child.children = [grandchild]
        rows = [(('parent',), parent), (('parent','child'), child), (('parent','child','grandchild'), grandchild)]
        namespace['apply_collection_rules'](rows, [(('parent',), parent, 'exclude')])
        self.assertEqual([flag[1:] for flag in namespace['collection_flags'](rows, [(('parent',), parent, 'exclude')])], [(True,False,False)]*3)
        self.assertTrue(grandchild.exclude)
        # Author puts the child first. Parent's exclude=False must run first,
        # otherwise the recursive setter erases the child's exclusion.
        rules = [(('parent','child'), child, 'exclude'), (('parent',), parent, 'holdout')]
        namespace['apply_collection_rules'](rows, rules)
        self.assertTrue(parent.holdout);self.assertFalse(parent.exclude)
        self.assertTrue(child.exclude);self.assertTrue(grandchild.exclude)
        for item, *expected in namespace['collection_flags'](rows, rules):
            self.assertEqual([item.exclude, item.holdout, item.indirect_only], expected)


if __name__ == '__main__':unittest.main()
