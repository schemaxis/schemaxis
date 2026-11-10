"""Native execution/readback for the finite trusted design-history catalogue."""
import math
import FreeCAD as App
import Part
import Sketcher
from schemaxis.errors import fail
from . import history as policy
from .part_design import names


def create(doc,prepared,node,index):
    from .adaptor import DECLARATIONS
    owner=prepared['partDesign']['owners'].get(node['id'])
    if owner:return doc.getObject(names(prepared)[owner]).newObject(DECLARATIONS[node['filter']]['native'],'N'+str(index))
    return doc.addObject(DECLARATIONS[node['filter']]['native'],'N'+str(index))


def placement(options):
    m=App.Matrix(*policy.matrix(options));return App.Placement(m)


def configure_profile(obj,node):
    kind,o=node['filter'],node['options']
    obj.MapMode='Deactivated';obj.AttachmentSupport=[];obj.AttachmentOffset=App.Placement();obj.Placement=placement(o)
    from .drilling import PROFILES as drilling_profiles
    if kind=='arcPath':
        from .sweep_native import path
        path(obj,node)
    elif kind in drilling_profiles:
        from .drilling_native import profile
        profile(obj,node)
    elif kind in ('rectangle','circle'):
        from .sketch_features import configure
        configure(obj,kind,o)
    elif kind=='slot':
        from .slot import geometry as slot_geometry,constraints as slot_constraints
        records=slot_geometry(o)
        for g in records:
            value=Part.LineSegment(App.Vector(*g['start'],0),App.Vector(*g['end'],0)) if g['kind']=='line' else Part.ArcOfCircle(Part.Circle(App.Vector(*g['centre'],0),App.Vector(0,0,1),g['radius']),math.radians(g['startAngle']),math.radians(g['endAngle']))
            obj.addGeometry(value,False)
        for c in slot_constraints(o):
            args=[c['first']]
            if c['firstPos']:args.append(c['firstPos'])
            if c['second']!=-2000:
                args.append(c['second'])
                if c['secondPos']:args.append(c['secondPos'])
            if c['type'] in ('Distance','DistanceX','DistanceY','Radius'):args.append(c['value'])
            index=obj.addConstraint(Sketcher.Constraint(c['type'],*args))
            if c['name']:obj.renameConstraint(index,c['name'])
        obj.setExpression('Constraints.anchorX','-Constraints.span / 2')
    elif kind=='polygon':
        points=o['points']
        for a,b in zip(points,points[1:]+points[:1]):obj.addGeometry(Part.LineSegment(App.Vector(*a,0),App.Vector(*b,0)),False)
        for index in range(len(points)):
            obj.renameConstraint(obj.addConstraint(Sketcher.Constraint('Block',index)),'fixed_'+str(index))
    else:
        for g in o['geometry']:
            if g['kind']=='line':geometry=Part.LineSegment(App.Vector(*g['start'],0),App.Vector(*g['end'],0))
            elif g['kind']=='circle':geometry=Part.Circle(App.Vector(*g['centre'],0),App.Vector(0,0,1),g['radius'])
            else:geometry=Part.ArcOfCircle(Part.Circle(App.Vector(*g['centre'],0),App.Vector(0,0,1),g['radius']),math.radians(g['startAngle']),math.radians(g['endAngle']))
            obj.addGeometry(geometry,g['construction'])
        from .sketch import definitions
        for c in definitions(node):
            args=[c['first']]
            if c['firstPos']:args.append(c['firstPos'])
            if c['second']!=-2000:
                args.append(c['second'])
                if c['secondPos']:args.append(c['secondPos'])
            if c['type'] in ('Distance','DistanceX','DistanceY','Radius','Diameter','Angle'):args.append(c['value'])
            index=obj.addConstraint(Sketcher.Constraint(c['type'],*args));obj.renameConstraint(index,c['name'])
    obj.Document.recompute()
    if obj.solve()!=0 or not obj.FullyConstrained:
        fail('CONSTRAINT_FAILED','Sketch must solve with no remaining degrees of freedom',node['id'])


