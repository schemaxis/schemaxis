"""Independent noncommuting profile/Body/component fixtures for Body layout."""
import copy
import math

BODY={'origin':[7,-11,13],'xAxis':[.6,.8,0],'normal':[.48,-.36,.8]}
CHANGED_BODY={'origin':[-5,17,29],'xAxis':[0,-1,0],'normal':[1,0,0]}
OTHER_BODY={'origin':[41,43,47],'xAxis':[-.8,.6,0],'normal':[.36,.48,.8]}
PROFILE={'origin':[3,4,5],'xAxis':[0,1,0],'normal':[1,0,0]}


def document(*,attached=False,multiple=False,thickness=7,body_frame=BODY,bore_x=3):
    result={'version':'schemaxis.freecad/1','parameters':{
        'thickness':{'kind':'length','value':thickness,'minimum':5,'maximum':11}},'nodes':[
        {'id':'part','filter':'body','options':{'frame':copy.deepcopy(body_frame)}},
        {'id':'outline','filter':'rectangle','options':{'width':24,'height':16,'frame':copy.deepcopy(PROFILE)},'inputs':{'body':'part'}},
        {'id':'slab','filter':'pad','inputs':{'body':'part','profile':'outline'},'drive':{'length':{'terms':{'thickness':1}}}},
        {'id':'bore','filter':'circle','options':{'radius':2,'centre':[bore_x,2],
            **({'onFace':{'face':'right','anchor':'centroid'}} if attached else {'frame':copy.deepcopy(PROFILE)})},
            'inputs':{'body':'part',**({'support':'slab'} if attached else {})}},
        {'id':'finished','filter':'pocket','options':{'direction':'backward' if attached else 'forward'},
            'inputs':{'base':'slab','profile':'bore'}}], 'output':'finished',
        'measurements':[{'id':'featureCentre','node':'finished','quantity':'centreOfMass'},
                        {'id':'featureBounds','node':'finished','quantity':'bounds'},
                        {'id':'intermediateCentre','node':'slab','quantity':'centreOfMass'},
                        {'id':'intermediateBounds','node':'slab','quantity':'bounds'},
                        {'id':'worldEdges','node':'slab','quantity':'edgeCount','edges':{'where':{'parallelTo':copy.deepcopy(body_frame['xAxis'])},'expect':4}},
                        {'id':'worldEdgeLength','node':'slab','quantity':'totalEdgeLength','edges':{'where':{'parallelTo':copy.deepcopy(body_frame['xAxis'])},'expect':4}}]}
    if multiple:result['nodes'].extend([
        {'id':'other','filter':'body','options':{'frame':copy.deepcopy(OTHER_BODY)}},
        {'id':'otherProfile','filter':'circle','options':{'radius':3,'origin':[2,3,4]},'inputs':{'body':'other'}},
        {'id':'otherTip','filter':'pad','options':{'length':5},'inputs':{'body':'other','profile':'otherProfile'}}])
    return result


def matrix(frame):
    x,n=frame['xAxis'],frame['normal'];y=[n[1]*x[2]-n[2]*x[1],n[2]*x[0]-n[0]*x[2],n[0]*x[1]-n[1]*x[0]]
    return [[x[i],y[i],n[i],frame['origin'][i]] for i in range(3)]+[[0,0,0,1]]


def mul(a,b):return [[sum(a[i][k]*b[k][j] for k in range(4)) for j in range(4)] for i in range(4)]
def apply(m,p):return [sum(m[i][j]*p[j] for j in range(3))+m[i][3] for i in range(3)]
def flat(m):return [v for row in m for v in row]
def translation(p):return [[int(i==j) for j in range(3)]+[p[i]] for i in range(3)]+[[0,0,0,1]]


def clock(degrees):
    c,s=math.cos(math.radians(degrees)),math.sin(math.radians(degrees))
    return [[c,-s,0,0],[s,c,0,0],[0,0,1,0],[0,0,0,1]]


def local(thickness=7,bore_x=3):
    area=384-4*math.pi
    return {'volume':area*thickness,'area':2*area+80*thickness+4*math.pi*thickness,
        'centreOfMass':[3+thickness/2,4-4*math.pi*bore_x/area,5-8*math.pi/area],
        'bounds':[3,3+thickness,-8,16,-3,13]}


def placed(transform,thickness=7):
    value=local(thickness);points=[apply(transform,[x,y,z]) for x in (3,3+thickness) for y in (-8,16) for z in (-3,13)]
    return {**value,'centreOfMass':apply(transform,value['centreOfMass']),
            'bounds':[f(p[d] for p in points) for d in range(3) for f in (min,max)]}


def assembly(producers):
    # Keep parametered as the pure-guard part ID shared with the generic tool.
    parts=[{'id':key,'source':str(value/'model.FCStd'),
            'mounts':{'base':{},'neck':{'position':[{'terms':{'thickness':1},'offset':3},4,5],'z':'+X','x':'+Y'}}}
           for key,value in producers.items()]
    components=[{'id':'fixed','part':'parametered','position':[-17,19,23],'rotation':-23},
                {'id':'attached','part':'attached'},{'id':'again','part':'parametered'}]
    joints=[{'id':'join','type':'fixed','parent':{'component':'fixed','mount':'neck'},
             'child':{'component':'attached','mount':'base'},'offset':[11,13,17],'clocking':31},
            {'id':'duplicate','type':'fixed','parent':{'component':'fixed','mount':'base'},
             'child':{'component':'again','mount':'base'},'offset':[70,5,9],'clocking':47}]
    if 'multiple' in producers:
        components.append({'id':'multiple','part':'multiple'})
        joints.append({'id':'multiPlacement','type':'fixed','parent':{'component':'fixed','mount':'base'},
                       'child':{'component':'multiple','mount':'base'},'offset':[-60,7,-9],'clocking':13})
    return {'version':'schemaxis.freecad.assembly/1','parts':parts,'components':components,
            'grounded':'fixed','joints':joints}


def poses(thickness=7):
    root=mul(translation([-17,19,23]),clock(-23))
    mount=[[0,0,1,3+thickness],[1,0,0,4],[0,1,0,5],[0,0,0,1]]
    return {'fixed':root,'attached':mul(mul(mul(root,mount),translation([11,13,17])),clock(31)),
            'again':mul(mul(root,translation([70,5,9])),clock(47)),
            'multiple':mul(mul(root,translation([-60,7,-9])),clock(13))}
