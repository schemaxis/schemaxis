"""Finite included original geometry for seeded histories; host policy only.

These bytes supplement, never replace, full saved-history reconstruction. A
recorded hash or editable cached BREP is not admitted source geometry by itself.
"""
import hashlib
from .step_source import checkpoint


def descriptors(prepared):
    from .body_seed import active
    if not active(prepared):return {}
    return {'N'+str(index):{'id':node['id'],'route':node['filter'],
            'member':'source-asset-'+str(index)+('.stl' if node['filter']=='importMesh' else '.step'),
            'source':node['source'],'options':node['options'],'frame':node['frame']}
        for index,node in enumerate(prepared['nodes']) if node['filter'] in ('importMesh','importSTEP')}


def admit(data,descriptor,location):
    from schemaxis.errors import fail
    source=descriptor['source']
    if len(data)!=source['bytes'] or hashlib.sha256(data).hexdigest()!=source['sha256']:
        fail('VERIFICATION_FAILED','Included source asset bytes differ from typed import',location)
    if descriptor['route']=='importMesh':
        from .mesh_import import geometry
        facts,_,_=geometry(data,descriptor['options'],location)
    elif descriptor['route']=='importSTEP':
        from .step_source import admit as admit_step
        facts=admit_step(data,location)
        if facts['unit']!=descriptor['options']['units']:
            fail('VERIFICATION_FAILED','Included STEP assigns a different unit',location)
    else:fail('VERIFICATION_FAILED','Unknown included geometry source route',location)
    if any(source.get(key)!=value for key,value in facts.items()):
        fail('VERIFICATION_FAILED','Included source admission differs from its compiled facts',location)
    checkpoint()


def verify_property(prop,member,location):
    """Require the one compiled dynamic role, without filename heuristics."""
    from schemaxis.errors import fail
    expected={'name':'SourceAsset','type':'App::PropertyFileIncluded','group':'Schemaxis','doc':'','attr':'0','ro':'0','hide':'0','status':'2097152'}
    attributes=dict(prop.attrib)
    # Touched is the only transient role; all remaining bits stay exact.
    if attributes.get('status') in ('2097152','2097153'):attributes['status']='2097152'
    if attributes!=expected or len(prop)!=1 or prop[0].tag!='FileIncluded' or prop[0].attrib!={'file':member} or len(prop[0]):
        fail('VERIFICATION_FAILED','Included source property role or filename differs',location)


def copied_assets(part,index):
    """Allocate distinct finite included members for independently admitted sources."""
    from .source_bridge import capability
    facts=part.get('source',{});key=capability(facts)
    history=facts.get(key) if key else None
    if history is None:return {}
    return {name:{**item,'copiedMember':'assembly-source-'+str(index)+'-'+item['member']}
            for name,item in descriptors(history['definition']).items()}


def copied_property(original,copied,item,location):
    """Normalize only the exact compiled original-to-copy filename relation."""
    from xml.etree import ElementTree as ET
    verify_property(original,item['member'],location)
    verify_property(copied,item['copiedMember'],location)
    result=ET.fromstring(ET.tostring(copied));result[0].set('file',item['member'])
    return result


def verify_members(members,root,assets,location):
    """Bind exact dynamic role, native filename and independently admitted bytes."""
    from schemaxis.errors import fail
    for name,item in assets.items():
        checkpoint();properties=root.findall('./ObjectData/Object[@name="'+name+'"]/Properties/Property[@name="SourceAsset"]')
        if len(properties)!=1:fail('VERIFICATION_FAILED','Included source property is absent or duplicated',location)
        verify_property(properties[0],item['member'],location)
        data=members.get(item['member'])
        if data is None:fail('VERIFICATION_FAILED','Included source payload is missing',location)
        admit(data,item,location+'.'+name)


def verify(path,prepared,captured=None):
    assets=descriptors(prepared)
    if not assets:return
    from .source_envelope import read_members,prolog
    from xml.etree import ElementTree as ET
    members=read_members(path,str(path),'VERIFICATION_FAILED');prolog(members['Document.xml'],str(path),'VERIFICATION_FAILED')
    root=ET.fromstring(members['Document.xml']);verify_members(members,root,assets,str(path))
    if captured is not None:
        from .step_source import read_bounded
        from schemaxis.errors import fail
        for item in assets.values():
            if members[item['member']]!=read_bounded(captured[item['id']]['retained'],item['id']):
                fail('VERIFICATION_FAILED','Included original asset differs from retained original bytes',item['id'])
