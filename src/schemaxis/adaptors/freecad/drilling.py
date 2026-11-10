"""Mechanical drilling intent: locations, patterns and native Hole dimensions.

Native marker-circle radii do not define a PartDesign Hole diameter. The location
profiles therefore expose centres and pitch intent only; the hole feature owns
its drill/recess dimensions. All bindings below are trusted finite descriptors.
"""
import math
from schemaxis.errors import fail

PROFILES={'holeLocations','boltGrid','boltCircle'}
XY={'type':'array','items':{'type':'number','minimum':-100000,'maximum':100000},'minItems':2,'maxItems':2}
COUNT={'type':'integer','minimum':1,'maximum':64}
ANGLE={'type':'number','minimum':-180,'maximum':180,'default':0}


def declarations(declaration,length):
    result={
        'holeLocations':declaration('Sketcher::SketchObject',{'centres':{'type':'array','items':XY,'minItems':1,'maxItems':256,'required':True}}),
        'boltGrid':declaration('Sketcher::SketchObject',{'columns':{**COUNT,'default':2},'rows':{**COUNT,'default':2},
            'xPitch':{**length,'default':20},'yPitch':{**length,'default':15},'centre':{**XY,'default':[0,0]}}),
        'boltCircle':declaration('Sketcher::SketchObject',{'count':{**COUNT,'minimum':2,'default':4},'radius':{**length,'default':10},
            'phase':ANGLE,'centre':{**XY,'default':[0,0]}})}
    for record in result.values():
        record['kinds']=['profile'];record['options']['origin']={'value':{'type':'array','items':{'type':'number','minimum':-100000,'maximum':100000},'minItems':3,'maxItems':3,'default':[0,0,0]}}
        record['options']['plane']={'value':{'type':'enum','values':['XY','XZ','YZ'],'default':'XY'}}
    hole=declaration('PartDesign::Hole',{
        'diameter':{**length,'default':4},'extent':{'type':'enum','values':['length','throughAll'],'default':'throughAll'},'depth':length,
        'direction':{'type':'enum','values':['forward','backward'],'default':'backward'},
        'tip':{'type':'enum','values':['flat','conical'],'default':'flat'},'tipAngle':{'type':'number','minimum':1,'maximum':179,'default':118},
        'depthMeasure':{'type':'enum','values':['cylindrical','tip'],'default':'cylindrical'},
        'recess':{'type':'enum','values':['none','counterbore','countersink','counterdrill'],'default':'none'},
        'recessDiameter':length,'recessDepth':length,'recessAngle':{'type':'number','minimum':1,'maximum':179}},('body','base','profile'))
    hole['inputs']['body']['kind']='body';hole['inputs']['profile']['kind']='profile';result['hole']=hole
    return result


def centres(kind,o):
    if kind=='holeLocations':return o['centres']
    cx,cy=o['centre']
    if kind=='boltGrid':return [[cx+(c-(o['columns']-1)/2)*o['xPitch'],cy+(r-(o['rows']-1)/2)*o['yPitch']] for r in range(o['rows']) for c in range(o['columns'])]
    return [[cx+o['radius']*math.cos(math.radians(o['phase']+360*n/o['count'])),cy+o['radius']*math.sin(math.radians(o['phase']+360*n/o['count']))] for n in range(o['count'])]


