"""Native Freestyle compiler/readback using trusted logical handle maps only.

This production-owned kernel does not load projects, render, or choose source owners.
The production owner must reconstruct these maps from fresh authoritative inputs,
including effective layer/occurrence/material ownership, before submitted open.
"""
import math
import bpy

from schemaxis.errors import fail
from . import npr


PREFIX = '__schemaxis_npr_'
PRESENTATION = {'name', 'name_full', 'users', 'use_fake_user', 'use_extra_user',
                'is_embedded_data', 'is_missing', 'is_runtime_data', 'is_evaluated',
                'is_library_indirect', 'is_editable', 'tag', 'session_uid'}


def _check(checkpoint):
    if checkpoint:
        checkpoint()


def _reject(message, where='npr'):
    fail('VERIFICATION_FAILED', message, where)


def _scalar(owner):
    """Read every primitive setting of a reviewed native class, never author RNA.

    Pointer/collection closure is handled explicitly by each owning record below.
    Native names are only locators derived from the installed finite compiler.
    """
    result = {}
    for prop in owner.bl_rna.properties:
        key = prop.identifier
        if key == 'rna_type' or key in PRESENTATION:
            continue
        if prop.type not in {'BOOLEAN', 'INT', 'FLOAT', 'STRING', 'ENUM'}:
            continue
        value = getattr(owner, key)
        if getattr(prop, 'is_array', False):
            value = list(value)
        elif isinstance(value, set):
            value = sorted(value)
        values = value if isinstance(value, list) else [value]
        if any(type(x) not in (bool, int, float, str) or type(x) is float and not math.isfinite(x) for x in values):
            _reject('Freestyle primitive setting is outside finite JSON', key)
        result[key] = value
    return result


def _ramp(ramp):
    if len(ramp.elements) > 32:
        _reject('Freestyle colour ramp exceeds thirty-two elements')
    return {'settings': _scalar(ramp), 'elements': [
        {'position': float(x.position), 'colour': list(x.color)} for x in ramp.elements]}


def _style(style):
    if (style.bl_rna.identifier != 'FreestyleLineStyle' or style.library is not None
            or style.animation_data is not None or style.node_tree is not None
            or style.use_nodes or any(slot is not None for slot in style.texture_slots)
            or list(style.keys())):
        _reject('Freestyle style needs local, nonanimated parameter-editor data without nodes/textures/custom code')
    if style.alpha_modifiers or style.thickness_modifiers:
        _reject('Freestyle alpha/thickness modifiers need a typed contract')
    geometry = list(style.geometry_modifiers)
    if len(geometry) != 1 or geometry[0].type != 'SAMPLING':
        _reject('Freestyle geometry must retain the single fixed SDK Sampling modifier')
    colours = []
    if len(style.color_modifiers) > 1:
        _reject('Freestyle colour modifier inventory differs')
    for modifier in style.color_modifiers:
        if modifier.type != 'MATERIAL' or modifier.material_attribute != 'LINE' or modifier.use_ramp:
            _reject('Freestyle colour modifier is outside the material-line contract')
        colours.append({'type': modifier.bl_rna.identifier, 'settings': _scalar(modifier),
                        'ramp': _ramp(modifier.color_ramp)})
    return {'settings': _scalar(style), 'geometry': [
        {'type': x.bl_rna.identifier, 'settings': _scalar(x)} for x in geometry], 'colourModifiers': colours}


def _names(plan):
    styles = {spec['id']: PREFIX+'style_'+str(i) for i, spec in enumerate(plan['styles'])}
    sets = {(layer['layer'], spec['id']): PREFIX+'set_'+str(i)+'_'+str(j)
            for i, layer in enumerate(plan['layers']) for j, spec in enumerate(layer['lineSets'])}
    scopes = {(layer['layer'], spec['id']): PREFIX+'scope_'+str(i)+'_'+str(j)
              for i, layer in enumerate(plan['layers']) for j, spec in enumerate(layer['lineSets'])
              if spec['scope']['kind'] == 'objects'}
    return styles, sets, scopes


