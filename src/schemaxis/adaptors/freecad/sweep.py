"""Mechanical sweep intent and a native dimensioned bend-path template."""
import math
from schemaxis.errors import fail

PATHS={'arcPath'}
FEATURES={'additivePipe','subtractivePipe'}
ORIENTATION={'normal':'Standard','fixed':'Fixed','frenet':'Frenet','auxiliary':'Auxiliary','binormal':'Binormal'}
TRANSITION={'transformed':'Transformed','miter':'Right corner','rounded':'Round corner'}


def declarations(factory,length,vector):
    path=factory('Sketcher::SketchObject',{'bendRadius':{**length,'default':10},
        'sweepAngle':{'type':'number','minimum':1,'maximum':359,'default':90},
        'origin':{**vector,'default':[0,0,0]},'plane':{'type':'enum','values':['XY','XZ','YZ'],'default':'XY'}},('body',))
    path['kinds']=['profile'];path['inputs']['body']['kind']='body';result={'arcPath':path}
    options={'orientation':{'type':'enum','values':list(ORIENTATION),'default':'normal'},
        'transition':{'type':'enum','values':list(TRANSITION),'default':'transformed'},
        'binormal':vector,'auxiliaryEquivalence':{'type':'boolean','default':True}}
    for name,native in [('additivePipe','AdditivePipe'),('subtractivePipe','SubtractivePipe')]:
        record=factory('PartDesign::'+native,options,('body','profile','spine'))
        record['inputs']['body']['kind']='body'
        for key in ['profile','spine']:record['inputs'][key]['kind']='profile'
        record['inputs']['base']={'required':name=='subtractivePipe','kind':'solid'}
        record['inputs']['sections']={'required':False,'kind':'profile','multiple':True,'minItems':1,'maxItems':31}
        record['inputs']['auxiliary']={'required':False,'kind':'profile'};result[name]=record
    return result


def validate(kind,options,identity):
    if kind=='arcPath':
        if any(abs(c)>100000 for g in path_geometry(options) for key in ('start','end','centre') if key in g for c in g[key]):
            fail('INVALID_SWEEP_PATH','Generated bend path exceeds the coordinate range',identity)
        return
    if (options['orientation']=='binormal')!=('binormal' in options):fail('INVALID_SWEEP_ORIENTATION','Only binormal orientation requires the binormal direction',identity)
    if 'binormal' in options and math.hypot(*options['binormal'])<1e-12:fail('INVALID_SWEEP_ORIENTATION','Binormal direction must be nonzero',identity)
    if options['orientation']!='auxiliary' and not options['auxiliaryEquivalence']:fail('INVALID_SWEEP_ORIENTATION','Auxiliary equivalence applies only to auxiliary orientation',identity)


def path_geometry(o):
    r=o['bendRadius'];a=math.radians(o['sweepAngle']);centre=[-r,0];end=[-r+r*math.cos(a),r*math.sin(a)]
    return [{'kind':'line','start':centre,'end':[0,0],'construction':True},
        {'kind':'line','start':centre,'end':end,'construction':True},
        {'kind':'arc','centre':centre,'radius':r,'startAngle':0,'endAngle':o['sweepAngle'],'construction':False}]


def path_constraints(o):
    def c(name,typ,first,firstPos=0,second=-2000,secondPos=0,value=0):
        return {'name':name,'type':typ,'first':first,'firstPos':firstPos,'second':second,'secondPos':secondPos,'third':-2000,'thirdPos':0,'value':value}
    return [c('origin','Coincident',0,2,-1,1),c('radialDirection','Horizontal',0),c('bendRadius','Distance',0,value=o['bendRadius']),
        c('sharedCentre','Coincident',1,1,0,1),c('sweep','Angle',1,value=math.radians(o['sweepAngle'])),
        c('arcCentre','Coincident',2,3,0,1),c('arcStart','Coincident',2,1,-1,1),c('arcEnd','Coincident',2,2,1,2)]


# Reviewed finite native descriptors. Authored data never supplies these paths.
PROPERTIES={'orientation':('Mode','App::PropertyEnumeration'),'transition':('Transition','App::PropertyEnumeration'),
    'transformation':('Transformation','App::PropertyEnumeration'),'binormal':('Binormal','App::PropertyVector'),
    'spineTangent':('SpineTangent','App::PropertyBool'),'auxiliaryTangent':('AuxiliarySpineTangent','App::PropertyBool'),
    'auxiliaryEquivalence':('AuxiliaryCurvilinear','App::PropertyBool'),'midplane':('Midplane','App::PropertyBool'),
    'reversed':('Reversed','App::PropertyBool')}
ENUMS={'orientation':['Standard','Fixed','Frenet','Auxiliary','Binormal'],
    'transition':['Transformed','Right corner','Round corner'],'transformation':['Constant','Multisection','Linear','S-shape','Interpolation']}


def settings(node):
    o=node['options'];return {'orientation':ORIENTATION[o['orientation']],'transition':TRANSITION[o['transition']],
        'transformation':'Multisection' if 'sections' in node['inputs'] else 'Constant','binormal':o.get('binormal',[0,0,0]),
        'spineTangent':False,'auxiliaryTangent':False,'auxiliaryEquivalence':o['auxiliaryEquivalence'],'midplane':False,'reversed':False}


def saved_settings(xml,name):
    result={}
    for key,(prop,typ) in PROPERTIES.items():
        if typ=='App::PropertyBool':value=xml.boolean(name,prop)
        elif typ=='App::PropertyVector':
            item=xml.child(name,prop,'PropertyVector',typ);value=[float(item.get('value'+a)) for a in 'XYZ']
            from .history_saved import placement
            frame=placement(xml,name,'Placement');value=[sum(frame[4*r+c]*value[c] for c in range(3)) for r in range(3)]
        else:
            index=int(xml.child(name,prop,'Integer',typ).get('value'))
            if not 0<=index<len(ENUMS[key]):raise ValueError('saved sweep enum differs: '+prop)
            value=ENUMS[key][index]
        result[key]=value
    return result
