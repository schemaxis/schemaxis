"""Trusted reconstruction and geometry-only reads for saved typed Part graphs.

Submitted FCStd documents are never restored. The installed native worker builds
from typed intent and retained admitted sources; every saved object/property and
payload then binds to that reconstruction. Independent STL facets additionally
bind the source BREP, so editable observation records never establish geometry.
"""
import copy,json,math,re,sys,tempfile,uuid,zipimport
from pathlib import Path
from xml.etree import ElementTree as ET
from schemaxis.artifacts import atomic_json,file_digest,runtime_archive
from schemaxis.configuration import executable
from schemaxis.core.faults import SchemaxisError,Fault
from schemaxis.core.runners import Interpreter
from schemaxis.dispatch import remaining_timeout
from schemaxis.errors import fail
from .document_xml import Document,ARCHIVE_ERRORS,read_member
from .mesh_geometry import verify_inventory,verify_placement
from .process import SubprocessRunner


def _canonical(element):
    # Only native Touched is transient. Persistent/read-only/dynamic roles stay
    # bound; a refreshed receipt cannot turn a persistent property transient.
    attrs=dict(element.attrib)
    if 'status' in attrs:
        value=attrs['status']
        if re.fullmatch(r'[0-9]{1,10}',value) is None or int(value)>2**32-1:raise ValueError('invalid property status')
        attrs['status']=str(int(value)&~1)
    elif element.tag=='Property':
        # PropertyContainer::Save omits status only when its value is zero.
        # An unchanged native restore/save can serialize status=1 (Touched).
        attrs['status']='0'
    return (element.tag,tuple(sorted(attrs.items())),(element.text or '').strip(),tuple(_canonical(c) for c in element))


def compare_xml(actual, reference):
    """Compare complete typed records, retaining transient and extension children."""
    if actual.attrib!=reference.attrib or [c.tag for c in actual]!=[c.tag for c in reference]:
        raise ValueError('Part document root structure differs from trusted reconstruction')
    for tag in ('StringHasher','StringHasher2'):
        a,b=actual.find(tag),reference.find(tag)
        if (a is None)!=(b is None) or a is not None and _canonical(a)!=_canonical(b):
            raise ValueError('Part string-table metadata differs from trusted reconstruction')
    a,b=copy.deepcopy(actual.find('Properties')),copy.deepcopy(reference.find('Properties'))
    if a is None or b is None:raise ValueError('missing document properties')
    for container in (a,b):
        for prop in container:
            name=prop.get('name')
            if name in ('CreationDate','LastModifiedDate'):
                if len(prop)!=1 or prop[0].tag!='String' or set(prop[0].attrib)!={'value'} or len(prop[0]):raise ValueError('invalid native date record')
                from datetime import datetime
                datetime.fromisoformat(prop[0].get('value'));prop[0].set('value','<native-date>')
            elif name=='Uid':
                if len(prop)!=1 or prop[0].tag!='Uuid' or set(prop[0].attrib)!={'value'} or len(prop[0]):raise ValueError('invalid native UUID record')
                uuid.UUID(prop[0].get('value'));prop[0].set('value','<native-uuid>')
    if _canonical(a)!=_canonical(b):raise ValueError('Part document properties differ from trusted reconstruction')
    a,b=copy.deepcopy(actual.find('Objects')),copy.deepcopy(reference.find('Objects'))
    if a is None or b is None:raise ValueError('missing object inventory')
    for container in (a,b):
        for obj in container:
            if obj.tag=='Object':obj.attrib.pop('id',None)
    if _canonical(a)!=_canonical(b):raise ValueError('Part object/dependency inventory differs from trusted reconstruction')
    from .source_envelope import document_ids
    actual_ids,reference_ids=document_ids(actual),document_ids(reference)
    if set(actual_ids)!=set(reference_ids):raise ValueError('Part object identity membership differs')
    a,b=copy.deepcopy(actual.find('ObjectData')),copy.deepcopy(reference.find('ObjectData'))
    if a is None or b is None:raise ValueError('missing object data')
    for candidate in (a,b):
        for element in candidate.iter():
            if element.get('shadow'):
                # The full map/persistent string binding separately resolves
                # these complete shadows; normalize only their allocation here.
                element.set('shadow','<fresh-regenerated-shadow>')
    # Regeneration binds the complete native values, including redundant
    # axis/angle fields. Permit only binary64 serialization roundoff in a
    # Placement; all enclosing property roles and children remain exact.
    for left,right in zip(a.iter(),b.iter()):
        if left.tag==right.tag=='PropertyPlacement' and set(left.attrib)==set(right.attrib) and not len(left) and not len(right):
            for key in left.attrib:
                x,y=float(left.get(key)),float(right.get(key))
                if not math.isfinite(x) or not math.isfinite(y) or abs(x-y)>64*max(math.ulp(x),math.ulp(y),math.ulp(1.0)):
                    raise ValueError('Part Placement differs from trusted reconstruction')
            left.attrib.update(right.attrib)
    if _canonical(a)!=_canonical(b):raise ValueError('Part object properties differ from trusted reconstruction')


