# Copyright (C) 2026 David L F Gaden
"""Native Body ownership and a bounded sketch/Pad/through-Pocket history."""
import FreeCAD as App
from schemaxis.errors import fail
from . import part_design as policy


def create(doc, prepared, node, index):
    if prepared['partDesign'].get('generation')==2:
        from .history_native import create as action
        return action(doc,prepared,node,index)
    from .adaptor import DECLARATIONS
    native=DECLARATIONS[node['filter']]['native'];name='N'+str(index)
    if node['id'] in prepared['partDesign']['members']:
        body=doc.getObject(policy.names(prepared)[prepared['partDesign']['body']])
        return body.newObject(native,name)
    return doc.addObject(native,name)


def configure(obj,node,objects):
    kind,options=node['filter'],node['options']
    if kind=='body':return
    obj.Profile=objects[node['inputs']['profile']]
    obj.SideType='One side';obj.AlongSketchNormal=True;obj.UseCustomVector=False
    obj.Refine=True
    if kind=='pad':
        obj.Type='Length';obj.Reversed=False;obj.Length=options['length']
    else:
        obj.Type='Length' if options['extent']=='length' else 'ThroughAll';obj.Reversed=True
        if options['extent']=='length':obj.Length=options['length']
        obj.BaseFeature=objects[node['inputs']['base']]


def attach(obj,body):
    planes=[o for o in body.Origin.OriginFeatures if o.Role=='XY_Plane']
    if len(planes)!=1:fail('VERIFICATION_FAILED','Body XY origin plane is absent or ambiguous')
    obj.AttachmentSupport=[(planes[0],[''])];obj.MapMode='FlatFace'
    obj.AttachmentOffset=App.Placement()


def finish(doc,prepared):
    if prepared['partDesign'].get('generation')==2:
        from .history_native import finish as action
        return action(doc,prepared)
    mapped=policy.names(prepared);record=prepared['partDesign']
    body=doc.getObject(mapped[record['body']])
    body.Tip=doc.getObject(mapped[record['tip']]) if record['tip'] is not None else None
    doc.recompute()


def auxiliaries(doc,prepared):
    if prepared['partDesign'].get('generation')==2:
        from .history_native import auxiliaries as action
        return action(doc,prepared)
    body=doc.getObject(policy.names(prepared)[prepared['partDesign']['body']])
    if body is None or body.TypeId!='PartDesign::Body' or body.Origin is None:
        fail('VERIFICATION_FAILED','Native Body or its Origin is absent')
    origin=body.Origin
    result={'container':{'name':origin.Name,'type':origin.TypeId}}
    for item in origin.OriginFeatures:
        role=item.Role
        if role in result:fail('VERIFICATION_FAILED','Duplicate Body origin role',role)
        result[role]={'name':item.Name,'type':item.TypeId}
    expected=policy.verify_auxiliaries(prepared,result)
    names=set(policy.names(prepared).values())|set(expected)
    if 'parameters' in prepared:names.add('SchemaxisParameters')
    if len(doc.Objects)!=len(names) or {o.Name for o in doc.Objects}!=names:
        fail('VERIFICATION_FAILED','Native Body document object membership differs')
    return result


def observe(doc,prepared, *, visibility=True):
    if prepared['partDesign'].get('generation')==2:
        from .history_native import observe as action
        return action(doc,prepared,visibility=visibility)
    mapped=policy.names(prepared);record=prepared['partDesign'];body=doc.getObject(mapped[record['body']])
    aux=auxiliaries(doc,prepared)
    result={'body':{'name':body.Name,'type':body.TypeId,'label':body.Label,
                   'group':[o.Name for o in body.Group],'tip':body.Tip.Name if body.Tip else None,
                   'baseFeature':body.BaseFeature.Name if body.BaseFeature else None,
                   'origin':body.Origin.Name,'placement':list(body.Placement.toMatrix().A)},'auxiliaries':aux,'profiles':{},'features':{},'expressions':{o.Name:[list(p) for p in o.ExpressionEngine] for o in doc.Objects}}
    for role,item in aux.items():
        obj=doc.getObject(item['name'])
        if obj.ExpressionEngine:fail('VERIFICATION_FAILED','Body origin helpers cannot have expressions',role)
    for node in prepared['nodes']:
        if node['id'] not in record['members']:continue
        obj=doc.getObject(mapped[node['id']]);owner=obj.getParentGeoFeatureGroup()
        if owner!=body:fail('VERIFICATION_FAILED','Native feature is outside its declared Body',node['id'])
        if any(s in obj.State for s in ('Invalid','Error','Touched')):
            fail('INVALID_GEOMETRY','PartDesign feature failed recompute',node['id'])
        if node['filter'] in ('rectangle','circle'):
            result['profiles'][node['id']]={'owner':owner.Name,'mapMode':obj.MapMode,
                'support':[[o.Name,list(sub)] for o,sub in obj.AttachmentSupport],
                'offset':list(obj.AttachmentOffset.toMatrix().A),'placement':list(obj.Placement.toMatrix().A),
                'fullyConstrained':bool(obj.FullyConstrained),'solver':obj.solve(),
                'constraints':[{'name':c.Name,'type':c.Type,'value':float(c.Value),
                    **{k:getattr(c,k[0].upper()+k[1:]) for k in ('first','firstPos','second','secondPos','third','thirdPos')}} for c in obj.Constraints]}
            if any(not c.Driving or not c.IsActive for c in obj.Constraints):
                fail('VERIFICATION_FAILED','Body sketch constraints must remain active and driving',node['id'])
        else:
            source,sub=obj.Profile
            result['features'][node['id']]={'owner':owner.Name,'profile':[source.Name,list(sub)],
                'baseFeature':obj.BaseFeature.Name if obj.BaseFeature else None,'type':obj.Type,
                'sideType':obj.SideType,'reversed':bool(obj.Reversed),'alongSketchNormal':bool(obj.AlongSketchNormal),
                'customVector':bool(obj.UseCustomVector),'refine':bool(obj.Refine)}
            if node['filter']=='pad' or node['options']['extent']=='length':result['features'][node['id']]['length']=float(obj.Length.Value)
            if node['filter']=='pocket' and not obj.Shape.Volume < obj.BaseFeature.Shape.Volume-1e-7:
                fail('INVALID_GEOMETRY','Pocket must remove a positive volume from its base',node['id'])
    if visibility:result['visibility']={o.Name:bool(o.Visibility) for o in doc.Objects}
    policy.verify_observation(prepared,result,visibility=visibility)
    return result


def set_visibility(doc,prepared):
    if prepared['partDesign'].get('generation')==2:
        from .history_native import set_visibility as action
        return action(doc,prepared)
    mapped=policy.names(prepared);record=prepared['partDesign']
    visible={mapped[prepared['output']]}
    if prepared['output']==record['tip']:visible.add(mapped[record['body']])
    for obj in doc.Objects:obj.Visibility=obj.Name in visible