def _collection_scope(root, objects, checkpoint):
    """Bind the entire selected group, including otherwise-unused child groups.

    Mesh identity comes from the trusted logical handle map. Unmapped faced
    owners require the production owner's effective occurrence closure; native
    object names cannot silently become an authored source-selection authority.
    """
    pending = [(root, ())]; records = []; links = 0
    while pending:
        collection, path = pending.pop()
        _check(checkpoint)
        if len(path) > 128 or len(records) >= 4096 or collection.library is not None:
            fail('RESOURCE_BUDGET_EXCEEDED', 'Freestyle collection scope exceeds bounded local hierarchy')
        members = []
        for obj in collection.objects:
            links += 1
            if links > 4096:
                fail('RESOURCE_BUDGET_EXCEEDED', 'Freestyle collection scope exceeds4096 member links')
            logical = sorted(key for key, owner in objects.items() if owner == obj)
            if obj.type == 'MESH' and not logical:
                fail('UNSUPPORTED_NPR_SCOPE', 'Collection contains a faced owner absent from effective logical closure')
            members.append({'logical': logical, 'type': obj.type,
                            'nonGeometricLocator': obj.name if not logical else ''})
        children = sorted(collection.children, key=lambda child: child.name)
        records.append({'path': list(path), 'settings': _scalar(collection),
                        'members': sorted(members, key=lambda item: (item['logical'], item['type'], item['nonGeometricLocator'])),
                        'children': [child.name for child in children]})
        pending.extend((child, path+(child.name,)) for child in reversed(children))
    return records


def _context(plan, scene, layers, objects, collections, materials, checkpoint):
    if bpy.app.version != (5, 2, 3):
        fail('UNSUPPORTED_RUNTIME', 'This Freestyle kernel needs qualified Blender5.2.3')
    if scene.render.engine not in {'CYCLES', 'BLENDER_EEVEE_NEXT'}:
        fail('UNSUPPORTED_NPR_ENGINE', 'Freestyle engine rendering needs separate native qualification')
    canonical = npr.validate({key: plan[key] for key in npr.OPTIONS if key in plan},
                             layers=layers, objects=objects, collections=collections, materials=materials)
    if canonical != plan:
        _reject('Freestyle plan differs from complete typed intent')
    if len(scene.objects) > 4096:
        fail('RESOURCE_BUDGET_EXCEEDED', 'Freestyle exceeds4096 scene objects')
    faces = vertices = 0
    # Freestyle consumes the complete view map, including occluding objects.
    # General modifier/instance expansion must also pass the production budget;
    # until its effective occurrence closure is integrated this kernel refuses it.
    for obj in scene.objects:
        _check(checkpoint)
        if obj.type not in {'MESH', 'CAMERA', 'LIGHT', 'EMPTY'} or obj.instance_type != 'NONE':
            fail('UNSUPPORTED_NPR_GEOMETRY', 'Freestyle occurrence/curve scopes need qualified effective scene closure', obj.name)
        if obj.type == 'MESH':
            if obj.modifiers:
                fail('UNSUPPORTED_NPR_GEOMETRY', 'Evaluated Freestyle modifiers need the shared occurrence/geometry budget', obj.name)
            faces += len(obj.data.polygons); vertices += len(obj.data.vertices)
            if faces > 100000 or vertices > 200000:
                fail('RESOURCE_BUDGET_EXCEEDED', 'Freestyle exceeds100000 faces or200000 vertices')
    for spec in plan['layers']:
        if layers[spec['layer']] not in list(scene.view_layers):
            _reject('Logical Freestyle layer is outside the selected scene')
        for item in spec['lineSets']:
            scope = item['scope']
            if scope['kind'] == 'objects':
                selected = [objects[x] for x in scope['objects']]
                if len(set(selected)) != len(selected):
                    fail('ALIASED_NPR_OWNER', 'Distinct logical object references alias one Freestyle owner')
                if any(obj.type != 'MESH' or obj not in list(scene.objects) for obj in selected):
                    fail('UNSUPPORTED_NPR_GEOMETRY', 'Object-scoped Freestyle needs actual faced Mesh owners')
    selected_materials = [materials[spec['material']] for spec in plan['materials']]
    if len(set(selected_materials)) != len(selected_materials):
        fail('ALIASED_NPR_OWNER', 'Material line settings are owner-wide; duplicate logical owner aliases refuse')
    if any(mat.library is not None for mat in selected_materials):
        fail('UNSUPPORTED_NPR_OWNER', 'Material line overlays require admitted local owners')


