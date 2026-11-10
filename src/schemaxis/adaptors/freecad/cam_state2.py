"""Whole trusted CAM2 reconstruction binding; submitted documents stay unopened.

Fresh native construction uses the actual captured input bytes and typed intent.
Editable built/reopened observations, proxy JSON and geometry summaries are never
authority. Native reopen is permitted only after complete XML/SID/map/payload and
posted-program binding and a checked native-byte handoff.
"""
from contextlib import contextmanager
import copy
import json
from pathlib import Path
import tempfile
from zipfile import ZipFile
from schemaxis.artifacts import file_digest
from schemaxis.dispatch import remaining_timeout
from schemaxis.errors import fail
from .document_xml import Document,read_member
from .cam_evidence2 import same,read,binary


def admit(directory,prepared):
    """Bind working source BREP to the selected original captured archive bytes."""
    if prepared.get('version')=='schemaxis.freecad.cam.plan/2':
        from .cam_plan2 import plan
    elif prepared.get('version')=='schemaxis.freecad.cam.plan/3':
        from .cam_plan3 import plan
    else:fail('VERIFICATION_FAILED','Expected a finite compiled CAM authority family')
    from .solid_source import digest
    directory=Path(directory);authored=read(directory/'authored.json')
    source=authored.get('source')
    if not isinstance(source,dict) or not isinstance(source.get('file'),str):
        fail('VERIFICATION_FAILED','Missing authored machining source')
    capture='source.FCStd' if Path(source['file']).suffix.lower()=='.fcstd' else 'source.step'
    expected=plan(authored,captured=directory/capture)
    if not same(prepared,expected):fail('VERIFICATION_FAILED','CAM2 plan differs from typed intent and captured source')
    if expected['source']['format']=='FCStd':
        with ZipFile(directory/capture) as archive:
            data=read_member(archive,expected['source']['member'],32*1024*1024)
        working=directory/'source.brep'
        if (working.is_symlink() or not working.is_file() or working.stat().st_size>32*1024*1024
                or working.read_bytes()!=data or digest(data)!=expected['source']['brepSha256']):
            fail('VERIFICATION_FAILED','Working machining BREP differs from selected captured source bytes')
        staged='source.brep'
    else:data=binary(directory/capture,64*1024*1024);staged='source.step'
    return expected,staged,data


def _closure(path,document):
    from .source_envelope import read_members
    from .assembly_payloads import file_map
    members=read_members(path,'CAM2','VERIFICATION_FAILED');files=file_map(document.root)
    tables=document.root.findall('StringHasher2')
    inline=document.root.findall('StringHasher')
    if (len(tables)!=1 or len(inline)!=1
            or inline[0].attrib!={'saveall':'0','threshold':'0','count':'0','new':'1'}
            or len(inline[0]) or (inline[0].text or '').strip()):
        raise ValueError('CAM2 requires one complete native external string table')
    table=tables[0].get('file');named=[table,*files.values()]
    if None in named or len(named)!=len(set(named)) or set(members)!={'Document.xml',*named}:
        raise ValueError('CAM2 archive membership differs from complete unique typed payload ownership')
    return members,files


def _tool_owners(reference,prepared):
    """Read ownership only from the fresh trusted compiler, never the submission."""
    owned={};sketches=set()
    for tool in prepared['tools']:
        identity=tool['nativeTool'];body=reference.link(identity,'BitBody')
        names={identity,body,*reference.links(body,'Group')};origin=reference.link(body,'Origin')
        names.update({origin,*reference.links(origin,'OriginFeatures')})
        # The trusted native template's attribute object is linked through its
        # tool body and has a fixed, separately compared proxy/property grammar.
        body_sketches=[n for n in names if reference.types[n]=='Sketcher::SketchObject']
        if len(body_sketches)!=1:raise ValueError('trusted native tool does not own exactly one profile sketch')
        sketch=body_sketches[0];sketches.add(sketch)
        deps=reference.root.findall("./Objects/ObjectDeps[@Name='"+sketch+"']/Dep")
        # PropertyBag is a dependency of the builtin constrained sketch; select
        # only that finite fresh native type, with whole graph binding afterward.
        bags={e.get('Name') for e in deps if reference.types.get(e.get('Name'))=='App::FeaturePython'}
        if len(bags)!=1:raise ValueError('trusted native tool has no unique attribute dependency')
        names.update(bags)
        if any(n in owned for n in names):raise ValueError('trusted CAM2 tool subtrees overlap')
        owned.update({n:tool for n in names})
    return owned,sketches


