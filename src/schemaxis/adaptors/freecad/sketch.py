"""Named planar geometry and typed Sketcher relations; no native imports."""
import math
from schemaxis.errors import fail
from schemaxis.pipeline import name
POINT={'type':'array','items':{'type':'number','minimum':-100000,'maximum':100000},'minItems':2,'maxItems':2}

def declaration(factory,vector,length):
    def item(kind,properties):return {'type':'object','properties':{'id':{'type':'string','required':True},'kind':{'type':'enum','values':[kind],'required':True},'construction':{'type':'boolean','default':False},**properties}}
    geometries=[item('line',{'start':{**POINT,'required':True},'end':{**POINT,'required':True}}),
        item('circle',{'centre':{**POINT,'required':True},'radius':{**length,'required':True}}),
        item('arc',{'centre':{**POINT,'required':True},'radius':{**length,'required':True},
            'startAngle':{'type':'number','minimum':-360,'maximum':360,'required':True},
            'endAngle':{'type':'number','minimum':-360,'maximum':720,'required':True}})]
    endpoint={'type':'object','properties':{'geometry':{'type':'string','required':True},
        'point':{'type':'enum','values':['start','end','centre','whole'],'default':'whole'}}}
    constraint={'type':'object','properties':{'id':{'type':'string','required':True},
        'kind':{'type':'enum','values':['coincident','horizontal','vertical','parallel','perpendicular','tangent','equal','distance','distanceX','distanceY','radius','diameter','angle','block'],'required':True},
        'first':{**endpoint,'required':True},'second':endpoint,
        'value':{'type':'number','minimum':-100000,'maximum':100000}}}
    result=factory('Sketcher::SketchObject',{
        'geometry':{'type':'array','items':{'type':'union','options':geometries},'minItems':1,'maxItems':200,'required':True},
        'constraints':{'type':'array','items':constraint,'minItems':0,'maxItems':500,'default':[]},
        'constraintMode':{'type':'enum','values':['fixed','solve'],'default':'fixed'},
        'plane':{'type':'enum','values':['XY','XZ','YZ'],'default':'XY'},'origin':vector})
    result['kinds']=['profile'];result['inputs']['body']={'required':False,'kind':'body'}
    return result

TYPES={'coincident':'Coincident','horizontal':'Horizontal','vertical':'Vertical','parallel':'Parallel','perpendicular':'Perpendicular','tangent':'Tangent','equal':'Equal','distance':'Distance','distanceX':'DistanceX','distanceY':'DistanceY','radius':'Radius','diameter':'Diameter','angle':'Angle','block':'Block'}
POSITIONS={'whole':0,'start':1,'end':2,'centre':3}

def validate(options,identity):
    geometry=options['geometry'];seen=set()
    for g in geometry:
        name(g['id'],identity+'.geometry.id')
        if g['id'] in seen:fail('INVALID_PROFILE','Sketch geometry names must be unique',identity)
        seen.add(g['id'])
        if g['kind']=='line' and math.dist(g['start'],g['end'])<1e-7:fail('INVALID_PROFILE','Sketch lines must have positive length',identity)
        if g['kind']=='arc' and not 0<g['endAngle']-g['startAngle']<360:
            fail('INVALID_PROFILE','Arc endAngle must follow startAngle by less than360 degrees',identity)
    if options['constraintMode']=='fixed' and options['constraints']:
        fail('CONFLICTING_CONSTRAINTS','Fixed mode generates Block constraints; use solve for authored relations',identity)
    lookup={g['id']:g for g in geometry};ids=set()
    binary={'coincident','parallel','perpendicular','tangent','equal'}
    valued={'distance','distanceX','distanceY','radius','diameter','angle'}
    for c in options['constraints']:
        name(c['id'],identity+'.constraints.id')
        if c['id'] in ids:fail('INVALID_CONSTRAINT','Sketch constraint names must be unique',identity)
        ids.add(c['id']);kind=c['kind']
        if (kind in binary)!=('second' in c) and kind not in ('distance','distanceX','distanceY','angle'):
            fail('INVALID_CONSTRAINT','Constraint endpoint count differs from its kind',identity+'.'+c['id'])
        if (kind in valued)!=('value' in c):fail('INVALID_CONSTRAINT','Dimensional constraints require value; geometric relations omit it',identity+'.'+c['id'])
        if kind in ('distance','radius','diameter') and c['value']<=0:fail('INVALID_CONSTRAINT','Length/radius/diameter constraints require a positive value',identity)
        for endpoint in [c['first']]+([c['second']] if 'second' in c else []):
            if endpoint['geometry'] not in lookup:fail('INVALID_CONSTRAINT','Constraint refers to unknown named geometry',identity)
            g=lookup[endpoint['geometry']];pos=endpoint['point']
            if g['kind']=='circle' and pos in ('start','end') or g['kind']=='line' and pos=='centre':
                fail('INVALID_CONSTRAINT','Constraint point is not defined on that geometry kind',identity)
        first,second=c['first'],c.get('second')
        if kind=='coincident' and (first['point']=='whole' or second['point']=='whole'):
            fail('INVALID_CONSTRAINT','Coincident names two geometry points',identity)
        if kind in ('horizontal','vertical','parallel','perpendicular','equal','tangent','radius','diameter','angle','block') and any(e['point']!='whole' for e in [first]+([second] if second else [])):
            fail('INVALID_CONSTRAINT','This typed relation selects whole curves; use coincident for point joins',identity)
        if kind=='tangent' and any(lookup[e['geometry']]['kind'] not in ('line','circle','arc') for e in (first,second)):
            fail('INVALID_CONSTRAINT','Tangent requires line/circular curve geometry',identity)
        if kind=='equal' and ((lookup[first['geometry']]['kind']=='line')!=(lookup[second['geometry']]['kind']=='line')):
            fail('INVALID_CONSTRAINT','Equal compares two lengths or two circular radii',identity)
        if kind=='distance' and (('second' in c and any(e['point']=='whole' for e in (first,second))) or ('second' not in c and (first['point']!='whole' or lookup[first['geometry']]['kind']!='line'))):
            fail('INVALID_CONSTRAINT','Distance measures one whole line or two points',identity)
        if kind in ('horizontal','vertical','parallel','perpendicular') and any(lookup[c[p]['geometry']]['kind']!='line' for p in ('first','second') if p in c):
            fail('INVALID_CONSTRAINT','This relation requires line geometry',identity)
        if kind in ('radius','diameter') and lookup[c['first']['geometry']]['kind'] not in ('circle','arc'):
            fail('INVALID_CONSTRAINT','Radius/diameter requires a circular curve',identity)


