"""Independent exact layered conduction solution and bounded native field parser."""
import math
import re
from schemaxis.core.faults import Fault, SchemaxisError

def fail(code,message,location='$'):
    recovery={'UNANCHORED_FIELD':'Set at least one end to a fixed temperature or positive convection film.',
        'INVALID_TEMPERATURE':'Use nonnegative kelvin throughout the continuum, including between-node extrema; revise sources or end conditions.',
        'RESOURCE_LIMIT':'Rescale the material/source inputs to the declared bounded numeric range.',
        'VERIFICATION_FAILED':'Restore complete original native evidence or execute the thermal model in a fresh directory.'}.get(code,'Correct the thermal input and retry.')
    raise SchemaxisError(Fault(code,message,location,'pipeline',recovery=recovery))


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
        layer=p['layers'][material];dx=x[i+1]-x[i];s=layer['heatGeneration_W_m3'];k=layer['conductivity_W_mK']
        midflux.append(q+s*dx/2)
        t-=q*dx/k+s*dx*dx/(2*k);q+=s*dx;nodes.append(t)
    return nodes,midflux,q


def exact(p):
    # Transfer relation T_R = T_L - R*q_L - B, q_R = q_L + G.
    r=sum(l['thickness_m']/l['conductivity_W_mK'] for l in p['layers'])
    b=-propagate(p,0,0)[0][-1];g=sum(l['heatGeneration_W_m3']*l['thickness_m'] for l in p['layers'])
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
        length=layer['thickness_m'];source=layer['heatGeneration_W_m3'];k=layer['conductivity_W_mK']
        if source and 0 < -q0/source < length:
            distance=-q0/source;extrema.append(t0-q0*distance/k-source*distance*distance/(2*k))
        t0-=q0*length/k+source*length*length/(2*k);q0+=source*length
    if min(extrema)<0: fail('INVALID_TEMPERATURE','exact continuum temperature, including interior extrema, must be nonnegative kelvin')
    return nodes,flux,q,qr


def inspect(p,nodes,flux):
    expected,expected_flux,ql,qr=exact(p)
    scale=max(1,*map(abs,expected));fscale=max(1,*map(abs,expected_flux))
    error=max(abs(a-b) for a,b in zip(nodes,expected));ferror=max(abs(a-b) for a,b in zip(flux,expected_flux))
    check(len(nodes)==len(expected) and len(flux)==len(expected_flux),'native field size differs')
    check(error<=2e-7*scale and ferror<=2e-7*fscale,'native field differs from independent piecewise-quadratic conduction solution')
    x,elements=mesh(p)
    # Recover physical end flux from native linear-element midpoint flux and source.
    left=-flux[0]+p['layers'][0]['heatGeneration_W_m3']*(x[1]-x[0])/2
    right=flux[-1]+p['layers'][-1]['heatGeneration_W_m3']*(x[-1]-x[-2])/2
    generation=sum(l['heatGeneration_W_m3']*l['thickness_m'] for l in p['layers'])
    residual=left+right-generation
    check(abs(residual)<=4e-7*max(1,abs(left),abs(right),abs(generation)),'native global source/outflow balance fails')
    for i in range(1,len(flux)):
        l=p['layers'][elements[i-1]];r=p['layers'][elements[i]]
        mismatch=flux[i-1]+l['heatGeneration_W_m3']*(x[i]-x[i-1])/2-flux[i]+r['heatGeneration_W_m3']*(x[i+1]-x[i])/2
        check(abs(mismatch)<=4e-7*fscale,'native interface flux balance fails')
    return {'maximumFieldError':error,'maximumFluxError':ferror,'leftOutwardFlux':left,'rightOutwardFlux':right,
            'generatedTotal':generation*p['area_m2'],'leftOutflowTotal':left*p['area_m2'],'rightOutflowTotal':right*p['area_m2'],
            'balanceResidual':residual*p['area_m2'],'minimumField':min(nodes),'maximumField':max(nodes),
            'maxAbsFlux':max(abs(v) for v in flux),'length_m':x[-1],'nodes':len(nodes),'elements':len(flux)}
