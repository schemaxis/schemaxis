"""Typed multi-Body modelling policy, independent of the native application.

Feature names and property bindings are application code. Authored data never
selects a native TypeId, a property path or executable Python.
"""
import math
from schemaxis.errors import fail

PROFILES = {'rectangle', 'circle', 'polygon', 'sketch', 'slot', 'holeLocations', 'boltGrid', 'boltCircle', 'arcPath'}
FEATURES = {'pad', 'pocket', 'bodyRevolve', 'groove', 'bodyFillet', 'bodyChamfer',
            'linearPattern', 'polarPattern', 'mirror', 'additiveLoft', 'subtractiveLoft', 'hole', 'shell', 'additivePipe', 'subtractivePipe', 'bodyDraft', 'additiveHelix', 'subtractiveHelix'}
NEW_FEATURES = FEATURES - {'pad', 'pocket'} | {'datumAxis','bodySeed'}
VEC = {'type':'array','items':{'type':'number','minimum':-100000,'maximum':100000},'minItems':3,'maxItems':3}
FRAME = {'type':'object','properties':{
    'origin':{**VEC,'required':True}, 'xAxis':{**VEC,'required':True}, 'normal':{**VEC,'required':True}}}


def declarations(declaration, length):
    from .selections import EDGES
    angle={'type':'number','minimum':0,'exclusiveMinimum':True,'maximum':360,'default':360}
    direction={'type':'enum','values':['forward','backward','symmetric']}
    result={}
    for name,native in [('bodyRevolve','Revolution'),('groove','Groove')]:
        record=declaration('PartDesign::'+native,{'angle':angle,'axis':{'type':'enum','values':['X','Y','Z'],'default':'Z'},'reversed':{'type':'boolean','default':False}},('body','profile'))
        record['inputs']['body']['kind']='body';record['inputs']['profile']['kind']='profile'
        record['inputs']['base']={'required':False,'kind':'solid'};record['inputs']['axis']={'required':False,'kind':'axis'};result[name]=record
    for name,native,field in [('bodyFillet','Fillet','radius'),('bodyChamfer','Chamfer','distance')]:
        result[name]=declaration('PartDesign::'+native,{field:{**length,'default':1},'edges':EDGES},('base',))
    result['linearPattern']=declaration('PartDesign::LinearPattern',{
        'length':{**length,'default':20},'count':{'type':'integer','minimum':2,'maximum':100,'default':2},
        'direction':{'type':'enum','values':['X','Y','Z'],'default':'X'}},('base','feature'))
    result['polarPattern']=declaration('PartDesign::PolarPattern',{
        'angle':angle,'count':{'type':'integer','minimum':2,'maximum':100,'default':4},
        'axis':{'type':'enum','values':['X','Y','Z'],'default':'Z'}},('base','feature'))
    result['mirror']=declaration('PartDesign::Mirrored',{
        'plane':{'type':'enum','values':['XY','XZ','YZ'],'default':'YZ'}},('base','feature'))
    for name,native in [('additiveLoft','AdditiveLoft'),('subtractiveLoft','SubtractiveLoft')]:
        record=declaration('PartDesign::'+native,{'ruled':{'type':'boolean','default':False}},('body','sections'))
        record['inputs']['body']['kind']='body';record['inputs']['sections'].update(kind='profile',multiple=True,minItems=2,maxItems=32)
        record['inputs']['base']={'required':False,'kind':'solid'};result[name]=record
    result['datumAxis']=declaration('PartDesign::Line',{'origin':{**VEC,'default':[0,0,0]},'direction':{**VEC,'default':[0,0,1]}},('body',))
    result['datumAxis']['inputs']['body']['kind']='body';result['datumAxis']['kinds']=['axis']
    from .drilling import declarations as drilling_declarations
    result.update(drilling_declarations(declaration,length))
    from .shell import declaration as shell_declaration
    result['shell']=shell_declaration(declaration,length)
    from .sweep import declarations as sweep_declarations
    result.update(sweep_declarations(declaration,length,VEC))
    return result


def extend_profiles(result):
    for kind in PROFILES & set(result):
        result[kind]['options']['frame']={'value':FRAME}
        from .drilling import PROFILES as drilling_profiles
        from .sweep import PATHS
        result[kind]['inputs']['body']={'required':kind in drilling_profiles|PATHS,'kind':'body'}
        result[kind]['inputs']['support']={'required':False,'kind':'solid'}
        from .faces import ARGUMENT
        result[kind]['options']['onFace']={'value':ARGUMENT}
    for kind in ('pad','pocket'):
        result[kind]['options']['direction']={'value':{'type':'enum','values':['forward','backward','symmetric']}}
    result['pad']['inputs']['base']={'required':False,'kind':'solid'}