def definitions(node):
    o=node['options'];indices={g['id']:n for n,g in enumerate(o['geometry'])}
    def record(kind,first,value=0,label='',firstPos=0,second=-2000,secondPos=0):
        return {'name':label,'type':kind,'value':value,'first':first,'firstPos':firstPos,'second':second,'secondPos':secondPos,'third':-2000,'thirdPos':0}
    if o['constraintMode']=='fixed':return [record('Block',n,label='fixed_'+g['id']) for n,g in enumerate(o['geometry'])]
    result=[]
    for c in o['constraints']:
        a=c['first'];b=c.get('second')
        value=c.get('value',0)
        if c['kind']=='angle':value=math.radians(value)
        result.append(record(TYPES[c['kind']],indices[a['geometry']],value,c['id'],POSITIONS[a['point']],indices[b['geometry']] if b else -2000,POSITIONS[b['point']] if b else 0))
    return result


def geometry_definitions(node):
    k,o=node['filter'],node['options']
    if k=='arcPath':
        from .sweep import path_geometry
        return path_geometry(o)
    from .drilling import PROFILES as drilling_profiles,geometry as drilling_geometry
    if k in drilling_profiles:return drilling_geometry(k,o)
    if k=='slot':
        from .slot import geometry
        return geometry(o)
    if k=='sketch':return [{key:value for key,value in g.items() if key!='id'} for g in o['geometry']]
    if k=='circle':return [{'kind':'circle','centre':o.get('centre',[0,0]),'radius':o['radius'],'construction':False}]
    if k=='rectangle':
        w,h=o['width'],o['height'];points=[[-w/2,-h/2],[w/2,-h/2],[w/2,h/2],[-w/2,h/2]]
    else:points=o['points']
    return [{'kind':'line','start':a,'end':b,'construction':False} for a,b in zip(points,points[1:]+points[:1])]


