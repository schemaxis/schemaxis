"""Declarative technical sheets from checked CAD geometry; host-safe boundary.

FCStd inputs are read as bounded archives: only an explicitly named object's
BREP is extracted. Original native documents, proxies and macros are never
restored. The drawing owns a frozen shape, not the source feature history.
"""
import copy
import hashlib
import json
import math
import os
from pathlib import Path
import textwrap
from zipfile import ZipFile

from schemaxis.artifacts import atomic_json, runtime_archive
from schemaxis.core.faults import SchemaxisError, Fault
from schemaxis.core.runners import Interpreter
from .process import SubprocessRunner
from schemaxis.documents import resolve_document
from schemaxis.errors import fail, keys
from schemaxis.pipeline import name
from .adaptor import close
from .document_xml import Document, read_member

VERSION = 'schemaxis.freecad.drawing/1'
SHEETS = {'A4': [297, 210], 'A3': [420, 297]}
VIEWS = {'front': {'direction': [0,-1,0], 'right': [1,0,0], 'axes': [0,2]},
         'top': {'direction': [0,0,1], 'right': [1,0,0], 'axes': [0,1]},
         'right': {'direction': [1,0,0], 'right': [0,1,0], 'axes': [1,2]},
         'rear': {'direction': [0,1,0], 'right': [-1,0,0], 'axes': [0,2]},
         'bottom': {'direction': [0,0,-1], 'right': [1,0,0], 'axes': [0,1]},
         'left': {'direction': [-1,0,0], 'right': [0,-1,0], 'axes': [1,2]},
         'isometric': {'direction': [1,-1,1], 'right': [1,1,0], 'axes': None}}


def dimension_axis(kind):
    if kind in ('diameter','radius'):return 'radial'
    return 'vertical' if kind in ('overallHeight','vertical') else 'horizontal'


def dimension_format(kind):
    return {'radius':'R%.3f','diameter':'\u2300%.3f'}.get(kind,'%.3f')