def active(prepared):
    nodes=prepared['nodes']
    return (sum(n['filter']=='body' for n in nodes)>1 or sum(n['filter']=='pad' for n in nodes)>1
        or any(n['filter'] in NEW_FEATURES|{'sketch','slot','holeLocations','boltGrid','boltCircle','arcPath'} or 'frame' in n['options'] or 'onFace' in n['options'] or 'direction' in n['options'] and n['filter'] in ('pad','pocket')
            or n['filter'] in PROFILES and 'body' in n['inputs'] and (n['filter']=='polygon' or n['options']['plane']!='XY' or n['options']['origin']!=[0,0,0])
            or n['filter']=='pad' and 'base' in n['inputs'] for n in nodes))


def frame(options):
    if 'frame' in options:return options['frame']
    axes={'XY':([1,0,0],[0,0,1]),'XZ':([1,0,0],[0,-1,0]),'YZ':([0,1,0],[1,0,0])}
    x,n=axes[options['plane']]
    return {'origin':options['origin'],'xAxis':x,'normal':n}


def matrix(options):
    f=frame(options);x,n=f['xAxis'],f['normal'];y=[n[1]*x[2]-n[2]*x[1],n[2]*x[0]-n[0]*x[2],n[0]*x[1]-n[1]*x[0]]
    return [x[0],y[0],n[0],f['origin'][0],x[1],y[1],n[1],f['origin'][1],x[2],y[2],n[2],f['origin'][2],0,0,0,1]


def validate(kind,options,identity):
    from . import drilling
    if kind in drilling.PROFILES|{'hole'}:drilling.validate(kind,options,identity)
    if kind=='shell':
        from .shell import validate as validate_shell
        validate_shell(options,identity)
    if kind=='bodyDraft':
        from .draft import validate as validate_draft
        validate_draft(options,identity)
    if kind in ('additiveHelix','subtractiveHelix'):
        from .helix import validate as validate_helix
        validate_helix(options,identity)
    from .sweep import PATHS,FEATURES as sweeps,validate as validate_sweep
    if kind in PATHS|sweeps:validate_sweep(kind,options,identity)
    if 'onFace' in options and ('frame' in options or options['plane']!='XY' or options['origin']!=[0,0,0]):fail('CONFLICTING_FRAME','Face attachment replaces explicit frame/plane/origin',identity)
    if 'frame' in options:
        if options.get('plane','XY')!='XY' or options.get('origin',[0,0,0])!=[0,0,0]:fail('CONFLICTING_FRAME','Use either frame or plane/origin, not both',identity)
        f=options['frame'];x,n=f['xAxis'],f['normal']
        if any(abs(math.hypot(*v)-1)>1e-8 for v in (x,n)) or abs(sum(a*b for a,b in zip(x,n)))>1e-8:
            fail('INVALID_FRAME','Frame xAxis and normal must be perpendicular unit vectors',identity+'.frame')
    if kind in ('bodyFillet','bodyChamfer'):
        from .selections import validate as validate_edges
        validate_edges(options['edges'],identity+'.edges')
    for key in ('axis','normal','direction'):
        if key in options and isinstance(options[key],list) and math.hypot(*options[key])<1e-12:
            fail('INVALID_AXIS','Feature direction must be nonzero',identity+'.'+key)


