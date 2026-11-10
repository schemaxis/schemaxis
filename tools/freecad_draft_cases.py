"""Independent tapered-wall geometry oracles and materially different Draft inputs."""
import copy,json,math
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]


def load(name):return json.loads((ROOT/'examples/schemaxis'/('freecad-draft-'+name+'.json')).read_text())


def tilted():
    c,s=math.cos(math.radians(25)),math.sin(math.radians(25));C,S=math.cos(math.radians(30)),math.sin(math.radians(30))
    x=[c,s,0];n=[s*S,-c*S,C];y=[-s*C,c*C,S]
    return {'version':'schemaxis.freecad/1','nodes':[
        {'id':'body','filter':'body'},
        {'id':'outline','filter':'rectangle','options':{'width':40,'height':30,'frame':{'origin':[3,-7,11],'xAxis':x,'normal':n}},'inputs':{'body':'body'}},
        {'id':'pull','filter':'datumAxis','options':{'origin':[3,-7,11],'direction':n},'inputs':{'body':'body'}},
        {'id':'stock','filter':'pad','options':{'length':20},'inputs':{'body':'body','profile':'outline'}},
        {'id':'release','filter':'bodyDraft','options':{'angle':4,'faces':[{'surface':'plane','normal':[sign*v for v in axis]} for axis in (x,y) for sign in (-1,1)]},'inputs':{'base':'stock','neutralPlane':'outline','axis':'pull'}}],
        'output':'release'}


def oracle(document):
    nodes={n['id']:n for n in document['nodes']};release=nodes['release'];angle=release['options'].get('angle',3)
    k=(1 if release['options'].get('reversed',False) else -1)*math.tan(math.radians(angle))
    outline=nodes['outline'];o=outline['options'];cylinder=outline['filter']=='circle';shell='housing' in nodes or 'cavity' in nodes
    params={key:value['value'] for key,value in document.get('parameters',{}).items()}
    H=params.get('height',nodes['stock'].get('options',{}).get('length',20));t=params.get('wall',nodes.get('housing',{}).get('options',{}).get('thickness',2))
    a,b=(o['radius'],0) if cylinder else (o['width'],o['height']);offset=t/math.cos(math.radians(angle))
    def integral(a,b,lo,hi,moment=False):
        if cylinder:
            return math.pi*(a*a*(hi**2-lo**2)/2+2*a*k*(hi**3-lo**3)/3+k*k*(hi**4-lo**4)/4) if moment else math.pi*(a*a*(hi-lo)+a*k*(hi**2-lo**2)+k*k/3*(hi**3-lo**3))
        return a*b*(hi**2-lo**2)/2+2*k*(a+b)*(hi**3-lo**3)/3+k*k*(hi**4-lo**4) if moment else a*b*(hi-lo)+k*(a+b)*(hi**2-lo**2)+4*k*k/3*(hi**3-lo**3)
    V=integral(a,b,0,H);M=integral(a,b,0,H,True)
    ai,bi=(a-offset,0) if cylinder else (a-2*offset,b-2*offset)
    if shell:V-=integral(ai,bi,t,H);M-=integral(ai,bi,t,H,True)
    bosses='boss1' in nodes;bh=params.get('bossHeight',0);r=params.get('mountDiameter',0)/2
    if bosses:
        add=4*math.pi*2**2*bh;remove=4*math.pi*r*r*(t+bh)
        V+=add-remove;M+=add*(t+bh/2)-remove*(t+bh)/2
    f=o.get('frame',{'origin':o.get('origin',[0,0,0]),'xAxis':[1,0,0],'normal':[0,0,1]});origin=f['origin'];x=f['xAxis'];n=f['normal'];y=[n[1]*x[2]-n[2]*x[1],n[2]*x[0]-n[0]*x[2],n[0]*x[1]-n[1]*x[0]]
    def world(q):return [origin[i]+x[i]*q[0]+y[i]*q[1]+n[i]*q[2] for i in range(3)]
    if cylinder:
        bounds=[extreme(origin[i]+n[i]*z+sign*(a+k*z)*math.sqrt(max(0,1-n[i]*n[i])) for z in (0,H) for sign in (-1,1)) for i in range(3) for extreme in (min,max)]
    else:
        corners=[world([sx*(a+2*k*z)/2,sy*(b+2*k*z)/2,z]) for z in (0,H) for sx in (-1,1) for sy in (-1,1)]
        bounds=[extreme(q[i] for q in corners) for i in range(3) for extreme in (min,max)]
    sections={}
    for z in (1,5,15):
        outer=math.pi*(a+k*z)**2 if cylinder else (a+2*k*z)*(b+2*k*z)
        areas=[outer]
        if shell and z>t:areas.append(math.pi*(ai+k*z)**2 if cylinder else (ai+2*k*z)*(bi+2*k*z))
        if bosses:
            if t<z<t+bh:areas.extend([4*math.pi]*4)
            if z<t+bh:areas.extend([math.pi*r*r]*4)
        sections[str(z)]={'distance':sum(origin[i]*n[i] for i in range(3))+z,'areas':sorted(areas)}
    points=[{'point':world([0,0,10]),'inside':not shell},{'point':world([0,0,1]),'inside':True}]
    points.append({'point':world([14.5 if cylinder else 18,0,10]),'inside':True})
    points.append({'point':world([30,0,10]),'inside':False})
    if bosses:points.extend([{'point':[-14,-9,5],'inside':False},{'point':[-12.25,-9,5],'inside':True}])
    return {'volume':V,'centre':world([0,0,M/V]),'bounds':bounds,'normal':n,'sections':sections,'points':points,
            'lidVolume':(1176-math.pi)*t if bosses else None}


def changed(document,number):
    document=copy.deepcopy(document)
    values={'wall':2.5,'height':24,'bossHeight':4,'mountDiameter':2.5} if number==1 else {'wall':3,'height':18,'bossHeight':5,'mountDiameter':1.5}
    for key,value in values.items():document['parameters'][key]['value']=value
    next(n for n in document['nodes'] if n['id']=='release')['options']['angle']=5 if number==1 else 2
    return document
