"""Closed editable CAM state and trusted regenerated builtin tool comparison."""
import math
import re
import copy
from xml.etree import ElementTree as ET

from schemaxis.errors import fail
from .cam_names import operation_names
from .document_xml import Document
from .cam_vocabulary import PROPERTY_TYPES,EXTENSIONS,TRANSIENT

TOOLS={'Endmill','PropertyBag','Body','Sketch','Revolution','Origin','Origin001','X_Axis','Y_Axis','Z_Axis','XY_Plane','XZ_Plane','YZ_Plane'}
EXPRESSIONS=[['Constraints[10]','<<Attributes>>.Length'],['Constraints[16]','<<Attributes>>.ShankDiameter'],['Constraints[18]','<<Attributes>>.CuttingEdgeHeight'],['Constraints[9]','<<Attributes>>.Diameter']]
FLOAT=re.compile(r'[-+]?(?:[0-9]+\.[0-9]*|\.[0-9]+)(?:[eE][-+]?[0-9]+)?')


def closed(saved,p,path=None):
    """Preflight every object before a consumer can open the editable document."""
    roles={operation_names(p)[s['id']]:s['operation'] for s in p['operations']}
    for obj in saved.root.findall('./ObjectData/Object'):
        name=obj.get('name');role=roles.get(name,name);properties=saved.properties[name]
        if role not in PROPERTY_TYPES or {k:v.get('type') for k,v in properties.items()}!=PROPERTY_TYPES[role]:
            fail('VERIFICATION_FAILED','Saved CAM property membership or types differ from the closed native vocabulary',name)
        props=obj.find('Properties');transient=props.findall('_Property');expected_transient=TRANSIENT[role]
        if (props.attrib!={'Count':str(len(properties)),'TransientCount':str(len(expected_transient))}
                or len(props)!=len(properties)+len(expected_transient) or len(transient)!=len(expected_transient)):
            fail('VERIFICATION_FAILED','Saved CAM transient property membership differs',name)
        for value,reference in zip(transient,expected_transient):
            attrs=dict(value.attrib)
            if name=='Revolution' and attrs.get('name')=='_Body' and attrs.get('status')==str(int(reference['status'])|1):attrs['status']=reference['status']
            if attrs!=reference or len(value):fail('VERIFICATION_FAILED','Saved CAM transient property state differs',name)
        extensions=EXTENSIONS[role];expected={'name':name,**({'Extensions':'True'} if extensions else {})}
        if obj.attrib!=expected or [c.tag for c in obj] != (['Extensions','Properties'] if extensions else ['Properties']):
            fail('VERIFICATION_FAILED','Saved CAM object or extension structure differs',name)
        node=obj.find('Extensions')
        if extensions and (node.attrib!={'Count':str(len(extensions))} or [(c.tag,c.attrib,len(c)) for c in node]!=[('Extension',e,0) for e in extensions]):
            fail('VERIFICATION_FAILED','Saved CAM native extensions differ',name)
        if saved.engine(name)!=(EXPRESSIONS if name=='Sketch' else []):
            fail('VERIFICATION_FAILED','Saved CAM expression dependencies differ',name)
    for obj in saved.root.findall('./Objects/Object'):
        if set(obj.attrib)-{'type','name','id','Touched'} or obj.get('Touched','0') not in ('0','1'):
            fail('VERIFICATION_FAILED','Saved CAM object declares foreign native restore state',obj.get('name'))
    if path is not None:
        from .source_envelope import read_members
        from .assembly_payloads import file_map
        members=read_members(path,'CAM','VERIFICATION_FAILED');files=file_map(saved.root)
        table=saved.root.find('StringHasher2').get('file')
        if len(set(files.values()))!=len(files) or set(members)!={'Document.xml',table,*files.values()}:
            fail('VERIFICATION_FAILED','Published CAM contains foreign GUI state or archive payloads')


def _numeric(a,b,scale):
    # The same installed constrained tool template can differ by a few double
    # rounding steps after extra document recomputations. This allowance is
    # 64 binary ULPs at the larger tool/coordinate magnitude, far below OCCT's
    # 1e-7 mm model tolerance. Integer topology and all lexical structure stay exact.
    return math.isfinite(a) and math.isfinite(b) and abs(a-b)<=64*math.ulp(max(1,scale,abs(a),abs(b)))


def _element(a,b,scale,geometry=False):
    if a.tag!=b.tag or a.attrib.keys()!=b.attrib.keys() or (a.text or '').strip()!=(b.text or '').strip() or len(a)!=len(b):return False
    geometry=geometry or a.tag=='GeometryList'
    for key in a.attrib:
        if geometry and a.tag=='LineSegment' and key in {'StartX','StartY','StartZ','EndX','EndY','EndZ'}:
            if not _numeric(float(a.get(key)),float(b.get(key)),scale):return False
        elif a.get(key)!=b.get(key):return False
    return all(_element(x,y,scale,geometry) for x,y in zip(a,b))


def _brep(a,b,scale):
    from .source_envelope import brep
    from .drawing_checks import checked_brep
    brep(a,'tool','VERIFICATION_FAILED','tool.brep');brep(b,'tool','VERIFICATION_FAILED','tool.brep')
    aa=checked_brep(a).decode('ascii');bb=checked_brep(b).decode('ascii')
    if FLOAT.sub('@',aa)!=FLOAT.sub('@',bb):return False
    av=FLOAT.findall(aa);bv=FLOAT.findall(bb)
    return len(av)==len(bv) and all(_numeric(float(x),float(y),scale) for x,y in zip(av,bv))