def prepare(prepared):
    bodies={n['id']:{'members':[],'tip':None} for n in prepared['nodes'] if n['filter']=='body'}
    owners={};used=set();lookup={n['id']:n for n in prepared['nodes']}
    for node in prepared['nodes']:
        kind,identity,inputs=node['filter'],node['id'],node['inputs']
        if kind in PROFILES and (('support' in inputs)!=('onFace' in node['options'])):fail('INVALID_ATTACHMENT','Provide support and onFace together',identity)
        if kind in PROFILES and 'body' in inputs:
            owner=inputs['body']
            if 'support' in inputs and (owners.get(inputs['support'])!=owner or bodies[owner]['tip']!=inputs['support']):fail('INVALID_BODY_HISTORY','Attach to the current solid tip of the same Body',identity)
            owners[identity]=owner;bodies[owner]['members'].append(identity)
        elif kind=='datumAxis':
            owner=inputs['body'];owners[identity]=owner;bodies[owner]['members'].append(identity)
        elif kind=='bodySeed':
            owner=inputs['body'];record=bodies[owner]
            if record['members'] or record['tip'] is not None:
                fail('INVALID_BODY_SEED','Seed must be the first member of an empty Body',identity)
            owners[identity]=owner;record['members'].append(identity);record['tip']=identity
        elif kind in FEATURES:
            base=inputs.get('base');owner=inputs.get('body') or owners.get(base)
            if owner not in bodies:fail('INVALID_BODY_OWNERSHIP','Feature must name a Body or continue a Body-owned base',identity)
            record=bodies[owner]
            if base!=record['tip']:
                fail('INVALID_BODY_HISTORY','Feature base must be the current tip of its own Body; omit base only for its first additive feature',identity)
            if base is None and kind not in ('pad','bodyRevolve','additiveLoft','additivePipe','additiveHelix'):
                fail('INVALID_BODY_HISTORY','Start a Body with an additive feature',identity)
            if 'axis' in inputs and owners.get(inputs['axis'])!=owner:fail('INVALID_BODY_OWNERSHIP','Reference axis must belong to the same Body',identity)
            if kind=='bodyDraft' and owners.get(inputs['neutralPlane'])!=owner:
                fail('INVALID_BODY_OWNERSHIP','Draft neutral plane must be an earlier profile owned by the same Body',identity)
            profiles=inputs.get('sections',[inputs['profile']] if 'profile' in inputs else [])
            from .sweep import PATHS,FEATURES as sweeps
            if kind in sweeps:
                profiles=[inputs['profile']]+inputs.get('sections',[])
                if len(set(profiles))!=len(profiles):fail('INVALID_SWEEP_SECTION','Sweep cross-sections must be distinct',identity)
                if (node['options']['orientation']=='auxiliary')!=('auxiliary' in inputs):fail('INVALID_SWEEP_ORIENTATION','Only auxiliary orientation requires its guide path',identity)
                paths=[inputs['spine']]+([inputs['auxiliary']] if 'auxiliary' in inputs else [])
                if len(set(paths))!=len(paths) or set(paths)&set(profiles) or any(owners.get(p)!=owner for p in paths):fail('INVALID_SWEEP_PATH','Use distinct same-Body paths separate from cross-sections',identity)
            if any(owners.get(p)!=owner or p in used for p in profiles):
                fail('INVALID_BODY_OWNERSHIP','Use unused profiles owned by the same Body',identity)
            from . import drilling
            if any(lookup[p]['filter'] in drilling.PROFILES for p in profiles) and kind!='hole':fail('INVALID_HOLE_PROFILE','Drilling location profiles feed a Hole feature only',identity)
            if any(lookup[p]['filter'] in PATHS for p in profiles):fail('INVALID_SWEEP_SECTION','Bend paths are sweep guides, not material cross-sections',identity)
            if kind=='hole':
                source=lookup[inputs['profile']]
                if source['filter'] not in drilling.PROFILES|{'circle','sketch'} or source['filter']=='sketch' and (not any(not g['construction'] for g in source['options']['geometry']) or any(g['kind']!='circle' for g in source['options']['geometry'] if not g['construction'])):fail('INVALID_HOLE_PROFILE','Hole locations are circles or a typed drilling pattern',identity)
            used.update(profiles)
            if kind in ('linearPattern','polarPattern','mirror'):
                feature=inputs['feature']
                if owners.get(feature)!=owner or lookup[feature]['filter'] not in ('pad','pocket','bodyRevolve','groove','hole'):
                    fail('INVALID_BODY_HISTORY','Pattern an additive or subtractive sketch feature from the same Body',identity)
            if kind=='pocket':
                if (node['options']['extent']=='length')!=('length' in node['options']):
                    fail('INVALID_POCKET_EXTENT','Finite extent requires length; throughAll omits length',identity+'.options.length')
            owners[identity]=owner;record['members'].append(identity);record['tip']=identity
        elif kind!='body':
            for value in inputs.values():
                for source in value if isinstance(value,list) else [value]:
                    if source in owners:fail('INVALID_BODY_OWNERSHIP','Body members feed only their own PartDesign history',identity)
    output=prepared['output']
    if output in owners and output!=bodies[owners[output]]['tip']:
        fail('INVALID_BODY_HISTORY','Publish a final Body tip',output)
    if 'designStudy' in prepared:fail('UNSUPPORTED_BODY_STUDY','Use batch variants for native design histories')
    prepared['partDesign']={'generation':2,'bodies':bodies,'owners':owners}
    from .body_seed import prepare as prepare_seeds
    seeds=prepare_seeds(prepared,bodies,owners)
    if seeds:prepared['partDesign']['seeds']=seeds
    if any(n['options'].get('onFace',{}).get('anchor')=='centroid' for n in prepared['nodes']):
        prepared['partDesign']['centroidAttachment']='native-centre-of-mass'


