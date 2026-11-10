"""Closed FileOutput format ownership for fresh native source signatures.

Reading these structs does not authorize executing a source node's file paths.
The publication runner must separately bind and stage every enabled file writer.
"""
import json


def _class(reader, native, expected):
    if native is None or native.bl_rna.identifier != expected:
        reader.reject('render output needs a reviewed native settings class', expected)
    return native


def _pointers(reader, native, allowed):
    for prop in native.bl_rna.properties:
        if prop.type == 'POINTER' and prop.identifier != 'rna_type' and prop.identifier not in allowed:
            if getattr(native, prop.identifier) is not None:
                reader.reject('render format pointer needs an explicit source mapping', prop.identifier)


def _curve_mapping(reader, mapping):
    if mapping is None:
        return None
    _class(reader, mapping, 'CurveMapping')
    _pointers(reader, mapping, set())
    if len(mapping.curves) > 8:
        reader.reject('render color curves exceed eight channels', 'format.curveMapping')
    curves = []
    for curve in mapping.curves:
        _pointers(reader, curve, set())
        if len(curve.points) > 256:
            reader.reject('render color curve exceeds 256 controls', 'format.curveMapping')
        for point in curve.points:
            _pointers(reader, point, set())
        curves.append({'settings': reader.primitive(curve),
                       'points': reader.payload(reader.primitive(p) for p in curve.points)})
    return {'settings': reader.primitive(mapping), 'curves': curves}


def format_snapshot(reader, native):
    _class(reader, native, 'ImageFormatSettings')
    _pointers(reader, native, {'stereo_3d_format', 'view_settings', 'display_settings',
                              'linear_colorspace_settings'})
    if native.media_type not in ('IMAGE', 'MULTI_LAYER_IMAGE'):
        reader.reject('video file writers need a typed encoder contract', 'format.media_type')
    view = _class(reader, native.view_settings, 'ColorManagedViewSettings')
    _pointers(reader, view, {'curve_mapping'})
    stereo = _class(reader, native.stereo_3d_format, 'Stereo3dFormat')
    display = _class(reader, native.display_settings, 'ColorManagedDisplaySettings')
    linear = _class(reader, native.linear_colorspace_settings, 'ColorManagedInputColorspaceSettings')
    for group in (stereo, display, linear):
        _pointers(reader, group, set())
    record = {'settings': reader.primitive(native), 'stereo': reader.primitive(stereo),
              'view': reader.primitive(view), 'display': reader.primitive(display),
              'linearColorSpace': reader.primitive(linear),
              'curveMapping': _curve_mapping(reader, view.curve_mapping)}
    reader.budget(len(json.dumps(record, allow_nan=False).encode()))
    return record


def node_snapshot(reader, node):
    if node.bl_idname != 'CompositorNodeOutputFile':
        reader.reject('render writer requires the reviewed FileOutput class', node.bl_idname)
    if len(node.directory.encode('utf-8')) > 4096 or len(node.file_name.encode('utf-8')) > 256:
        reader.reject('render writer directory or filename exceeds its bound', node.name)
    if any(c in node.directory + node.file_name for c in '{}'):
        reader.reject('render writer template expressions need an explicit output contract', node.name)
    if len(node.file_output_items) > 64:
        reader.reject('render writer exceeds 64 image/layer items', node.name)
    _pointers(reader, node, {'rna_type', 'parent', 'format'})
    if node.id_data.animation_data is not None:
        reader.reject('animated file-writer configuration needs a typed channel contract', node.name)
    items = []
    names = set()
    for item in node.file_output_items:
        _class(reader, item, 'NodeCompositorFileOutputItem')
        _pointers(reader, item, {'format'})
        if item.name in names or len(item.name.encode('utf-8')) > 128:
            reader.reject('render writer item names repeat or exceed their bound', node.name)
        names.add(item.name)
        if item.socket_type not in ('FLOAT', 'RGBA', 'VECTOR'):
            reader.reject('render writer input needs a reviewed image/data socket kind', item.socket_type)
        record = {'settings': reader.primitive(item), 'format': format_snapshot(reader, item.format)}
        reader.budget(len(json.dumps(record, allow_nan=False).encode()))
        items.append(record)
    return {'format': format_snapshot(reader, node.format), 'items': items}
