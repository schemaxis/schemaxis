"""Distinguish Body-local assembly geometry from world-space part exports."""
from .operations import output_names


def local_shape(body):
    shape=body.Shape.copy()
    shape.Placement=body.Placement.inverse().multiply(shape.Placement)
    return shape


def local_evidence(doc,prepared):
    history=prepared.get('partDesign',{})
    if not history:return {}
    if history.get('generation',1)==1:
        owner=history['body'];tip=history['tip']
    else:
        owner=history.get('owners',{}).get(prepared['output'])
        tip=history.get('bodies',{}).get(owner,{}).get('tip')
    if owner is None or tip!=prepared['output']:return {}
    from .native import export_snapshot
    body=doc.getObject(output_names(prepared)[owner])
    return {'bodyLocalExportEvidence':{'frame':'bodyLocal','body':body.Name,
            'bodyLayout':list(body.Placement.toMatrix().A),'shape':export_snapshot(local_shape(body))}}
