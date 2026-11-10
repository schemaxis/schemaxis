"""Independent geometric expectations for native engineering-table examples."""
import copy,json,math
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]


def enclosure():
    return json.loads((ROOT/'examples/schemaxis/freecad-spreadsheet-enclosure.json').read_text())


def turned():
    a,b=math.radians(25),math.radians(30)
    return {'version':'schemaxis.freecad/1','spreadsheet':{
        'inputs':{'radius':{'value':.125,'minimum':.1,'maximum':.2,'unit':'in'},
                  'length':{'value':2,'minimum':1,'maximum':4,'unit':'cm'},
                  'allowance':{'value':1,'minimum':.5,'maximum':2,'unit':'mm'}},
        'formulas':{'axial':{'terms':{'length':1,'allowance':2}}}},
        'nodes':[{'id':'body','filter':'body'},
            {'id':'outline','filter':'circle','options':{'frame':{
                'origin':[3,-7,11],'xAxis':[math.cos(a),math.sin(a),0],
                'normal':[math.sin(a)*math.sin(b),-math.cos(a)*math.sin(b),math.cos(b)]}},
                'inputs':{'body':'body'},'drive':{'radius':{'terms':{'radius':1}}}},
            {'id':'stock','filter':'pad','inputs':{'body':'body','profile':'outline'},
                'drive':{'length':{'terms':{'axial':1}}}}], 'output':'stock'}


def changed(document,number):
    result=copy.deepcopy(document)
    values=({'height':24,'wall':2.5,'width':3.5,'depth':1.25} if number==1 else
            {'height':18,'wall':3,'width':4,'depth':.75}) if document['output']=='housing' else (
            {'radius':.15,'length':3,'allowance':1.5} if number==1 else {'radius':.1,'length':1.5,'allowance':.75})
    for alias,value in values.items():result['spreadsheet']['inputs'][alias]['value']=value
    return result


def oracle(document):
    # Independent literal unit conversions and direct solid geometry, no table
    # compiler/native measurements. Formula intent is expanded by hand here.
    values=document['spreadsheet']['inputs']
    if document['output']=='housing':
        t=values['wall']['value'];W=values['width']['value']*10+2*t
        D=values['depth']['value']*25.4;H=values['height']['value']+t
        outer=W*D*H;inner=(W-2*t)*(D-2*t)*(H-t);V=outer-inner
        return {'volume':V,'centre':[0,0,(outer*H/2-inner*(H+t)/2)/V],
                'bounds':[-W/2,W/2,-D/2,D/2,0,H],
                'sections':[(t/2,[W*D]),((H+t)/2,[(W-2*t)*(D-2*t),W*D])],
                'normal':[0,0,1],'sectionOrigin':[0,0,0],
                'points':[([0,0,t/2],True),([0,0,(H+t)/2],False),([W/2-t/2,0,H/2],True)],
                'dimensions':{'width':W,'depth':D,'height':H,'wall':t}}
    R=values['radius']['value']*25.4;H=values['length']['value']*10+2*values['allowance']['value']
    frame=document['nodes'][1]['options']['frame'];n=frame['normal'];o=frame['origin'];x=frame['xAxis']
    def point(z,r=0):return [o[i]+z*n[i]+r*x[i] for i in range(3)]
    return {'volume':math.pi*R*R*H,'centre':point(H/2),
            'bounds':[extreme(o[i]+z*n[i]+s*R*math.sqrt(1-n[i]*n[i]) for z in (0,H) for s in (-1,1)) for i in range(3) for extreme in (min,max)],
            'normal':n,'sectionOrigin':o,'sections':[(H/3,[math.pi*R*R]),(H*2/3,[math.pi*R*R])],
            'points':[(point(H/2),True),(point(H/2,R*1.2),False)],'dimensions':{'radius':R,'height':H}}
