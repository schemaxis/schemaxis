"""Typed Body portability fixtures and literal geometric expectations.

Only the case compiler reads public example JSON. The oracles below use the
specified dimensions and elementary volume/area/first-moment formulae, rather
than the adaptor's geometric evaluator.
"""
import copy
import json
import math
from pathlib import Path


def rotate(point, degrees):
    angle=math.radians(degrees);c,s=math.cos(angle),math.sin(angle)
    x,y,z=point
    return [c*x-s*y,s*x+c*y,z]


def add(a,b):return [x+y for x,y in zip(a,b)]


def stock_point(point):return add(rotate(point,31),[3,4,5])


def stock_bounds():
    points=[stock_point([x,y,z]) for x in (0,20) for y in (0,12) for z in (0,5)]
    return [f(p[d] for p in points) for d in range(3) for f in (min,max)]


def enclosure_oracle(height,boss,radius):
    volume=384*height+2448+16*math.pi*boss-4*math.pi*radius**2*(3+boss)
    moment=192*height**2+3672+16*math.pi*boss*(3+boss/2)-2*math.pi*radius**2*(3+boss)**2
    area=2052+256*height+16*math.pi*boss+8*math.pi*radius*(3+boss)-8*math.pi*radius**2
    return {'volume':volume,'area':area,'centreOfMass':[0,0,moment/volume],
            'bounds':[-20,20,-15,15,0,height]}


def plate_oracle(thickness=5):
    section=4000-9*math.pi
    return {'volume':section*thickness,
            'area':2*section+260*thickness+6*math.pi*thickness,
            'centreOfMass':[-135*math.pi/section,-90*math.pi/section,thickness/2],
            'bounds':[-40,40,-25,25,0,thickness]}


def expectations():
    pv=1200-math.pi
    return {
        'parametered':plate_oracle(),
        'deepIndividual':enclosure_oracle(22,5,1),
        'deepHole':enclosure_oracle(21,7,1.25),
        'imported':{'volume':1200,'area':800,'centreOfMass':stock_point([10,6,2.5]),'bounds':stock_bounds()},
        'primitive':{'volume':pv,'area':800+4*math.pi+2*math.pi*math.sqrt(13),
                     'centreOfMass':[(15600+28*math.pi)/pv,12000/pv,(9000+5.5*math.pi)/pv],
                     'bounds':[3,23,4,16,5,13]},
        'hybrid':{'volume':1212,'area':824,'centreOfMass':[12072/1212,6,3078/1212],
                  'bounds':[0,20,0,12,0,8]}}


def world_expectations():
    result=copy.deepcopy(expectations())
    def corners(bounds):
        return [[x,y,z] for x in bounds[:2] for y in bounds[2:4] for z in bounds[4:]]
    for name in ('primitive','hybrid'):
        value=result[name]
        def placed(p):return [7+p[2],8-p[1],9+p[0]]
        points=[placed(p) for p in corners(value['bounds'])]
        value['centreOfMass']=placed(value['centreOfMass'])
        value['bounds']=[f(p[d] for p in points) for d in range(3) for f in (min,max)]
    # The imported fixture has a 35 degree Y Body rotation AFTER its 31 degree
    # source Z rotation. Transform actual box corners, not an inflated local AABB.
    c,s=math.cos(math.radians(35)),math.sin(math.radians(35))
    def body(p):return [7+c*p[0]+s*p[2],8+p[1],9-s*p[0]+c*p[2]]
    result['imported']['centreOfMass']=body(result['imported']['centreOfMass'])
    points=[body(stock_point([x,y,z])) for x in (0,20) for y in (0,12) for z in (0,5)]
    result['imported']['bounds']=[f(p[d] for p in points) for d in range(3) for f in (min,max)]
    return result


def documents(examples,asset):
    examples=Path(examples)
    def read(name):return json.loads((examples/name).read_text())
    plate=read('freecad-part-design.json')
    individual=read('freecad-parametric-enclosure.json')
    for name,value in [('height',22),('bossHeight',5)]:individual['parameters'][name]['value']=value
    drilled=read('freecad-drilled-enclosure.json')
    for name,value in [('height',21),('bossHeight',7),('mountDiameter',2.5)]:drilled['parameters'][name]['value']=value
    imported=read('freecad-body-stock-turned.json')
    imported['nodes']=imported['nodes'][:3];imported['output']='seed'
    imported['nodes'][0]['options']['file']=str(asset)
    frame={'origin':[7,8,9],'xAxis':[0,0,1],'normal':[1,0,0]}
    body={'id':'part','filter':'body','options':{'frame':frame}}
    seed={'id':'seed','filter':'bodySeed','inputs':{'body':'part','source':'casting'}}
    primitive={'version':'schemaxis.freecad/1','nodes':[
        {'id':'box','filter':'box','options':{'length':20,'width':12,'height':5,'origin':[3,4,5]}},
        {'id':'bore','filter':'cylinder','options':{'radius':1,'height':5,'origin':[8,8,5]}},
        {'id':'cut','filter':'cut','inputs':{'base':'box','tool':'bore'}},
        {'id':'boss','filter':'cone','options':{'radius1':2,'radius2':0,'height':3,'origin':[17,10,10]}},
        {'id':'casting','filter':'fuse','inputs':{'base':'cut','tool':'boss'}},
        copy.deepcopy(body),copy.deepcopy(seed)],'output':'seed'}
    hybrid={'version':'schemaxis.freecad/1','nodes':[
        {'id':'stock','filter':'importMesh','options':{'file':str(asset),'units':'mm','refine':True}},
        {'id':'boss','filter':'box','options':{'length':2,'width':2,'height':3,'origin':[5,5,5]}},
        {'id':'casting','filter':'fuse','inputs':{'base':'stock','tool':'boss'}},
        copy.deepcopy(body),copy.deepcopy(seed)],'output':'seed'}
    return {'parametered':plate,'deepIndividual':individual,'deepHole':drilled,
            'imported':imported,'primitive':primitive,'hybrid':hybrid}


def assembly_document(producers):
    parts=[{'id':key,'source':str(value/'model.FCStd'),'mounts':{'o':{}}}
           for key,value in producers.items()]
    parts[0]['mounts']['top']={'position':[0,0,{'terms':{'thickness':1}}]}
    components=[{'id':key,'part':key,**({'position':[11,13,17],'rotation':30} if i==0 else {})}
                for i,key in enumerate(producers)]
    components.append({'id':'parameteredAgain','part':'parametered'})
    joints=[{'id':'j'+str(i),'type':'fixed','parent':{'component':'parametered','mount':'o'},
             'child':{'component':c['id'],'mount':'o'},'offset':[70*i,20*i,0],'clocking':15*i}
            for i,c in enumerate(components[1:],1)]
    joints[-1]={'id':'j6','type':'fixed','parent':{'component':'parametered','mount':'top'},
                'child':{'component':'parameteredAgain','mount':'o'},'clocking':17}
    return {'version':'schemaxis.freecad.assembly/1','units':'mm','parts':parts,
            'components':components,'grounded':'parametered','joints':joints}


def world_centres():
    centres={key:value['centreOfMass'] for key,value in expectations().items()}
    centres['parameteredAgain']=centres['parametered'];result={}
    for i,(name,centre) in enumerate(centres.items()):
        position=add([11,13,17],rotate([70*i,20*i,0],30));angle=30+15*i
        if name=='parameteredAgain':position=[11,13,22];angle=47
        result[name]=add(position,rotate(centre,angle))
    return result
