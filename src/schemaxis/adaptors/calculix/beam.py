"""Deterministic quadratic solids and independent finite-element readback checks."""
import math
import re

from .faults import fault

LOCAL = [(0,0,0),(2,0,0),(2,2,0),(0,2,0),(0,0,2),(2,0,2),(2,2,2),(0,2,2),
         (1,0,0),(2,1,0),(1,2,0),(0,1,0),(1,0,2),(2,1,2),(1,2,2),(0,1,2),
         (0,0,1),(2,0,1),(2,2,1),(0,2,1)]
FACE_WEIGHTS = [(0,0,-1/12),(2,0,-1/12),(2,2,-1/12),(0,2,-1/12),
                (1,0,1/3),(2,1,1/3),(1,2,1/3),(0,1,1/3)]
TOLERANCES = {'tipTheoryRelative': .03, 'axialRefinementRelative': .01,
              'transverseRefinementRelative': .01, 'interiorStressScaled': .05,
              'equilibriumScaled': 1e-4, 'readbackRelative': 1e-6}


def model(prepared, stage):
    nx = prepared['mesh']['lengthCells'] * (1 if stage == 'coarse' else 2)
    ny = nz = prepared['mesh']['sectionCells'] * (2 if stage in ('fine','reopened') else 1)
    L,b,h = (prepared['beam'][k] for k in ('length_m','width_m','height_m'))
    nodes = {}; elements = []
    for ix in range(nx):
        for iy in range(ny):
            for iz in range(nz):
                identities = []
                for x,y,z in LOCAL:
                    key = (2*ix+x,2*iy+y,2*iz+z)
                    if key not in nodes: nodes[key] = len(nodes)+1
                    identities.append(nodes[key])
                elements.append({'nodes': identities, 'cell': (ix,iy,iz)})
    xyz = {identity:(x*L/(2*nx), y*b/(2*ny)-b/2, z*h/(2*nz)-h/2)
           for (x,y,z),identity in nodes.items()}
    weights = {}
    for iy in range(ny):
        for iz in range(nz):
            for y,z,weight in FACE_WEIGHTS:
                identity = nodes[(2*nx,2*iy+y,2*iz+z)]
                weights[identity] = weights.get(identity,0)+weight/(ny*nz)
    root = [identity for (x,y,z),identity in nodes.items() if x == 0]
    return {'nodes':xyz,'elements':elements,'root':root,'tipWeights':weights,'cells':(nx,ny,nz)}


def deck(prepared, stage):
    mesh = model(prepared,stage)
    lines = ['*HEADING','Schemaxis bounded elastic cantilever; SI m N Pa; C3D20R','*NODE,NSET=ALL']
    lines.extend(str(i)+','+','.join(format(v,'.16g') for v in xyz) for i,xyz in mesh['nodes'].items())
    lines.append('*ELEMENT,TYPE=C3D20R,ELSET=ALL')
    for i,element in enumerate(mesh['elements'],1):
        ids = element['nodes']
        lines.extend([','.join(map(str,[i]+ids[:15]))+',', ','.join(map(str,ids[15:]))])
    for name,identities in [('ROOT',mesh['root']),('TIP',list(mesh['tipWeights']))]:
        lines.append('*NSET,NSET='+name)
        for start in range(0,len(identities),12):lines.append(','.join(map(str,identities[start:start+12])))
    material = prepared['material']; force = prepared['load']['tipForceZ_N']
    lines += ['*MATERIAL,NAME=ELASTIC','*ELASTIC',
              f"{material['youngsModulus_Pa']:.16g},{material['poissonRatio']:.16g}",
              '*SOLID SECTION,ELSET=ALL,MATERIAL=ELASTIC','*BOUNDARY','ROOT,1,3',
              '*STEP','*STATIC','*CLOAD']
    lines.extend(f'{i},3,{force*w:.16g}' for i,w in mesh['tipWeights'].items())
    lines += ['*NODE PRINT,NSET=TIP,GLOBAL=YES','U','*NODE PRINT,NSET=ROOT,GLOBAL=YES','RF',
              '*EL PRINT,ELSET=ALL,GLOBAL=YES','COORD,S','*NODE FILE','U','*EL FILE','S','*END STEP']
    return ('\n'.join(lines)+'\n').encode('ascii')


HEADERS = {'U':r'displacements \(vx,vy,vz\) for set TIP and time',
           'RF':r'forces \(fx,fy,fz\) for set ROOT and time',
           'COORD':r'global coordinates \(elem, integ.pnt.,x,y,z\) for set ALL and time',
           'S':r'stresses \(elem, integ.pnt.,sxx,syy,szz,sxy,sxz,syz\) for set ALL and time'}


