# Copyright (C) 2026 David L F Gaden
"""Bounded Body / first Pad / finite-depth/through-all Pocket ownership, host-safe."""
from schemaxis.errors import fail

ROLES = {'X_Axis':'App::Line','Y_Axis':'App::Line','Z_Axis':'App::Line',
         'XY_Plane':'App::Plane','XZ_Plane':'App::Plane','YZ_Plane':'App::Plane','Origin':'App::Point'}
FEATURES = {'body','pad','pocket'}


def declarations(declaration, length):
    body=declaration('PartDesign::Body',{});body['kinds']=['body']
    from .history import FRAME
    body['options']['frame']={'value':FRAME}
    pad=declaration('PartDesign::Pad',{'length':{**length,'default':10}},('body','profile'))
    pad['inputs']['body']['kind']='body';pad['inputs']['profile']['kind']='profile'
    pocket=declaration('PartDesign::Pocket',{'extent':{'type':'enum','values':['throughAll','length'],'default':'throughAll'},'length':{**length,'required':False}},('base','profile'))
    pocket['inputs']['profile']['kind']='profile'
    return {'body':body,'pad':pad,'pocket':pocket}


def prepare(prepared):
    from .history import active,prepare as prepare_history
    if active(prepared):return prepare_history(prepared)
    nodes=prepared['nodes'];lookup={n['id']:n for n in nodes}
    bodies=[n['id'] for n in nodes if n['filter']=='body']
    if len(bodies)>1:fail('UNSUPPORTED_BODY','This increment supports one PartDesign Body per document')
    owners={};members=[];tip=None;used=set()
    for node in nodes:
        kind,identity,inputs=node['filter'],node['id'],node['inputs']
        if kind in ('rectangle','circle') and 'body' in inputs:
            owner=inputs['body'];owners[identity]=owner;members.append(identity)
            if node['options']['plane']!='XY' or node['options']['origin']!=[0,0,0]:
                fail('UNSUPPORTED_ATTACHMENT','Body sketches use the native origin XY plane with zero attachment offset',identity)
        elif kind=='pad':
            if tip is not None:fail('INVALID_BODY_HISTORY','Only the first Pad is supported; continue the tip with Pocket',identity)
            owner=inputs['body'];profile=inputs['profile']
            if owners.get(profile)!=owner:fail('INVALID_BODY_OWNERSHIP','Pad profile must belong to its declared Body',identity)
            owners[identity]=owner;members.append(identity);used.add(profile);tip=identity
        elif kind=='pocket':
            if node['options']['extent']=='length':
                if 'length' not in node['options']:
                    fail('INVALID_POCKET_EXTENT','For extent length, provide a positive length in mm or drive.length',identity+'.options.length')
            elif 'length' in node['options']:
                fail('INVALID_POCKET_EXTENT','Use extent length with length or drive.length; throughAll has no finite length',identity+'.options.length')
            base,profile=inputs['base'],inputs['profile'];owner=owners.get(base)
            if not owner or base!=tip or lookup[base]['filter'] not in ('pad','pocket'):
                fail('INVALID_BODY_HISTORY','Pocket must continue the current Pad or Pocket tip',identity)
            if owners.get(profile)!=owner or profile in used:
                fail('INVALID_BODY_OWNERSHIP','Pocket needs an unused profile in the same Body',identity)
            owners[identity]=owner;members.append(identity);used.add(profile);tip=identity
        elif kind!='body':
            for value in inputs.values():
                for source in value if isinstance(value,list) else [value]:
                    if source in owners:fail('INVALID_BODY_OWNERSHIP','Use Body-owned geometry only in its PartDesign feature chain',identity)
    if not bodies:
        return
    output=prepared['output']
    if output in owners and output!=tip:fail('INVALID_BODY_HISTORY','Select the final solid tip of the Body',output)
    if 'designStudy' in prepared:fail('UNSUPPORTED_BODY_STUDY','PartDesign currently supports batch variants, not scalar designStudy')
    prepared['partDesign']={'body':bodies[0],'members':members,'tip':tip}


