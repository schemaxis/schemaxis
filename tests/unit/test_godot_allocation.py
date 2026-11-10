"""Offline verification of the retained scene.tscn hierarchy against the plan."""
import hashlib
import json
from pathlib import Path
import tempfile
import unittest

from schemaxis.adaptors.godot import adaptor as godot
from schemaxis.adaptors.godot.adaptor import (
    _verify, artifact_manifest, expected_basis, expected_bounds, group_bounds, plan, world_transform)
from schemaxis.adaptors.godot.scripts import ORBIT, PROJECT, WORKER
from schemaxis.core.faults import SchemaxisError

ROOT = Path(__file__).resolve().parents[2]

# Genuine Godot 4.7.2 PackedScene output for examples/schemaxis/godot-hierarchy.json.
SCENE = '''[gd_scene format=3]

[sub_resource type="StandardMaterial3D" id="StandardMaterial3D_drvgu"]
resource_name = "paint"
albedo_color = Color(0.2, 0.6, 0.9, 1)
roughness = 0.6

[sub_resource type="BoxMesh" id="BoxMesh_ulcgi"]
size = Vector3(2, 2, 4)

[sub_resource type="BoxMesh" id="BoxMesh_nxogm"]
size = Vector3(2, 2, 2)

[node name="SchemaxisScene" type="Node3D" unique_id=2128618768]

[node name="assembly" type="Node3D" parent="." unique_id=59922907]
transform = Transform3D(-8.742278e-08, -1, 0, 2, -4.371139e-08, 0, 0, 0, 1, 10, 0, 0)

[node name="arm" type="Node3D" parent="assembly" unique_id=30314520]
transform = Transform3D(0.70710677, -2.1213202, 0, 0.70710677, 2.1213202, 0, 0, 0, 1, 1, 0, 0)

[node name="block" type="MeshInstance3D" parent="assembly/arm" unique_id=1231338513]
transform = Transform3D(1, 0, 0, 0, 1, 0, 0, 0, 1, 0, 1, 0)
material_override = SubResource("StandardMaterial3D_drvgu")
mesh = SubResource("BoxMesh_ulcgi")

[node name="marker" type="MeshInstance3D" parent="assembly" unique_id=1164913658]
transform = Transform3D(1, 0, 0, 0, 1, 0, 0, 0, 1, -4, 0, 0)
material_override = SubResource("StandardMaterial3D_drvgu")
mesh = SubResource("BoxMesh_nxogm")

[node name="empty" type="Node3D" parent="." unique_id=1246581913]

[node name="view" type="Camera3D" parent="." unique_id=323624685]
transform = Transform3D(0.9438583, -0.11668264, 0.30905756, 0, 0.93554455, 0.35320866, -0.33035046, -0.33337894, 0.88302153, 15, 8, 20)
current = true
fov = 55.0
far = 1000.0
metadata/schemaxis_target = [8.0, 0.0, 0.0]

[node name="sun" type="DirectionalLight3D" parent="." unique_id=1350602502]
transform = Transform3D(0.8660254, 0.35355338, -0.35355338, 0, 0.70710677, 0.70710677, 0.5, -0.6123724, 0.6123724, 0, 0, 0)
'''


def write_json(path, value):
    path.write_text(json.dumps(value, indent=2, sort_keys=True))


def receipt(prepared, stage, pid):
    """Receipt equivalent to the native readback, derived from literal host algebra."""
    nodes = {n['id']: n for n in prepared['nodes']}
    records = {}
    for identity, node in nodes.items():
        operation, options = node['filter'], node['options']
        if operation == 'material':
            continue
        parent = node['inputs'].get('parent')
        record = {'owned': True, 'owner': '.', 'parent': parent}
        if operation in ('transformGroup', 'box'):
            origin, basis = world_transform(node, nodes)
            record.update(worldPosition=origin, worldBasis=basis, topLevel=False,
                          position=options['position'], basis=expected_basis(options))
        if operation == 'transformGroup':
            record.update({'class': 'Node3D', 'bounds': group_bounds(identity, nodes, {})})
        elif operation == 'box':
            record.update({'class': 'MeshInstance3D', 'mesh': 'BoxMesh', 'triangles': 12,
                           'bounds': expected_bounds(node, {}, nodes), 'parameters': {'size': options['size']},
                           'material': nodes[node['inputs']['material']]['options']})
        elif operation == 'camera':
            delta = [b-a for a, b in zip(options['position'], options['target'])]
            length = sum(x*x for x in delta)**0.5
            record.update({'class': 'Camera3D', 'current': True, 'position': options['position'],
                           'forward': [x/length for x in delta], 'target': options['target'],
                           **{k: options[k] for k in ('fov', 'near', 'far', 'orbit')}})
        else:
            record.update({'class': 'DirectionalLight3D', 'settings': options})
        records[identity] = record
    return {'stage': stage, 'pid': pid, 'runtime': '4.7.2-stable (official)', 'definition': prepared,
            'scene': {'nodeCount': prepared['expectedNodeCount'], 'nodes': records}}


