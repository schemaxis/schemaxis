# Copyright (C) 2026 David L F Gaden
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

LOAD_KEYS = ('tipForceX_N','tipForceY_N','tipForceZ_N','tipMomentX_Nm','tipMomentY_Nm','tipMomentZ_Nm')


def torsion_constant(width,height):
    """Saint-Venant rectangular torsion series, retaining 100 odd harmonics."""
    a,b = max(width,height),min(width,height)
    return a*b**3/3*(1-192*b/(math.pi**5*a)*sum(math.tanh(n*math.pi*a/(2*b))/n**5 for n in range(1,200,2)))


def torsion_shear(width,height,y,z,torque):
    """Independent Prandtl stress function: return tau_xy,tau_xz in Pa.

    The cosh/sinh ratios use decaying exponentials to avoid overflow. Swapping
    section coordinates reverses orientation, so shear components/signs swap.
    """
    if width < height:
        xy,xz = torsion_shear(height,width,z,y,-torque)
        return xz,xy
    a,b = width/2,height/2; sine = cosine = 0.
    for n in range(1,200,2):
        k = n*math.pi/(2*b); sign = (-1)**((n-1)//2)
        decay = math.exp(k*(abs(y)-a)); denominator = 1+math.exp(-2*k*a)
        c = decay*(1+math.exp(-2*k*abs(y)))/denominator
        sh = math.copysign(decay*(1-math.exp(-2*k*abs(y)))/denominator,y)
        sine += sign*c*math.sin(k*z)/n**2
        cosine += sign*sh*math.cos(k*z)/n**2
    factor = torque/torsion_constant(width,height)
    return factor*(-2*z+16*b/math.pi**2*sine),factor*16*b/math.pi**2*cosine


def face_moments(ny,nz,width,height,identities):
    """Integrate N_i*y and N_i*z with exact degree-five Gauss quadrature.

    Consistent moment loading and rotation observation are work conjugate;
    area weights alone are insufficient for a quadratic face's first moments.
    """
    moments = {i:[0.,0.] for i in identities.values()}
    gauss = [(-math.sqrt(3/5),5/9),(0,8/9),(math.sqrt(3/5),5/9)]
    for iy in range(ny):
        for iz in range(nz):
            for u,wu in gauss:
                for v,wv in gauss:
                    y = (iy+(u+1)/2)*width/ny-width/2
                    z = (iz+(v+1)/2)*height/nz-height/2
                    for ly,lz,_ in FACE_WEIGHTS:
                        sy,sz = ly-1,lz-1
                        if sy and sz: shape=(1+sy*u)*(1+sz*v)*(sy*u+sz*v-1)/4
                        elif not sy: shape=(1-u*u)*(1+sz*v)/2
                        else: shape=(1-v*v)*(1+sy*u)/2
                        row = moments[identities[(2*iy+ly,2*iz+lz)]]
                        row[0] += shape*wu*wv*y/(4*ny*nz)
                        row[1] += shape*wu*wv*z/(4*ny*nz)
    for row in moments.values():
        for axis,size in enumerate((width,height)):
            if abs(row[axis]) < size*1e-16: row[axis]=0.
    return moments


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
    first = face_moments(ny,nz,b,h,{(y,z):i for (x,y,z),i in nodes.items() if x==2*nx})
    return {'tipFirstMoments':first,'nodes':xyz,'elements':elements,'root':root,'tipWeights':weights,'cells':(nx,ny,nz)}


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
    material = prepared['material']; Fx,Fy,Fz,Mx,My,Mz = (prepared['load'][k] for k in LOAD_KEYS)
    b,h = prepared['beam']['width_m'],prepared['beam']['height_m']
    area=b*h; iy=b*h**3/12; iz=h*b**3/12; polar=iy+iz
    lines += ['*MATERIAL,NAME=ELASTIC','*ELASTIC',
              f"{material['youngsModulus_Pa']:.16g},{material['poissonRatio']:.16g}",
              '*SOLID SECTION,ELSET=ALL,MATERIAL=ELASTIC','*BOUNDARY']
    if prepared['support'] == 'clamped': lines.append('ROOT,1,3')
    else:
        lines.append('ROOT,1,1')
        for i in mesh['root']:
            _,y,z=mesh['nodes'][i]
            if abs(y)<b*1e-12: lines.append(f'{i},2,2')
            if abs(z)<h*1e-12: lines.append(f'{i},3,3')
    lines += ['*STEP','*STATIC','*CLOAD']
    for i,w in mesh['tipWeights'].items():
        wy,wz = mesh['tipFirstMoments'][i]
        loads = [Fx*w+My*area*wz/iy-Mz*area*wy/iz,
                 Fy*w-Mx*area*wz/polar,Fz*w+Mx*area*wy/polar]
        lines.extend(f'{i},{axis},{value:.12g}' for axis,value in enumerate(loads,1) if value)
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
    Fx,Fy,Fz,Mx,My,Mz = (prepared['load'][k] for k in LOAD_KEYS)
    inertia = prepared['theory']['secondMoment_m4']; izz=prepared['theory']['secondMomentZ_m4']; area=b*h
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
            target = Fx/area+(My-Fz*(L-x))*z/inertia-(Mz+Fy*(L-x))*y/izz
            # Section surface stress is a physical scale even for points near
            # the neutral axis; no division by a near-zero sample stress.
            scale = abs(Fx)/area+(abs(My)+abs(Fz)*(L-x))*h/(2*inertia)+(abs(Mz)+abs(Fy)*(L-x))*b/(2*izz)
            error = abs(stress[0]-target)/(scale or abs(Mx)*max(b,h)/prepared['theory']['torsionConstant_m4'])
            worst = max(worst,error)
            stress_rows.append([element,point,*xyz,*stress])
    if not stress_rows: fault('VERIFICATION_FAILED','no interior stress samples')
    tip = [sum(output['U'][i][axis]*w for i,w in mesh['tipWeights'].items()) for axis in range(3)]
    forces = [sum(force[axis] for force in output['RF'].values()) for axis in range(3)]
    moments = [0.,0.,0.]
    for i,force in output['RF'].items():
        x,y,z = mesh['nodes'][i]; fx,fy,fz = force
        moments[0] += y*fz-z*fy; moments[1] += z*fx-x*fz; moments[2] += x*fy-y*fx
    force_scale = max(abs(v) for v in (Fx,Fy,Fz,Mx/L,My/L,Mz/L))
    moment_scale = max(abs(v) for v in (Fx*L,Fy*L,Fz*L,Mx,My,Mz))
    force_error = max(abs(forces[a]+value) for a,value in enumerate((Fx,Fy,Fz)))/force_scale
    moment_error = max(abs(moments[a]-value) for a,value in enumerate((-Mx,L*Fz-My,-L*Fy-Mz)))/moment_scale
    reference = prepared['theory']['tipTranslation_m']; scales=prepared['theory']['translationScales_m']
    displacement_errors = [abs(tip[a]-reference[a])/(scale or max(scales+[abs(prepared['theory']['tipTwist_rad'])*max(b,h)])*1e-4) for a,scale in enumerate(scales)]
    tip_error = max((error for error,scale in zip(displacement_errors,scales) if scale),default=0)
    twist = sum(mesh['tipFirstMoments'][i][0]*output['U'][i][2]-mesh['tipFirstMoments'][i][1]*output['U'][i][1] for i in mesh['tipWeights'])*area/(inertia+izz)
    twist_error = abs(twist-prepared['theory']['tipTwist_rad'])/abs(prepared['theory']['tipTwist_rad']) if Mx else 0
    torsion_error = 0.
    if Mx:
        # Project even-y/odd-z (xy) and odd-y/even-z (xz) parity to
        # isolate torsion from axial and biaxial bending shear. The result
        # must match the independent Prandtl stress-function series.
        lookup = {}
        for element,entry in enumerate(mesh['elements'],1):
            ix,iy,iz=entry['cell']
            for point in range(1,9):
                p=point-1; lookup[(ix,2*iy+(1 if p&2 else 0),2*iz+(1 if p&4 else 0),p&1)]=(element,point)
        for row in stress_rows:
            element,point=row[:2];ix,iy,iz=mesh['elements'][element-1]['cell'];p=point-1
            gy=2*iy+(1 if p&2 else 0);gz=2*iz+(1 if p&4 else 0)
            sy=output['S'][lookup[(ix,2*ny-1-gy,gz,p&1)]]
            sz=output['S'][lookup[(ix,gy,2*nz-1-gz,p&1)]]
            syz=output['S'][lookup[(ix,2*ny-1-gy,2*nz-1-gz,p&1)]]
            expected=torsion_shear(b,h,row[3],row[4],Mx)
            observed=[(row[8]+sy[3]-sz[3]-syz[3])/4,(row[9]+sz[4]-sy[4]-syz[4])/4]
            scale=abs(Mx)*max(b,h)/prepared['theory']['torsionConstant_m4']
            torsion_error=max(torsion_error,*(abs(a-e)/scale for a,e in zip(observed,expected)))
    if max(force_error,moment_error) > TOLERANCES['equilibriumScaled']:
        fault('VERIFICATION_FAILED','actual support force or moment fails equilibrium',stage,force=forces,moment=moments)
    if any(error>1 for error,scale in zip(displacement_errors,scales) if not scale):
        fault('VERIFICATION_FAILED','unexpected area-averaged displacement in an unloaded direction',stage,displacement=tip)
    if stage in ('fine','reopened') and (max(tip_error,twist_error) > TOLERANCES['tipTheoryRelative'] or max(worst,torsion_error) > TOLERANCES['interiorStressScaled']):
        fault('NUMERICAL_ACCEPTANCE_FAILED','fine mesh disagrees with independent axial/bending/torsion checks',stage,
              tipTheoryRelativeError=tip_error,twistTheoryRelativeError=twist_error,interiorStressScaledError=worst,interiorTorsionScaledError=torsion_error)
    def von_mises(row):
        xx,yy,zz,xy,xz,yz=row[5:]
        try: value=math.sqrt(((xx-yy)**2+(yy-zz)**2+(zz-xx)**2)/2+3*(xy**2+xz**2+yz**2))
        except OverflowError: fault('VERIFICATION_FAILED','native equivalent stress exceeds the finite numeric range',stage)
        if not math.isfinite(value): fault('VERIFICATION_FAILED','native equivalent stress is not finite',stage)
        return value
    native = {'cells':list(mesh['cells']),'nodeCount':len(mesh['nodes']),'elementCount':len(mesh['elements']),
              'tipAreaMeanDisplacement_m':tip,'rootReaction_N':forces,'rootMomentAboutClampCentre_Nm':moments,
              'forceBalanceScaledError':force_error,'momentBalanceScaledError':moment_error,
              'tipTwist_rad':twist,'twistTheoryRelativeError':twist_error,'interiorTorsionScaledError':torsion_error,
              'maxInteriorSampleVonMises_Pa':max(von_mises(row) for row in stress_rows),
              'tipTheoryRelativeError':tip_error,'interiorStressScaledError':worst,
              'interiorSampleCount':len(stress_rows),'maxInteriorSampleNormalStress_Pa':max(abs(row[5]) for row in stress_rows)}
    return native,stress_rows
