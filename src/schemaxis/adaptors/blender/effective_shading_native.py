"""Bounded layer-effective shader ownership from a fresh native construction.

Production supplies bindings as native handles returned by the
trusted constructors/imports, never names/tags supplied by a saved packet. A
fresh plan nominates the canonical owner/occurrence set for submitted readback.
One depsgraph walk per layer replaces writer-times-object geometry conversion.
"""
import hashlib
import json
import bpy

from schemaxis.errors import fail


MAX_INSTANCES = 16384
MAX_ROWS = 65536
MAX_GEOMETRIES = 4096
MAX_FACES = 1000000
MAX_ATTRIBUTES = 65536
MAX_BYTES = 16 * 1024 * 1024
GEOMETRY = {'MESH', 'CURVE', 'SURFACE', 'FONT', 'META', 'CURVES', 'POINTCLOUD', 'VOLUME'}
# These are the initial mesh-field contracts, to be qualified at fixed 5.2.3.
# Unsupported domains/types refuse rather than letting Attribute return zero.
FIELD_TYPES = {'factor': {'FLOAT', 'INT', 'BOOLEAN'},
               'alpha': {'FLOAT_COLOR', 'BYTE_COLOR'},
               'colour': {'FLOAT_COLOR', 'BYTE_COLOR'},
               'vector': {'FLOAT_VECTOR', 'FLOAT2'}}
FIELD_DOMAINS = {'POINT', 'FACE', 'CORNER'}


def original(value):
    return value.original if value is not None and value.is_evaluated else value