def validate(kind,o,identity):
    if kind in PROFILES:
        p=centres(kind,o)
        if len(p)>256:fail('RESOURCE_LIMIT','Drilling patterns contain at most 256 centres',identity)
        if any(math.dist(a,b)<1e-7 for n,a in enumerate(p) for b in p[n+1:]):fail('INVALID_HOLE_LOCATIONS','Drill centres must be distinct',identity)
        if any(abs(v)>100000 for xy in p for v in xy):fail('INVALID_HOLE_LOCATIONS','Generated drill centres exceed the coordinate range',identity)
        return
    if (o['extent']=='length')!=('depth' in o):fail('INVALID_HOLE_EXTENT','Finite drilling needs depth; through-all omits it',identity)
    if o['extent']=='throughAll' and (o['tip']!='flat' or o['depthMeasure']!='cylindrical'):fail('INVALID_HOLE_EXTENT','Through-all drilling has no blind-tip depth convention',identity)
    wanted={'none':set(),'counterbore':{'recessDiameter','recessDepth'},'countersink':{'recessDiameter','recessAngle'},'counterdrill':{'recessDiameter','recessDepth','recessAngle'}}[o['recess']]
    if {k for k in o if k in {'recessDiameter','recessDepth','recessAngle'}}!=wanted:fail('INVALID_HOLE_RECESS','Declare exactly the dimensions used by the selected recess type',identity)
    if o['recess']!='none' and o['recessDiameter']<=o['diameter']:fail('INVALID_HOLE_RECESS','Head recess diameter must exceed drill diameter',identity)
    if o['extent']=='length':
        cylinder=o['depth']-(o['diameter']/2/math.tan(math.radians(o['tipAngle']/2)) if o['tip']=='conical' and o['depthMeasure']=='tip' else 0)
        if cylinder<=0:fail('INVALID_HOLE_EXTENT','Blind hole needs a positive cylindrical drilling length before its tip',identity)
        recess=o.get('recessDepth',0)
        if o['recess'] in ('countersink','counterdrill'):recess+=(o['recessDiameter']-o['diameter'])/2/math.tan(math.radians(o['recessAngle']/2))
        if recess>=cylinder:fail('INVALID_HOLE_RECESS','Blind drilling must continue below the head recess',identity)


def geometry(kind,o):
    result=[]
    if kind=='boltGrid':
        result=[{'kind':'line','start':[0,0],'end':[o['xPitch'],0],'construction':True},
            {'kind':'line','start':[0,0],'end':[0,o['yPitch']],'construction':True}]
    elif kind=='boltCircle':
        angle=math.radians(o['phase']);result=[{'kind':'circle','centre':[0,0],'radius':o['radius'],'construction':True},
            {'kind':'line','start':[0,0],'end':[math.cos(angle),math.sin(angle)],'construction':True}]
    return result+[{'kind':'circle','centre':xy,'radius':1,'construction':False} for xy in centres(kind,o)]


def constraints(kind,o):
    def r(name,typ,first,value=0,firstPos=0,second=-2000,secondPos=0):
        return {'name':name,'type':typ,'value':value,'first':first,'firstPos':firstPos,'second':second,'secondPos':secondPos,'third':-2000,'thirdPos':0}
    result=[]
    if kind=='boltGrid':
        for i,axis in enumerate(('x','y')):
            result.extend([r('origin_'+axis,'Coincident',i,firstPos=1,second=-1,secondPos=1),
                r('direction_'+axis,'Horizontal' if i==0 else 'Vertical',i),r(axis+'Pitch','Distance',i,o[axis+'Pitch'])])
    elif kind=='boltCircle':
        result.extend([r('pitchCentre','Coincident',0,firstPos=3,second=-1,secondPos=1),r('pitchRadius','Radius',0,o['radius']),
            r('phaseOrigin','Coincident',1,firstPos=1,second=-1,secondPos=1),r('phaseMarkerLength','Distance',1,1),r('phase','Angle',1,math.radians(o['phase']))])
    offset=0 if kind=='holeLocations' else 2
    for n,xy in enumerate(centres(kind,o)):
        result.extend([r('x_'+str(n),'DistanceX',offset+n,xy[0],firstPos=3),r('y_'+str(n),'DistanceY',offset+n,xy[1],firstPos=3),r('marker_'+str(n),'Radius',offset+n,1)])
    return result


