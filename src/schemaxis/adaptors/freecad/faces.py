"""Named planar-face attachment intent, resolved with explicit ambiguity failures."""
import math
from schemaxis.errors import fail
NORMALS={'top':[0,0,1],'bottom':[0,0,-1],'right':[1,0,0],'left':[-1,0,0],'back':[0,1,0],'front':[0,-1,0]}
ARGUMENT={'type':'object','properties':{'face':{'type':'enum','values':list(NORMALS),'required':True},
    'position':{'type':'enum','values':['outermost','innermost'],'default':'outermost'},
    'anchor':{'type':'enum','values':['projectOrigin','centroid'],'default':'projectOrigin'},
    'offset':{'type':'number','minimum':-100000,'maximum':100000,'default':0}}}


def attachment_mode(prepared,node):
    intent=node['options'].get('onFace')
    if intent is None:return 'Deactivated'
    if intent['anchor']=='centroid' and prepared['partDesign'].get('centroidAttachment')=='native-centre-of-mass':return 'CenterOfMass'
    return 'FlatFace'


def check_attacher(mode,engine,identity):
    allowed={'Attacher::AttachEnginePoint'} if mode=='CenterOfMass' else {'Attacher::AttachEngine3D','Attacher::AttachEnginePlane'}
    if engine not in allowed:fail('VERIFICATION_FAILED','Native sketch attachment engine differs from its typed materialisation',identity)


def resolve(intent,inventory,location='$'):
    if not isinstance(inventory,list) or not 1<=len(inventory)<=10000:fail('VERIFICATION_FAILED','Face inventory is missing or oversized',location)
    n=NORMALS[intent['face']];candidates=[]
    for index,f in enumerate(inventory):
        if not isinstance(f,dict) or set(f)!={'index','planar','normal','centre','area'} or type(f['index']) is not int or f['index']!=index+1 or type(f['planar']) is not bool:
            fail('VERIFICATION_FAILED','Face inventory record differs',location)
        if type(f['area']) not in (int,float) or not math.isfinite(f['area']) or f['area']<=0:fail('VERIFICATION_FAILED','Face area is invalid',location)
        for key in ('normal','centre'):
            if not isinstance(f[key],list) or len(f[key])!=3 or any(type(v) not in (int,float) or not math.isfinite(v) for v in f[key]):fail('VERIFICATION_FAILED','Face geometry is invalid',location)
        if f['planar'] and math.dist(f['normal'],n)<1e-7:candidates.append(f)
    if not candidates:fail('EMPTY_SELECTION','No planar face has the requested outward direction',location)
    coordinate=(max if intent.get('position','outermost')=='outermost' else min)(sum(a*b for a,b in zip(n,f['centre'])) for f in candidates)
    selected=[f for f in candidates if abs(sum(a*b for a,b in zip(n,f['centre']))-coordinate)<1e-6]
    if len(selected)!=1:fail('AMBIGUOUS_SELECTION','Attachment requires exactly one extreme planar face; use another support feature or explicit frame',location,count=len(selected))
    return selected[0]


def frame(intent,face):
    n=NORMALS[intent['face']];x=[0,1,0] if abs(n[0])==1 else [1,0,0]
    centre=face['centre'] if intent.get('anchor','projectOrigin')=='centroid' else [v*sum(a*b for a,b in zip(n,face['centre'])) for v in n]
    return {'origin':[p+intent['offset']*v for p,v in zip(centre,n)],'normal':n,'xAxis':x}


def native_inventory(shape):
    result=[]
    for index,face in enumerate(shape.Faces):
        planar=type(face.Surface).__name__=='Plane'
        u0,u1,v0,v1=face.ParameterRange
        normal=list(face.normalAt((u0+u1)/2,(v0+v1)/2)) if planar else [0,0,0]
        result.append({'index':index+1,'planar':planar,'normal':normal,'centre':list(face.CenterOfMass),'area':float(face.Area)})
    return result
