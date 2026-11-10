"""Independent exact layered conduction solution and bounded native field parser."""
import math
import re
from schemaxis.errors import fail


def check(condition, message):
    if not condition: fail('VERIFICATION_FAILED', message)


def mesh(p):
    x=[0.0]; elements=[]
    for index,layer in enumerate(p['layers']):
        start=x[-1]
        for i in range(layer['cells']):
            x.append(start+layer['thickness_m']*(i+1)/layer['cells'])
            elements.append(index)
    return x,elements


def propagate(p,t,q):
    nodes=[t];midflux=[];x,elements=mesh(p)
    for i,material in enumerate(elements):
        layer=p['layers'][material];dx=x[i+1]-x[i];s=layer['source'];k=layer['conductivity']
        midflux.append(q+s*dx/2)
        t-=q*dx/k+s*dx*dx/(2*k);q+=s*dx;nodes.append(t)
    return nodes,midflux,q


def exact(p):
    # Transfer relation T_R = T_L - R*q_L - B, q_R = q_L + G.
    r=sum(l['thickness_m']/l['conductivity'] for l in p['layers'])
    b=-propagate(p,0,0)[0][-1];g=sum(l['source']*l['thickness_m'] for l in p['layers'])
    equations=[]
    for side in ('left','right'):
        bc=p[side];kind=bc['kind']
        if side=='left':
            row={'value':(1,0,bc.get('value',0)), 'flux':(0,-1,bc.get('value',0)),
                 'convection':(-bc.get('coefficient',0),-1,-bc.get('coefficient',0)*bc.get('ambient',0))}[kind]
        else:
            h=bc.get('coefficient',0)
            row={'value':(1,-r,bc.get('value',0)+b), 'flux':(0,1,bc.get('value',0)-g),
                 'convection':(-h,1+h*r,-g-h*(b+bc.get('ambient',0)))}[kind]
        equations.append(row)
    a,c,u=equations[0];b,d,v=equations[1];det=a*d-b*c
    if not math.isfinite(det) or det==0: fail('UNANCHORED_FIELD','at least one value or convection boundary must anchor the field','$.left')
    t=(u*d-v*c)/det;q=(a*v-b*u)/det
    nodes,flux,qr=propagate(p,t,q)
    if any(not math.isfinite(v) or abs(v)>1e12 for v in nodes+flux+[q,qr]):
        fail('RESOURCE_LIMIT','field or flux exceeds the bounded numeric scale; rescale material/source inputs')
    extrema=list(nodes);t0=t;q0=q
    for layer in p['layers']:
        length=layer['thickness_m'];source=layer['source'];k=layer['conductivity']
        if source and 0 < -q0/source < length:
            distance=-q0/source;extrema.append(t0-q0*distance/k-source*distance*distance/(2*k))
        t0-=q0*length/k+source*length*length/(2*k);q0+=source*length
    if p['operation']=='steadyHeat' and min(extrema)<0: fail('INVALID_TEMPERATURE','exact continuum temperature, including interior extrema, must be nonnegative kelvin')
    return nodes,flux,q,qr


def read_pos(path,p,vector=False):
    text=path.read_text();x,elements=mesh(p);rows=[]
    tag='VL' if vector else 'SL';width=6 if vector else 2
    pattern=re.compile(r'\b'+tag+r'\(([^()]*)\)\s*\{([^{}]*)\}\s*;')
    for match in pattern.finditer(text):
        coords=[float(v) for v in match[1].split(',')];values=[float(v) for v in match[2].split(',')]
        check(len(coords)==6 and len(values)==width and all(math.isfinite(v) for v in coords+values),'invalid native field record')
        rows.append((coords,values))
    check(len(rows)==len(elements),'native field element membership differs')
    rows.sort(key=lambda row:row[0][0])
    for i,(coords,values) in enumerate(rows):
        check(all(math.isclose(a,b,rel_tol=1e-8,abs_tol=1e-11) for a,b in zip(coords,[x[i],0,0,x[i+1],0,0])),'native mesh coordinates differ')
        if vector:check(all(abs(values[j])<=1e-12 for j in (1,2,4,5)),'unexpected transverse flux')
    if vector:
        check(all(math.isclose(v[0],v[3],rel_tol=1e-9,abs_tol=1e-9) for _,v in rows),'linear-element flux is not constant')
        return [v[0] for _,v in rows]
    for (_,a),(_,b) in zip(rows,rows[1:]):check(math.isclose(a[1],b[0],rel_tol=1e-9,abs_tol=1e-8),'field is discontinuous at layer/node interface')
    return [rows[0][1][0]]+[v[1] for _,v in rows]


