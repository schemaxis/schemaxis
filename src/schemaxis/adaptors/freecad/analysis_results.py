"""Bounded independent readers/checks for native-generated static elasticity decks."""
import math
import re
from pathlib import Path
from schemaxis.errors import fail
from .analysis_mesh import dot,cross,volume_and_energy,face_weights,checkpoint


def read_text(path,limit=128*1024*1024):
    checkpoint();p=Path(path)
    if p.is_symlink() or not p.is_file() or p.stat().st_size>limit:fail('VERIFICATION_FAILED','Analysis file is missing, linked or oversized',p.name)
    try:return p.read_text(encoding='utf-8')
    except (UnicodeError,OSError):fail('VERIFICATION_FAILED','Analysis file is unreadable UTF-8',p.name)


def number(text):
    try:r=float(text.replace('D','E').replace('d','e'))
    except (ValueError,OverflowError):fail('VERIFICATION_FAILED','Analysis number is malformed')
    if not math.isfinite(r):fail('VERIFICATION_FAILED','Analysis number is nonfinite')
    return r


def deck(path):
    nodes={};cells={};sets={};elsets={};forces={};boundaries={};pressures={};elastic=[];density=[];section=None;params={};alltypes=set();step_count=0;static_count=0;materials=[];sections=[]
    text=read_text(path)
    for serial,raw in enumerate(text.splitlines()):
        if serial%2048==0:checkpoint()
        line=raw.strip()
        if not line or line.startswith('**'):continue
        if line.startswith('*'):
            parts=[p.strip().upper() for p in line.split(',')];section=parts[0];params={p.split('=',1)[0]:p.split('=',1)[1] for p in parts[1:] if '=' in p};flags=set(parts[1:])
            allowed={'*PHYSICAL CONSTANTS','*NODE','*ELEMENT','*NSET','*ELSET','*MATERIAL','*ELASTIC','*DENSITY','*EXPANSION','*SOLID SECTION','*BOUNDARY','*CLOAD','*DLOAD','*STEP','*STATIC','*NODE FILE','*EL FILE','*NODE PRINT','*OUTPUT','*END STEP'}
            if section not in allowed:fail('VERIFICATION_FAILED','Solver deck keyword is outside the native static-solid contract',keyword=section)
            if section in ('*ELASTIC','*BOUNDARY','*CLOAD','*DLOAD') and len(parts)!=1:fail('VERIFICATION_FAILED','Material/support/load modifiers are outside constant linear elasticity',keyword=section)
            if section=='*STATIC':static_count+=1
            if section=='*MATERIAL':materials.append(params.get('NAME'))
            if section=='*SOLID SECTION':sections.append(dict(params))
            if section=='*STEP':
                step_count+=1
                if any('NLGEOM' in p for p in parts):fail('VERIFICATION_FAILED','Nonlinear step is outside the linear-static contract')
            if section=='*ELEMENT':
                typ=params.get('TYPE');alltypes.add(typ)
                if typ not in ('C3D4','C3D10'):fail('VERIFICATION_FAILED','Only C3D4/C3D10 solid elements are allowed')
            continue
        values=[v.strip() for v in line.split(',') if v.strip()]
        if section=='*NODE':
            if len(values)!=4:fail('VERIFICATION_FAILED','Node row differs')
            identity=int(values[0])
            if identity in nodes:fail('VERIFICATION_FAILED','Duplicate mesh node')
            nodes[identity]=[number(v) for v in values[1:]]
            if params.get('NSET'):sets.setdefault(params['NSET'],set()).add(identity)
        elif section=='*ELEMENT':
            conn=[int(v) for v in values];identity=conn[0]
            if identity in cells or len(conn)!=(5 if params['TYPE']=='C3D4' else 11):fail('VERIFICATION_FAILED','Duplicate or malformed cell')
            cells[identity]=conn[1:]
            if params.get('ELSET'):elsets.setdefault(params['ELSET'],set()).add(identity)
        elif section in ('*NSET','*ELSET'):
            target=sets if section=='*NSET' else elsets;key=params.get('NSET' if section=='*NSET' else 'ELSET');out=target.setdefault(key,set())
            if 'GENERATE' in flags:
                a,b,c=map(int,values)
                if c<=0 or b<a:fail('VERIFICATION_FAILED','Invalid generated set range')
                out.update(range(a,b+1,c))
            else:
                for value in values:
                    if value.upper() in target:out.update(target[value.upper()])
                    else:out.add(int(value))
        elif section=='*BOUNDARY':
            first=int(values[1]);last=int(values[2]) if len(values)>2 else first;value=number(values[3]) if len(values)>3 else 0
            identities=sets[values[0].upper()] if values[0].upper() in sets else [int(values[0])]
            for n in identities:
                if n not in nodes:fail('VERIFICATION_FAILED','Displacement constraint has a foreign mesh node')
                for axis in range(first,last+1):
                    if axis not in (1,2,3) or (n,axis) in boundaries:fail('VERIFICATION_FAILED','Repeated or unsupported displacement constraint')
                    boundaries[n,axis]=value
        elif section=='*CLOAD':
            if len(values)!=3:fail('VERIFICATION_FAILED','Nodal load row differs')
            identity,axis=int(values[0]),int(values[1])
            if identity not in nodes or axis not in (1,2,3):fail('VERIFICATION_FAILED','Nodal load has a foreign node or invalid displacement DOF')
            force=number(values[2]);forces.setdefault(identity,[0.,0.,0.])[axis-1]+=force
        elif section=='*DLOAD':
            if not re.fullmatch(r'P[1-4]',values[1].upper()):fail('VERIFICATION_FAILED','Unsupported distributed load in static-solid deck')
            identity,side=int(values[0]),int(values[1][1:]);pressures[identity,side]=pressures.get((identity,side),0)+number(values[2])
        elif section=='*ELASTIC':elastic.append([number(v) for v in values])
        elif section=='*DENSITY':density.append(number(values[0]))
    if step_count!=1 or static_count!=1 or not nodes or not cells or len(elastic)!=1 or len(density)>1 or len(materials)!=1 or len(sections)!=1 or sections[0].get('MATERIAL')!=materials[0] or elsets.get(sections[0].get('ELSET'))!=set(cells):fail('VERIFICATION_FAILED','Static deck membership/material differs')
    return {'nodes':nodes,'cells':cells,'sets':sets,'forces':forces,'boundaries':boundaries,'pressures':pressures,'elastic':elastic[0],'density':density[0] if density else None,'elementTypes':sorted(alltypes)}


