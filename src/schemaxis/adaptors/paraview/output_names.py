"""Descriptive publication properties from resolved ParaView settings.

Copyright (C) 2026 David L. F. Gaden.
SPDX-License-Identifier: Apache-2.0
"""
import math


def image_properties(scene, appearance, plane, time, appearance_index):
    result = {'kind': 'slice' if plane else 'image', 'scene': scene['id']}
    if plane:
        normal, origin = plane['normal'], plane['origin']
        length = math.hypot(*normal)
        axis = next((i for i, value in enumerate(normal) if length and abs(value)/length > 1-1e-8), None)
        if axis is None:
            result.update(origin=origin, normal=normal)
        else:
            result.update(axis='XYZ'[axis], pos=origin[axis])
    styles = [v for k, v in appearance.items() if k not in scene.get('text', ())]
    fields = list(dict.fromkeys(v['field'][1] for v in styles if 'field' in v))
    if fields:
        result['var'] = fields[0] if len(fields) == 1 else fields
        components = list(dict.fromkeys(v.get('component', -1) for v in styles if 'field' in v))
        if any(c != -1 for c in components):
            result['component'] = components[0] if len(components) == 1 else components
    result['time'] = time
    opacities = list(dict.fromkeys(v.get('opacity', 1) for v in styles))
    if opacities != [1] and opacities:
        result['opacity'] = opacities[0] if len(opacities) == 1 else opacities
    # A native scene may vary colours, ranges or other settings for the same
    # field. Retain an appearance discriminator only where field names repeat.
    signatures = [tuple(repr(v.get('field')) for k, v in a.items() if k not in scene.get('text', ()))
                  for a in scene['appearances']]
    if signatures.count(signatures[appearance_index]) > 1:
        result['appearance'] = appearance_index
    return result