def verify_auxiliaries(prepared,auxiliaries):
    from .part_design import ROLES,names
    if not isinstance(auxiliaries,dict) or set(auxiliaries)!=set(prepared['partDesign']['bodies']):
        fail('VERIFICATION_FAILED','Body origin membership differs')
    declared=set(names(prepared).values())|{'SchemaxisParameters'};result={}
    expected={'container':'App::Origin',**ROLES}
    for body,record in auxiliaries.items():
        if not isinstance(record,dict) or set(record)!=set(expected):fail('VERIFICATION_FAILED','Body origin role membership differs',body)
        for role,typ in expected.items():
            item=record[role]
            if not isinstance(item,dict) or set(item)!={'name','type'} or item['type']!=typ or not isinstance(item['name'],str) or not item['name'] or item['name'] in declared|set(result):
                fail('VERIFICATION_FAILED','Body origin identity or type differs',body+'.'+role)
            result[item['name']]=typ
    return result


def expected(prepared,auxiliaries):
    from .part_design import names,IDENTITY,constraint_definitions
    mapped=names(prepared);record=prepared['partDesign'];bodies={};profiles={};features={}
    for body,info in record['bodies'].items():
        from .body_seed import frame as body_frame
        from .operations import output_names
        source=record.get('seeds',{}).get(body)
        bodies[body]={'name':mapped[body],'type':'PartDesign::Body','label':body,'group':[mapped[k] for k in info['members']],
            'tip':mapped[info['tip']] if info['tip'] else None,'baseFeature':output_names(prepared)[source] if source else None,'origin':auxiliaries[body]['container']['name'],'placement':body_frame(prepared,body)}
    for node in prepared['nodes']:
        identity,kind,inputs,options=node['id'],node['filter'],node['inputs'],node['options']
        if identity not in record['owners'] and kind not in PROFILES:continue
        owner=mapped[record['owners'][identity]] if identity in record['owners'] else None
        if kind in PROFILES:
            from .faces import attachment_mode
            profiles[identity]={'owner':owner,'mapMode':attachment_mode(prepared,node),'support':[],'offset':IDENTITY,
                'placement':matrix(options),'fullyConstrained':True,'solver':0,'constraints':constraint_definitions(node)}
        elif kind=='datumAxis':
            features[identity]={'owner':owner,'mapMode':'Deactivated','support':[],'origin':options['origin'],'direction':[v/math.hypot(*options['direction']) for v in options['direction']]}
        elif kind=='bodySeed':
            features[identity]={'owner':owner,'baseFeature':node['seed']['source'],'suppressed':False}
        else:
            features[identity]=feature_expected(node,mapped,owner)
            if kind in ('bodyRevolve','groove','additiveHelix','subtractiveHelix'):
                features[identity]['referenceAxis']=[mapped[inputs['axis']] if 'axis' in inputs else auxiliaries[record['owners'][identity]][options['axis']+'_Axis']['name'],['']]
            if kind in ('additiveHelix','subtractiveHelix'):
                axis=next((n['options'] for n in prepared['nodes'] if n['id']==inputs.get('axis')),None)
                features[identity]['axisOrigin']=axis['origin'] if axis else [0,0,0]
                direction=axis['direction'] if axis else [int(a==options['axis']) for a in 'XYZ']
                features[identity]['axisDirection']=[v/math.hypot(*direction) for v in direction]
    return bodies,profiles,features


