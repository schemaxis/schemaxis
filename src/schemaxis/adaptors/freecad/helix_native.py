"""Installed native Helix mapping with complete input/derived-field readback."""
from schemaxis.errors import fail
from .helix import settings,PROPERTIES


def configure(obj,node,objects):
    o,i=node['options'],node['inputs'];s=settings(o)
    obj.Profile=objects[i['profile']]
    body=objects[i['body']];roles={p.Role:p for p in body.Origin.OriginFeatures}
    obj.ReferenceAxis=(objects[i['axis']] if 'axis' in i else roles[o['axis']+'_Axis'],[''])
    obj.Mode=s['mode']
    # HasBeenEdited prevents the GUI's initial-pitch proposal from replacing intent.
    obj.HasBeenEdited=True
    for key,(prop,typ) in PROPERTIES.items():setattr(obj,prop,s[key])


def observe(obj,node):
    expected={p:t for p,t in PROPERTIES.values()}
    expected.update(Mode='App::PropertyEnumeration',Base='App::PropertyVector',Axis='App::PropertyVector')
    if any(obj.getTypeIdOfProperty(prop)!=typ for prop,typ in expected.items()):
        fail('VERIFICATION_FAILED','Native Helix property types differ',node['id'])
    result={}
    for key,(prop,typ) in PROPERTIES.items():
        value=getattr(obj,prop)
        result[key]=bool(value) if typ=='App::PropertyBool' else float(value.Value if hasattr(value,'Value') else value)
    result.update(mode=str(obj.Mode),axisOrigin=list(obj.Base),axisDirection=list(obj.Axis))
    return result