def names(prepared):
    return {node['id']:'N'+str(index) for index,node in enumerate(prepared['nodes'])}


def expected_links(prepared):
    mapped=names(prepared);body=prepared['partDesign']
    return {'name':mapped[body['body']],'type':'PartDesign::Body','label':body['body'],
            'group':[mapped[k] for k in body['members']],
            'tip':mapped[body['tip']] if body['tip'] is not None else None,'baseFeature':None,'placement':IDENTITY}


def verify_auxiliaries(prepared, auxiliaries):
    if prepared['partDesign'].get('generation')==2:
        from .history import verify_auxiliaries as verify
        return verify(prepared,auxiliaries)
    expected={'container':'App::Origin',**ROLES}
    if not isinstance(auxiliaries,dict) or set(auxiliaries)!=set(expected):
        fail('VERIFICATION_FAILED','Body origin role membership differs')
    declared=set(names(prepared).values())|{'SchemaxisParameters'};seen=set()
    for role,typeid in expected.items():
        item=auxiliaries[role]
        if (not isinstance(item,dict) or set(item)!={'name','type'} or item['type']!=typeid
                or not isinstance(item['name'],str) or not item['name'] or item['name'] in declared|seen):
            fail('VERIFICATION_FAILED','Body origin identity, ownership or type differs',role)
        seen.add(item['name'])
    return {item['name']:item['type'] for item in auxiliaries.values()}

IDENTITY = [1.,0.,0.,0.,0.,1.,0.,0.,0.,0.,1.,0.,0.,0.,0.,1.]


def verify_observation(prepared, observed, *, visibility=True, saved=False):
    if prepared['partDesign'].get('generation')==2:
        from .history import verify_observation as verify
        return verify(prepared,observed,visibility=visibility,saved=saved)
    import math
    wanted={'body','auxiliaries','profiles','features','expressions'}|({'visibility'} if visibility else set())
    if not isinstance(observed,dict) or set(observed)!=wanted:
        fail('VERIFICATION_FAILED','PartDesign observations are absent or malformed')
    aux=verify_auxiliaries(prepared,observed['auxiliaries']);mapped=names(prepared)
    from .parameters import check_engines
    check_engines(prepared,observed['expressions'],observed['auxiliaries'])
    body=prepared['partDesign'];body_name=mapped[body['body']]
    if observed['body']!={**expected_links(prepared),'origin':observed['auxiliaries']['container']['name']}:
        fail('VERIFICATION_FAILED','Body Group, Tip, identity or origin link differs')
    profiles={};features={}
    for node in prepared['nodes']:
        if node['id'] not in body['members']:continue
        kind=node['filter']
        if kind in ('rectangle','circle'):
            profiles[node['id']]={'owner':body_name,'mapMode':'FlatFace',
                'support':[[observed['auxiliaries']['XY_Plane']['name'],['']]],
                'offset':IDENTITY,'placement':IDENTITY,'fullyConstrained':True,'solver':0}
            if saved:profiles[node['id']].pop('solver')
        else:
            features[node['id']]={'owner':body_name,'profile':[mapped[node['inputs']['profile']],[]],
                'baseFeature':None if kind=='pad' else mapped[node['inputs']['base']],
                'type':'Length' if kind=='pad' or node['options']['extent']=='length' else 'ThroughAll','sideType':'One side',
                'reversed':kind=='pocket','alongSketchNormal':True,'customVector':False,'refine':True}
            if kind=='pad' or node['options']['extent']=='length':features[node['id']]['length']=node['options']['length']
    if not isinstance(observed['profiles'],dict) or set(observed['profiles'])!=set(profiles):
        fail('VERIFICATION_FAILED','Body sketch membership differs')
    lookup={n['id']:n for n in prepared['nodes']}
    for identity,expected in profiles.items():
        actual=observed['profiles'][identity]
        if not isinstance(actual,dict) or set(actual)!=set(expected)|{'constraints'}:
            fail('VERIFICATION_FAILED','Body sketch record differs',identity)
        verify_constraints(lookup[identity],actual['constraints'])
        if {k:v for k,v in actual.items() if k!='constraints'}!=expected:
            fail('VERIFICATION_FAILED','Body sketch ownership, attachment or solver state differs',identity)
    if not isinstance(observed['features'],dict) or set(observed['features'])!=set(features):
        fail('VERIFICATION_FAILED','PartDesign feature membership differs')
    for identity,expected in features.items():
        actual=observed['features'][identity]
        if not isinstance(actual,dict) or set(actual)!=set(expected):fail('VERIFICATION_FAILED','PartDesign feature record differs',identity)
        for key,value in expected.items():
            valid=(type(actual[key]) in (int,float) and math.isfinite(actual[key]) and math.isclose(actual[key],value,rel_tol=1e-7,abs_tol=1e-6)) if key=='length' else actual[key]==value
            if not valid:fail('VERIFICATION_FAILED','Native PartDesign feature semantics differ',identity,property=key)
    if visibility:
        visible={mapped[prepared['output']]}
        if prepared['output']==body['tip']:visible.add(body_name)
        expected_names=set(mapped.values())|set(aux)|({'SchemaxisParameters'} if 'parameters' in prepared else set())
        if observed['visibility']!={name:name in visible for name in expected_names}:
            fail('VERIFICATION_FAILED','PartDesign scene visibility differs')