def feature_expected(node,mapped,owner):
    k,o,i=node['filter'],node['options'],node['inputs']
    record={'owner':owner,'baseFeature':mapped[i['base']] if i.get('base') else None,'refine':True}
    if k in ('pad','pocket'):
        direction=o.get('direction','forward')
        record.update(profile=[mapped[i['profile']],[]],type='ThroughAll' if k=='pocket' and o['extent']=='throughAll' else 'Length',
            sideType='Symmetric' if direction=='symmetric' else 'One side',reversed=(direction=='backward') if k=='pad' else direction!='backward',alongSketchNormal=True,customVector=False)
        if k=='pad' or o['extent']=='length':record['length']=o['length']
    elif k=='hole':
        from .drilling import hole_settings
        record.update(profile=[mapped[i['profile']],[]],**hole_settings(o))
    elif k=='shell':
        from .shell import settings
        record.update(base=[mapped[i['base']],None],**settings(o))
    elif k in ('additivePipe','subtractivePipe'):
        from .sweep import settings
        record.update(profile=[mapped[i['profile']],[]],spine=[mapped[i['spine']],[]],sections=[mapped[p] for p in i.get('sections',[])],
            auxiliary=[mapped[i['auxiliary']],[]] if 'auxiliary' in i else None,**settings(node))
    elif k=='bodyDraft':
        record.update(base=[mapped[i['base']],None],neutralPlane=[mapped[i['neutralPlane']],['']],
                      pullDirection=[mapped[i['axis']],['']] if 'axis' in i else None,
                      angle=o['angle'],reversed=o['reversed'],suppressed=False,supportTransform=False,fuzzyTolerance=-1)
    elif k in ('additiveHelix','subtractiveHelix'):
        from .helix import settings
        record.update(profile=[mapped[i['profile']],[]],**settings(o))
    elif k in ('bodyRevolve','groove'):
        record.update(profile=[mapped[i['profile']],[]],angle=o['angle'],reversed=o['reversed'],midplane=False)
    elif k in ('bodyFillet','bodyChamfer'):
        record.update(base=[mapped[i['base']],None],size=o['radius' if k=='bodyFillet' else 'distance'])
    elif k in ('linearPattern','polarPattern','mirror'):
        record.update(originals=[mapped[i['feature']]],count=o.get('count',2))
        if k=='linearPattern':record.update(length=o['length'],direction=o['direction'])
        elif k=='polarPattern':record.update(angle=o['angle'],axis=o['axis'])
        else:record.update(plane=o['plane'])
    elif k in ('additiveLoft','subtractiveLoft'):
        record.update(profile=[mapped[i['sections'][0]],[]],sections=[mapped[p] for p in i['sections'][1:]],ruled=o['ruled'],closed=False)
    return record


