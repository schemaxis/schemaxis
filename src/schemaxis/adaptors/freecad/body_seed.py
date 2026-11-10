"""Typed bridge from an external solid into an editable Body history.

The source placement is interpreted in Body-local coordinates. The Body frame
then maps the completed history into world coordinates. Native property paths,
helper classes and the Placement expression are compiled application policy.
"""
from schemaxis.errors import fail


def declaration(declare):
    result=declare('PartDesign::FeatureBase',{},('body','source'))
    result['inputs']['body']['kind']='body'
    return result


def active(prepared):
    return any(n['filter']=='bodySeed' for n in prepared['nodes'])


def prepare(prepared,bodies,owners):
    """Validate seeds after ordinary ordered ownership has been constructed."""
    from .operations import output_names
    mapped=output_names(prepared)
    seeds={}
    for node in prepared['nodes']:
        if node['filter']!='bodySeed':continue
        owner,source=node['inputs']['body'],node['inputs']['source']
        record=bodies[owner]
        if record['members'][0]!=node['id'] or source in owners or source in bodies:
            fail('INVALID_BODY_SEED','Seed must be the first Body member and refer to an external solid',node['id'])
        # Earlier typed graph edges already establish acyclic order. A seeded
        # Body cannot depend back on another Body member through a Part node.
        node['seed']={'source':mapped[source]}
        seeds[owner]=source
    if seeds and any(node['filter']=='readSTEP' for node in prepared['nodes']):
        fail('UNSUPPORTED_SOURCE','Seed checked importSTEP/importMesh geometry or typed Part solids; the legacy reader cannot supply a seeded history',
             recovery='use importSTEP with explicit units and expectations, or importMesh with explicit units')
    return seeds


def world_body(prepared,identity):
    """Body supplying a final world export, selected only by compiled intent.

    Unframed ordinary tips and every intermediate feature keep their earlier
    native names. A frame is an explicit typed Body option, never receipt data.
    """
    history=prepared.get('partDesign',{})
    owner=history.get('owners',{}).get(identity)
    if owner is None or history.get('bodies',{}).get(owner,{}).get('tip')!=identity:
        return None
    node=next(n for n in prepared['nodes'] if n['id']==owner)
    if owner in history.get('seeds',{}) or 'frame' in node['options']:
        return owner
    return None


def output_name(prepared,identity):
    """Final seeded/explicit-framed Body exports world; feature inputs stay local."""
    from .operations import output_names
    mapped=output_names(prepared)
    return mapped[world_body(prepared,identity) or identity]


def frame(prepared,identity):
    from .history import matrix
    from .part_design import IDENTITY
    node=next(n for n in prepared['nodes'] if n['id']==identity)
    return matrix(node['options']) if 'frame' in node['options'] else IDENTITY
