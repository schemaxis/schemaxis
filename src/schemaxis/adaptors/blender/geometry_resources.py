"""Finite geometry resources and source selectors for procedural compositions."""
from schemaxis.errors import fail,keys
from schemaxis.core.declarations import validate_arguments
from schemaxis.schema import object_schema
from .node_catalogue import text

NAME={'type':'string','minLength':1,'maxLength':128}

def schema_property():
    variants=[]
    for kind,fields in [('object',{'object':NAME,'sourceObject':{'type':'string','maxLength':128}}),('collection',{'collection':NAME}),('asset',{'asset':NAME})]:
        variants.append(object_schema({'id':NAME,'kind':{'const':kind},**fields},['id','kind',next(iter(fields))]))
    return {'type':'array','maxItems':256,'items':{'oneOf':variants}}


def validate(value,kinds,collections,assets,where):
    if not isinstance(value,list) or len(value)>256:fail('INVALID_GEOMETRY_RESOURCE','geometryResources must contain at most256 records',where)
    result=[];seen=set(kinds)|set(collections)
    for i,r in enumerate(value):
        loc=f'{where}[{i}]'
        if not isinstance(r,dict) or r.get('kind') not in ('object','collection','asset'):fail('INVALID_GEOMETRY_RESOURCE','choose object, collection or whole asset geometry',loc)
        kind=r['kind'];field={'object':'object','collection':'collection','asset':'asset'}[kind]
        keys(r,('id','kind',field,*(['sourceObject'] if kind=='object' else [])),loc)
        specs={'id':{**NAME,'required':True},field:{**NAME,'required':True}}
        if kind=='object':specs['sourceObject']={**text(),'maxLength':128}
        item=validate_arguments(specs,{k:v for k,v in r.items() if k!='kind'},location=loc)
        if item['id'] in seen:fail('DUPLICATE_ID','geometry resource aliases must differ from public Objects, collections and other aliases',loc)
        seen.add(item['id']);ref=item[field]
        if kind=='object':
            if ref not in kinds:fail('UNKNOWN_REFERENCE','resource Object is absent',loc)
            if item['sourceObject'] and kinds[ref]!='asset':fail('INVALID_GEOMETRY_RESOURCE','sourceObject selects a captured asset member',loc)
            if item['sourceObject'] and assets[ref]['format'] not in ('blend','glb','gltf'):fail('INVALID_GEOMETRY_RESOURCE','sourceObject needs a native or unique glTF source identity',loc)
        elif ref not in (collections if kind=='collection' else assets):fail('UNKNOWN_REFERENCE','resource collection or asset is absent',loc)
        result.append({'kind':kind,**item})
    return result


def public_dependencies(spec):
    """Original public roots needed by the DAG, including aliased graph sources."""
    return {r['object'] for r in spec.get('geometryResources',[]) if r['kind']=='object'}

def verify(spec,actual):
    if not isinstance(actual,list) or len(actual)!=len(spec):fail('VERIFICATION_FAILED','geometry resource membership differs')
    for s,a in zip(spec,actual):
        if any(a.get(k)!=v for k,v in s.items()) or not isinstance(a.get('native'),str) or not a['native']:
            fail('VERIFICATION_FAILED','geometry resource declaration or native identity differs',s['id'])
