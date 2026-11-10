"""Materialise geometric support/traction intent on the actual discrete boundary.

FreeCAD's geometric node search can omit straight-sided quadratic midsides on
curved CAD edges. Use boundary tetrahedral faces, preserving the selected native
face, and integrate its constant traction consistently. No authored deck text is
accepted; only these reviewed displacement/force/pressure records are emitted.
"""
from .analysis_mesh import face_weights
from .faces import resolve
from .analysis_results import deck
from schemaxis.errors import fail


def materialise(prepared,path,inventory):
    data=deck(path);nodes,cells=data['nodes'],data['cells'];bcs={};forces={};pressures={}
    for support in prepared['supports']:
        face=resolve(support['face'],inventory,support['id']);weights,_,_=face_weights(nodes,cells,face)
        for n in weights:
            for axis,value in enumerate(support['displacementMM'],1):
                if value is not None:
                    key=(n,axis)
                    if key in bcs and bcs[key]!=value:fail('INVALID_ANALYSIS','Supports impose conflicting displacement values',support['id'])
                    bcs[key]=value
    for load in prepared['loads']:
        face=resolve(load['face'],inventory,load['id']);weights,area,sides=face_weights(nodes,cells,face)
        if load['kind']=='force':
            for n,w in weights.items():
                out=forces.setdefault(n,[0.,0.,0.])
                for j,v in enumerate(load['forceN']):out[j]+=v*w/area
        else:
            for item in sides:pressures[item]=pressures.get(item,0)+load['pressureMPa']
    blocks=['*BOUNDARY']+[f'{n}, {axis}, {axis}, {v:.17g}' for (n,axis),v in sorted(bcs.items())]
    if forces:blocks+=['*CLOAD']+[f'{n}, {j+1}, {v:.17g}' for n,vec in sorted(forces.items()) for j,v in enumerate(vec) if v!=0]
    if pressures:blocks+=['*DLOAD']+[f'{element}, P{side}, {v:.17g}' for (element,side),v in sorted(pressures.items())]
    output=[];skip=False;inserted=False
    for line in path.read_text().splitlines():
        stripped=line.strip()
        if stripped.startswith('*') and not stripped.startswith('**'):
            keyword=stripped.split(',',1)[0].upper();skip=keyword in ('*BOUNDARY','*CLOAD','*DLOAD')
            if keyword=='*NODE FILE':
                if inserted:fail('VERIFICATION_FAILED','Native static writer emitted multiple result sections')
                output.extend(blocks);inserted=True
        if not skip:output.append(line)
    if not inserted:fail('VERIFICATION_FAILED','Native static writer has no result section for boundary materialisation')
    path.write_text('\n'.join(output)+'\n')
