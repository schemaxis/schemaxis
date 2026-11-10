"""Typed additive/subtractive helical material intent and dependent dimensions."""
import math
from schemaxis.errors import fail

FEATURES={'additiveHelix','subtractiveHelix'}
MODES={'pitchHeight':'pitch-height-angle','pitchTurns':'pitch-turns-angle',
       'heightTurns':'height-turns-angle','heightTurnsGrowth':'height-turns-growth'}
INDEPENDENT={'pitchHeight':{'pitch','height'},'pitchTurns':{'pitch','turns'},
             'heightTurns':{'height','turns'},'heightTurnsGrowth':{'height','turns','growth'}}


def active(prepared):
    return any(node['filter'] in FEATURES for node in prepared.get('nodes',()))


def declarations(factory):
    length={'type':'number','minimum':0,'exclusiveMinimum':True,'maximum':100000}
    options={'mode':{'type':'enum','values':list(MODES),'default':'pitchHeight'},
        'pitch':length,'height':{'type':'number','minimum':0,'maximum':100000},
        'turns':{'type':'number','minimum':0,'exclusiveMinimum':True,'maximum':1000},
        'angle':{'type':'number','minimum':-89,'maximum':89,'default':0},
        'growth':{'type':'number','minimum':-100000,'maximum':100000},
        'axis':{'type':'enum','values':['X','Y','Z'],'default':'Z'},
        'leftHanded':{'type':'boolean','default':False},'reversed':{'type':'boolean','default':False}}
    result={}
    for name,native in [('additiveHelix','AdditiveHelix'),('subtractiveHelix','SubtractiveHelix')]:
        record=factory('PartDesign::'+native,options,('body','profile'))
        record['inputs']['body']['kind']='body';record['inputs']['profile']['kind']='profile'
        record['inputs']['axis']={'kind':'axis','required':False}
        record['inputs']['base']={'kind':'solid','required':name=='subtractiveHelix'}
        if name=='subtractiveHelix':
            record['options']['material']={'value':{'type':'enum','values':['outsideSweep','insideSweep'],'default':'outsideSweep'}}
        result[name]=record
    return result


def validate(options,identity):
    mode=options['mode'];found=set(options)&{'pitch','height','turns','growth'}
    if found!=INDEPENDENT[mode]:
        fail('INVALID_HELIX_EXTENT','Helix mode requires exactly its independent dimensions',identity,
             mode=mode,required=sorted(INDEPENDENT[mode]),observed=sorted(found))
    if mode=='heightTurnsGrowth':
        if options['angle']!=0:fail('INVALID_HELIX_EXTENT','Growth mode derives its cone angle; omit angle or keep zero',identity)
        if options['height']==0 and options['growth']==0 and options['turns']>1:
            fail('INVALID_HELIX_EXTENT','A zero-height spiral needs nonzero radial growth beyond one turn',identity)
    elif options.get('height',1)<=0:
        fail('INVALID_HELIX_EXTENT','This Helix mode requires positive axial height',identity)
    values=settings(options)
    if (not all(math.isfinite(values[k]) for k in ('pitch','height','turns','angle','growth'))
        or values['pitch']>100000 or values['height']>100000 or values['turns']>1000
        or abs(values['angle'])>89 or abs(values['growth']*values['turns'])>100000):
        fail('INVALID_HELIX_EXTENT','Derived Helix dimensions exceed the supported finite range',identity)


def settings(options):
    mode=options['mode'];angle=options['angle']
    if mode=='pitchHeight':pitch,height=options['pitch'],options['height'];turns=height/pitch
    elif mode=='pitchTurns':pitch,turns=options['pitch'],options['turns'];height=pitch*turns
    else:height,turns=options['height'],options['turns'];pitch=height/turns
    if mode=='heightTurnsGrowth':
        growth=options['growth'];angle=math.degrees(math.atan(turns*growth/height)) if height else 0
    else:growth=pitch*math.tan(math.radians(angle))
    return {'mode':MODES[mode],'pitch':pitch,'height':height,'turns':turns,'angle':angle,'growth':growth,
        'leftHanded':options['leftHanded'],'reversed':options['reversed'],
        'outside':options.get('material')=='insideSweep','hasBeenEdited':True,
        'tolerance':0.1,'suppressed':False,'midplane':False,'allowMultiFace':False,'fuzzyTolerance':-1}


PROPERTIES={'pitch':('Pitch','App::PropertyLength'),'height':('Height','App::PropertyLength'),
    'turns':('Turns','App::PropertyFloatConstraint'),'angle':('Angle','App::PropertyAngle'),
    'growth':('Growth','App::PropertyDistance'),'tolerance':('Tolerance','App::PropertyFloatConstraint'),
    'fuzzyTolerance':('FuzzyTolerance','App::PropertyFloatConstraint'),
    **{key:(prop,'App::PropertyBool') for key,prop in [('leftHanded','LeftHanded'),('reversed','Reversed'),
        ('outside','Outside'),('hasBeenEdited','HasBeenEdited'),('suppressed','Suppressed'),
        ('midplane','Midplane'),('allowMultiFace','AllowMultiFace')]}}


def saved_settings(xml,name):
    result={}
    for key,(prop,typ) in PROPERTIES.items():
        result[key]=xml.boolean(name,prop) if typ=='App::PropertyBool' else xml.number(name,prop,typ)
    mode=int(xml.child(name,'Mode','Integer','App::PropertyEnumeration').get('value'))
    if not 0<=mode<len(MODES):raise ValueError('saved Helix mode differs')
    result['mode']=list(MODES.values())[mode]
    for key,prop in [('axisOrigin','Base'),('axisDirection','Axis')]:
        value=xml.child(name,prop,'PropertyVector','App::PropertyVector')
        result[key]=[float(value.get('value'+a)) for a in 'XYZ']
    return result