def inspect(p,nodes,flux):
    expected,expected_flux,ql,qr=exact(p)
    scale=max(1,*map(abs,expected));fscale=max(1,*map(abs,expected_flux))
    error=max(abs(a-b) for a,b in zip(nodes,expected));ferror=max(abs(a-b) for a,b in zip(flux,expected_flux))
    check(len(nodes)==len(expected) and len(flux)==len(expected_flux),'native field size differs')
    check(error<=2e-7*scale and ferror<=2e-7*fscale,'native field differs from independent piecewise-quadratic conduction solution')
    x,elements=mesh(p)
    # Recover physical end flux from native linear-element midpoint flux and source.
    left=-flux[0]+p['layers'][0]['source']*(x[1]-x[0])/2
    right=flux[-1]+p['layers'][-1]['source']*(x[-1]-x[-2])/2
    generation=sum(l['source']*l['thickness_m'] for l in p['layers'])
    residual=left+right-generation
    check(abs(residual)<=4e-7*max(1,abs(left),abs(right),abs(generation)),'native global source/outflow balance fails')
    for i in range(1,len(flux)):
        l=p['layers'][elements[i-1]];r=p['layers'][elements[i]]
        mismatch=flux[i-1]+l['source']*(x[i]-x[i-1])/2-flux[i]+r['source']*(x[i+1]-x[i])/2
        check(abs(mismatch)<=4e-7*fscale,'native interface flux balance fails')
    return {'maximumFieldError':error,'maximumFluxError':ferror,'leftOutwardFlux':left,'rightOutwardFlux':right,
            'generatedTotal':generation*p['area_m2'],'leftOutflowTotal':left*p['area_m2'],'rightOutflowTotal':right*p['area_m2'],
            'balanceResidual':residual*p['area_m2'],'minimumField':min(nodes),'maximumField':max(nodes),
            'maxAbsFlux':max(abs(v) for v in flux),'length_m':x[-1],'nodes':len(nodes),'elements':len(flux)}


def read_solution(directory,p):
    """Reconstruct nodal values from documented GetDP ASCII dof/equation mapping."""
    pre=(directory/'model.pre').read_text().splitlines();res=(directory/'model.res').read_text().splitlines()
    check(pre.count('$EndDofData')==1 and res.count('$EndSolution')==1 and sum(line.startswith('$DofData') for line in pre)==1 and sum(line.startswith('$Solution') for line in res)==1,'expected one static scalar native system')
    begin=next(i for i,line in enumerate(pre) if line.startswith('$DofData'))
    header=pre[begin+1:begin+6]
    check(header[:4]==['0 0','1 0','1 0','1 0'],'unexpected native dof system header')
    total,unknown=map(int,header[4].split());x,_=mesh(p)
    check(total==len(x),'native dof count differs from mesh')
    start=next(i for i,line in enumerate(res) if line.startswith('$Solution'))
    check(res[start+1]=='0 0 0 0' and '1.1 0' in res,'native result must be a static ASCII solution')
    values=[]
    for line in res[start+2:res.index('$EndSolution')]:
        parts=[float(v) for v in line.split()];check(len(parts)==2 and all(math.isfinite(v) for v in parts) and parts[1]==0,'invalid real native solution row');values.append(parts[0])
    check(len(values)==unknown,'native unknown equation count differs')
    rows=pre[begin+6:pre.index('$EndDofData')];check(len(rows)==total,'native dof membership differs');nodes={};equations=set()
    for line in rows:
        parts=line.split();basis,entity,harmonic,kind=map(int,parts[:4])
        check(basis==1 and harmonic==0 and 1<=entity<=total and entity not in nodes,'native nodal identity differs')
        if kind==1:
            check(len(parts)==6 and parts[-1]=='1','invalid native unknown mapping');equation=int(parts[4]);check(1<=equation<=unknown and equation not in equations,'invalid native equation numbering');equations.add(equation);value=values[equation-1]
        elif kind==2:
            check(len(parts)==7 and parts[-2:]==['0','0'],'invalid native fixed mapping');value=float(parts[4]);check(math.isfinite(value),'nonfinite fixed native value')
        else:check(False,'unsupported native degree-of-freedom type')
        nodes[entity]=value
    check(len(equations)==unknown,'native equation membership differs')
    return [nodes[i+1] for i in range(total)]
