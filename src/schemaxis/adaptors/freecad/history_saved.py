"""Independent FCStd XML readback for typed multi-Body design histories."""
import math
from . import history as policy
from .part_design import names


def placement(xml,name,prop):
    item=xml.child(name,prop,'PropertyPlacement','App::PropertyPlacement')
    q=[float(item.attrib['Q'+str(k)]) for k in range(4)];x,y,z,w=q
    if abs(sum(v*v for v in q)-1)>1e-8:raise ValueError('placement quaternion is not unit')
    t=[float(item.attrib['P'+a]) for a in 'xyz']
    return [1-2*(y*y+z*z),2*(x*y-z*w),2*(x*z+y*w),t[0],
            2*(x*y+z*w),1-2*(x*x+z*z),2*(y*z-x*w),t[1],
            2*(x*z-y*w),2*(y*z+x*w),1-2*(x*x+y*y),t[2],0,0,0,1]


def link(xml,name,prop):
    item=xml.child(name,prop,'LinkSub','App::PropertyLinkSub')
    if int(item.get('count'))!=len(item) or any(c.tag!='Sub' for c in item):raise ValueError('saved link subelement count differs')
    return [item.get('value'),[c.get('value') for c in item]]


def enum(xml,name,prop,index,label):
    item=xml.child(name,prop,'Integer','App::PropertyEnumeration')
    if int(item.get('value'))!=index:raise ValueError('saved enumeration differs: '+name+'.'+prop)
    return label


def vector(xml,name,prop):
    item=xml.child(name,prop,'PropertyVector','App::PropertyVector');return [float(item.get('value'+a)) for a in 'XYZ']


def geometry(xml,name):
    values=xml.child(name,'Geometry','GeometryList','Part::PropertyGeometryList')
    if len(values)!=int(values.get('count')):raise ValueError('saved geometry count differs')
    result=[]
    for item in values:
        if item.tag!='Geometry':raise ValueError('saved geometry entry differs')
        typ=item.get('type');construction=item.find('Construction')
        if construction is None or construction.get('value') not in ('0','1'):raise ValueError('saved construction flag differs')
        def point(child,prefix):return [float(child.get(prefix+a)) for a in 'XY']
        if typ=='Part::GeomLineSegment':
            g=item.find('LineSegment');r={'kind':'line','start':point(g,'Start'),'end':point(g,'End')}
            if any(abs(float(g.get(p+'Z')))>1e-7 for p in ('Start','End')):raise ValueError('non-planar saved sketch')
        elif typ=='Part::GeomCircle':
            g=item.find('Circle');r={'kind':'circle','centre':point(g,'Center'),'radius':float(g.get('Radius'))}
        elif typ=='Part::GeomArcOfCircle':
            g=item.find('ArcOfCircle');r={'kind':'arc','centre':point(g,'Center'),'radius':float(g.get('Radius')),
                'startAngle':math.degrees(float(g.get('StartAngle'))),'endAngle':math.degrees(float(g.get('EndAngle')))}
        else:raise ValueError('unsupported saved sketch geometry '+str(typ))
        if r['kind'] in ('circle','arc') and (any(abs(float(g.get('Normal'+a))-v)>1e-7 for a,v in zip('XYZ',[0,0,1])) or abs(float(g.get('CenterZ')))>1e-7 or abs(float(g.get('AngleXU')))>1e-7):raise ValueError('saved circle/arc orientation differs')
        result.append({**r,'construction':construction.get('value')=='1'})
    return result