def source_brep_matches(reference, candidate):
    """Allow only a newly set Face.Checked bit in independently bound source geometry.

    OCCT TopTools_ShapeSet writes Free/Modified/Checked/Orientable/Closed/
    Infinite/Convex in that order. Native restore/check/save sets Checked on
    restored faces. Locate flags ONLY in the trusted regenerated
    V1 stream; the submitted stream cannot nominate positions to ignore. All
    other bytes remain bound, including geometry and unused BREP records.
    This is not a general history/copy equivalence or a geometry tolerance.
    """
    from .assembly_payloads import same_brep
    if candidate==reference or same_brep(reference,candidate):return True
    if not reference.startswith(b'\nCASCADE Topology V1, (c) Matra-Datavision\n'):return False
    old,new=reference.split(b'\n'),candidate.split(b'\n')
    if len(old)!=len(new):return False
    tables=[i for i,line in enumerate(old) if re.fullmatch(rb'TShapes [0-9]+',line)]
    if len(tables)!=1:return False
    # A generated planar face has one geometry record followed by a blank
    # line, seven flags, then its subshape references. Restrict this exception
    # to that exact producer grammar; unknown layouts remain byte-exact.
    for index in range(tables[0]+4,len(old)):
        if index%256==0:remaining_timeout(240)
        if (old[index-3]==b'Fa' and old[index-2] and old[index-1]==b''
                and re.fullmatch(rb'[01]{7}',old[index]) and re.fullmatch(rb'[01]{7}',new[index])
                and old[index][2:3]==b'0' and new[index][2:3]==b'1'):
            new[index]=new[index][:2]+b'0'+new[index][3:]
    # Line positions, rather than byte offsets, let the separately admitted
    # one-way negative-zero spelling compose with Checked. No numeric value or
    # other lexical difference is admitted by this final whole-stream check.
    return same_brep(reference,b'\n'.join(new))


def empty_inline_table(root):
    """The exact native empty table has no persistent StringIDs or payload."""
    entries=root.findall('StringHasher')
    if (root.find('StringHasher2') is not None or len(entries)!=1
            or entries[0].attrib!={'saveall':'0','threshold':'0','count':'0'}
            or len(entries[0]) or entries[0].text not in (None,'')
            or (entries[0].tail or '').strip()):
        raise ValueError('Part inline string inventory is not exactly empty')