def dat(path,nodes):
    records={};current=None
    for serial,raw in enumerate(read_text(path).splitlines()):
        if serial%2048==0:checkpoint()
        line=raw.strip();low=line.lower()
        if 'for set nall and time' in low:
            current='displacements' if low.startswith('displacements') else 'forces' if low.startswith('forces') else None
            if current:
                if current in records:fail('VERIFICATION_FAILED','More than one static result increment is present')
                records[current]={}
            continue
        if not line:continue
        if current:
            parts=line.split()
            if len(parts)==4 and parts[0].isdigit():
                identity=int(parts[0])
                if identity in records[current] or identity not in nodes:fail('VERIFICATION_FAILED','Duplicate or foreign result node')
                records[current][identity]=[number(v) for v in parts[1:]]
            else:current=None
    if set(records)!={'displacements','forces'} or any(set(r)!=set(nodes) for r in records.values()):fail('VERIFICATION_FAILED','Nodal displacement/force result membership differs')
    return records


def verify(prepared,directory,observed):
    """Replay actual applied loads/constraints, equilibrium and strain-energy work."""
    from .faces import resolve
    from .adaptor import close
    data=deck(Path(directory)/'Mesh.inp');nodes,cells=data['nodes'],data['cells'];result=dat(Path(directory)/'Mesh.dat',nodes)
    budget=prepared['mesh']
    if len(nodes)>budget['maxNodes'] or len(cells)>budget['maxElements']:fail('RESOURCE_BUDGET_EXCEEDED','Analysis mesh exceeds its authored resource budget')
    if data['elementTypes']!=['C3D10' if budget['order']==2 else 'C3D4']:fail('VERIFICATION_FAILED','Actual cell type/order differs from authored mesh')
    from .analysis_mesh import connectivity_key
    actual_nodes=observed.get('meshNodes',{});actual_cells=observed.get('meshCells',{})
    if set(actual_cells)!={str(n) for n in cells} or any(connectivity_key(actual_cells[str(n)])!=connectivity_key(v) for n,v in cells.items()) or set(actual_nodes)!={str(n) for n in nodes} or any(not close(actual_nodes[str(n)],v) for n,v in nodes.items()):fail('VERIFICATION_FAILED','Actual solver mesh differs from the saved native FEM mesh')
    material=prepared['material']
    if not close(data['elastic'],[material['youngModulusMPa'],material['poissonRatio']]) or data['density'] is not None and not math.isclose(data['density'],material['densityKgPerM3']*1e-12,rel_tol=1e-8,abs_tol=1e-20):fail('VERIFICATION_FAILED','Actual solver material/units differ')
    inventory=observed['faces'];expected_forces={};expected_bcs={};expected_pressures={};total_force=[0.,0.,0.];total_moment=[0.,0.,0.];load_areas={}
    for support in prepared['supports']:
        face=resolve(support['face'],inventory,support['id']);weights,area,sides=face_weights(nodes,cells,face)
        for n in weights:
            for axis,value in enumerate(support['displacementMM'],1):
                if value is not None:
                    if (n,axis) in expected_bcs and expected_bcs[n,axis]!=value:fail('VERIFICATION_FAILED','Supports impose conflicting nodal displacements')
                    expected_bcs[n,axis]=value
    for load in prepared['loads']:
        face=resolve(load['face'],inventory,load['id']);weights,area,sides=face_weights(nodes,cells,face);load_areas[load['id']]=area
        force=load['forceN'] if load['kind']=='force' else [-load['pressureMPa']*area*v for v in face['normal']]
        for j,v in enumerate(force):total_force[j]+=v
        for j,v in enumerate(cross(face['centre'],force)):total_moment[j]+=v
        for n,w in weights.items():
            vector=expected_forces.setdefault(n,[0.,0.,0.])
            for j,v in enumerate(force):vector[j]+=w/area*v
        if load['kind']=='pressure':
            for item in sides:expected_pressures[item]=expected_pressures.get(item,0)+load['pressureMPa']
    if set(data['boundaries'])!=set(expected_bcs) or any(not close(data['boundaries'][k],v) for k,v in expected_bcs.items()):fail('VERIFICATION_FAILED','Actual nodal support membership or values differ')
    # Pressure cards remain surface loads; force cards carry consistent nodal
    # weights. Compare each concrete record, not only resultant totals.
    if set(data['pressures'])!=set(expected_pressures) or any(not close(data['pressures'][k],v) for k,v in expected_pressures.items()):fail('VERIFICATION_FAILED','Actual element-face pressure membership differs')
    cload_expected={}
    for load in prepared['loads']:
        if load['kind']!='force':continue
        face=resolve(load['face'],inventory,load['id']);weights,area,_=face_weights(nodes,cells,face)
        for n,w in weights.items():
            out=cload_expected.setdefault(n,[0.,0.,0.])
            for j,v in enumerate(load['forceN']):out[j]+=w/area*v
    for n in set(data['forces'])|set(cload_expected):
        if not close(data['forces'].get(n,[0.,0.,0.]),cload_expected.get(n,[0.,0.,0.])):fail('VERIFICATION_FAILED','Actual distributed-force nodal traction weights differ',str(n))
    fields=frd(Path(directory)/'Mesh.frd',nodes)
    cached=observed.get('result',{})
    if cached.get('displacements')!={str(n):v for n,v in fields['DISP'].items()} or cached.get('stresses')!={str(n):v for n,v in fields['STRESS'].items()}:fail('VERIFICATION_FAILED','Native saved result cache differs from actual solver FRD fields')
    for n,vector in fields['DISP'].items():
        for a,b in zip(vector,result['displacements'][n]):
            if abs(a-b)>max(1e-10,abs(b)*8e-6):fail('VERIFICATION_FAILED','Independent DAT/FRD displacement outputs differ',str(n))
    from .analysis_mesh import verify_stress_field
    verify_stress_field(nodes,cells,result['displacements'],material,fields['STRESS'])
    intent_moment=list(total_moment)
    total_moment=[math.fsum(cross(nodes[n],f)[j] for n,f in expected_forces.items()) for j in range(3)]
    displacements=result['displacements'];reactions=result['forces'];force_scale=max(1,math.fsum(abs(x) for v in expected_forces.values() for x in v));tolerance=force_scale*2e-5
    for (n,axis),value in expected_bcs.items():
        if abs(displacements[n][axis-1]-value)>max(1e-8,abs(value)*1e-5):fail('VERIFICATION_FAILED','Solver displacement constraint is not satisfied')
    reaction_sum=[0.,0.,0.];reaction_moment=[0.,0.,0.]
    for n,r in reactions.items():
        for j in range(3):
            if (n,j+1) in expected_bcs:reaction_sum[j]+=r[j]-expected_forces.get(n,[0.,0.,0.])[j]
            elif abs(r[j]-expected_forces.get(n,[0.,0.,0.])[j])>tolerance:fail('VERIFICATION_FAILED','Unconstrained nodal force differs from applied loading',str(n))
        support_force=[r[j]-expected_forces.get(n,[0.,0.,0.])[j] if (n,j+1) in expected_bcs else 0 for j in range(3)]
        for j,v in enumerate(cross(nodes[n],support_force)):reaction_moment[j]+=v
    residual=[a+b for a,b in zip(total_force,reaction_sum)];moment=[a+b for a,b in zip(total_moment,reaction_moment)]
    length_scale=max(1,*(abs(v) for point in nodes.values() for v in point))
    if math.hypot(*residual)>tolerance or math.hypot(*moment)>tolerance*length_scale:fail('VERIFICATION_FAILED','Independent force/moment equilibrium failed',forceResidualN=residual,momentResidualNMM=moment)
    elastic=volume_and_energy(nodes,cells,displacements,material);source_volume=prepared['source']['volume']
    if abs(elastic['meshVolumeMM3']-source_volume)>source_volume*budget['volumeTolerance']:fail('INVALID_MESH','Mesh volume exceeds the authored CAD geometry approximation tolerance')
    work=.5*math.fsum(dot(expected_forces.get(n,[0.,0.,0.]),u) for n,u in displacements.items())
    work+=.5*math.fsum((reactions[n][axis-1]-expected_forces.get(n,[0.,0.,0.])[axis-1])*value for (n,axis),value in expected_bcs.items())
    if work<=0 or abs(work-elastic['strainEnergyNMM'])>max(1e-8,abs(work)*.005):fail('VERIFICATION_FAILED','Independent elastic strain energy and external work differ',strainEnergyNMM=elastic['strainEnergyNMM'],externalWorkNMM=work)
    summary={**elastic,'nodes':len(nodes),'elements':len(cells),'elementType':data['elementTypes'][0],
        'maxDisplacementMM':max(math.hypot(*v) for v in displacements.values()),'externalWorkNMM':work,
        'appliedForceN':total_force,'reactionForceN':reaction_sum,'forceResidualN':residual,'momentResidualNMM':moment,'cadIntentMomentNMM':intent_moment,'discreteAppliedMomentNMM':total_moment,'loadAreasMM2':load_areas}
    summary['limits']=[{'id':l['id'],'quantity':l['quantity'],'maximum':l['maximum'],'observed':summary[l['quantity']],'satisfied':summary[l['quantity']]<=l['maximum']} for l in prepared['limits']]
    summary['limitsSatisfied']=all(l['satisfied'] for l in summary['limits'])
    checkpoint();return summary


def frd(path,nodes):
    """Read the documented ASCII FRD displacement/stress datasets independently."""
    data={};current=None
    for serial,line in enumerate(read_text(path).splitlines()):
        if serial%2048==0:checkpoint()
        if line.startswith(' -4'):
            kind=line[5:17].strip();current=kind if kind in ('DISP','STRESS') else None
            if current:
                if current in data:fail('VERIFICATION_FAILED','Multiple FRD static result datasets')
                data[current]={}
        elif line.startswith(' -3'):current=None
        elif current and line.startswith(' -1'):
            identity=int(line[3:13]);count=3 if current=='DISP' else 6
            if identity in data[current] or identity not in nodes or len(line[13:].strip())>count*12:fail('VERIFICATION_FAILED','FRD result record membership differs')
            data[current][identity]=[number(line[13+12*k:25+12*k]) for k in range(count)]
    if set(data)!={'DISP','STRESS'} or any(set(v)!=set(nodes) for v in data.values()):fail('VERIFICATION_FAILED','FRD displacement/stress node membership differs')
    return data
