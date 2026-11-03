# Copyright (C) 2026 David L F Gaden
"""Native variable-set lifetime and readback for the batch-only driver contract."""
from . import parameters as policy
from schemaxis.errors import fail


def create(doc, prepared):
    obj = doc.addObject('App::VarSet', policy.OBJECT_NAME)
    obj.Label = policy.OBJECT_LABEL
    obj.Visibility = False
    for identity, parameter in prepared['parameters'].items():
        name = policy.property_name(identity)
        obj.addProperty('App::PropertyLength', name, 'Design parameters', identity + ' in mm')
        if name not in obj.PropertiesList or obj.getTypeIdOfProperty(name) != 'App::PropertyLength':
            fail('PARAMETER_ASSIGNMENT_FAILED', 'FreeCAD changed the parameter property name or type', identity)
        setattr(obj, name, parameter['value'])
        if float(getattr(obj, name).Value) != parameter['value']:
            fail('PARAMETER_ASSIGNMENT_FAILED', 'FreeCAD clamped or changed the requested driver value', identity)
    return obj


def bind(obj, node):
    for option, binding in node.get('drive', {}).items():
        obj.setExpression(policy.TARGETS[node['filter']][option], policy.expression(binding))


def observe(doc, prepared):
    obj = doc.getObject(policy.OBJECT_NAME)
    if obj is None:
        fail('VERIFICATION_FAILED', 'Native design parameter object is absent')
    from .operations import extra_objects
    expected_names = {policy.OBJECT_NAME, *('N'+str(i) for i in range(len(prepared['nodes']))), *extra_objects(prepared)}
    extra={}
    if 'partDesign' in prepared:
        from .part_design_native import auxiliaries
        extra['auxiliaries']=auxiliaries(doc,prepared)
        expected_names.update(v['name'] for v in extra['auxiliaries'].values())
    if {o.Name for o in doc.Objects} != expected_names or len(doc.Objects) != len(expected_names):
        fail('VERIFICATION_FAILED', 'Native parameterised document membership differs')
    result = {'object':{'name':obj.Name,'label':obj.Label,'type':obj.TypeId,
                        'properties':sorted(obj.PropertiesList),'visibility':bool(obj.Visibility)},
              'parameters':{},'expressions':{},'targets':{},**extra}
    for identity in prepared['parameters']:
        name = policy.property_name(identity)
        if name not in obj.PropertiesList:
            fail('VERIFICATION_FAILED', 'Native driver property is absent', identity)
        result['parameters'][identity] = {'property':name,'type':obj.getTypeIdOfProperty(name),
                                          'value':float(getattr(obj,name).Value)}
    for member in doc.Objects:
        if any(state in member.State for state in ('Invalid','Error')):
            fail('INVALID_GEOMETRY', 'Native driver or feature failed recompute', member.Label)
        result['expressions'][member.Name] = [list(pair) for pair in member.ExpressionEngine]
    for index,node in enumerate(prepared['nodes']):
        member = doc.getObject('N'+str(index))
        for option in node.get('drive', {}):
            if node['filter'] in ('rectangle','circle'):
                constraints=[c for c in member.Constraints if c.Name==option]
                if len(constraints)!=1:fail('VERIFICATION_FAILED','Named driven sketch constraint differs',node['id'])
                value=constraints[0].Value
            else:value=getattr(member,policy.TARGETS[node['filter']][option]).Value
            result['targets'][node['id']+'.'+option] = float(value)
    policy.verify_observation(prepared, result)
    return result
