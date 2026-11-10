"""Finite public Freestyle payload, independent of private native observations."""
import copy
import unittest
from jsonschema import Draft202012Validator

from schemaxis.adaptors.blender import npr
from schemaxis.core.faults import SchemaxisError


def payload():
    return {'styles': [{'id': 'outline', 'width': 3, 'colour': [0, 0, 1, 1]},
                       {'id': 'hidden', 'width': 2, 'colour': [1, 0, 0, 1],
                        'dash': [{'length': 7, 'gap': 3}]}],
            'layers': [{'layer': 'technical', 'lineSets': [
                {'id': 'outside', 'style': 'outline', 'edges': ['silhouette', 'border'],
                 'scope': {'kind': 'objects', 'objects': ['plate']}, 'visibility': {'kind': 'visible'}},
                {'id': 'occluded', 'style': 'hidden', 'edges': ['silhouette', 'border'],
                 'scope': {'kind': 'collection', 'collection': 'parts'}, 'visibility': {'kind': 'hidden'}}]}]}


def public(value, renderer='cycles'):
    return npr.validate_public(value, renderer=renderer, layers=['technical'], objects=['plate'],
                               collections=['parts'], materials=['finish'], kinds={'plate': 'mesh'})


class FreestyleDelivery(unittest.TestCase):
    def test_payload_is_detached_idempotent_schema_valid_and_has_no_private_version(self):
        raw = payload(); before = copy.deepcopy(raw)
        result = public(raw)
        self.assertEqual(raw, before)
        self.assertNotIn('version', result)
        self.assertEqual(public(result), result)
        validator = Draft202012Validator(npr.schema_property(public=True))
        self.assertEqual(list(validator.iter_errors(raw)), [])
        self.assertEqual(list(validator.iter_errors(result)), [])
        wrapped = npr.validate(result, layers=['technical'], objects=['plate'], collections=['parts'], materials=['finish'])
        self.assertEqual(wrapped['version'], npr.VERSION)

    def test_unqualified_catalogue_variants_refuse_in_schema_and_consumer(self):
        variants = [lambda p: p['styles'][0].update(caps='round'),
                    lambda p: p['styles'][0].update(chaining='individual'),
                    lambda p: p['styles'][0].update(sameObject=False),
                    lambda p: p['styles'][1]['dash'].append({'length': 2, 'gap': 1}),
                    lambda p: p['layers'][0].update(culling=True),
                    lambda p: p['layers'][0].update(smoothness=False),
                    lambda p: p['layers'][0]['lineSets'][0].update(edges=['crease']),
                    lambda p: p['layers'][0]['lineSets'][0].update(edgeMatch='all'),
                    lambda p: p['layers'][0]['lineSets'][0].update(invertEdges=True),
                    lambda p: p['layers'][0]['lineSets'][0].update(scope={'kind': 'all'}),
                    lambda p: p['layers'][0]['lineSets'][0]['scope'].update(invert=True)]
        validator = Draft202012Validator(npr.schema_property(public=True))
        for change in variants:
            value = payload(); change(value)
            with self.subTest(value=value):
                self.assertTrue(list(validator.iter_errors(value)))
                with self.assertRaises(SchemaxisError) as caught: public(value)
                self.assertEqual(caught.exception.fault.code, 'UNQUALIFIED_NPR_VARIANT')

    def test_engine_gate_has_no_silent_fallback(self):
        for engine in ('eevee', 'workbench', 'nativeScript', None):
            with self.subTest(engine=engine), self.assertRaises(SchemaxisError) as caught:
                public(payload(), engine)
            self.assertEqual(caught.exception.fault.code, 'UNSUPPORTED_NPR_ENGINE')

    def test_private_version_or_native_properties_cannot_be_public_authority(self):
        for field, value in (('version', npr.VERSION), ('nativeName', 'LineSet'),
                             ('rna', {'visibility': 'VISIBLE'}), ('script', 'module.py')):
            value = {**payload(), field: value}
            self.assertTrue(list(Draft202012Validator(npr.schema_property(public=True)).iter_errors(value)))
            with self.assertRaises(SchemaxisError): public(value)

    def test_material_line_colour_is_explicit_owner_wide_intent(self):
        value = payload(); value['styles'][0]['colourSource'] = 'materialLine'
        with self.assertRaises(SchemaxisError): public(value)
        value['materials'] = [{'material': 'finish', 'colour': [0, 1, 0, 1], 'priority': 9}]
        result = public(value)
        self.assertEqual(result['materials'][0]['material'], 'finish')
        self.assertEqual(result['materials'][0]['priority'], 9)
        self.assertEqual(list(Draft202012Validator(npr.schema_property(public=True)).iter_errors(result)), [])