def apply(plan, *, scene, layers, objects, collections, materials, checkpoint=None):
    """Construct only on a fresh authoritative scene, without touching visibility."""
    _context(plan, scene, layers, objects, collections, materials, checkpoint)
    if scene.render.use_freestyle:
        _reject('Construct Freestyle once on the fresh authoritative scene')
    style_names, set_names, scope_names = _names(plan)
    if any(value in bpy.data.linestyles for value in style_names.values()) or any(
            value in bpy.data.collections for value in scope_names.values()):
        fail('NPR_NAME_COLLISION', 'Fresh Freestyle compiler names already exist')
    # Complete preflight above precedes writes. Unlinked helper collections are
    # essential: scene linkage could re-include an otherwise excluded object.
    scene.render.use_freestyle = True
    scene.render.line_thickness_mode = 'ABSOLUTE'
    scene.render.line_thickness = 1
    styles = {}
    for spec in plan['styles']:
        _check(checkpoint)
        style = bpy.data.linestyles.new(style_names[spec['id']])
        style.color = spec['colour'][:3]; style.alpha = spec['colour'][3]
        style.thickness = spec['width']; style.thickness_position = 'CENTER'
        style.caps = spec['caps'].upper(); style.use_chaining = spec['chaining'] == 'plain'
        style.chaining = 'PLAIN'; style.use_same_object = spec['sameObject']
        style.use_dashed_line = bool(spec['dash'])
        for index in range(3):
            segment = spec['dash'][index] if index < len(spec['dash']) else {'length': 0, 'gap': 0}
            setattr(style, 'dash'+str(index+1), segment['length'])
            setattr(style, 'gap'+str(index+1), segment['gap'])
        if spec['colourSource'] == 'materialLine':
            modifier = style.color_modifiers.new('Material line colour', 'MATERIAL')
            modifier.material_attribute = 'LINE'; modifier.use_ramp = False
        styles[spec['id']] = style
    active = {layers[item['layer']] for item in plan['layers']}
    for layer in scene.view_layers:
        layer.use_freestyle = layer in active
    for layer_spec in plan['layers']:
        _check(checkpoint)
        settings = layers[layer_spec['layer']].freestyle_settings
        settings.mode = 'EDITOR'; settings.use_culling = layer_spec['culling']
        settings.use_smoothness = layer_spec['smoothness']; settings.crease_angle = layer_spec['creaseAngle']
        features = {edge for item in layer_spec['lineSets'] for edge in item['edges']}
        settings.use_material_boundaries = 'materialBoundary' in features
        settings.use_ridges_and_valleys = 'ridgeValley' in features
        settings.use_suggestive_contours = 'suggestiveContour' in features
        if len(settings.modules):
            _reject('Fresh Freestyle settings unexpectedly contain script modules')
        for item in list(settings.linesets):
            settings.linesets.remove(item)
        for spec in layer_spec['lineSets']:
            key = (layer_spec['layer'], spec['id'])
            item = settings.linesets.new(set_names[key]); item.linestyle = styles[spec['style']]
            item.select_by_visibility = True; item.visibility = spec['visibility']['kind'].upper()
            item.qi_start = spec['visibility'].get('minimum', 0); item.qi_end = spec['visibility'].get('maximum', 0)
            item.select_by_edge_types = True; item.edge_type_combination = {'any': 'OR', 'all': 'AND'}[spec['edgeMatch']]
            item.edge_type_negation = 'EXCLUSIVE' if spec['invertEdges'] else 'INCLUSIVE'
            for logical, native in npr.EDGES.items():
                setattr(item, 'select_'+native, logical in spec['edges'])
                setattr(item, 'exclude_'+native, False)
            item.select_by_face_marks = False; item.select_by_image_border = False
            scope = spec['scope']; item.select_by_collection = scope['kind'] != 'all'
            if scope['kind'] == 'objects':
                collection = bpy.data.collections.new(scope_names[key])
                # The fixed SDK's LineSet.collection pointer does not retain an
                # otherwise unlinked Collection across save/reopen. Persist the
                # owned helper explicitly without linking it into visibility.
                collection.use_fake_user = True
                for identity in scope['objects']:
                    collection.objects.link(objects[identity])
                item.collection = collection
            elif scope['kind'] == 'collection':
                item.collection = collections[scope['collection']]
            else:
                item.collection = None
            item.collection_negation = 'EXCLUSIVE' if scope.get('invert', False) else 'INCLUSIVE'
    for spec in plan['materials']:
        # These writes are deliberately Material-owner-wide, affecting all users.
        materials[spec['material']].line_color = spec['colour']
        materials[spec['material']].line_priority = spec['priority']
    _check(checkpoint)
    return observe(plan, scene=scene, layers=layers, objects=objects, collections=collections,
                   materials=materials, checkpoint=checkpoint)