def literal_maps(members,document,tags):
    """Bind every literal map/alias/shadow with no available StringIDs."""
    from .assembly_payloads import file_map
    from .source_envelope import element_map
    from .history_element_maps import canonical,Names
    result={};aliases={};names=Names({},tags);shadows={}
    for key,member in file_map(document).items():
        remaining_timeout(240)
        if key[2]!='ElementMap2':continue
        parsed=element_map(members[member],member,'VERIFICATION_FAILED',member);value=canonical(parsed,{},tags)
        for (alias,_),content in zip(parsed['maps'],value):
            if alias<=0 or alias in aliases and aliases[alias]!=content:raise ValueError('conflicting literal map alias')
            aliases[alias]=content
        # A local dictionary entry need not be referenced by a map row. Keep
        # its complete contents as well; local allocation order is immaterial.
        postfixes=sorted(json.dumps(names.text(text),sort_keys=True,separators=(',',':'))
                         for text in parsed['postfixes'])
        result[key]={'maps':value,'postfixes':postfixes}
    for obj in document.findall('./ObjectData/Object'):
        for prop in obj.findall('./Properties/Property'):
            for index,element in enumerate(prop.iter()):
                if element.get('shadow'):shadows[(obj.get('name'),prop.get('name'),index)]=names.text(element.get('shadow'))
    return result,shadows


def bind_literal_payloads(actual,root,expected,reference,normalized=None):
    """Complete payload binding for two exact-empty native inline tables."""
    from .assembly_payloads import file_map,same_brep
    from .source_envelope import document_ids
    for candidate in (root,reference):empty_inline_table(candidate)
    actual_ids,reference_ids=document_ids(root),document_ids(reference)
    if set(actual_ids)!=set(reference_ids):raise ValueError('Part map owner membership differs')
    remap={reference_ids[name]:actual_ids[name] for name in actual_ids}
    if literal_maps(actual,root,{v:v for v in actual_ids.values()})!=literal_maps(expected,reference,remap):
        raise ValueError('Part literal maps, postfix inventory or shadows differ from trusted reconstruction')
    files,others=file_map(root),file_map(reference)
    if set(files)!=set(others):raise ValueError('Part payload reference inventory differs')
    for members,payloads in ((actual,files),(expected,others)):
        if set(members)!={'Document.xml','GuiDocument.xml',*payloads.values()}:
            raise ValueError('Part archive has unbound payload members')
    normalized=normalized or {}
    for key,member in files.items():
        if key[2]=='ElementMap2':continue
        a,b=normalized.get(member,actual[member]),expected[others[key]]
        if a!=b and not (key[2]=='Part' and same_brep(b,a)):
            raise ValueError('Part payload differs from trusted reconstruction: '+member)


def bind_payloads(path, root, generated, source_names=()):
    from .source_envelope import read_members
    from .assembly_payloads import file_map,same_brep
    actual=read_members(path,'model.FCStd','VERIFICATION_FAILED')
    expected=read_members(generated/'model.FCStd','regenerated.FCStd','VERIFICATION_FAILED')
    reference=Document(generated/'model.FCStd').root
    if set(actual)!=set(expected):raise ValueError('Part archive member inventory differs from trusted reconstruction')
    files,others=file_map(root),file_map(reference)
    if set(files)!=set(others):raise ValueError('Part payload reference inventory differs')
    normalized={}
    for key,member in files.items():
        if key[0] not in source_names or key[1:]!=('Shape','Part'):continue
        a,b=actual[member],expected[others[key]]
        if not source_brep_matches(b,a):raise ValueError('Part source BREP differs from trusted reconstruction: '+member)
        if a!=b:normalized[member]=b
    if root.find('StringHasher2') is not None or reference.find('StringHasher2') is not None:
        from .history_copy_verify import bind_regenerated
        if normalized:
            # Keep the shared complete SID/map/payload binder unchanged. Only
            # independently admitted source payloads above can be normalized.
            from zipfile import ZipFile,ZIP_DEFLATED
            with tempfile.TemporaryDirectory(prefix='schemaxis-mesh-payload-') as temporary:
                canonical=Path(temporary).resolve(strict=True)/'model.FCStd'
                with ZipFile(canonical,'w',compression=ZIP_DEFLATED) as archive:
                    for member,data in actual.items():
                        remaining_timeout(240);archive.writestr(member,normalized.get(member,data))
                bind_regenerated(canonical,root,generated)
        else:bind_regenerated(path,root,generated)
    else:
        # Small Part graphs retain an exact empty inline string table while
        # maps can still contain literal names. Canonicalize every such map
        # under the complete object-ID bijection, with no available StringIDs.
        bind_literal_payloads(actual,root,expected,reference,normalized)
    compare_xml(root,reference)


