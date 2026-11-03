# Copyright (C) 2026 David L F Gaden
"""Curated mesh operations; public descriptions never import Blender."""
import copy


def opt(kind, default, **limits):
    return {'value': {'type': kind, 'default': default, **limits}, 'path': []}


def vec(default, **limits):
    return opt('array', default, items={'type': 'number', **limits}, minItems=3, maxItems=3)


def positive(default):
    return opt('number', default, minimum=0, exclusiveMinimum=True)


MATERIAL_INPUT = {'material': {'native': 'material', 'kind': 'material', 'required': True}}
MESH_INPUT = {'input': {'native': 'input', 'required': True}}
CENTRE = vec([0, 0, 0])
PRIMITIVES = {
    'lathe': {
        'profile': {'value': {'type': 'array', 'items': {'type': 'array', 'items': {'type': 'number', 'minimum': -100000, 'maximum': 100000}, 'minItems': 2, 'maxItems': 2}, 'minItems': 2, 'maxItems': 128, 'required': True}, 'path': []},
        'segments': opt('integer', 64, minimum=3, maximum=256), 'caps': opt('boolean', True)},
    'grid': {'width': positive(2), 'height': positive(2),
             'xSegments': opt('integer', 10, minimum=1, maximum=256),
             'ySegments': opt('integer', 10, minimum=1, maximum=256)},
    'disk': {'radius': positive(1), 'segments': opt('integer', 32, minimum=3, maximum=256)},
    'polylineTube': {
        'points': {'value': {'type': 'array', 'items': {'type': 'array', 'items': {'type': 'number', 'minimum': -100000, 'maximum': 100000}, 'minItems': 3, 'maxItems': 3}, 'minItems': 2, 'maxItems': 1024, 'required': True}, 'path': []},
        'radius': positive(0.05), 'resolution': opt('integer', 3, minimum=0, maximum=8),
        'closed': opt('boolean', False), 'caps': opt('boolean', True)},
    'curveFromCSV': {
        'file': {'value': {'type': 'string', 'minLength': 1, 'maxLength': 4096, 'required': True}, 'path': [], 'constructor': True},
        'xColumn': opt('string', 'x', minLength=1, maxLength=128),
        'yColumn': opt('string', 'y', minLength=1, maxLength=128),
        'zColumn': opt('string', '', maxLength=128),
        'radius': positive(0.05), 'resolution': opt('integer', 3, minimum=0, maximum=8),
        'closed': opt('boolean', False), 'caps': opt('boolean', True)},
    'plane': {'width': positive(2), 'height': positive(2)},
    'uvSphere': {'radius': positive(1), 'segments': opt('integer', 32, minimum=3, maximum=256),
                 'rings': opt('integer', 16, minimum=3, maximum=256)},
    'icoSphere': {'radius': positive(1), 'subdivisions': opt('integer', 2, minimum=1, maximum=5)},
    'cylinder': {'radius': positive(1), 'depth': positive(2),
                 'segments': opt('integer', 32, minimum=3, maximum=256)},
    'cone': {'radius': positive(1), 'tipRadius': opt('number', 0, minimum=0), 'depth': positive(2),
             'segments': opt('integer', 32, minimum=3, maximum=256)},
    'torus': {'majorRadius': positive(1), 'minorRadius': positive(.25),
              'majorSegments': opt('integer', 32, minimum=3, maximum=256),
              'minorSegments': opt('integer', 16, minimum=3, maximum=256)},
}
# Explicit native property names are trusted application code, not authored input.
MODIFIERS = {
    'weld': ('WELD', {'distance': ('merge_threshold', positive(.0001))}),
    'weightedNormal': ('WEIGHTED_NORMAL', {'weight': ('weight', opt('integer',50,minimum=1,maximum=100)), 'keepSharp': ('keep_sharp',opt('boolean',True))}),
    'voxelRemesh': ('REMESH', {'voxelSize': ('voxel_size',positive(.1)), 'adaptivity': ('adaptivity',opt('number',0,minimum=0,maximum=1))}),
    'bend': ('SIMPLE_DEFORM', {'angle': ('angle',opt('number',0.7853981633974483,minimum=-6.283185307179586,maximum=6.283185307179586)), 'axis': ('deform_axis',opt('enum','Z',values=['X','Y','Z']))}),
    'twist': ('SIMPLE_DEFORM', {'angle': ('angle',opt('number',0.7853981633974483,minimum=-6.283185307179586,maximum=6.283185307179586)), 'axis': ('deform_axis',opt('enum','Z',values=['X','Y','Z']))}),
    'shrinkwrap': ('SHRINKWRAP', {'offset': ('offset',opt('number',0)), 'mode': ('wrap_mode',opt('enum','ON_SURFACE',values=['ON_SURFACE','OUTSIDE','INSIDE','ABOVE_SURFACE']))}),
    'wireframe': ('WIREFRAME', {'thickness': ('thickness', positive(.02)),
                              'offset': ('offset', opt('number', 0, minimum=-1, maximum=1)),
                              'replace': ('use_replace', opt('boolean', True)),
                              'boundary': ('use_boundary', opt('boolean', True))}),
    'solidify': ('SOLIDIFY', {'thickness': ('thickness', opt('number', .1)),
                            'offset': ('offset', opt('number', -1, minimum=-1, maximum=1))}),
    'subdivision': ('SUBSURF', {'levels': ('levels', opt('integer', 1, minimum=0, maximum=4)),
        'method': ('subdivision_type',opt('enum','CATMULL_CLARK',values=['CATMULL_CLARK','SIMPLE']))}),
    'decimate': ('DECIMATE', {'ratio': ('ratio', opt('number', .5, minimum=0, maximum=1, exclusiveMinimum=True))}),
    'triangulate': ('TRIANGULATE', {}),
    'smooth': ('SMOOTH', {'factor': ('factor', opt('number', .5, minimum=-10, maximum=10)),
                         'iterations': ('iterations', opt('integer', 1, minimum=1, maximum=100))}),
    'array': ('ARRAY', {'count': ('count', opt('integer', 2, minimum=1, maximum=100)),
                       'relativeOffset': ('relative_offset_displace', vec([1, 0, 0]))}),
    'mirror': ('MIRROR', {'axes': ('use_axis', opt('array', [True, False, False],
                                 items={'type': 'boolean'}, minItems=3, maxItems=3)),
                         'merge': ('use_mirror_merge', opt('boolean', True))}),
    'boolean': ('BOOLEAN', {'operation': ('operation', opt('enum', 'DIFFERENCE',
                                        values=['DIFFERENCE', 'UNION', 'INTERSECT']))}),
}