def verify_observation(prepared,observed,*,visibility=True,saved=False):
    from .adaptor import close
    from .part_design import names
    wanted={'bodies','auxiliaries','profiles','features','expressions'}|({'visibility'} if visibility else set())
    if not isinstance(observed,dict) or set(observed)!=wanted:fail('VERIFICATION_FAILED','Design history observation membership differs')
    extras=verify_auxiliaries(prepared,observed['auxiliaries'])
    from .parameters import check_engines
    check_engines(prepared,observed['expressions'],observed['auxiliaries'])
    bodies,profiles,features=expected(prepared,observed['auxiliaries'])
    if saved:
        for record in profiles.values():record.pop('solver')
    def compare(actual,wanted,location):
        if isinstance(wanted,dict):
            if not isinstance(actual,dict) or set(actual)!=set(wanted):fail('VERIFICATION_FAILED','Design history fields differ',location)
            for k,v in wanted.items():compare(actual[k],v,location+'.'+k)
        elif isinstance(wanted,list):
            if not isinstance(actual,list) or len(actual)!=len(wanted):fail('VERIFICATION_FAILED','Design history list differs',location)
            for n,(a,b) in enumerate(zip(actual,wanted)):compare(a,b,location+'.'+str(n))
        elif type(wanted) in (int,float):
            if not close(actual,wanted):fail('VERIFICATION_FAILED','Design history value differs',location)
        elif type(actual)!=type(wanted) or actual!=wanted:fail('VERIFICATION_FAILED','Design history setting differs',location)
    compare(observed['bodies'],bodies,'bodies')
    from .sketch import verify_geometry
    lookup={n['id']:n for n in prepared['nodes']}
    if not isinstance(observed['profiles'],dict) or set(observed['profiles'])!=set(profiles):fail('VERIFICATION_FAILED','Sketch profile membership differs')
    for identity,wanted in profiles.items():
        actual=observed['profiles'][identity]
        if not isinstance(actual,dict) or 'geometry' not in actual:fail('VERIFICATION_FAILED','Sketch geometry evidence is absent',identity)
        verify_geometry(lookup[identity],actual['geometry'])
        node=lookup[identity]
        if 'onFace' in node['options']:
            if saved:
                if not isinstance(actual.get('support'),list) or len(actual['support'])!=1 or actual['support'][0][0]!=names(prepared)[node['inputs']['support']]:fail('VERIFICATION_FAILED','Saved attachment support differs',identity)
                wanted.update(support=actual['support'],offset=actual['offset'],placement=actual['placement'])
            else:
                from .faces import resolve,frame as face_frame
                face=resolve(node['options']['onFace'],actual.get('faceInventory'),identity)
                wanted.update(support=[[names(prepared)[node['inputs']['support']],['Face'+str(face['index'])]]],
                    placement=matrix({'frame':face_frame(node['options']['onFace'],face)}),offset=actual['offset'],faceInventory=actual['faceInventory'])
        compare(actual,{**wanted,'geometry':actual['geometry']},identity)
    # Dress-up edge indices are resolved from measured geometry, not guessed here.
    actual=observed['features']
    if not isinstance(actual,dict) or set(actual)!=set(features):fail('VERIFICATION_FAILED','Design feature membership differs')
    from .selections import resolve
    lookup={n['id']:n for n in prepared['nodes']}
    for identity,wanted in features.items():
        node=lookup[identity]
        if node['filter'] in ('shell','bodyDraft'):
            record=actual[identity]
            selector='openings' if node['filter']=='shell' else 'faces'
            if not isinstance(record,dict) or not isinstance(record.get('base'),list) or len(record['base'])!=2 or not isinstance(record['base'][1],list) or len(record['base'][1])!=len(node['options'][selector]) or any(not isinstance(n,str) or not n.startswith('Face') or not n[4:].isdigit() or int(n[4:])<1 or n!='Face'+str(int(n[4:])) for n in record['base'][1]) or len(set(record['base'][1]))!=len(record['base'][1]):fail('VERIFICATION_FAILED','Feature face linkage is malformed',identity)
            if saved:indices=record['base'][1]
            else:
                if node['filter']=='shell':from .shell import selected
                else:from .draft import selected
                indices=selected(node['options'],record.get('faceInventory'),identity)
                wanted={**wanted,'faceInventory':record['faceInventory']}
            wanted['base'][1]=indices
        if node['filter'] in ('bodyFillet','bodyChamfer'):
            record=actual[identity]
            if saved:
                if not isinstance(record,dict) or not isinstance(record.get('edges'),list) or not record['edges'] or any(not isinstance(e,str) or not e.startswith('Edge') or not e[4:].isdigit() for e in record['edges']):fail('VERIFICATION_FAILED','Saved dress-up edge linkage is malformed',identity)
                edges=record['edges']
                if isinstance(node['options']['edges'],list) and edges!=['Edge'+str(n) for n in node['options']['edges']]:fail('VERIFICATION_FAILED','Saved explicit dress-up edges differ',identity)
                wanted={**wanted,'edges':edges}
            else:
                if not isinstance(record,dict) or not {'edgeInventory','edges'}<=set(record):fail('VERIFICATION_FAILED','Dress-up selection evidence is absent',identity)
                edges=resolve(node['options']['edges'],record['edgeInventory'],identity)
                wanted={**wanted,'edgeInventory':record['edgeInventory'],'edges':['Edge'+str(n) for n in edges]}
            wanted['base'][1]=wanted['edges']
        compare(actual[identity],wanted,identity)
    if visibility:
        from .operations import extra_objects
        mapped=names(prepared);visible={mapped[prepared['output']]}
        for body,record in prepared['partDesign']['bodies'].items():
            if prepared['output']==record['tip']:visible.add(mapped[body])
        expected_names=set(mapped.values())|set(extras)|set(extra_objects(prepared))|({'SchemaxisParameters'} if 'parameters' in prepared else set())
        compare(observed['visibility'],{n:n in visible for n in expected_names},'visibility')


def equivalent(first,second):
    """Preserve exact structure, strings and booleans with native numeric tolerance.

    FCStd quaternion storage perturbs rotated placement matrices by a few ulps.
    The tolerance is the same public numeric contract used for each observation.
    """
    from .adaptor import close
    if isinstance(first,dict):return isinstance(second,dict) and set(first)==set(second) and all(equivalent(v,second[k]) for k,v in first.items())
    if isinstance(first,list):return isinstance(second,list) and len(first)==len(second) and all(equivalent(a,b) for a,b in zip(first,second))
    if type(first) in (int,float):return close(first,second)
    return type(first)==type(second) and first==second