def body_reference_lifecycle(directory, baseline=None):
    """Require every trusted save to retain its first complete indexed history.

    Only fresh worker output reaches this boundary. It supplements whole archive
    binding; neither a submitted receipt nor a scalar output snapshot can replace
    the complete geometry and actual subelement-consumer comparison.
    """
    from .draft_verify import read_object
    from .history_copy_verify import compare_ordered
    from .assembly_sources_native import HISTORY_SHAPES
    remaining_timeout(240)
    value=read_object(Path(directory)/'reference-lifecycle.json',64*1024*1024)
    if (set(value)!={'version','objects','before','after'}
            or value['version']!='schemaxis.freecad.body-reference-lifecycle/1'
            or not isinstance(value['objects'],list) or not value['objects']
            or any(not isinstance(name,str) or not name for name in value['objects'])
            or value['objects']!=sorted(set(value['objects']))):
        raise ValueError('Trusted Body reference lifecycle inventory is incomplete')
    root=Document(Path(directory)/'model.FCStd').root
    objects=sorted(obj.get('name') for obj in root.findall('./Objects/Object'))
    expected={'shapes':set(),'references':set()}
    for obj in root.findall('./ObjectData/Object'):
        for prop in obj.findall('./Properties/*'):
            key=obj.get('name')+'.'+prop.get('name')
            if prop.get('name') in HISTORY_SHAPES and prop.get('type')=='Part::PropertyPartShape':
                expected['shapes'].add(key)
            if prop.get('type') in ('App::PropertyLinkSub','App::PropertyLinkSubList'):
                expected['references'].add(key)
    if value['objects']!=objects or not expected['shapes']:
        raise ValueError('Trusted Body reference lifecycle object inventory differs')
    for stage in ('before','after'):
        record=value[stage]
        if (not isinstance(record,dict) or set(record)!=set(expected)
                or any(not isinstance(record[kind],dict) or set(record[kind])!=members
                       for kind,members in expected.items())):
            raise ValueError('Trusted Body reference lifecycle history inventory differs')
    compare_ordered(value['before'],value['after'])
    if baseline is None:
        baseline={'objects':value['objects'],'history':value['before']}
    if value['objects']!=baseline['objects']:
        raise ValueError('Trusted Body reference lifecycle object membership differs')
    compare_ordered(baseline['history'],value['before'])
    compare_ordered(baseline['history'],value['after'])
    remaining_timeout(240)
    return baseline


def verify(path, prepared, captured, *, exports=None, body_local=False):
    if type(body_local) is not bool:raise ValueError('body_local must be an exact boolean')
    if body_local and exports is not None:
        raise ValueError('Body-local verification and whole Helix export authority are distinct requests')
    if body_local:
        from .source_bridge import selected_body
        from schemaxis.dispatch import execution_deadline
        selected_body(prepared)
        # Cover the initial build as well as every subsequent trusted state.
        # The enclosing assembly budget still covers all sources and copy work.
        with execution_deadline(120):
            remaining_timeout(120)
            result=_verify(path,prepared,captured,body_local=True)
            remaining_timeout(120)
            return result
    return _verify(path,prepared,captured,exports=exports,body_local=False)