def configure(obj,node,objects,*,centroid_native=False):
    k,o,i=node['filter'],node['options'],node['inputs']
    if k=='body':
        if 'frame' in o:obj.Placement=placement(o)
        return
    if k=='bodySeed':
        source=objects[i['source']];obj.BaseFeature=source
        objects[i['body']].BaseFeature=source
        obj.setExpression('Placement',node['seed']['source']+'.Placement')
        obj.Document.recompute()
        return
    if k in policy.PROFILES:
        configure_profile(obj,node)
        if 'onFace' in o:
            from .faces import native_inventory,resolve,frame
            source=objects[i['support']];source.Document.recompute();face=resolve(o['onFace'],native_inventory(source.Shape),node['id'])
            obj.AttachmentSupport=[(source,['Face'+str(face['index'])])]
            if centroid_native and o['onFace']['anchor']=='centroid':
                obj.changeAttacherType('Attacher::AttachEnginePoint');obj.MapMode='CenterOfMass'
                desired=frame(o['onFace'],face);desired['origin']=[o['onFace']['offset']*v for v in desired['normal']]
                obj.AttachmentOffset=placement({'frame':desired});obj.Document.recompute()
                return
            obj.MapMode='FlatFace';obj.AttachmentOffset=App.Placement();obj.Document.recompute()
            desired=placement({'frame':frame(o['onFace'],face)})
            obj.AttachmentOffset=obj.Placement.inverse().multiply(desired);obj.Document.recompute()
        return
    if k=='datumAxis':
        obj.MapMode='Deactivated';obj.AttachmentSupport=[];obj.Placement=App.Placement(App.Vector(*o['origin']),App.Rotation(App.Vector(0,0,1),App.Vector(*o['direction'])))
        return
    base=objects[i['base']] if i.get('base') else None
    obj.Refine=True
    if k in ('pad','pocket'):
        obj.Profile=objects[i['profile']];obj.SideType='Symmetric' if o.get('direction')=='symmetric' else 'One side'
        obj.AlongSketchNormal=True;obj.UseCustomVector=False;obj.Type='ThroughAll' if k=='pocket' and o['extent']=='throughAll' else 'Length'
        obj.Reversed=(o.get('direction','forward')=='backward') if k=='pad' else o.get('direction','forward')!='backward'
        if k=='pad' or o['extent']=='length':obj.Length=o['length']
    elif k=='hole':
        from .drilling_native import configure as configure_hole
        configure_hole(obj,node,objects)
    elif k=='shell':
        from .shell import selected,settings
        from .faces import native_inventory
        base.Document.recompute();obj.Base=(base,selected(o,native_inventory(base.Shape),node['id']))
        s=settings(o);obj.Value=s['thickness'];obj.Mode=s['mode'];obj.Join=s['join'];obj.Reversed=s['reversed'];obj.Intersection=s['intersectionHandling']
    elif k in ('additivePipe','subtractivePipe'):
        from .sweep_native import configure as configure_sweep
        configure_sweep(obj,node,objects)
    elif k=='bodyDraft':
        from .draft_native import configure as configure_draft
        configure_draft(obj,node,objects)
    elif k in ('additiveHelix','subtractiveHelix'):
        from .helix_native import configure as configure_helix
        configure_helix(obj,node,objects)
    elif k in ('bodyRevolve','groove'):
        obj.Profile=objects[i['profile']]
        body=objects[i['body']];roles={p.Role:p for p in body.Origin.OriginFeatures}
        obj.ReferenceAxis=(objects[i['axis']] if 'axis' in i else roles[o['axis']+'_Axis'],[''])
        obj.Angle=o['angle'];obj.Type='Angle';obj.Reversed=o['reversed'];obj.Midplane=False
    elif k in ('bodyFillet','bodyChamfer'):
        base.Document.recompute()
        from .selections import native_edges,resolve
        edges=resolve(o['edges'],native_edges(base.Shape),node['id'])
        obj.Base=(base,['Edge'+str(n) for n in edges])
        if k=='bodyFillet':obj.Radius=o['radius']
        else:obj.Size=o['distance'];obj.ChamferType='Equal distance'
    elif k in ('linearPattern','polarPattern','mirror'):
        body=base.getParentGeoFeatureGroup();roles={p.Role:p for p in body.Origin.OriginFeatures}
        obj.Originals=[objects[i['feature']]]
        if k=='linearPattern':obj.Direction=(roles[o['direction']+'_Axis'],['']);obj.Length=o['length'];obj.Occurrences=o['count'];obj.Reversed=False
        elif k=='polarPattern':obj.Axis=(roles[o['axis']+'_Axis'],['']);obj.Angle=o['angle'];obj.Occurrences=o['count'];obj.Reversed=False
        else:obj.MirrorPlane=(roles[o['plane']+'_Plane'],[''])
    elif k in ('additiveLoft','subtractiveLoft'):
        obj.Profile=objects[i['sections'][0]];obj.Sections=[(objects[p],['']) for p in i['sections'][1:]];obj.Ruled=o['ruled'];obj.Closed=False
    if base is not None:obj.BaseFeature=base
    obj.Document.recompute()
    if k=='hole':
        from .drilling_native import check_removal
        check_removal(obj,base)