CONSTRAINT_TYPES={4:'Parallel',5:'Tangent',9:'Angle',10:'Perpendicular',12:'Equal',17:'Block',18:'Diameter',1:'Coincident',2:'Horizontal',3:'Vertical',6:'Distance',7:'DistanceX',8:'DistanceY',11:'Radius'}


def constraint_definitions(node):
    """Discrete Sketcher semantics, including constrained geometry endpoints."""
    def c(kind,first,value=0,name='',first_pos=0,second=-2000,second_pos=0):
        return {'name':name,'type':kind,'value':value,'first':first,'firstPos':first_pos,
                'second':second,'secondPos':second_pos,'third':-2000,'thirdPos':0}
    options=node['options']
    if node['filter']=='arcPath':
        from .sweep import path_constraints
        return path_constraints(options)
    from .drilling import PROFILES as drilling_profiles,constraints as drilling_constraints
    if node['filter'] in drilling_profiles:return drilling_constraints(node['filter'],options)
    if node['filter']=='slot':
        from .slot import constraints
        return constraints(options)
    if node['filter']=='sketch':
        from .sketch import definitions
        return definitions(node)
    if node['filter']=='polygon':
        return [c('Block',i,name='fixed_'+str(i)) for i in range(len(options['points']))]
    if node['filter']=='circle':
        if 'centre' in options:
            result=[c('DistanceX',0,options['centre'][0],'centreX',3),c('DistanceY',0,options['centre'][1],'centreY',3)]
        else:result=[c('Coincident',0,first_pos=3,second=-1,second_pos=1)]
        return result+[c('Radius',0,options['radius'],'radius')]
    width,height=options['width'],options['height']
    return ([c('Coincident',i,first_pos=2,second=(i+1)%4,second_pos=1) for i in range(4)]
        +[c('Horizontal' if i%2==0 else 'Vertical',i) for i in range(4)]
        +[c('Distance',0,width,'width'),c('Distance',1,height,'height'),
          c('DistanceX',0,-width/2,'anchorX',1),c('DistanceY',0,-height/2,'anchorY',1)])


def verify_constraints(node,observed):
    import math
    expected=constraint_definitions(node)
    if not isinstance(observed,list) or len(observed)!=len(expected):fail('VERIFICATION_FAILED','Sketch constraint membership differs',node['id'])
    for actual,wanted in zip(observed,expected):
        if not isinstance(actual,dict) or set(actual)!=set(wanted):fail('VERIFICATION_FAILED','Sketch constraint record differs',node['id'])
        for key,value in wanted.items():
            valid=(type(actual[key]) in (int,float) and math.isfinite(actual[key]) and math.isclose(actual[key],value,rel_tol=1e-7,abs_tol=1e-6)) if key=='value' else actual[key]==value
            if not valid:fail('VERIFICATION_FAILED','Sketch constraint identity, endpoints or value differ',node['id'],property=key)