def parse_dat(text, mesh):
    """Accept one closed, complete static step with exact node/point membership."""
    sections = {}; active = None; sequence = []
    for line in text.splitlines():
        line = line.strip()
        if not line: continue
        if line in ('S T E P       1','INCREMENT     1'):
            sequence.append(line); continue
        matched = False
        for kind,header in HEADERS.items():
            match = re.fullmatch(header+r'\s+([^ ]+)',line)
            if match:
                try: step_time = float(match[1])
                except ValueError: fault('VERIFICATION_FAILED','malformed native step time')
                if kind in sections or step_time != 1: fault('VERIFICATION_FAILED','unexpected native step or duplicate output section')
                sections[kind] = {}; active = kind; matched = True; break
        if matched: continue
        if active is None: fault('VERIFICATION_FAILED','unrecognised native DAT header')
        values = line.split(); count = 8 if active == 'S' else 4
        integers = 2 if active in ('S','COORD') else 1
        if len(values) != count + (1 if active == 'COORD' else 0): fault('VERIFICATION_FAILED','native output row shape differs',active)
        if not all(re.fullmatch(r'[1-9][0-9]*',v) for v in values[:integers]): fault('VERIFICATION_FAILED','native identities must be positive integers',active)
        identity = tuple(map(int,values[:2])) if integers == 2 else int(values[0])
        try: numbers = list(map(float,values[integers:]))
        except ValueError: fault('VERIFICATION_FAILED','malformed native numeric row',active)
        if identity in sections[active] or not all(math.isfinite(v) for v in numbers): fault('VERIFICATION_FAILED','duplicate or nonfinite native output',active)
        sections[active][identity] = numbers
    if sequence != ['S T E P       1','INCREMENT     1'] or list(sections) != ['U','RF','COORD','S']:
        fault('VERIFICATION_FAILED','expected one complete static step and four native output sections')
    points = {(i,j) for i in range(1,len(mesh['elements'])+1) for j in range(1,9)}
    for key,expected in [('U',set(mesh['tipWeights'])),('RF',set(mesh['root'])),('COORD',points),('S',points)]:
        if set(sections[key]) != expected: fault('VERIFICATION_FAILED','native output membership differs from intended mesh',key)
    return sections


def assess(prepared,stage,text):
    mesh = model(prepared,stage); output = parse_dat(text,mesh)
    L,b,h = (prepared['beam'][k] for k in ('length_m','width_m','height_m'))
    F = prepared['load']['tipForceZ_N']; inertia = prepared['theory']['secondMoment_m4']
    nx,ny,nz = mesh['cells']; stress_rows = []; worst = 0; coordinates_tolerance = 1e-6
    for (element,point),xyz in output['COORD'].items():
        ix,iy,iz = mesh['elements'][element-1]['cell']
        p = point-1; g = [(-1 if not p & (1<<axis) else 1)/math.sqrt(3) for axis in range(3)]
        expected = [(ix+.5+g[0]/2)*L/nx,(iy+.5+g[1]/2)*b/ny-b/2,(iz+.5+g[2]/2)*h/nz-h/2]
        for axis,size in enumerate((L,b,h)):
            if abs(xyz[axis]-expected[axis]) > coordinates_tolerance*size:
                fault('VERIFICATION_FAILED','native integration-point geometry differs',stage,element=element,point=point)
        x,y,z = xyz
        if .3*L <= x <= .7*L:
            stress = output['S'][(element,point)]
            target = -F*(L-x)*z/inertia
            # Section surface stress is a physical scale even for points near
            # the neutral axis; no division by a near-zero sample stress.
            scale = abs(F)*(L-x)*(h/2)/inertia
            error = abs(stress[0]-target)/scale
            worst = max(worst,error)
            stress_rows.append([element,point,*xyz,*stress])
    if not stress_rows: fault('VERIFICATION_FAILED','no interior stress samples')
    tip = [sum(output['U'][i][axis]*w for i,w in mesh['tipWeights'].items()) for axis in range(3)]
    forces = [sum(force[axis] for force in output['RF'].values()) for axis in range(3)]
    moments = [0.,0.,0.]
    for i,force in output['RF'].items():
        x,y,z = mesh['nodes'][i]; fx,fy,fz = force
        moments[0] += y*fz-z*fy; moments[1] += z*fx-x*fz; moments[2] += x*fy-y*fx
    force_error = max(abs(forces[a]+(F if a==2 else 0)) for a in range(3))/abs(F)
    moment_error = max(abs(moments[a]-(L*F if a==1 else 0)) for a in range(3))/(abs(F)*L)
    tip_error = abs(tip[2]-prepared['theory']['tipDeflection_m'])/abs(prepared['theory']['tipDeflection_m'])
    if max(force_error,moment_error) > TOLERANCES['equilibriumScaled']:
        fault('VERIFICATION_FAILED','actual support force or moment fails equilibrium',stage,force=forces,moment=moments)
    if max(abs(tip[0]),abs(tip[1])) > abs(prepared['theory']['tipDeflection_m'])*1e-4:
        fault('VERIFICATION_FAILED','unexpected area-averaged axial or lateral displacement',stage)
    if stage in ('fine','reopened') and (tip_error > TOLERANCES['tipTheoryRelative'] or worst > TOLERANCES['interiorStressScaled']):
        fault('NUMERICAL_ACCEPTANCE_FAILED','fine mesh disagrees with independent slender-beam checks',stage,
              tipTheoryRelativeError=tip_error,interiorStressScaledError=worst)
    native = {'cells':list(mesh['cells']),'nodeCount':len(mesh['nodes']),'elementCount':len(mesh['elements']),
              'tipAreaMeanDisplacement_m':tip,'rootReaction_N':forces,'rootMomentAboutClampCentre_Nm':moments,
              'forceBalanceScaledError':force_error,'momentBalanceScaledError':moment_error,
              'tipTheoryRelativeError':tip_error,'interiorStressScaledError':worst,
              'interiorSampleCount':len(stress_rows),'maxInteriorSampleNormalStress_Pa':max(abs(row[5]) for row in stress_rows)}
    return native,stress_rows