def finish(doc,prepared):
    mapped=names(prepared)
    for body,info in prepared['partDesign']['bodies'].items():
        obj=doc.getObject(mapped[body]);obj.Tip=doc.getObject(mapped[info['tip']]) if info['tip'] else None
    doc.recompute()


def auxiliaries(doc,prepared):
    result={};mapped=names(prepared)
    for identity in prepared['partDesign']['bodies']:
        body=doc.getObject(mapped[identity]);origin=body.Origin
        record={'container':{'name':origin.Name,'type':origin.TypeId}}
        for obj in origin.OriginFeatures:record[obj.Role]={'name':obj.Name,'type':obj.TypeId}
        result[identity]=record
    extra=policy.verify_auxiliaries(prepared,result)
    from .operations import extra_objects
    expected=set(mapped.values())|set(extra)|set(extra_objects(prepared))|({'SchemaxisParameters'} if 'parameters' in prepared else set())
    if {o.Name for o in doc.Objects}!=expected:fail('VERIFICATION_FAILED','Native design-history object membership differs')
    return result


def link(value):
    if value is None:return None
    obj,sub=value;return [obj.Name,list(sub)]


def observe_feature(obj,node):
    k,o=node['filter'],node['options']
    if k=='bodySeed':
        return {'owner':obj.getParentGeoFeatureGroup().Name,'baseFeature':obj.BaseFeature.Name if obj.BaseFeature else None,'suppressed':bool(obj.Suppressed)}
    r={'owner':obj.getParentGeoFeatureGroup().Name,'baseFeature':obj.BaseFeature.Name if obj.BaseFeature else None,'refine':bool(obj.Refine)}
    if k in ('pad','pocket'):
        r.update(profile=link(obj.Profile),type=obj.Type,sideType=obj.SideType,reversed=bool(obj.Reversed),alongSketchNormal=bool(obj.AlongSketchNormal),customVector=bool(obj.UseCustomVector))
        if k=='pad' or o['extent']=='length':r['length']=float(obj.Length.Value)
    elif k=='hole':
        from .drilling_native import observe as observe_hole
        r.update(profile=link(obj.Profile),**observe_hole(obj,node))
    elif k=='shell':
        from .faces import native_inventory
        expected={'Value':'App::PropertyLength','Mode':'App::PropertyEnumeration','Join':'App::PropertyEnumeration','Reversed':'App::PropertyBool','Intersection':'App::PropertyBool'}
        if any(obj.getTypeIdOfProperty(p)!=t for p,t in expected.items()):fail('VERIFICATION_FAILED','Native shell property types differ',node['id'])
        r.update(base=link(obj.Base),thickness=float(obj.Value.Value),mode=str(obj.Mode),join=str(obj.Join),reversed=bool(obj.Reversed),intersectionHandling=bool(obj.Intersection),faceInventory=native_inventory(obj.BaseFeature.Shape))
    elif k in ('additivePipe','subtractivePipe'):
        from .sweep_native import observe as observe_sweep
        if any(list(sub)!=[''] for target,sub in obj.Sections):fail('VERIFICATION_FAILED','Sweep section linkage differs',node['id'])
        r.update(profile=link(obj.Profile),spine=link(obj.Spine),sections=[target.Name for target,sub in obj.Sections],auxiliary=link(obj.AuxiliarySpine),**observe_sweep(obj))
    elif k=='bodyDraft':
        from .draft_native import observe as observe_draft
        r.update(observe_draft(obj,node))
    elif k in ('additiveHelix','subtractiveHelix'):
        from .helix_native import observe as observe_helix
        r.update(profile=link(obj.Profile),referenceAxis=link(obj.ReferenceAxis),**observe_helix(obj,node))
    elif k in ('bodyRevolve','groove'):
        r.update(profile=link(obj.Profile),angle=float(obj.Angle.Value),referenceAxis=link(obj.ReferenceAxis),reversed=bool(obj.Reversed),midplane=bool(obj.Midplane))
        if obj.Type!='Angle':fail('VERIFICATION_FAILED','Revolution uses an unexpected axis reference or extent',node['id'])
    elif k in ('bodyFillet','bodyChamfer'):
        from .selections import native_edges
        r.update(base=link(obj.Base),size=float((obj.Radius if k=='bodyFillet' else obj.Size).Value),edges=list(obj.Base[1]),edgeInventory=native_edges(obj.BaseFeature.Shape))
        if k=='bodyChamfer' and obj.ChamferType!='Equal distance':fail('VERIFICATION_FAILED','Chamfer type differs',node['id'])
    elif k in ('linearPattern','polarPattern','mirror'):
        body=obj.getParentGeoFeatureGroup();roles={p.Name:p.Role for p in body.Origin.OriginFeatures}
        def role(value,suffix):
            target,sub=value
            if list(sub)!=[''] or target.Name not in roles or not roles[target.Name].endswith(suffix):fail('VERIFICATION_FAILED','Pattern datum reference differs',node['id'])
            return roles[target.Name][:-len(suffix)]
        r.update(originals=[x.Name for x in obj.Originals],count=int(obj.Occurrences) if k!='mirror' else 2)
        if k=='linearPattern':r.update(direction=role(obj.Direction,'_Axis'),length=float(obj.Length.Value))
        elif k=='polarPattern':r.update(axis=role(obj.Axis,'_Axis'),angle=float(obj.Angle.Value))
        else:r.update(plane=role(obj.MirrorPlane,'_Plane'))
        if k!='mirror' and obj.Reversed:fail('VERIFICATION_FAILED','Pattern direction differs',node['id'])
    else:r.update(profile=link(obj.Profile),sections=[p.Name for p,sub in obj.Sections],ruled=bool(obj.Ruled),closed=bool(obj.Closed))
    return r