class PublicExamplesAndOracles(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        import importlib.util
        from pathlib import Path
        cls.root = Path(__file__).resolve().parents[2]
        # Tools are installed separately from the provider; importing the public
        # qualifier must not import Blender or execute a native process.
        import sys
        folder = str(cls.root/'tools')
        if folder not in sys.path: sys.path.insert(0, folder)
        spec = importlib.util.spec_from_file_location('freestyle_delivery_oracles', cls.root/'tools/qualify_blender_freestyle.py')
        cls.tool = importlib.util.module_from_spec(spec); spec.loader.exec_module(cls.tool)

    def test_runnable_examples_match_parameterized_recipes_and_public_plan(self):
        import json
        from schemaxis.adaptors.blender.adaptor import plan
        from schemaxis.adaptors.blender.production_job import document_schema
        validator = Draft202012Validator(document_schema())
        for kind in ('plate', 'sphere'):
            with self.subTest(kind=kind):
                value = json.loads((self.root/f'examples/schemaxis/blender-freestyle-{kind}.json').read_text())
                self.assertEqual(value, self.tool.fixture(kind))
                self.assertEqual(list(validator.iter_errors(value)), [])
                master, _, _ = plan(value)
                self.assertNotIn('version', master.document['scenes'][0]['production']['npr'])
        # Exclusion is an actual layer rule, not hide_render or native names.
        plan(self.tool.fixture(excluded=True))

    def test_sphere_is_closed_oriented_and_material_partition_is_geometric(self):
        import math
        source, upper = self.tool.sphere_mesh(); vertices, faces = source['vertices'], source['faces']
        occurrences = {}
        volume = 0
        for face in faces:
            for a, b in zip(face, face[1:]+face[:1]): occurrences.setdefault(tuple(sorted((a, b))), []).append((a, b))
            for i in range(1, len(face)-1):
                a, b, c = [vertices[index] for index in (face[0], face[i], face[i+1])]
                volume += (a[0]*(b[1]*c[2]-b[2]*c[1])-a[1]*(b[0]*c[2]-b[2]*c[0])+a[2]*(b[0]*c[1]-b[1]*c[0]))/6
        self.assertTrue(all(len(value)==2 and value[0]==tuple(reversed(value[1])) for value in occurrences.values()))
        self.assertEqual(len(vertices)-len(occurrences)+len(faces), 2)
        self.assertGreater(volume, 4); self.assertLess(volume, 4*math.pi/3)
        self.assertEqual(upper, [i for i, face in enumerate(faces) if sum(vertices[v][2] for v in face)>0])
        self.assertTrue(0 < len(upper) < len(faces))

    def test_oracles_refuse_blank_and_wrong_dimensions_without_native_execution(self):
        for oracle, dimensions in ((self.tool.plate_oracle, (256, 256)), (self.tool.sphere_oracle, (320, 256))):
            with self.subTest(oracle=oracle.__name__):
                w, h = dimensions
                with self.assertRaises(AssertionError): oracle((w, h, bytes([255, 255, 255, 255])*w*h))
                with self.assertRaises(AssertionError): oracle((32, 32, bytes([255, 255, 255, 255])*32*32))