def expressions(kind,o):
    """Compile only this fixed mechanical template; no authored expression text."""
    def offset(term,value):
        return term+(' + '+format(value,'.15g')+' mm' if value>0 else ' - '+format(-value,'.15g')+' mm' if value<0 else '')
    result={}
    if kind=='boltGrid':
        for n in range(o['rows']*o['columns']):
            for axis,k in [('x',n%o['columns']-(o['columns']-1)/2),('y',n//o['columns']-(o['rows']-1)/2)]:
                if k:
                    term=('.Constraints.'+axis+'Pitch') if k==1 else ('-.Constraints.'+axis+'Pitch') if k==-1 else format(k,'.15g')+' * .Constraints.'+axis+'Pitch'
                    result['.Constraints.'+axis+'_'+str(n)]=offset(term,o['centre'][0 if axis=='x' else 1])
    elif kind=='boltCircle':
        for n in range(o['count']):
            angle='.Constraints.phase'+(' + '+format(360*n/o['count'],'.15g')+' deg' if n else '')
            for axis,function,value in [('x','cos',o['centre'][0]),('y','sin',o['centre'][1])]:result['.Constraints.'+axis+'_'+str(n)]=offset(function+'('+angle+') * .Constraints.pitchRadius',value)
    return result

# Reviewed native property names/types. Authored input never supplies these paths.
HOLE_PROPERTIES={
    'threadType':('ThreadType','App::PropertyEnumeration'),'threaded':('Threaded','App::PropertyBool'),
    'modelThread':('ModelThread','App::PropertyBool'),'tapered':('Tapered','App::PropertyBool'),
    'customRecess':('HoleCutCustomValues','App::PropertyBool'),'recess':('HoleCutType','App::PropertyEnumeration'),
    'diameter':('Diameter','App::PropertyLength'),'depthType':('DepthType','App::PropertyEnumeration'),
    'reversed':('Reversed','App::PropertyBool'),'tip':('DrillPoint','App::PropertyEnumeration'),
    'tipAngle':('DrillPointAngle','App::PropertyAngle'),'tipIncludesDepth':('DrillForDepth','App::PropertyBool'),
    'recessDiameter':('HoleCutDiameter','App::PropertyLength'),'recessAngle':('HoleCutCountersinkAngle','App::PropertyAngle'),
    'recessDepth':('HoleCutDepth','App::PropertyLength'),'depth':('Depth','App::PropertyLength')}
HOLE_ENUMS={'threadType':['None','ISOMetricProfile','ISOMetricFineProfile','UNC','UNF','UNEF','NPT','BSP','BSW','BSF','ISOTyre'],
    'recess':['None','Counterbore','Countersink','Counterdrill'],'depthType':['Dimension','ThroughAll'],'tip':['Flat','Angled']}


def hole_settings(o):
    result={'threadType':'None','threaded':False,'modelThread':False,'tapered':False,'customRecess':True,
        'recess':{'none':'None','counterbore':'Counterbore','countersink':'Countersink','counterdrill':'Counterdrill'}[o['recess']],
        'diameter':o['diameter'],'depthType':'Dimension' if o['extent']=='length' else 'ThroughAll','reversed':o['direction']=='forward',
        'tip':'Flat' if o['tip']=='flat' else 'Angled','tipAngle':o['tipAngle'],'tipIncludesDepth':o['depthMeasure']=='tip',
        'recessDiameter':o.get('recessDiameter',0),'recessAngle':o.get('recessAngle',90)}
    # Native countersink depth describes the cone to its virtual apex, not only
    # the annular part above the drill diameter; it is computed by FreeCAD.
    result['recessDepth']=o['recessDiameter']/2/math.tan(math.radians(o['recessAngle']/2)) if o['recess']=='countersink' else o.get('recessDepth',0)
    if o['extent']=='length':result['depth']=o['depth']
    return result


def saved_settings(xml,name,node):
    """Read only reviewed typed Hole properties and their active enum meaning."""
    result={}
    for key in hole_settings(node['options']):
        prop,typeid=HOLE_PROPERTIES[key]
        if typeid=='App::PropertyBool':value=xml.boolean(name,prop)
        elif typeid in ('App::PropertyLength','App::PropertyAngle'):value=xml.number(name,prop,typeid)
        else:
            item=xml.properties[name][prop]
            if item.get('type')!=typeid or len(item.findall('Integer'))!=1 or any(c.tag not in ('Integer','CustomEnumList') for c in item):raise ValueError('saved Hole enumeration structure differs: '+prop)
            index=int(item.find('Integer').get('value'));choices=HOLE_ENUMS[key];custom=item.findall('CustomEnumList')
            if len(custom)>1:raise ValueError('saved Hole enumeration list is ambiguous')
            if custom:
                entries=custom[0]
                if entries.get('count')!=str(len(entries)) or any(c.tag!='Enum' for c in entries):raise ValueError('saved Hole enumeration list is malformed')
                choices=[c.get('value') for c in entries]
            if not 0<=index<len(choices):raise ValueError('saved Hole enumeration index is invalid')
            value=choices[index]
        result[key]=value
    return result