def observe(doc,prepared,*,visibility=True):
    mapped=names(prepared);aux=auxiliaries(doc,prepared);result={'bodies':{},'auxiliaries':aux,'profiles':{},'features':{},'expressions':{o.Name:[list(p) for p in o.ExpressionEngine] for o in doc.Objects}}
    for identity,info in prepared['partDesign']['bodies'].items():
        obj=doc.getObject(mapped[identity]);result['bodies'][identity]={'name':obj.Name,'type':obj.TypeId,'label':obj.Label,
            'group':[o.Name for o in obj.Group],'tip':obj.Tip.Name if obj.Tip else None,'baseFeature':obj.BaseFeature.Name if obj.BaseFeature else None,
            'origin':obj.Origin.Name,'placement':list(obj.Placement.toMatrix().A)}
    for node in prepared['nodes']:
        if node['id'] not in prepared['partDesign']['owners'] and node['filter'] not in policy.PROFILES:continue
        identity=node['id']
        obj=doc.getObject(mapped[node['id']])
        if any(s in obj.State for s in ('Invalid','Error','Touched')):fail('INVALID_GEOMETRY','Native design feature failed recompute',node['id'])
        if node['filter'] in policy.PROFILES:
            from .faces import attachment_mode,check_attacher
            check_attacher(attachment_mode(prepared,node),obj.AttacherType,identity)
            result['profiles'][node['id']]={'owner':obj.getParentGeoFeatureGroup().Name if obj.getParentGeoFeatureGroup() else None,'mapMode':obj.MapMode,'support':[[o.Name,list(sub)] for o,sub in obj.AttachmentSupport],
                'offset':list(obj.AttachmentOffset.toMatrix().A),'placement':list(obj.Placement.toMatrix().A),'fullyConstrained':bool(obj.FullyConstrained),'solver':obj.solve(),
                'constraints':[{'name':c.Name,'type':c.Type,'value':float(c.Value),**{k:getattr(c,k[0].upper()+k[1:]) for k in ('first','firstPos','second','secondPos','third','thirdPos')}} for c in obj.Constraints]}
            result['profiles'][node['id']]['geometry']=geometry(obj)
            if 'onFace' in node['options']:
                from .faces import native_inventory
                result['profiles'][node['id']]['faceInventory']=native_inventory(doc.getObject(mapped[node['inputs']['support']]).Shape)
            if any(not c.Driving or not c.IsActive for c in obj.Constraints):fail('VERIFICATION_FAILED','Sketch constraint is inactive or non-driving',node['id'])
        elif node['filter']=='datumAxis':
            result['features'][node['id']]={'owner':obj.getParentGeoFeatureGroup().Name if obj.getParentGeoFeatureGroup() else None,'mapMode':obj.MapMode,'support':[[o.Name,list(sub)] for o,sub in obj.AttachmentSupport],
                'origin':list(obj.Placement.Base),'direction':list(obj.Placement.Rotation.multVec(App.Vector(0,0,1)))}
        else:
            result['features'][node['id']]=observe_feature(obj,node)
            if len(obj.Shape.Solids)!=1 or obj.Shape.Volume<=0:fail('INVALID_GEOMETRY','Each Body feature must leave one solid',node['id'])
            if node['filter'] in ('pocket','groove','subtractiveLoft','subtractivePipe') and not obj.Shape.Volume < obj.BaseFeature.Shape.Volume-1e-7:
                fail('INVALID_GEOMETRY','Subtractive feature must remove material',node['id'])
    if visibility:result['visibility']={o.Name:bool(o.Visibility) for o in doc.Objects}
    policy.verify_observation(prepared,result,visibility=visibility)
    return result