def _verify(path, prepared, captured, *, exports=None, body_local=False):
    if 'FreeCAD' in sys.modules or isinstance(__loader__,zipimport.zipimporter):
        fail('VERIFICATION_CONTEXT_REQUIRED','Part source verification runs in the installed host after native workers exit')
    location=executable('freecad')
    if not location:fail('VERIFICATION_RUNTIME_REQUIRED','Part verification needs a configured installed FreeCAD command executable')
    remaining_timeout(240)
    from .assembly_sources import check_archive
    from .source_envelope import brep,MEMBER_BYTES
    from .mesh_import import geometry
    from .draft_verify import read_object
    check_archive(path,str(path),code='VERIFICATION_FAILED')
    try:
        xml=Document(path)
        with tempfile.TemporaryDirectory(prefix='schemaxis-mesh-verify-') as temporary:
            scratch=Path(temporary).resolve(strict=True);generated=scratch/'generated';generated.mkdir()
            requests={'importMesh':[],'draftProfile':[]};retained={};size=0
            from zipfile import ZipFile
            with ZipFile(path) as archive:
                for index,node in enumerate(prepared['nodes']):
                    remaining_timeout(240)
                    if node['id'] in captured:
                        record=dict(captured[node['id']]);original=Path(record['retained'])
                        from .step_source import read_bounded
                        data=read_bounded(original,node['id']);size+=len(data)
                        if size>64*1024*1024:fail('RESOURCE_LIMIT','Part reconstruction source budget exceeds 64 MiB')
                        target=generated/('source-'+str(index)+original.suffix);target.write_bytes(data)
                        if file_digest(target)!=record['sha256']:raise ValueError('captured reconstruction source digest differs')
                        record['retained']=str(target);retained[node['id']]=record
                    if node['filter'] not in requests:continue
                    prop=xml.properties['N'+str(index)]['Shape'];parts=prop.findall('Part')
                    if prop.get('type')!='Part::PropertyPartShape' or len(parts)!=1:raise ValueError('Part source shape property differs')
                    member=parts[0].get('file');data=read_member(archive,member,MEMBER_BYTES)
                    size+=len(data)
                    if not data or size>64*1024*1024:raise ValueError('Part source BREP is empty or exceeds its aggregate measurement budget')
                    brep(data,node['id'],'VERIFICATION_FAILED',member)
                    target=scratch/('mesh-'+str(index)+'.brp');target.write_bytes(data)
                    requests[node['filter']].append({'id':node['id'],'file':target.name,'sha256':file_digest(target)})
            atomic_json(generated/'plan.json',prepared);atomic_json(generated/'sources.json',retained)
            atomic_json(scratch/'mesh-breps.json',requests['importMesh'])
            atomic_json(scratch/'draft-profile-breps.json',requests['draftProfile'])
            (scratch/'trusted-runtime.zip').write_bytes(runtime_archive())
            code=('import sys\nsys.path.insert(0,'+repr(str(scratch/'trusted-runtime.zip'))+')\n'
                  'from schemaxis.adaptors.freecad.native import build\n'
                  'from schemaxis.adaptors.freecad.mesh_native import inspect_saved_breps as inspect_mesh\n'
                  'from schemaxis.adaptors.freecad.drafting_native import inspect_saved_breps as inspect_draft\n'
                  'from schemaxis.native_boundary import execute_guarded\n'
                  'execute_guarded(build,'+repr(str(generated))+')\n'
                  'execute_guarded(inspect_mesh,'+repr(str(scratch))+')\n'
                  'execute_guarded(inspect_draft,'+repr(str(scratch))+')\n')
            try:SubprocessRunner(Interpreter('freecad',str(Path(location).expanduser().absolute())),scratch,timeout=240)(code)
            except SchemaxisError as error:
                if error.fault.code in ('RUNNER_CANCELLED','RUNNER_TIMED_OUT','RESOURCE_LIMIT'):raise
                for directory in (scratch,generated):
                    if (directory/'native-fault.json').exists():
                        fault=read_object(directory/'native-fault.json',128*1024)
                        if fault.get('code') in ('RUNNER_CANCELLED','RUNNER_TIMED_OUT','RESOURCE_LIMIT'):raise SchemaxisError(Fault(**fault))
                fail('VERIFICATION_FAILED','Fresh Part reconstruction failed',reason=str(error))
            for directory in (scratch,generated):
                if (directory/'native-fault.json').exists():
                    fault=read_object(directory/'native-fault.json',128*1024)
                    if fault.get('code') in ('RUNNER_CANCELLED','RUNNER_TIMED_OUT','RESOURCE_LIMIT'):raise SchemaxisError(Fault(**fault))
                    fail('VERIFICATION_FAILED','Fresh Part reconstruction or BREP measurement refused its input',fault=fault)
            observations={}
            for kind,filename in (('importMesh','mesh-inventories.json'),('draftProfile','draft-profile-inventories.json')):
                value=read_object(scratch/filename,32*1024*1024)
                if set(value)!={r['id'] for r in requests[kind]}:raise ValueError('fresh source geometry inventory membership differs')
                observations.update(value)
            for node in prepared['nodes']:
                if node['filter']=='draftProfile':
                    from .drafting import verify_inventory as verify_profile,placement
                    measured=observations[node['id']]
                    if set(measured)!={'placement','geometry'}:raise ValueError('fresh Draft profile observation differs')
                    verify_placement(measured['placement'],placement(node),node['id'])
                    verify_profile(measured['geometry'],node)
                    continue
                if node['filter']!='importMesh':continue
                from .step_source import read_bounded
                facts,points,faces=geometry(read_bounded(captured[node['id']]['retained'],node['id']),node['options'],node['id'])
                measured=observations[node['id']];r=node['frame']['worldFromFile'];t=node['frame']['translation']
                if set(measured)!={'placement','geometry'}:raise ValueError('fresh mesh observation differs')
                verify_placement(measured['placement'],[*r[0],t[0],*r[1],t[1],*r[2],t[2]],node['id'])
                verify_inventory(measured['geometry'],points,faces,node['id'])
            source_names={'N'+str(index) for index,node in enumerate(prepared['nodes']) if node['filter'] in requests}
            remaining_timeout(240)
            bound_reference=generated
            try:bind_payloads(path,xml.root,generated,source_names)
            except ValueError:
                if body_local:
                    from .body_reference import bind_lifecycle
                    bind_lifecycle(path,xml.root,generated,scratch/'trusted-runtime.zip',
                                   Interpreter('freecad',str(Path(location).expanduser().absolute())),
                                   prepared,retained,source_names)
                else:
                    from .helix import active as helical
                    if not requests['draftProfile'] and not prepared.get('partDesign',{}).get('seeds') and not helical(prepared):raise
                    # Draft/Helix persistent names and seeded import curve directions
                    # can change on the first native reopen/recompute/save.
                    # Reproduce that finite state using ONLY our fresh trusted
                    # reference, built from admitted original inputs. Compare
                    # the entire second archive; never mix fields from references,
                    # discard map records, or restore the submitted document.
                    code=('import sys\nsys.path.insert(0,'+repr(str(scratch/'trusted-runtime.zip'))+')\n'
                          'from schemaxis.adaptors.freecad.part_reference_native import resave\n'
                          'from schemaxis.native_boundary import execute_guarded\n'
                          'execute_guarded(resave,'+repr(str(generated))+')\n')
                    try:SubprocessRunner(Interpreter('freecad',str(Path(location).expanduser().absolute())),scratch,timeout=240)(code)
                    except SchemaxisError as fault:
                        if fault.fault.code in ('RUNNER_CANCELLED','RUNNER_TIMED_OUT','RESOURCE_LIMIT'):raise
                        if (generated/'native-fault.json').exists():
                            value=read_object(generated/'native-fault.json',128*1024)
                            if value.get('code') in ('RUNNER_CANCELLED','RUNNER_TIMED_OUT','RESOURCE_LIMIT'):raise SchemaxisError(Fault(**value))
                        raise
                    if (generated/'native-fault.json').exists():
                        value=read_object(generated/'native-fault.json',128*1024)
                        if value.get('code') in ('RUNNER_CANCELLED','RUNNER_TIMED_OUT','RESOURCE_LIMIT'):raise SchemaxisError(Fault(**value))
                        raise ValueError('trusted Part reference save lifecycle failed')
                    if not (generated/'resaved/model.FCStd').is_file():
                        raise ValueError('trusted Part reference save lifecycle failed')
                    remaining_timeout(240);bind_payloads(path,xml.root,generated/'resaved',source_names)
                    bound_reference=generated/'resaved'
            remaining_timeout(240)
            if exports is not None:
                from .helix import active as helical
                from .export_payloads import bind
                if not helical(prepared):raise ValueError('export reconstruction requires a typed Helix plan')
                bound=bind(exports['step'],exports['stl'],expected_step=generated/'model.step',
                           expected_stl=generated/'model.stl',location='$.exports')
                trusted=read_object(generated/'built.json',64*1024*1024)
                if bound_reference!=generated:
                    # The whole native archive bound above is the one reopened
                    # for its own per-state observations. Only trusted generated
                    # exports and declarations are copied beside it.
                    import shutil
                    for filename in ('plan.json','sources.json','model.step','model.stl'):
                        shutil.copyfile(generated/filename,bound_reference/filename)
                    if prepared.get('measurements'):
                        shutil.copyfile(generated/'measurements.json',bound_reference/'measurements.json')
                # Native build and native reopen have distinct mesh-cache and
                # conditioning states. Reproduce the WHOLE trusted reopen;
                # never waive fields or combine numerical facts across states.
                code=('import sys\nsys.path.insert(0,'+repr(str(scratch/'trusted-runtime.zip'))+')\n'
                      'from schemaxis.adaptors.freecad.native import reopen\n'
                      'from schemaxis.native_boundary import execute_guarded\n'
                      'execute_guarded(reopen,'+repr(str(bound_reference))+')\n')
                try:SubprocessRunner(Interpreter('freecad',str(Path(location).expanduser().absolute())),scratch,timeout=240)(code)
                except SchemaxisError as error:
                    if error.fault.code in ('RUNNER_CANCELLED','RUNNER_TIMED_OUT','RESOURCE_LIMIT'):raise
                    if (bound_reference/'native-fault.json').exists():
                        fault=read_object(bound_reference/'native-fault.json',128*1024)
                        if fault.get('code') in ('RUNNER_CANCELLED','RUNNER_TIMED_OUT','RESOURCE_LIMIT'):raise SchemaxisError(Fault(**fault))
                    fail('VERIFICATION_FAILED','Fresh trusted Helix reopening failed',reason=str(error))
                if (bound_reference/'native-fault.json').exists():
                    raise ValueError('fresh trusted Helix reopening refused')
                reopened=read_object(bound_reference/'verification.json',64*1024*1024)
                return {'exportEvidence':trusted['exportEvidence'],
                        'reopenEvidence':reopened['exportEvidence'],
                        'shape':trusted['shape'],
                        'built':trusted,'reopened':reopened,
                        'referenceLifecycle':'built' if bound_reference==generated else 'fresh-resaved',
                        'bodyLocalExportEvidence':trusted.get('bodyLocalExportEvidence'),
                        'exportDigests':{key:value.sha256 for key,value in bound.items()}}
            if body_local or prepared.get('partDesign',{}).get('seeds'):
                trusted=read_object(generated/'built.json',64*1024*1024)
                local=trusted.get('bodyLocalExportEvidence')
                if body_local:
                    from .source_bridge import selected_body
                    from .part_design import names
                    expected=names(prepared)[selected_body(prepared)['body']]
                    if not isinstance(local,dict) or local.get('frame')!='bodyLocal' or local.get('body')!=expected:
                        raise ValueError('Trusted reconstruction lacks selected Body-local geometry')
                return local
    except (OSError,ValueError,KeyError,IndexError,TypeError,AttributeError,OverflowError,*ARCHIVE_ERRORS) as error:
        fail('VERIFICATION_FAILED','Saved Part graph differs from trusted geometry and reconstruction',str(path),detail=str(error)[:300])
