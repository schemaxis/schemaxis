"""Application-specific console policy; session persistence stays in the framework."""
import copy
from schemaxis.errors import fail
import uuid
from .adaptor import plan
from schemaxis.adaptors.registry import declarations


def validate(document, draft=True):
    nodes = document['nodes']
    candidate = copy.deepcopy(document)
    if draft:
        # Exercise the provider's complete validator even while a scene is
        # being assembled. Temporary consumers/camera are validation-only.
        suffix = uuid.uuid4().hex
        used = {v for n in nodes for v in n.get('inputs', {}).values() if isinstance(v, str)}
        for index, node in enumerate(nodes):
            if node['filter'] == 'material' and node['id'] not in used:
                candidate['nodes'].append({'id': 'validationBox' + str(index) + suffix,
                    'filter': 'box', 'inputs': {'material': node['id']}})
        kinds = [declarations("godot").get(n['filter'], {}).get('kinds') for n in candidate['nodes']]
        if ['geometry'] not in kinds:
            identity = 'validationMaterial' + suffix
            candidate['nodes'].extend([{'id': identity, 'filter': 'material'},
                {'id': 'validationBox' + suffix, 'filter': 'box', 'inputs': {'material': identity}}])
        if not any(n['filter'] == 'camera' for n in nodes):
            candidate['nodes'].append({'id': 'validationCamera' + suffix, 'filter': 'camera'})
        plan(candidate)
        return {'status': 'draft', 'document': copy.deepcopy(document)}
    return plan(candidate)