def observation(prepared,xml):
    mapped=names(prepared);record=prepared['partDesign'];aux={};bodies={}
    for identity,info in record['bodies'].items():
        name=mapped[identity];origin=xml.link(name,'Origin');a={'container':{'name':origin,'type':xml.types[origin]}}
        for helper in xml.links(origin,'OriginFeatures'):
            role=xml.string(helper,'Role')
            if role in a:raise ValueError('duplicate Body origin role')
            a[role]={'name':helper,'type':xml.types[helper]}
        aux[identity]=a
        bodies[identity]={'name':name,'type':xml.types[name],'label':xml.string(name,'Label'),'group':xml.links(name,'Group'),
            'tip':xml.link(name,'Tip'),'baseFeature':xml.link(name,'BaseFeature'),'origin':origin,'placement':placement(xml,name,'Placement')}
    extra=policy.verify_auxiliaries(prepared,aux)
    from .adaptor import DECLARATIONS
    expected={mapped[n['id']]:DECLARATIONS[n['filter']]['native'] for n in prepared['nodes']};expected.update(extra)
    from .operations import extra_objects
    expected.update(extra_objects(prepared))
    if 'parameters' in prepared:
        from .parameters import object_type
        expected['SchemaxisParameters']=object_type(prepared)
    if xml.types!=expected:raise ValueError('saved design-history object membership/type differs')
    result={'bodies':bodies,'auxiliaries':aux,'profiles':{},'features':{},'expressions':{n:xml.engine(n) for n in expected},'visibility':{n:xml.boolean(n,'Visibility') for n in expected}}
    for node in prepared['nodes']:
        identity,k,o,i=node['id'],node['filter'],node['options'],node['inputs']
        if identity not in record['owners'] and k not in policy.PROFILES:continue
        name=mapped[identity];owner=mapped[record['owners'][identity]] if identity in record['owners'] else None
        if owner is not None and name not in bodies[record['owners'][identity]]['group']:raise ValueError('saved feature is outside Body group')
        if k in policy.PROFILES:
            from .faces import attachment_mode,check_attacher
            mode=attachment_mode(prepared,node);check_attacher(mode,xml.string(name,'AttacherType'),identity)
            support=xml.child(name,'AttachmentSupport','LinkSubList','App::PropertyLinkSubList')
            if int(support.get('count'))!=len(support):raise ValueError('saved attachment support count differs')
            result['profiles'][identity]={'owner':owner,'mapMode':enum(xml,name,'MapMode',{'Deactivated':0,'FlatFace':5,'CenterOfMass':37}[mode],mode),
                'support':[[c.get('obj'),[c.get('sub')]] for c in support],
                'offset':placement(xml,name,'AttachmentOffset'),'placement':placement(xml,name,'Placement'),
                'fullyConstrained':xml.boolean(name,'FullyConstrained'),'constraints':xml.constraints(name),'geometry':geometry(xml,name)}
            continue
        if k=='datumAxis':
            m=placement(xml,name,'Placement');support=xml.child(name,'AttachmentSupport','LinkSubList','App::PropertyLinkSubList')
            if len(support) or support.get('count')!='0':raise ValueError('saved datum support differs')
            result['features'][identity]={'owner':owner,'mapMode':enum(xml,name,'MapMode',0,'Deactivated'),'support':[],
                'origin':[m[3],m[7],m[11]],'direction':[m[2],m[6],m[10]]}
            continue
        if k=='bodySeed':
            result['features'][identity]={'owner':owner,'baseFeature':xml.link(name,'BaseFeature'),'suppressed':xml.boolean(name,'Suppressed')}
            continue
        r={'owner':owner,'baseFeature':xml.link(name,'BaseFeature'),'refine':xml.boolean(name,'Refine')}
        if k in ('pad','pocket'):
            finite=k=='pad' or o['extent']=='length'
            r.update(profile=link(xml,name,'Profile'),type=enum(xml,name,'Type',0 if finite else 1,'Length' if finite else 'ThroughAll'),
                sideType=enum(xml,name,'SideType',2 if o.get('direction')=='symmetric' else 0,'Symmetric' if o.get('direction')=='symmetric' else 'One side'),
                reversed=xml.boolean(name,'Reversed'),alongSketchNormal=xml.boolean(name,'AlongSketchNormal'),customVector=xml.boolean(name,'UseCustomVector'))
            if finite:r['length']=xml.number(name,'Length')
        elif k=='hole':
            from .drilling import saved_settings
            r.update(profile=link(xml,name,'Profile'),**saved_settings(xml,name,node))
        elif k=='shell':
            r.update(base=link(xml,name,'Base'),thickness=xml.number(name,'Value','App::PropertyLength'),mode=enum(xml,name,'Mode',0,'Skin'),
                join=enum(xml,name,'Join',1 if o['corners']=='sharp' else 0,'Intersection' if o['corners']=='sharp' else 'Arc'),
                reversed=xml.boolean(name,'Reversed'),intersectionHandling=xml.boolean(name,'Intersection'))
        elif k=='bodyDraft':
            direction=link(xml,name,'PullDirection')
            r.update(base=link(xml,name,'Base'),neutralPlane=link(xml,name,'NeutralPlane'),
                     pullDirection=direction if direction[0] else None,
                     angle=xml.number(name,'Angle','App::PropertyAngle'),reversed=xml.boolean(name,'Reversed'),suppressed=xml.boolean(name,'Suppressed'),
                     supportTransform=xml.boolean(name,'SupportTransform'),fuzzyTolerance=xml.number(name,'FuzzyTolerance','App::PropertyFloatConstraint'))
        elif k in ('additiveHelix','subtractiveHelix'):
            from .helix import saved_settings
            r.update(profile=link(xml,name,'Profile'),referenceAxis=link(xml,name,'ReferenceAxis'),**saved_settings(xml,name))
        elif k in ('additivePipe','subtractivePipe'):
            from .sweep import saved_settings
            sections=xml.child(name,'Sections','LinkSubList','App::PropertyLinkSubList')
            if len(sections)!=int(sections.get('count')) or any(c.tag!='Link' or c.get('sub')!='' for c in sections):raise ValueError('saved sweep sections differ')
            auxiliary=link(xml,name,'AuxiliarySpine')
            r.update(profile=link(xml,name,'Profile'),spine=link(xml,name,'Spine'),sections=[c.get('obj') for c in sections],
                auxiliary=auxiliary if auxiliary[0] else None,**saved_settings(xml,name))
        elif k in ('bodyRevolve','groove'):
            r.update(profile=link(xml,name,'Profile'),angle=xml.number(name,'Angle','App::PropertyAngle'),referenceAxis=link(xml,name,'ReferenceAxis'),
                reversed=xml.boolean(name,'Reversed'),midplane=xml.boolean(name,'Midplane'))
            enum(xml,name,'Type',0,'Angle')
        elif k in ('bodyFillet','bodyChamfer'):
            r.update(base=link(xml,name,'Base'),size=xml.number(name,'Radius' if k=='bodyFillet' else 'Size','App::PropertyQuantityConstraint'))
            # Geometry inventory is not XML metadata. The caller obtains it from the
            # separately bound native observations and verifies both saved links and
            # the independently replayed geometric selection.
            r.update(edges=r['base'][1])
            if k=='bodyChamfer':enum(xml,name,'ChamferType',0,'Equal distance')
        elif k in ('linearPattern','polarPattern','mirror'):
            roles={h['name']:role for role,h in aux[record['owners'][identity]].items()}
            def role(prop,suffix):
                target,subs=link(xml,name,prop)
                if subs!=[''] or target not in roles or not roles[target].endswith(suffix):raise ValueError('saved pattern datum differs')
                return roles[target][:-len(suffix)]
            r.update(originals=xml.links(name,'Originals'),count=int(xml.child(name,'Occurrences','Integer','App::PropertyIntegerConstraint').get('value')) if k!='mirror' else 2)
            if k=='linearPattern':r.update(direction=role('Direction','_Axis'),length=xml.number(name,'Length'))
            elif k=='polarPattern':r.update(axis=role('Axis','_Axis'),angle=xml.number(name,'Angle','App::PropertyAngle'))
            else:r.update(plane=role('MirrorPlane','_Plane'))
            if k!='mirror' and xml.boolean(name,'Reversed'):raise ValueError('saved pattern reversal differs')
        else:
            sections=xml.child(name,'Sections','LinkSubList','App::PropertyLinkSubList')
            if len(sections)!=int(sections.get('count')) or any(c.get('sub')!='' for c in sections):raise ValueError('saved loft sections differ')
            r.update(profile=link(xml,name,'Profile'),sections=[c.get('obj') for c in sections],ruled=xml.boolean(name,'Ruled'),closed=xml.boolean(name,'Closed'))
        result['features'][identity]=r
    # Saved-only inspection cannot invent a native edge inventory. It validates
    # every available setting here; compare_saved verifies the selection linkage.
    validate_saved(prepared,result)
    return result



def validate_saved(prepared,result):
    policy.verify_observation(prepared,result,saved=True)
