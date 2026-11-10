"""Independent direct-stiffness mechanics, with no OpenSees dependency."""
import math
from schemaxis.errors import fail


def system(p):
    nodes=p['nodes']; index={n['id']:i for i,n in enumerate(nodes)}; count=2*len(nodes)
    K=[[0.0]*count for _ in range(count)]; F=[0.0]*count; fixed=set(); geometries=[]
    for i,n in enumerate(nodes):
        fixed.update(2*i+j for j in range(2) if n['fixed'][j])
    for load in p['loads']:
        i=index[load['node']]
        for j in range(2): F[2*i+j]+=load['force_N'][j]
    for m in p['members']:
        a,b=(index[m[k]] for k in ('a','b')); dx=nodes[b]['x_m']-nodes[a]['x_m']; dy=nodes[b]['y_m']-nodes[a]['y_m']
        L=math.hypot(dx,dy)
        if L < 1e-6: fail('INVALID_TRUSS','member length must be at least 1 micrometre','$.members')
        c,s=dx/L,dy/L; v=[-c,-s,c,s]; dofs=[2*a,2*a+1,2*b,2*b+1]; k=m['youngsModulus_Pa']*m['area_m2']/L
        for i in range(4):
            for j in range(4): K[dofs[i]][dofs[j]]+=k*v[i]*v[j]
        geometries.append((L,v,dofs,k))
    return K,F,fixed,geometries


def solve(p):
    K,F,fixed,geometries=system(p); free=[i for i in range(len(F)) if i not in fixed]
    if not free: fail('INVALID_TRUSS','provide at least one free degree of freedom','$.nodes')
    # Diagonal scaling makes the Cholesky stability test dimensionless.
    scales=[math.sqrt(K[i][i]) if K[i][i]>0 else 0 for i in free]
    if not all(scales): fail('UNSTABLE_TRUSS','unrestrained degree of freedom has no stiffness','$.nodes')
    n=len(free); L=[[0.0]*n for _ in range(n)]
    for i in range(n):
        for j in range(i+1):
            value=K[free[i]][free[j]]/(scales[i]*scales[j])-math.fsum(L[i][k]*L[j][k] for k in range(j))
            if i==j:
                if value < 1e-9: fail('UNSTABLE_TRUSS','network is a mechanism or too ill-conditioned; brace it or revise supports','$.nodes')
                L[i][j]=math.sqrt(value)
            else: L[i][j]=value/L[j][j]
    y=[]
    for i in range(n): y.append((F[free[i]]/scales[i]-math.fsum(L[i][j]*y[j] for j in range(i)))/L[i][i])
    z=[0.0]*n
    for i in reversed(range(n)): z[i]=(y[i]-math.fsum(L[j][i]*z[j] for j in range(i+1,n)))/L[i][i]
    u=[0.0]*len(F)
    for i,dof in enumerate(free): u[dof]=z[i]/scales[i]
    R=[math.fsum(a*b for a,b in zip(row,u))-f for row,f in zip(K,F)]
    members=[]
    for m,(length,v,dofs,k) in zip(p['members'],geometries):
        strain=math.fsum(v[i]*u[dofs[i]] for i in range(4))/length
        if abs(strain)>.001: fail('INVALID_TRUSS','linear product requires member strain <=0.001','$.loads')
        members.append({'id':m['id'],'length_m':length,'force_N':strain*m['youngsModulus_Pa']*m['area_m2'],'stress_Pa':strain*m['youngsModulus_Pa'],'strain':strain})
    for i,node in enumerate(p['nodes']):
        lengths=[g[0] for m,g in zip(p['members'],geometries) if node['id'] in (m['a'],m['b'])]
        if math.hypot(*u[2*i:2*i+2])>.01*min(lengths): fail('INVALID_TRUSS','translation exceeds 1% of adjacent member length','$.loads')
    return {'nodes':[{'id':node['id'],'displacement_m':u[2*i:2*i+2],'reaction_N':R[2*i:2*i+2]} for i,node in enumerate(p['nodes'])], 'members':members}


def check(p,native):
    expected=solve(p)
    def near(a,b,absolute):
        if type(a) not in (int,float) or not math.isfinite(a) or not math.isclose(a,b,rel_tol=1e-7,abs_tol=absolute):
            fail('VERIFICATION_FAILED','native mechanics disagree with independent direct stiffness reference')
    if set(native)!=set(expected): fail('VERIFICATION_FAILED','native result membership differs')
    for kind in ('nodes','members'):
        if len(native[kind])!=len(expected[kind]): fail('VERIFICATION_FAILED','native result shape differs')
        for got,want in zip(native[kind],expected[kind]):
            if set(got)!=set(want) or got['id']!=want['id']: fail('VERIFICATION_FAILED','native identity differs')
            for key,value in want.items():
                if key=='id': continue
                if isinstance(value,list):
                    if not isinstance(got[key],list) or len(got[key])!=2: fail('VERIFICATION_FAILED','native vector shape differs')
                    for a,b in zip(got[key],value): near(a,b,1e-12 if key=='displacement_m' else 1e-6)
                else: near(got[key],value,1e-12 if key=='strain' else 1e-6)
    fx=fy=moment=0.0
    for node,row in zip(p['nodes'],native['nodes']):
        rx,ry=row['reaction_N']; fx+=rx;fy+=ry;moment+=node['x_m']*ry-node['y_m']*rx
    for load in p['loads']:
        node=next(n for n in p['nodes'] if n['id']==load['node']); x,y=load['force_N'];fx+=x;fy+=y;moment+=node['x_m']*y-node['y_m']*x
    scale=max(1,sum(math.hypot(*v['force_N']) for v in p['loads'])); length=max(1,max(math.hypot(n['x_m'],n['y_m']) for n in p['nodes']))
    if max(abs(fx),abs(fy),abs(moment)/length)>1e-7*scale: fail('VERIFICATION_FAILED','native force or moment equilibrium failed')
    return {'method':'independent scaled Cholesky direct stiffness; per-member constitutive and global force/moment balance','forceResidual_N':[fx,fy],'momentResidual_Nm':moment,'relativeTolerance':1e-7}