def verify_geometry(node,observed):
    """Check native sketch facts without calling a native solver on the host."""
    from .adaptor import close
    expected=geometry_definitions(node)
    if not isinstance(observed,list) or len(observed)!=len(expected):fail('VERIFICATION_FAILED','Sketch geometry membership differs',node['id'])
    fixed=node['filter']!='sketch' or node['options']['constraintMode']=='fixed'
    for a,b in zip(observed,expected):
        if not isinstance(a,dict) or set(a)!=set(b) or a['kind']!=b['kind'] or type(a['construction']) is not bool or a['construction']!=b['construction']:
            fail('VERIFICATION_FAILED','Sketch geometry type or construction status differs',node['id'])
        if a['kind']=='line' and (not isinstance(a.get('start'),list) or not isinstance(a.get('end'),list)):fail('VERIFICATION_FAILED','Sketch line endpoints are malformed',node['id'])
        for key,value in b.items():
            if key in ('kind','construction'):continue
            values=a[key] if isinstance(a[key],list) else [a[key]]
            if (isinstance(value,list) and (not isinstance(a[key],list) or len(a[key])!=len(value))) or any(type(v) not in (int,float) or not math.isfinite(v) for v in values):
                fail('VERIFICATION_FAILED','Sketch geometry is malformed',node['id'])
            same=abs(math.remainder(a[key]-value,360))<1e-6 if key in ('startAngle','endAngle') else close(a[key],value)
            if fixed and not same:fail('VERIFICATION_FAILED','Fixed sketch geometry differs',node['id'])
        if a['kind']=='line' and math.dist(a['start'],a['end'])<1e-7:fail('VERIFICATION_FAILED','Sketch line is degenerate',node['id'])
        if a['kind'] in ('circle','arc') and a['radius']<=0:fail('VERIFICATION_FAILED','Sketch curve radius is invalid',node['id'])
        if fixed and a['kind']=='arc' and not close(a['endAngle']-a['startAngle'],b['endAngle']-b['startAngle']):fail('VERIFICATION_FAILED','Fixed arc sweep differs',node['id'])
    if fixed:return
    lookup={g['id']:a for g,a in zip(node['options']['geometry'],observed)}
    def point(e):
        g=lookup[e['geometry']];p=e['point']
        if p=='whole':return None
        if p=='centre':return g['centre']
        if g['kind']=='line':return g[p]
        angle=math.radians(g['startAngle' if p=='start' else 'endAngle'])
        return [g['centre'][j]+g['radius']*v for j,v in enumerate((math.cos(angle),math.sin(angle)))]
    def direction(e):
        g=lookup[e['geometry']]
        if g['kind']!='line':fail('VERIFICATION_FAILED','Line relation has non-line geometry',node['id'])
        return [b-a for a,b in zip(g['start'],g['end'])]
    for c in node['options']['constraints']:
        kind=c['kind'];a=c['first'];b=c.get('second');pa=point(a);pb=point(b) if b else [0,0];wanted=c.get('value',0);residual=0
        ga=lookup[a['geometry']];gb=lookup[b['geometry']] if b else None
        if kind=='block':
            initial=next(g for g in node['options']['geometry'] if g['id']==a['geometry'])
            for key,value in initial.items():
                if key not in ('id','kind','construction') and not close(ga[key],value):fail('VERIFICATION_FAILED','Blocked geometry differs',node['id'])
        elif kind=='coincident':residual=math.dist(pa,pb)
        elif kind in ('horizontal','vertical'):residual=direction(a)[1 if kind=='horizontal' else 0]
        elif kind in ('parallel','perpendicular'):
            da,db=direction(a),direction(b);scale=math.hypot(*da)*math.hypot(*db)
            residual=(da[0]*db[1]-da[1]*db[0] if kind=='parallel' else sum(x*y for x,y in zip(da,db)))/scale
        elif kind=='equal':residual=(math.hypot(*direction(a))-math.hypot(*direction(b))) if ga['kind']=='line' else ga['radius']-gb['radius']
        elif kind in ('radius','diameter'):residual=ga['radius']*(2 if kind=='diameter' else 1)-wanted
        elif kind=='distance':residual=(math.dist(pa,pb) if pa is not None else math.hypot(*direction(a)))-wanted
        elif kind in ('distanceX','distanceY'):
            axis=0 if kind=='distanceX' else 1
            if pa is None:
                da=direction(a);actual=da[axis]
            else:actual=pa[axis]-(pb[axis] if b else 0)
            # Native two-point dimensions are second minus first.
            if b:actual=-actual
            residual=actual-wanted
        elif kind=='angle':
            da=direction(a);angle=math.atan2(da[1],da[0])
            if b:
                db=direction(b);angle=math.atan2(da[0]*db[1]-da[1]*db[0],sum(x*y for x,y in zip(da,db)))
            residual=math.remainder(angle-math.radians(wanted),2*math.pi)
        elif kind=='tangent':
            if ga['kind']=='line' and gb['kind'] in ('circle','arc') or gb['kind']=='line' and ga['kind'] in ('circle','arc'):
                line,circle=(ga,gb) if ga['kind']=='line' else (gb,ga)
                d=[v-u for u,v in zip(line['start'],line['end'])];p=[v-u for u,v in zip(line['start'],circle['centre'])]
                residual=abs(d[0]*p[1]-d[1]*p[0])/math.hypot(*d)-circle['radius']
            elif ga['kind'] in ('circle','arc') and gb['kind'] in ('circle','arc'):
                dist=math.dist(ga['centre'],gb['centre']);residual=min(abs(dist-ga['radius']-gb['radius']),abs(dist-abs(ga['radius']-gb['radius'])))
            else:fail('VERIFICATION_FAILED','Unsupported tangent geometry pair',node['id'])
        if not math.isfinite(residual) or abs(residual)>max(1e-6,abs(wanted)*1e-7):
            fail('VERIFICATION_FAILED','Independent sketch constraint residual differs',node['id']+'.'+c['id'],residual=residual)