def declarations():
    result = {}
    for name, options in PRIMITIVES.items():
        result[name] = {'id': name, 'native': name, 'inputs': copy.deepcopy(MATERIAL_INPUT),
                        'options': {**copy.deepcopy(options), 'centre': copy.deepcopy(CENTRE),
                                    'smoothShading': opt('boolean', False)}}
    for name, (_, options) in MODIFIERS.items():
        result[name] = {'id': name, 'native': name, 'inputs': copy.deepcopy(MESH_INPUT),
                        'options': {key: copy.deepcopy(spec) for key, (_, spec) in options.items()}}
    result['assignMaterial'] = {'id': 'assignMaterial', 'native': 'assignMaterial',
                                'inputs': {**copy.deepcopy(MESH_INPUT), **copy.deepcopy(MATERIAL_INPUT)},
                                'options': {}}
    result['applyTransform'] = {'id':'applyTransform','native':'applyTransform','inputs':copy.deepcopy(MESH_INPUT),'options':{}}
    result['shadeSmooth'] = {'id':'shadeSmooth','native':'shadeSmooth','inputs':copy.deepcopy(MESH_INPUT),
                             'options':{'enabled':opt('boolean',True)}}
    result['join'] = {'id':'join','native':'join','inputs':{'inputs':{'native':'inputs','required':True,'multiple':True}},'options':{}}
    result['shrinkwrap']['inputs']['target']={'native':'target','required':True}
    for kind in ('readSTL','readPLY'):
        result[kind]={'id':kind,'native':kind,'inputs':{},'options':{
            'file':{'value':{'type':'string','minLength':1,'required':True},'path':[],'constructor':True},
            'scale':{**opt('number',1,minimum=0.000001,maximum=1000000),'constructor':True},
        }}
    result['boolean']['inputs']['operand'] = {'native': 'operand', 'required': True}
    result['transform'] = {'id': 'transform', 'native': 'transform', 'inputs': copy.deepcopy(MESH_INPUT),
                           'options': {'translation': vec([0, 0, 0]), 'rotation': vec([0, 0, 0]),
                                       'scale': vec([1, 1, 1], minimum=0, exclusiveMinimum=True)}}
    return result