def observe(plan, *, scene, layers, objects, collections, materials, checkpoint=None):
    """Complete closed state for comparison with a fresh expected construction.

    This snapshot is evidence, never the expected authority by itself. The caller
    must compare against an independently reconstructed complete expected state.
    """
    _context(plan, scene, layers, objects, collections, materials, checkpoint)
    style_names, set_names, scope_names = _names(plan)
    styles = {}
    for logical, native in style_names.items():
        owner = bpy.data.linestyles.get(native)
        if owner is None:
            _reject('Compiled reusable Freestyle style is missing', logical)
        styles[logical] = _style(owner)
    result = {'version': npr.VERSION, 'scene': {'enabled': scene.render.use_freestyle,
        'widthMode': scene.render.line_thickness_mode, 'widthMultiplier': scene.render.line_thickness},
        'styles': styles, 'layers': {}, 'materials': {}}
    declared = {item['layer']: item for item in plan['layers']}
    for layer in scene.view_layers:
        if layer not in [layers[key] for key in declared] and layer.use_freestyle:
            _reject('Undeclared layer enables Freestyle')
    for logical, spec in declared.items():
        _check(checkpoint)
        layer = layers[logical]; settings = layer.freestyle_settings
        if len(settings.modules) or settings.mode != 'EDITOR':
            _reject('Freestyle cannot use script modules or script control')
        expected_names = [set_names[(logical, item['id'])] for item in spec['lineSets']]
        if [item.name for item in settings.linesets] != expected_names:
            _reject('Freestyle complete line-set order or membership differs', logical)
        record = {'enabled': layer.use_freestyle, 'settings': _scalar(settings), 'lineSets': []}
        for item, intent in zip(settings.linesets, spec['lineSets']):
            scope = intent['scope']; key = (logical, intent['id'])
            expected_style = bpy.data.linestyles[style_names[intent['style']]]
            if item.linestyle != expected_style:
                _reject('Freestyle style pointer differs', intent['id'])
            collection = None
            if scope['kind'] == 'objects':
                collection = bpy.data.collections.get(scope_names[key])
                if (collection is None or not collection.use_fake_user or len(collection.children)
                        or set(collection.objects) != {objects[x] for x in scope['objects']}
                        or any(collection in list(root.collection.children_recursive) for root in bpy.data.scenes)):
                    _reject('Private object scope membership or unlinked lifecycle differs', intent['id'])
            elif scope['kind'] == 'collection':
                collection = collections[scope['collection']]
            if item.collection != collection:
                _reject('Freestyle scope collection pointer differs', intent['id'])
            record['lineSets'].append({'id': intent['id'], 'style': intent['style'],
                                      'scope': scope, 'settings': _scalar(item),
                                      'collectionGraph': _collection_scope(collection, objects, checkpoint)
                                          if scope['kind'] == 'collection' else None})
        result['layers'][logical] = record
    for spec in plan['materials']:
        material = materials[spec['material']]
        result['materials'][spec['material']] = {'colour': list(material.line_color), 'priority': material.line_priority}
    _check(checkpoint)
    return result


def verify(plan, expected, **context):
    """Compare with a caller-held fresh reference, never a submitted receipt.

    The expected argument must come from a separate authoritative reconstruction
    before the submitted project is opened. The kernel cannot authenticate a
    mutable saved readback supplied as its own expected state.
    """
    from .asset_fidelity import matching
    current = observe(plan, **context)
    if not matching(current, expected):
        _reject('Complete Freestyle settings differ from fresh typed reconstruction')
    return current