def refresh(directory):
    """Recompute every hash manifest, as an actor editing the scene could."""
    prepared = json.loads((directory/'plan.json').read_text())
    names = ['project.godot', 'scene.tscn', 'orbit.gd', 'worker.gd']
    write_json(directory/'artifacts.json', {n: hashlib.sha256((directory/n).read_bytes()).hexdigest() for n in names})
    write_json(directory/'verification.json', {'artifacts': artifact_manifest(directory, prepared)})


def build(directory, scene=SCENE):
    source = json.loads((ROOT/'examples/schemaxis/godot-hierarchy.json').read_text())
    prepared = plan(source)
    write_json(directory/'authored.json', source)
    write_json(directory/'plan.json', prepared)
    write_json(directory/'sources.json', {})
    write_json(directory/'built.json', receipt(prepared, 'build', 101))
    write_json(directory/'reopened.json', receipt(prepared, 'reopen', 102))
    write_json(directory/'result.json', {'status': 'succeeded', 'verified': True})
    (directory/'project.godot').write_text(PROJECT)
    (directory/'orbit.gd').write_text(ORBIT)
    (directory/'worker.gd').write_text(WORKER)
    (directory/'scene.tscn').write_text(scene)
    refresh(directory)


class SceneHierarchyEvidenceTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory(); self.addCleanup(temporary.cleanup)
        self.directory = Path(temporary.name)

    def verify_scene(self, scene):
        build(self.directory, scene)
        return _verify(self.directory)

    def fault(self, scene):
        with self.assertRaises(SchemaxisError) as caught:
            self.verify_scene(scene)
        return caught.exception.fault

    def test_hidden_headers_transforms_and_root_edits_are_refused(self):
        cases = [SCENE+'\n [node name="hidden" type="Node3D" parent="."]\n',
                 SCENE+'\n[ node name="hidden" type="Node3D" parent="."]\n',
                 SCENE.replace('name="empty" type="Node3D" parent="." unique_id=1246581913]\n',
                               'name="empty" type="Node3D" parent="." unique_id=1246581913]\ntransform = Transform3D(1, 0, 0,\n 0, 1, 0, 0, 0, 1, 9, 0, 0)\n'),
                 SCENE.replace('name="SchemaxisScene" type="Node3D" unique_id=2128618768]\n',
                               'name="SchemaxisScene" type="Node3D" unique_id=2128618768]\ntransform = Transform3D(1, 0, 0, 0, 1, 0, 0, 0, 1, 9, 0, 0)\n'),
                 SCENE+'position = Vector3(9, 0, 0)\n',
                 SCENE.replace('current = true', 'current = true transform = Transform3D(1, 0, 0, 0, 1, 0, 0, 0, 1, 0, 0, 0)'),
                 SCENE.replace('fov = 55.0', 'fov = 55.0 [node name="hidden" type="Node3D" parent="."]'),
                 SCENE.replace('[node name="marker"', 'metadata/x = 1 x\n[node name="marker"'),
                 SCENE+'global_basis = Basis(2, 0, 0, 0, 2, 0, 0, 0, 2)\n']
        for index, scene in enumerate(cases):
            with self.subTest(index=index):
                directory = self.directory / str(index); directory.mkdir()
                build(directory, scene)
                with self.assertRaises(SchemaxisError): _verify(directory)

    def test_headers_cannot_hide_in_other_sections_or_multiline_strings(self):
        cases = [SCENE+'\n[editable path="empty"] [node name="stray" type="Node3D" parent="."]\ntransform = Transform3D(1,0,0,0,1,0,0,0,1,9,0,0)\n',
                 SCENE.replace('[sub_resource type="BoxMesh" id="BoxMesh_nxogm"]', '[sub_resource type="BoxMesh" id="BoxMesh_nxogm"]\nresource_name = "\n[node name=empty type=Node3D parent=.]\n;"').replace('[node name="empty" type="Node3D" parent="." unique_id=1246581913]\n',''),
                 SCENE.replace('name="empty" type="Node3D" parent="."', 'name="empty" type="Node3D" parent="." instance = ExtResource("1")')]
        for index, scene in enumerate(cases):
            with self.subTest(index=index):
                directory = self.directory / str(index); directory.mkdir()
                build(directory, scene)
                with self.assertRaises(SchemaxisError): _verify(directory)

    def test_complete_multiline_resource_values_and_strings_remain_supported(self):
        resource = '[sub_resource type="ArrayMesh" id="Mesh_x"]\n_surfaces = [{\n"name": "test",\n"vertices": PackedVector3Array(0, 0, 0, 1, 0, 0, 0, 1, 0),\n}]\nmetadata/nodes = Array[NodePath]([NodePath(".")])\nresource_name = "first\n[node name=hidden type=Node3D parent=.]\nlast"\n'
        scene = SCENE.replace('[node name="SchemaxisScene"', resource+'\n[node name="SchemaxisScene"')
        self.assertTrue(self.verify_scene(scene)['verified'])

    def test_genuine_native_scene_verifies(self):
        self.assertTrue(self.verify_scene(SCENE)['verified'])

    def test_reparented_scene_with_refreshed_manifests_is_rejected(self):
        # Receipts and hashes are internally consistent; only the saved topology lies.
        for old, new in [('name="arm" type="Node3D" parent="assembly"', 'name="arm" type="Node3D" parent="."'),
                         ('parent="assembly/arm"', 'parent="assembly"'),
                         ('parent="assembly" unique_id=1164913658', 'parent="empty" unique_id=1164913658')]:
            with self.subTest(old=old):
                fault = self.fault(SCENE.replace(old, new))
                self.assertEqual(fault.code, 'VERIFICATION_FAILED')
                self.assertTrue(fault.location.endswith('scene.tscn'), fault.location)
                self.assertIn('parent', fault.message)

    def test_moved_retyped_added_or_removed_nodes_are_rejected(self):
        shifted = SCENE.replace('1, 0, 0, 0, 1, 0, 0, 0, 1, -4, 0, 0)', '1, 0, 0, 0, 1, 0, 0, 0, 1, -4, 0.5, 0)')
        cases = {
            'local position': shifted,
            'local transform basis': SCENE.replace('-2.1213202', '-2.5'),
            'node type': SCENE.replace('name="empty" type="Node3D"', 'name="empty" type="Node3D2D"'),
            'camera direction': SCENE.replace('0.30905756', '-0.30905756'),
            'node membership': SCENE.replace('[node name="empty" type="Node3D" parent="." unique_id=1246581913]\n', ''),
            'ownership or membership attribute owner': SCENE.replace(
                'parent="assembly" unique_id=1164913658', 'parent="assembly" owner="arm" unique_id=1164913658'),
            'ownership or membership attribute instance': SCENE.replace(
                'name="empty" type="Node3D"', 'name="empty" type="Node3D" instance=ExtResource("1")'),
            'root node': SCENE.replace('name="SchemaxisScene"', 'name="Other"'),
        }
        cases['node membership extra'] = SCENE+'\n[node name="stray" type="Node3D" parent="."]\n'
        for expected, scene in cases.items():
            with self.subTest(expected=expected):
                directory = self.directory/expected.replace(' ', '-')
                directory.mkdir()
                build(directory, scene)
                with self.assertRaises(SchemaxisError) as caught: _verify(directory)
                self.assertEqual(caught.exception.fault.code, 'VERIFICATION_FAILED')
                self.assertIn(expected.split(' extra')[0], caught.exception.fault.message)
                self.assertIn('scene.tscn', caught.exception.fault.location)
                self.assertIn('fresh directory', caught.exception.fault.recovery)

    def test_malformed_scene_is_distinct_from_contradiction(self):
        cases = [SCENE.replace('[gd_scene format=3]', 'not a scene'),
                 SCENE.replace('transform = Transform3D(1, 0, 0, 0, 1, 0, 0, 0, 1, 0, 1, 0)', 'transform = Transform3D(1, 0, 0)'),
                 SCENE.replace('Transform3D(1, 0, 0, 0, 1, 0, 0, 0, 1, 0, 1, 0)', 'Transform3D(1, 0, 0, 0, 1, 0, 0, 0, 1, 0, nan, 0)'),
                 SCENE+'\n[node name="second" type="Node3D"]\n', SCENE+'[node type="Node3D" parent="."]\n',
                 SCENE.replace('name="arm"', 'name="assembly"')]
        for index, scene in enumerate(cases):
            with self.subTest(index=index):
                directory = self.directory/str(index); directory.mkdir()
                build(directory, scene)
                with self.assertRaises(SchemaxisError) as caught: _verify(directory)
                self.assertEqual(caught.exception.fault.code, 'SCENE_MALFORMED')
                self.assertRegex(caught.exception.fault.location, r'scene\.tscn:\d+')
        directory = self.directory/'binary'; directory.mkdir(); build(directory)
        (directory/'scene.tscn').write_bytes(b'\xff\xfe'); refresh(directory)
        with self.assertRaises(SchemaxisError) as caught: _verify(directory)
        self.assertEqual(caught.exception.fault.code, 'SCENE_MALFORMED')
        build(directory)
        # Large embedded resources were already admitted; no new 4MiB whole-scene cap.
        large = '[sub_resource type="ArrayMesh" id="Large"]\n_surfaces = [{"data": PackedByteArray('+('0, '*1500000)+'0)}]\n'
        (directory/'scene.tscn').write_text(SCENE.replace('[node name="SchemaxisScene"',large+'\n[node name="SchemaxisScene"'))
        refresh(directory)
        self.assertTrue(_verify(directory)['verified'])

    def test_long_comment_or_blank_continuation_cannot_invent_structure(self):
        for prefix in (';'+'x'*65535, ' '*65536):
            with self.subTest(prefix=prefix[:1]):
                scene = SCENE.replace('[node name="empty"', prefix+'[node name="empty"')
                self.assertEqual(self.fault(scene).code, 'RESOURCE_LIMIT')

    def test_oversized_padded_tag_is_refused_without_regex_search(self):
        scene = SCENE+'\n[node'+(' '*1000000)+'name="]"]\n'
        fault = self.fault(scene)
        self.assertEqual(fault.code, 'RESOURCE_LIMIT')

    def test_long_declared_hierarchy_paths_fit_the_tag_guard(self):
        parts = ['[gd_scene format=3]', '[node name="SchemaxisScene" type="Node3D"]']
        parents = []
        for i in range(125):
            identity = f'g{i:03d}'+('x'*60)
            parts.append(f'[node name="{identity}" type="Node3D" parent="{"/".join(parents) or "."}"]')
            parents.append(identity)
        root, nodes = godot.tscn.inspect(('\n'.join(parts)+'\n').encode())
        self.assertEqual(len(nodes), 126)

    def test_unrefreshed_edit_still_fails_the_artifact_digest(self):
        build(self.directory)
        (self.directory/'scene.tscn').write_text(SCENE.replace('parent="assembly/arm"', 'parent="."'))
        with self.assertRaises(SchemaxisError) as caught: _verify(self.directory)
        self.assertIn('Artifact changed: scene.tscn', caught.exception.fault.message)

    def test_flat_root_children_default_to_identity_transform(self):
        scene = ('[gd_scene format=3]\n\n[node name="SchemaxisScene" type="Node3D"]\n\n'
                 '[node name="pad" type="MeshInstance3D" parent="."]\n')
        root, saved = godot.tscn.inspect(scene.encode())
        self.assertEqual((root, saved['pad']['parent'], saved['pad']['transform'][9:]),
                         ('SchemaxisScene', '.', [0.0, 0.0, 0.0]))