def compare(path,canonical,tool):
    """Compare tool subtree only; never claim a full-document regeneration."""
    from .source_envelope import read_members,document_ids
    from .assembly_payloads import file_map
    from .history_element_maps import archive_maps
    actual=Document(path);expected=Document(canonical)
    a=read_members(path,'CAM tool','VERIFICATION_FAILED');b=read_members(canonical,'CAM tool','VERIFICATION_FAILED')
    aa=file_map(actual.root);bb=file_map(expected.root)
    # This geometry-only reader never opens submitted proxies or GUI state.
    # Product publication separately requires the closed initial batch archive;
    # edited GUI documents may carry additional visual payloads without those
    # payloads becoming executable authority or part of this tool-geometry claim.
    if len(set(aa.values()))!=len(aa) or len(set(bb.values()))!=len(bb):
        fail('VERIFICATION_FAILED','Saved editable tool shares an ambiguous payload reference')
    names={name:i+1 for i,name in enumerate(sorted(set(actual.types)|set(expected.types)))}
    tags_a={identity:names[name] for name,identity in document_ids(actual.root).items()}
    tags_b={identity:names[name] for name,identity in document_ids(expected.root).items()}
    amap,ashadow=archive_maps(a,actual.root,tags=tags_a);bmap,bshadow=archive_maps(b,expected.root,tags=tags_b)
    aobjects={e.get('name'):e for e in actual.root.findall('./ObjectData/Object')}
    bobjects={e.get('name'):e for e in expected.root.findall('./ObjectData/Object')}
    adeps={e.get('Name'):e for e in actual.root.findall('./Objects/ObjectDeps')}
    bdeps={e.get('Name'):e for e in expected.root.findall('./Objects/ObjectDeps')}
    scale=tool['length']
    for name in sorted(TOOLS):
        left=copy.deepcopy(aobjects[name]);right=bobjects[name]
        # GUI restoration changes presentation visibility and promotes the
        # builtin tool to its local canonical 'Endmill' asset identity. Admit
        # only these observed closed states in this geometry-only comparison;
        # product CAM publication still requires the initial closed state.
        visible=left.find("./Properties/Property[@name='Visibility']/Bool")
        other=right.find("./Properties/Property[@name='Visibility']/Bool")
        if visible is not None and other is not None:
            if visible.attrib not in ({'value':'true'},{'value':'false'}):fail('VERIFICATION_FAILED','Saved editable tool visibility is malformed',name)
            visible.set('value',other.get('value'))
        if name=='Revolution':
            transient=left.find("./Properties/_Property[@name='_Body']");reference=right.find("./Properties/_Property[@name='_Body']")
            if transient is not None and reference is not None and transient.get('status') in (reference.get('status'),str(int(reference.get('status'))|1)):
                # Native GUI recomputation toggles only the touched bit on this
                # transient, valueless Body cache; no persisted link is dropped.
                transient.set('status',reference.get('status'))
        if name=='Endmill':
            from .cam_proxies import check,tool_state
            actual_proxy=left.find("./Properties/Property[@name='Proxy']");expected_proxy=right.find("./Properties/Property[@name='Proxy']")
            if actual_proxy.attrib!=expected_proxy.attrib or len(actual_proxy)!=1:fail('VERIFICATION_FAILED','Saved editable tool proxy representation differs')
            state=tool_state(tool)
            try:check(actual_proxy[0],'Path.Tool.toolbit.models.endmill','ToolBitEndmill',state)
            except ValueError:
                state['_obj_data']['shape']='Endmill.fcstd';state['_shape_data']['id']='Endmill'
                del state['_shape_data']['parameters']['Material'];del state['_shape_data']['parameters']['SpindleDirection']
                check(actual_proxy[0],'Path.Tool.toolbit.models.endmill','ToolBitEndmill',state)
            actual_proxy[0].attrib.clear();actual_proxy[0].attrib.update(expected_proxy[0].attrib)
        if actual.types.get(name)!=expected.types.get(name) or not _element(left,right,scale):
            fail('VERIFICATION_FAILED','Saved editable tool property or dependency graph differs from the trusted builtin template',name)
        if (name in adeps)!=(name in bdeps) or name in adeps and not _element(adeps[name],bdeps[name],scale):
            fail('VERIFICATION_FAILED','Saved editable tool object dependencies differ',name)
    owned_a={key:member for key,member in aa.items() if key[0] in TOOLS};owned_b={key:member for key,member in bb.items() if key[0] in TOOLS}
    if owned_a!=owned_b:fail('VERIFICATION_FAILED','Saved editable tool payload ownership differs')
    for key,member in owned_a.items():
        if key[2]=='Part':
            if not _brep(a[member],b[member],scale):fail('VERIFICATION_FAILED','Saved editable tool BREP differs from the trusted builtin geometry',member)
        elif key[2]=='ElementMap2':
            if amap[key]!=bmap[key]:fail('VERIFICATION_FAILED','Saved editable tool topological map differs',member)
        elif a[member]!=b[member]:fail('VERIFICATION_FAILED','Saved editable tool payload differs',member)
    if {key:value for key,value in ashadow.items() if key[0] in TOOLS}!={key:value for key,value in bshadow.items() if key[0] in TOOLS}:
        fail('VERIFICATION_FAILED','Saved editable tool shadow references differ')