def dimension_position(view,scale,axis,lane):
    x,y=view['position'];width,height=view['expectedSpan']
    if axis=='radial':
        # Distinct sides give circular leaders distinct directions. Merely
        # moving labels farther up the same ray makes native text overlap.
        offset=14+10*(lane//2)
        return [x+(1 if lane%2==0 else -1)*(width*scale/2+offset),y+height*scale/2+offset]
    offset=14+10*lane
    return [x+width*scale/2+offset,y] if axis=='vertical' else [x,y+height*scale/2+offset]


from .solid_source import number as cad_number,vector as cad_vector,text as cad_text,digest,source_record,capture_source

def number(*args,**kwargs):return cad_number(*args,**kwargs,code='INVALID_DRAWING')
def vector(*args,**kwargs):return cad_vector(*args,**kwargs,code='INVALID_DRAWING')
def text(*args,**kwargs):return cad_text(*args,**kwargs,code='INVALID_DRAWING')


def project(point,source,view):
    """World-to-unscaled standard drawing coordinates about the shape box centre."""
    centre=[(source['bounds'][2*i]+source['bounds'][2*i+1])/2 for i in range(3)]
    right=view['right'];direction=view['direction']
    up=[direction[1]*right[2]-direction[2]*right[1],direction[2]*right[0]-direction[0]*right[2],direction[0]*right[1]-direction[1]*right[0]]
    return [sum((point[i]-centre[i])*basis[i] for i in range(3)) for basis in (right,up)]


def plan(document, *, captured=None, unread=False):
    document,_=resolve_document(copy.deepcopy(document))
    keys(document,('version','source','sheet','views','dimensioning','notes','definitions','settings'),'$')
    if document.get('version')!=VERSION:fail('UNSUPPORTED_VERSION','Expected '+VERSION)
    source=source_record(document.get('source'),captured=captured,unread=unread)
    sheet=document.get('sheet',{});keys(sheet,('size','title','revision','scale'),'$.sheet')
    size=sheet.get('size','A4')
    if not isinstance(size,str) or size not in SHEETS:fail('INVALID_DRAWING','Choose A4 or A3 landscape','$.sheet.size')
    title=text(sheet.get('title','Technical drawing'),'$.sheet.title',120)
    revision=text(sheet.get('revision','A'),'$.sheet.revision',32)
    scale=sheet.get('scale','fit')
    if scale!='fit':scale=number(scale,'$.sheet.scale',0.001,100)
    raw=document.get('views',['front','top','right','isometric'])
    if not isinstance(raw,list) or not 1<=len(raw)<=6 or any(not isinstance(v,str) or v not in VIEWS for v in raw) or len(set(raw))!=len(raw):
        fail('INVALID_DRAWING','Choose one to six distinct named standard views','$.views')
    dims=document.get('dimensioning',[])
    if not isinstance(dims,list) or len(dims)>24:fail('INVALID_DRAWING','Use at most 24 dimensions','$.dimensioning')
    lanes={view:{'horizontal':0,'vertical':0,'radial':0} for view in raw}
    for d in dims:
        keys(d,('id','view','type','radius','length','from','to','position'),'$.dimensioning')
        view=d.get('view');kind=d.get('type')
        if view not in raw or view=='isometric':fail('INVALID_DRAWING','Dimensions need a declared orthographic view','$.dimensioning')
        if kind not in ('overallWidth','overallHeight','diameter','radius','edgeLength','horizontal','vertical','distance'):fail('INVALID_DRAWING','Unsupported dimension intent','$.dimensioning')
        if 'position' not in d:lanes[view][dimension_axis(kind)]+=1
    width,height=SHEETS[size];columns=2 if len(raw)>1 else 1;rows=math.ceil(len(raw)/columns)
    cell=[(width-40)/columns,(height-60)/rows]
    spans=[source['bounds'][2*i+1]-source['bounds'][2*i] for i in range(3)]
    candidates=[];layouts={}
    for view in raw:
        axes=VIEWS[view]['axes']
        if axes:projected=[spans[a] for a in axes]
        else:
            right=[x/math.sqrt(2) for x in VIEWS[view]['right']];direction=[x/math.sqrt(3) for x in VIEWS[view]['direction']]
            up=[direction[1]*right[2]-direction[2]*right[1],direction[2]*right[0]-direction[0]*right[2],direction[0]*right[1]-direction[1]*right[0]]
            projected=[sum(spans[i]*abs(basis[i]) for i in range(3)) for basis in (right,up)]
        margin={'left':8,'bottom':12,'right':14+10*(lanes[view]['vertical']-1)+8 if lanes[view]['vertical'] else 8,
                'top':14+10*(lanes[view]['horizontal']-1)+8 if lanes[view]['horizontal'] else 8}
        if lanes[view]['radial']:
            radial=lanes[view]['radial'];offset=14+10*((radial-1)//2)
            margin['right']=max(margin['right'],offset+18)
            if radial>1:margin['left']=max(margin['left'],offset+18)
            margin['top']=max(margin['top'],offset+8)
        inner=[cell[0]-margin['left']-margin['right'],cell[1]-margin['bottom']-margin['top']]
        candidates.extend([inner[i]/projected[i] for i in range(2)])
        layouts[view]={'margin':margin,'inner':inner}
    fit=min(candidates)
    if scale=='fit':scale=min(10,math.floor(fit*1000)/1000)
    if scale<0.001 or scale>fit:fail('DRAWING_OVERFLOW','Views and dimension lanes do not fit: choose fit or a smaller scale, larger paper, fewer views or fewer annotations','$.sheet.scale')
    views=[]
    for i,view in enumerate(raw):
        layout=layouts[view];left=20+cell[0]*(i%columns);bottom=height-20-cell[1]*(i//columns+1)
        position=[left+layout['margin']['left']+layout['inner'][0]/2,bottom+layout['margin']['bottom']+layout['inner'][1]/2]
        axes=VIEWS[view]['axes'];views.append({'id':view,**VIEWS[view],'position':position,
            'expectedSpan':None if axes is None else [spans[a] for a in axes]})
    used_lanes={view:{'horizontal':0,'vertical':0,'radial':0} for view in raw}
    dimensions=[];ids=set(raw)
    for d in dims:
        keys(d,('id','view','type','radius','length','from','to','position'),'$.dimensioning')
        identity=name(d.get('id'),'$.dimensioning.id');view=d.get('view');kind=d.get('type')
        if identity in ids:fail('INVALID_DRAWING','Drawing identities must be unique',identity)
        ids.add(identity)
        if view not in raw or view=='isometric':fail('INVALID_DRAWING','Dimensions need a declared orthographic view',identity)
        if kind not in ('overallWidth','overallHeight','diameter','radius','edgeLength','horizontal','vertical','distance'):fail('INVALID_DRAWING','Unsupported dimension intent',identity)
        v=next(v for v in views if v['id']==view)
        item={'id':identity,'view':view,'type':kind}
        if kind in ('horizontal','vertical','distance'):
            if 'radius' in d or 'length' in d:fail('INVALID_DRAWING','Point dimensions derive their value from the endpoints',identity)
            for end in ('from','to'):
                anchor=d.get(end);keys(anchor,('point','on','radius'),identity+'.'+end)
                point=vector(anchor.get('point'),3,identity+'.'+end+'.point');on=anchor.get('on','vertex')
                if on not in ('vertex','circleCentre'):fail('INVALID_DRAWING','Select a projected vertex or circular centre',identity+'.'+end)
                item[end]={'point':point,'on':on,'projected':project(point,source,v)}
                if on=='circleCentre':item[end]['radius']=number(anchor.get('radius'),identity+'.'+end+'.radius',1e-6,100000)
                elif 'radius' in anchor:fail('INVALID_DRAWING','A vertex has no selection radius',identity+'.'+end)
            delta=[item['to']['projected'][i]-item['from']['projected'][i] for i in range(2)]
            item['expected']=abs(delta[0]) if kind=='horizontal' else abs(delta[1]) if kind=='vertical' else math.hypot(*delta)
            if item['expected']<1e-6:fail('INVALID_DRAWING','Dimension endpoints need a nonzero projected distance',identity)
        elif kind in ('overallWidth','overallHeight'):
            if 'radius' in d or 'length' in d:fail('INVALID_DRAWING','Overall dimensions derive from expected bounds',identity)
            item['expected']=v['expectedSpan'][kind=='overallHeight']
        elif kind in ('diameter','radius'):
            if 'length' in d:fail('INVALID_DRAWING','Circular dimensions select by radius',identity)
            item['radius']=number(d.get('radius'),identity+'.radius',1e-6,100000)
            item['expected']=item['radius']*(2 if kind=='diameter' else 1)
        else:
            if 'radius' in d:fail('INVALID_DRAWING','Edge length selects a straight projected edge by length',identity)
            item['expected']=number(d.get('length'),identity+'.length',1e-6,100000)
        axis=dimension_axis(kind)
        default=dimension_position(v,scale,axis,used_lanes[view][axis])
        if 'position' not in d:used_lanes[view][axis]+=1
        if kind not in ('horizontal','vertical','distance') and ('from' in d or 'to' in d):fail('INVALID_DRAWING','Endpoint selectors apply to horizontal, vertical or distance dimensions',identity)
        item['position']=vector(d.get('position',default),2,identity+'.position')
        if not (10<=item['position'][0]<=width-10 and 35<=item['position'][1]<=height-10):fail('DRAWING_OVERFLOW','Dimension label lies outside drawing content area',identity)
        dimensions.append(item)
    # Small dimensions stay nearest the geometry; overall dimensions occupy
    # outer lanes. Native identities never determine geometric anchor choice.
    for view in views:
        for axis in ('horizontal','vertical','radial'):
            automatic=[(item,d) for item,d in zip(dimensions,dims) if item['view']==view['id'] and 'position' not in d and dimension_axis(item['type'])==axis]
            for lane,(item,_) in enumerate(sorted(automatic,key=lambda pair:(pair[0]['expected'],pair[0]['id']))):
                item['position']=dimension_position(view,scale,axis,lane)
    notes=document.get('notes',[])
    if not isinstance(notes,list) or len(notes)>4:fail('INVALID_DRAWING','Use at most 4 single-line notes','$.notes')
    notes=[text(note,'$.notes',120) for note in notes]
    characters=max(1,math.floor((width/2-20)/4))
    title_lines=textwrap.wrap(title,width=characters)+textwrap.wrap('Revision '+revision+' | mm | Scale '+format(scale,'.6g'),width=characters)
    note_lines=[line for note in notes for line in textwrap.wrap(note,width=characters)]
    if max(len(title_lines),len(note_lines))>5:fail('DRAWING_OVERFLOW','Title or notes exceed the reserved text strip: shorten the text or choose larger paper','$.notes')
    annotations={'Title':{'text':title_lines,'position':[width/4,17.5]}}
    if notes:annotations['Notes']={'text':note_lines,'position':[width*3/4,17.5]}
    return {'version':'schemaxis.freecad.drawing.plan/1','source':source,'sheet':{'size':size,'title':title,'revision':revision,'scale':scale,'width':width,'height':height},'views':views,'dimensions':dimensions,'notes':notes,'annotations':annotations,'units':'mm'}


def schema():
    from schemaxis.schema import object_schema as obj,DRAFT,json_value_schema
    n={'type':'number'};v2={'type':'array','items':n,'minItems':2,'maxItems':2}
    bounded_text={'type':'string','minLength':1,'maxLength':120}
    return {'$schema':DRAFT,'$defs':{'json':json_value_schema()},**obj({'version':{'const':VERSION},
      'source':obj({'file':{'type':'string','minLength':1,'maxLength':4096},'object':{'type':'string','minLength':1,'maxLength':128},'units':{'enum':['mm','cm','m','inch']},'expect':obj({'volume':{'type':'number','exclusiveMinimum':0},'bounds':{'type':'array','items':n,'minItems':6,'maxItems':6},'centreOfMass':{'type':'array','items':n,'minItems':3,'maxItems':3}},['volume','bounds','centreOfMass'])},['file','units','expect']),
      'sheet':obj({'size':{'enum':list(SHEETS),'default':'A4'},'title':bounded_text,'revision':{'type':'string','minLength':1,'maxLength':32},'scale':{'oneOf':[{'const':'fit'},{'type':'number','minimum':0.001,'maximum':100}],'default':'fit'}},[]),
      'views':{'type':'array','items':{'enum':list(VIEWS)},'minItems':1,'maxItems':6,'uniqueItems':True},
      'dimensioning':{'type':'array','maxItems':24,'items':obj({'id':{'type':'string','pattern':'^[A-Za-z][A-Za-z0-9_-]*$'},'view':{'enum':list(VIEWS)[:-1]},'type':{'enum':['overallWidth','overallHeight','diameter','radius','edgeLength','horizontal','vertical','distance']},**{end:obj({'point':{'type':'array','items':n,'minItems':3,'maxItems':3},'on':{'enum':['vertex','circleCentre'],'default':'vertex'},'radius':{'type':'number','exclusiveMinimum':0}},['point']) for end in ('from','to')},'radius':{'type':'number','exclusiveMinimum':0},'length':{'type':'number','exclusiveMinimum':0},'position':v2},['id','view','type'])},
      'notes':{'type':'array','items':bounded_text,'maxItems':4},**{k:{'$ref':'#/$defs/json'} for k in ('definitions','settings')}},['version','source'])}


def resources(document,spec,identity):
    from schemaxis.parallel import provisional
    _native_plan(provisional(document),unread=True)
    return {}


def reusableInputs(document):
    s=plan(document)['source'];return {s['file']:s['sha256']}


def retainedInputs(directory,document):
    directory=Path(directory);p=json.loads((directory/'plan.json').read_text());current=plan(document,captured=directory/p['source']['capture'])
    if current!=p:fail('VERIFICATION_FAILED','Captured drawing source does not match authored geometry',str(directory))
    return {p['source']['file']:p['source']['sha256']}


def run(document,directory,*,executable=None,gui_executable=None,timeout=120):
    prepared=plan(document)
    for value,label in ((executable,'command-line'),(gui_executable,'GUI publication')):
        if not value or not Path(value).is_absolute() or not Path(value).is_file() or not os.access(value,os.X_OK):
            fail('INTERPRETER_NOT_FOUND','Provide an absolute FreeCAD '+label+' executable')
    directory=Path(directory).absolute()
    if directory.exists() or directory.is_symlink():fail('OUTPUT_EXISTS','Choose a fresh drawing output directory',str(directory))
    directory.mkdir(parents=True);atomic_json(directory/'authored.json',document);atomic_json(directory/'plan.json',prepared)
    atomic_json(directory/'result.json',{'status':'incomplete','verified':False})
    capture_source(prepared['source'],directory)
    snapshot=runtime_archive();(directory/'runtime.zip').write_bytes(snapshot)
    runner=SubprocessRunner(Interpreter('freecad',str(Path(executable).resolve())),directory,timeout=timeout)
    try:
        for stage in ('build','reopen'):
            report=runner('import sys\nsys.path.insert(0,'+repr(str(directory/'runtime.zip'))+')\nfrom schemaxis.adaptors.freecad.drawing_native import '+stage+'\nfrom schemaxis.native_boundary import execute_guarded\nexecute_guarded('+stage+','+repr(str(directory))+')\n')
            atomic_json(directory/(stage+'-submission.json'),report.to_dict())
            if (directory/'native-fault.json').exists():raise SchemaxisError(Fault(**json.loads((directory/'native-fault.json').read_text())))
        _publish(directory,gui_executable,timeout)
        result=verify(directory,require_result=False);result.update(status='succeeded',runtimeSha256=digest(snapshot));atomic_json(directory/'result.json',result);return result
    except Exception as error:
        atomic_json(directory/'result.json',{'status':'failed','verified':False,'fault':error.fault.to_dict() if isinstance(error,SchemaxisError) else {'message':str(error)}});raise


def _publish(directory,executable,timeout):
    from .gui_process import run
    return run(directory,executable,'publish',timeout=timeout,family='drawing')


def verify(directory,require_result=True):
    from .drawing_checks import verify as check
    try:return check(Path(directory).absolute(),require_result)
    except SchemaxisError:raise
    except Exception as error:fail('VERIFICATION_FAILED','Missing or malformed drawing evidence: '+str(error),str(directory))


from schemaxis.adaptor_runtime import bind as _bind_runtime
_bind_runtime(globals())