class EffectiveShadingPlan:
    def __init__(self, scene, layers, *, objects, materials, worlds, original_materials,
                 fixed_world=None):
        self.scene = scene;self.layer_specs = layers
        self.object_ids = {};self.owner_aliases = {};self.owners = {};self.rows = []
        self.layer_aovs = {};self._geometries = {};self._faces = 0;self._attributes = 0
        self.captured_layers = set()
        self._instances = 0;self._bytes = 0;self.field_schemas = {}
        def object_binding(key, obj):
            obj = original(obj)
            previous = self.object_ids.get(obj)
            if previous is not None and previous != key:
                fail('AMBIGUOUS_RENDER_OWNER', 'one Object has conflicting logical identities', key)
            if previous is None:self._charge(key)
            self.object_ids[obj] = key
        for key, obj in objects.items():object_binding('object:' + key, obj)
        for key, owner in materials.items():self._alias('material:' + key, owner, 'Material')
        for key, owner in worlds.items():self._alias('world:' + key, owner, 'World')
        if fixed_world is not None:self._alias('world:@fixed', fixed_world, 'World')
        for asset, members in original_materials.items():
            for source_name, source in members.items():
                # JSON-style component escaping avoids separator collisions.
                key = 'captured:' + json.dumps([asset, source_name], separators=(',', ':'))
                object_binding(key, source['object'])
                for slot, (_, owner) in enumerate(source['slots']):
                    if owner is not None:self._alias(key + ':' + str(slot), owner, 'Material')
        for layer_spec in layers:
            if not layer_spec['enabled']:continue
            layer = scene.view_layers.get(layer_spec['id'])
            if layer is None:fail('UNKNOWN_REFERENCE', 'render layer is absent', layer_spec['id'])
            self.layer_aovs[layer_spec['id']] = frozenset(layer_spec['aovs'])

    def capture_layer(self, layer, graph):
        """Consume a caller's actual render graph, never a viewport substitute.

        Graphs are borrowed inside native render evaluation, not kept alive
        across layers. Public writers capture and qualify this lifecycle at the
        fixed runtime; a viewport graph never substitutes for render evaluation.
        """
        if (graph.mode != 'RENDER' or original(graph.scene) != self.scene
                or graph.view_layer.name != layer.name or layer.name not in self.layer_aovs):
            fail('VERIFICATION_FAILED', 'effective shading needs the declared layer actual render depsgraph', layer.name)
        if layer.name in self.captured_layers:
            fail('DUPLICATE_RENDER_LAYER', 'effective shading captured the same render layer twice', layer.name)
        self._layer(layer, graph)
        self.captured_layers.add(layer.name)

    def complete(self):
        if self.captured_layers != set(self.layer_aovs):
            fail('VERIFICATION_FAILED', 'effective shading has not captured every declared rendered layer',
                 missing=sorted(set(self.layer_aovs) - self.captured_layers))

    def _alias(self, identity, owner, kind):
        owner = original(owner)
        expected = bpy.types.Material if kind == 'Material' else bpy.types.World
        if not isinstance(owner, expected) or owner.library is not None:
            fail('TYPE_MISMATCH', 'effective shader binding requires its local native owner', identity)
        aliases = self.owner_aliases.setdefault(owner, set())
        if identity not in aliases:self._charge(identity)
        aliases.add(identity)

    def _charge(self, value):
        self._bytes += len(json.dumps(value, separators=(',', ':'), allow_nan=False).encode())
        if self._bytes > MAX_BYTES:
            fail('RESOURCE_BUDGET_EXCEEDED', 'effective shader plan exceeds 16 MiB')

    def _owner(self, owner):
        owner = original(owner)
        if owner is None:return None
        aliases = self.owner_aliases.get(owner)
        if not aliases:
            fail('UNKNOWN_RENDER_OWNER', 'effective shader has no trusted constructor/import binding',
                 owner.name)
        identity = min(aliases)
        self.owners[identity] = owner
        return identity

    def _object(self, obj):
        identity = self.object_ids.get(original(obj))
        if identity is None:
            fail('UNKNOWN_RENDER_OWNER', 'evaluated render Object has no trusted source binding', obj.name)
        return identity

    def _geometry(self, obj, graph):
        # Mesh datablocks can share geometry while keeping Object palettes.
        # Converted geometry is source-specific: distinct original Objects can
        # share Curve data while to_mesh exposes different fields. The dupli
        # iterator reuses borrowed Object storage, so use its stable original.
        converted = obj.type in {'CURVE', 'SURFACE', 'FONT', 'META'}
        key = (graph.view_layer.name, 'object' if converted else 'data',
               original(obj).as_pointer() if converted else obj.data.as_pointer())
        if key in self._geometries:return self._geometries[key]
        if len(self._geometries) >= MAX_GEOMETRIES:
            fail('RESOURCE_BUDGET_EXCEEDED', 'effective shading exceeds 4096 evaluated geometries')
        data = obj.to_mesh(preserve_all_data_layers=True, depsgraph=graph) if converted else obj.data
        try:
            attributes = getattr(data, 'attributes', ())
            self._attributes += len(attributes)
            if self._attributes > MAX_ATTRIBUTES:
                fail('RESOURCE_BUDGET_EXCEEDED', 'effective shader attribute headers exceed 65536')
            fields = {attribute.name: [attribute.domain, attribute.data_type] for attribute in attributes}
            if isinstance(data, bpy.types.Mesh):
                self._faces += len(data.polygons)
                if self._faces > MAX_FACES:
                    fail('RESOURCE_BUDGET_EXCEEDED', 'effective shading exceeds one million evaluated faces')
                used = frozenset(face.material_index for face in data.polygons)
                component = 'mesh'
            else:
                # Other components stay visible, and missing=error will refuse
                # until their actual shader field domains are qualified.
                used = frozenset(range(len(obj.material_slots)))
                component = obj.type.lower()
            encoded = json.dumps(fields, sort_keys=True, separators=(',', ':')).encode()
            schema = hashlib.sha256(encoded).hexdigest()
            if schema not in self.field_schemas:
                self._charge(fields);self.field_schemas[schema] = fields
            result = component, schema, used
            self._geometries[key] = result
            return result
        finally:
            if converted:obj.to_mesh_clear()

    def _row(self, value):
        if len(self.rows) >= MAX_ROWS:
            fail('RESOURCE_BUDGET_EXCEEDED', 'effective shader ownership exceeds 65536 rows')
        self._charge(value)
        self.rows.append(value)

    def _layer(self, layer, graph):
        world = layer.world_override or self.scene.world
        self._row({'layer': layer.name, 'object': None, 'parent': None, 'instance': [], 'slot': None,
                   'owner': self._owner(world), 'role': 'World', 'reason': 'worldOverride' if layer.world_override else 'sceneWorld',
                   'used': True, 'component': 'world', 'fieldSchema': None})
        for instance in graph.object_instances:
            self._instances += 1
            if self._instances > MAX_INSTANCES:
                fail('RESOURCE_BUDGET_EXCEEDED', 'effective shading exceeds 16384 layer instances')
            obj = instance.object
            if obj.type not in GEOMETRY:continue
            visible = bool(instance.show_self)
            identity = self._object(obj)
            parent = self._object(instance.parent) if instance.is_instance and instance.parent else None
            persistent = list(instance.persistent_id) if instance.is_instance else []
            component, schema, used = self._geometry(obj, graph)
            slots = list(obj.material_slots)
            if len(slots) > 64:
                fail('RESOURCE_BUDGET_EXCEEDED', 'effective shader object exceeds 64 material slots', identity)
            # Cycles clamps polygon indices to the final effective slot. Keep
            # raw indices in the geometry cache and resolve them per Object,
            # so palette ownership and missing-field checks follow rendering.
            used = {min(max(index, 0), max(len(slots)-1, 0)) for index in used}
            indices = set(range(len(slots))) | used
            if not indices:indices.add(0)
            for index in sorted(indices):
                owner = layer.material_override or (slots[index].material if index < len(slots) else None)
                self._row({'layer': layer.name, 'object': identity, 'parent': parent, 'instance': persistent,
                           'slot': index, 'owner': self._owner(owner), 'role': 'Material',
                           'reason': 'materialOverride' if layer.material_override else 'slot',
                           'used': visible and index in used, 'component': component, 'fieldSchema': schema})

    def require_fields(self, writers, owners):
        self.complete()
        users = {};seen = set();checks = 0
        for row in self.rows:
            if row['owner'] is not None and row['used']:
                users.setdefault(self.owners[row['owner']], []).append(row)
        for writer in writers:
            owner = original(owners[writer['id']]);source = writer['source']
            alias = owner, writer['aov']
            if alias in seen:
                fail('DUPLICATE_AOV_WRITER', 'one actual owner may write each pass only once', writer['id'])
            seen.add(alias)
            rows = [row for row in users.get(owner, ())
                    if writer['aov'] in self.layer_aovs[row['layer']]]
            if not rows:
                fail('MISSING_AOV_OWNER', 'writer has no effective owner on a layer enabling its pass', writer['id'])
            if source['kind'] != 'attribute' or source['missing'] != 'error':continue
            for row in rows:
                checks += 1
                if checks > MAX_ROWS * 32:
                    fail('RESOURCE_BUDGET_EXCEEDED', 'effective AOV field checks exceed their bounded layer/pass product')
                field = self.field_schemas.get(row['fieldSchema'], {}).get(source['name'])
                if (row['component'] != 'mesh' or field is None
                        or field[0] not in FIELD_DOMAINS or field[1] not in FIELD_TYPES[source['channel']]):
                    fail('MISSING_AOV_ATTRIBUTE', 'required field lacks a compatible evaluated shading domain/type',
                         writer['id'], layer=row['layer'], object=row['object'],
                         attribute=source['name'], observed=field, component=row['component'])

    def observe(self):
        self.complete()
        # Names here are only bindings nominated by the fresh plan. A current
        # file must resolve exactly these trusted identities and compare the
        # same complete rows, plus full shader/input fidelity, before reuse.
        return {'fieldSchemas': dict(sorted(self.field_schemas.items())),
                'owners': {identity: {'kind': owner.bl_rna.identifier, 'name': owner.name,
                                     'aliases': sorted(self.owner_aliases[owner])}
                           for identity, owner in sorted(self.owners.items())},
                'rows': sorted(self.rows, key=lambda row: (row['layer'], row['object'] or '',
                                                          row['parent'] or '', row['instance'],
                                                          -1 if row['slot'] is None else row['slot']))}