from .history_element_maps import postfix_inventory


def bind(path,canonical,prepared):
    """Bind one coherent full native state, without unions of independent fields."""
    from .assembly_payloads import same_brep,object_ids
    from .history_element_maps import archive_maps,string_inventory
    from .part_reconstruction import compare_xml
    from .cam_tool_checks import _element,_brep
    path=Path(path);canonical=Path(canonical)
    if path.is_symlink() or not path.is_file() or path.stat().st_size>64*1024*1024:
        raise ValueError('CAM2 native input must be one regular bounded publication')
    checked=file_digest(path)
    actual=Document(path);reference=Document(canonical)
    a,afiles=_closure(path,actual);b,bfiles=_closure(canonical,reference)
    if actual.types!=reference.types:raise ValueError('CAM2 object names or types differ from complete trusted reconstruction')
    owners,sketches=_tool_owners(reference,prepared)
    left=copy.deepcopy(actual.root)
    for name in sketches:
        node=left.find("./ObjectData/Object[@name='"+name+"']/Properties/Property[@name='Geometry']")
        expected=reference.properties[name]['Geometry']
        if node is None or not _element(node,expected,owners[name]['length']):
            raise ValueError('CAM2 tool profile differs from trusted physical template')
        # Existing 64-binary-ULP constrained-tool line-coordinate rule only.
        # Every type/role/child/other attribute was bound by _element first.
        node.clear();node.tag=expected.tag;node.attrib.update(expected.attrib)
        node.text=expected.text;node.extend(copy.deepcopy(list(expected)))
    compare_xml(left,reference.root)
    names=object_ids(actual.root);others=object_ids(reference.root)
    tags={others[n]:names[n] for n in names}
    if string_inventory(a,actual.root)!=string_inventory(b,reference.root,tags):
        raise ValueError('CAM2 complete native string inventory differs from trusted reconstruction')
    maps,shadows=archive_maps(a,actual.root);expected_maps,expected_shadows=archive_maps(b,reference.root,tags=tags)
    if maps!=expected_maps or shadows!=expected_shadows:
        raise ValueError('CAM2 complete maps or subelement shadows differ from trusted reconstruction')
    if postfix_inventory(a,actual.root)!=postfix_inventory(b,reference.root,tags):
        raise ValueError('CAM2 complete local postfix inventory differs from trusted reconstruction')
    if afiles.keys()!=bfiles.keys():raise ValueError('CAM2 payload ownership differs from trusted reconstruction')
    for key,member in afiles.items():
        remaining_timeout()
        if key[2]=='ElementMap2':continue
        aa,bb=a[member],b[bfiles[key]]
        if aa==bb:continue
        if key[2]=='Part':
            matched=_brep(aa,bb,owners[key[0]]['length']) if key[0] in owners else same_brep(bb,aa)
            if matched:continue
        raise ValueError('CAM2 saved payload differs from trusted reconstruction: '+member)
    remaining_timeout()
    if file_digest(path)!=checked:raise ValueError('CAM2 native bytes changed during complete saved-state binding')
    return checked


@contextmanager
def reference(directory,prepared):
    """Native-worker-only trusted construction; never recursively launch a worker."""
    expected,member,data=admit(directory,prepared)
    if expected['version']=='schemaxis.freecad.cam.plan/2':
        from .cam_native2 import construct
    else:
        from .cam_native3 import construct
    with tempfile.TemporaryDirectory(prefix='schemaxis-cam-reference-') as temporary:
        root=Path(temporary);(root/member).write_bytes(data)
        construct(root,expected)
        remaining_timeout()
        yield root
        # Successful consumers cannot publish while their captured source has
        # changed during trusted native reconstruction/readback.
        admit(directory,prepared);remaining_timeout()


def verify(directory,prepared):
    directory=Path(directory)
    program=file_digest(directory/'program.ngc')
    with reference(directory,prepared) as root:
        checked=bind(directory/'machining.FCStd',root/'machining.FCStd',prepared)
        if binary(directory/'program.ngc',4*1024*1024)!=binary(root/'program.ngc',4*1024*1024):
            fail('VERIFICATION_FAILED','Posted CAM2 program differs from current trusted typed construction')
        if file_digest(directory/'program.ngc')!=program:
            fail('VERIFICATION_FAILED','CAM2 program changed during trusted reconstruction')
        remaining_timeout()
        return checked