def set_visibility(doc,prepared):
    mapped=names(prepared);visible={mapped[prepared['output']]}
    for identity,record in prepared['partDesign']['bodies'].items():
        if prepared['output']==record['tip']:visible.add(mapped[identity])
    for obj in doc.Objects:obj.Visibility=obj.Name in visible


def geometry(obj):
    result=[]
    for n,g in enumerate(obj.Geometry):
        construction=bool(obj.getConstruction(n))
        typ=type(g).__name__
        if typ=='LineSegment':r={'kind':'line','start':list(g.StartPoint)[:2],'end':list(g.EndPoint)[:2]}
        elif typ=='Circle':r={'kind':'circle','centre':list(g.Center)[:2],'radius':float(g.Radius)}
        elif typ=='ArcOfCircle':r={'kind':'arc','centre':list(g.Center)[:2],'radius':float(g.Radius),'startAngle':math.degrees(g.FirstParameter),'endAngle':math.degrees(g.LastParameter)}
        else:fail('VERIFICATION_FAILED','Unexpected native sketch geometry type',obj.Label,type=typ)
        if typ in ('Circle','ArcOfCircle') and (list(g.Axis)!=[0.,0.,1.] or abs(g.XAxis.y)>1e-7 or abs(g.XAxis.x-1)>1e-7):fail('VERIFICATION_FAILED','Sketch circular curve orientation differs',obj.Label)
        if any(abs(v)>1e-7 for v in ([g.StartPoint.z,g.EndPoint.z] if typ=='LineSegment' else [g.Center.z])):fail('VERIFICATION_FAILED','Sketch geometry is not local planar geometry',obj.Label)
        result.append({**r,'construction':construction})
    return result
