"""Finite observation/edit stages for the Body-frame qualification's OWN projects.

Imported only in FreeCAD. No authored route dispatches these test stages.
"""
import json
import os
from pathlib import Path
import FreeCAD as App
from schemaxis.artifacts import atomic_json
from schemaxis.adaptors.freecad.body_seed_native import local_shape
from schemaxis.adaptors.freecad.native import export_snapshot
from schemaxis.adaptors.freecad.assembly_sources_native import snapshot,solve_probe


def capture(doc,prepared,renames):
    result=snapshot(doc,prepared,renames)
    result['sourceBodies']={}
    for part in prepared['parts']:
        body=doc.getObject(renames[part['id']][part['source']['body']])
        result['sourceBodies'][part['id']]={'placement':list(body.Placement.toMatrix().A),
            'world':export_snapshot(body.Shape),'local':export_snapshot(local_shape(body))}
    return result


def inspect_copy(directory):
    directory=Path(directory);r=json.loads((directory/'frame-request.json').read_text())
    prepared=json.loads((directory/'plan.json').read_text())
    renames=json.loads((directory/'built.json').read_text())['renames']
    doc=App.openDocument(str(directory/'model.FCStd'))
    try:
        before=capture(doc,prepared,renames)
        if 'thickness' in r:
            part=next(p for p in prepared['parts'] if p['id']=='parametered')
            variable=doc.getObject(renames['parametered'][part['source']['varset']])
            variable.dim_thickness=r['thickness']
        if 'bodyFrame' in r:
            f=r['bodyFrame'];x,n=f['xAxis'],f['normal'];y=list(App.Vector(*n).cross(App.Vector(*x)))
            m=App.Matrix(x[0],y[0],n[0],f['origin'][0],x[1],y[1],n[1],f['origin'][1],x[2],y[2],n[2],f['origin'][2],0,0,0,1)
            part=next(p for p in prepared['parts'] if p['id']=='parametered')
            doc.getObject(renames['parametered'][part['source']['body']]).Placement=App.Placement(m)
        for obj in doc.Objects:obj.touch()
        doc.recompute();recomputed=capture(doc,prepared,renames)
        code=doc.getObject('Assembly').solve();assert code==0,code
        doc.recompute();after=capture(doc,prepared,renames);solver=solve_probe(doc,prepared)
        doc.recompute();doc.saveAs(str(directory/'model.FCStd'))
        objects=[o.Name for o in doc.Objects]
        report={'pid':os.getpid(),'before':before,'recomputed':recomputed,'after':after,'solver':solver}
    finally:App.closeDocument(doc.Name)
    from schemaxis.adaptors.freecad.gui_state import persist
    from schemaxis.adaptors.freecad.assembly_sources import visibility,proxies
    persist(directory/'model.FCStd',visibility(prepared,objects,renames),proxies(prepared))
    atomic_json(directory/r['receipt'],report)


def inspect_parts(directory):
    from schemaxis.artifacts import file_digest
    directory=Path(directory);request=json.loads((directory/'frame-sources.json').read_text())
    report={'pid':os.getpid(),'parts':{}}
    for case in request:
        assert file_digest(case['file'])==case['sha256']
        doc=App.openDocument(case['file'])
        try:
            def bodies():
                return {obj.Name:{'placement':list(obj.Placement.toMatrix().A),
                    'world':export_snapshot(obj.Shape),'local':export_snapshot(local_shape(obj))}
                    for obj in doc.Objects if obj.TypeId=='PartDesign::Body'}
            before=bodies()
            witnesses=([bool(local_shape(doc.getObject(case['body'])).isInside(App.Vector(*point),1e-7,True))
                        for point in case.get('witnessPoints',[])])
            for obj in doc.Objects:obj.touch()
            doc.recompute();after=bodies()
            report['parts'][case['id']]={'before':before,'after':after,'witnesses':witnesses}
        finally:App.closeDocument(doc.Name)
        assert file_digest(case['file'])==case['sha256']
    atomic_json(directory/'frame-sources-result.json',report)
