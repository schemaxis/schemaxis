"""Current-code regeneration oracle for embedded typed design histories.

FreeCAD copy/recompute regenerates persistent names. We do not equate those
names to the producer's encoding. Instead, rebuild from the retained, admitted
sources in a fresh trusted process and bind every resulting map, XML shadow and
geometry payload to that regeneration. Source-to-copy history and reference
correspondence is checked separately; geometry alone cannot accept a map.
"""
from contextlib import contextmanager
import json
import os
from pathlib import Path
import shutil
import tempfile
from xml.etree import ElementTree as ET

from schemaxis.artifacts import atomic_json,runtime_archive
from schemaxis.errors import fail


@contextmanager
def regenerate(directory,prepared,retained,*,executable=None,timeout=120):
    from schemaxis.configuration import executable as configured
    from schemaxis.core.runners import Interpreter
    from .process import SubprocessRunner
    location=executable or configured('freecad') or os.environ.get('FREECAD_CMD')
    if not location:
        fail('VERIFICATION_RUNTIME_REQUIRED','Design-history assembly verification requires a configured FreeCAD launcher')
    with tempfile.TemporaryDirectory(prefix='schemaxis-freecad-history-') as temporary:
        scratch=Path(temporary);(scratch/'sources').mkdir()
        for part in prepared['parts']:
            shutil.copyfile(retained[part['id']],scratch/prepared['native']['retained'][part['id']])
        atomic_json(scratch/'authored.json',json.loads((directory/'authored.json').read_text()))
        atomic_json(scratch/'plan.json',prepared)
        (scratch/'trusted-runtime.zip').write_bytes(runtime_archive())
        script=('import sys\nsys.path.insert(0,'+repr(str(scratch/'trusted-runtime.zip'))+')\n'
                'from schemaxis.adaptors.freecad.assembly_sources_native import capture,build\n'
                'from schemaxis.native_boundary import execute_guarded\n'
                'execute_guarded(capture,'+repr(str(scratch))+')\n'
                'execute_guarded(build,'+repr(str(scratch))+')\n')
        runner=SubprocessRunner(Interpreter('freecad',str(Path(location).expanduser().absolute())),scratch,
                                timeout=timeout,environment={'PYTHONDONTWRITEBYTECODE':'1'})
        runner(script)
        if (scratch/'native-fault.json').exists() or not (scratch/'model.FCStd').is_file():
            fail('VERIFICATION_FAILED','Fresh source-history regeneration failed')
        captured=json.loads((scratch/'capture.json').read_text())
        built=json.loads((scratch/'built.json').read_text())
        from .source_bridge import requires_copy_regeneration
        for part in prepared['parts']:
            if requires_copy_regeneration(part['source']):
                compare_ordered(captured['parts'][part['id']]['orderedHistory'],built['copiedHistory'][part['id']])
        yield scratch


def compare_ordered(source,copied):
    """Indexed geometry and actual face/edge consumers must survive regeneration."""
    from .assembly_sources import same_history_shape
    def same_element(a,b):
        if not isinstance(a,dict) or not isinstance(b,dict):return False
        orientation=a.get('orientation')
        if orientation not in ('Forward','Reversed','Internal','External') or b.get('orientation')!=orientation:return False
        return same_history_shape({k:v for k,v in a.items() if k!='orientation'},
                                  {k:v for k,v in b.items() if k!='orientation'})
    if set(source)!= {'shapes','references'} or set(copied)!=set(source):
        fail('VERIFICATION_FAILED','Ordered history correspondence evidence is incomplete')
    for kind in source:
        if set(source[kind])!=set(copied[kind]):
            fail('VERIFICATION_FAILED','Copied history correspondence membership differs',family=kind)
    for name,a in source['shapes'].items():
        b=copied['shapes'][name]
        if a is None or b is None:
            if a is not None or b is not None:fail('VERIFICATION_FAILED','Copied null history shape differs',shape=name)
            continue
        if set(a)!= {'faces','edges','vertices'} or set(b)!=set(a):
            fail('VERIFICATION_FAILED','Copied indexed topology inventory differs',shape=name)
        for kind,values in a.items():
            if len(values)!=len(b[kind]) or any(not same_element(x,y) for x,y in zip(values,b[kind])):
                fail('VERIFICATION_FAILED','Copied indexed history geometry differs',shape=name,elements=kind)
    for name,a in source['references'].items():
        b=copied['references'][name]
        if len(a)!=len(b) or any(set(x)!= {'target','sub','shape'} or set(y)!=set(x)
                or x['target']!=y['target'] or x['sub']!=y['sub'] or not same_element(x['shape'],y['shape'])
                for x,y in zip(a,b)):
            fail('VERIFICATION_FAILED','Copied downstream subelement selection differs',property=name)


def bind_regenerated(path,root,regenerated):
    from .assembly_payloads import file_map,object_ids,same_brep
    from .source_envelope import read_members
    from .history_element_maps import archive_maps, string_inventory, postfix_inventory
    actual=read_members(path,'model.FCStd','VERIFICATION_FAILED')
    expected=read_members(Path(regenerated)/'model.FCStd','regenerated.FCStd','VERIFICATION_FAILED')
    reference=ET.fromstring(expected['Document.xml'])
    names=object_ids(root);reference_names=object_ids(reference)
    if set(names)!=set(reference_names):raise ValueError('fresh regeneration object membership differs')
    # Document object IDs and StringIDs are allocation details. Their contents
    # and owner identity remain bound under one complete object-name bijection.
    tags={reference_names[name]:names[name] for name in names}
    if string_inventory(actual, root) != string_inventory(expected, reference, tags):
        raise ValueError('saved complete string inventory differs from fresh source-history regeneration')
    maps,shadows=archive_maps(actual,root)
    reference_maps,reference_shadows=archive_maps(expected,reference,tags=tags)
    if maps!=reference_maps:raise ValueError('saved topology maps differ from fresh source-history regeneration')
    if shadows!=reference_shadows:raise ValueError('saved subelement shadows differ from fresh source-history regeneration')
    if postfix_inventory(actual,root)!=postfix_inventory(expected,reference,tags):
        raise ValueError('saved complete local postfix inventory differs from fresh source-history regeneration')
    files=file_map(root);reference_files=file_map(reference)
    if set(files)!=set(reference_files):raise ValueError('fresh regeneration payload membership differs')
    for key,member in files.items():
        if key[2]=='ElementMap2':continue
        a,b=actual[member],expected[reference_files[key]]
        if a!=b and not (key[2]=='Part' and same_brep(b,a)):
            raise ValueError('saved payload differs from fresh source-history regeneration: '+member)
