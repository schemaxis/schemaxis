"""Independent imported-mesh facts and compatibility entry points.

The complete typed Part graph verifier lives in part_reconstruction; importMesh
retains independent captured-STL geometry authority in addition to regeneration.
"""
from schemaxis.errors import fail
from .mesh_geometry import verify_placement
from .part_reconstruction import compare_xml,source_brep_matches,bind_payloads,verify


def verify_observation(node, record, stage):
    from .saved_checks import _close
    if not isinstance(record,dict):fail('VERIFICATION_FAILED','Mesh observation is missing',node['id'],stage=stage)
    r=node['frame']['worldFromFile'];t=node['frame']['translation']
    verify_placement(record.get('placement'),[*r[0],t[0],*r[1],t[1],*r[2],t[2]],node['id'])
    local=record.get('fileFrame',{});source=node['source']
    if (local.get('valid') is not True or local.get('solids')!=1 or local.get('faces')!=source['facets']
            or not local.get('shellsClosed') or any(v is not True for v in local['shellsClosed'])
            or any(not _close(local.get(k),source[k]) for k in ('volume','area','bounds','centreOfMass'))):
        fail('VERIFICATION_FAILED','Native mesh material facts differ from independent captured STL integrals',node['id'],stage=stage)
