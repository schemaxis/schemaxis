"""Bind Draft selections to fresh geometry-only reads of saved base BREPs.

Editable build/reopen inventories are witnesses, never geometric authority.
No submitted FCStd document or saved Python property is restored by this check.
"""
import json,tempfile,sys,zipimport,math
from pathlib import Path
from zipfile import ZipFile
from schemaxis.artifacts import atomic_json,file_digest,runtime_archive
from schemaxis.configuration import executable
from schemaxis.core.runners import Interpreter
from schemaxis.core.faults import SchemaxisError,Fault
from schemaxis.dispatch import remaining_timeout
from schemaxis.errors import fail
from .document_xml import Document,read_member
from .part_design import names
from .process import SubprocessRunner


def read_object(path,limit=64*1024*1024):
    """Bound generated receipts and reject duplicate keys/nonfinite numbers."""
    def pairs(items):
        result={}
        for key,value in items:
            if key in result:raise ValueError('duplicate JSON key')
            result[key]=value
        return result
    def number(value):
        result=float(value)
        if not math.isfinite(result):raise ValueError('nonfinite JSON number')
        return result
    def constant(_):raise ValueError('nonfinite JSON constant')
    try:
        if path.stat().st_size>limit:raise ValueError('receipt exceeds its byte bound')
        with path.open('rb') as handle:data=handle.read(limit+1)
        if len(data)>limit:raise ValueError('receipt exceeds its byte bound')
        result=json.loads(data,object_pairs_hook=pairs,parse_float=number,parse_constant=constant)
        if not isinstance(result,dict):raise ValueError('receipt must be an object')
        return result
    except (OSError,ValueError,UnicodeError,RecursionError) as error:
        fail('VERIFICATION_FAILED','Fresh Draft geometry receipt is missing, malformed or unbounded',detail=str(error)[:200])


def fresh_inventories(path,prepared):
    nodes=[n for n in prepared['nodes'] if n['filter']=='bodyDraft']
    if not nodes:return {}
    if 'FreeCAD' in sys.modules or isinstance(__loader__,zipimport.zipimporter):
        fail('VERIFICATION_CONTEXT_REQUIRED','Draft selection verification must run in the installed host after the native worker exits')
    remaining_timeout(180)
    location=executable('freecad')
    if not location:
        fail('VERIFICATION_RUNTIME_REQUIRED','Draft selection verification needs a configured FreeCAD command executable; saved receipts do not select it')
    from .assembly_sources import check_archive
    from .source_envelope import brep,MEMBER_BYTES
    check_archive(path,str(path),code='VERIFICATION_FAILED')
    xml=Document(path);mapped=names(prepared)
    with tempfile.TemporaryDirectory(prefix='schemaxis-draft-verify-') as temporary:
        scratch=Path(temporary);requests=[];size=0
        with ZipFile(path) as archive:
            for index,identity in enumerate(dict.fromkeys(n['inputs']['base'] for n in nodes)):
                remaining_timeout(180)
                prop=xml.properties[mapped[identity]]['Shape'];parts=prop.findall('Part')
                if prop.get('type')!='Part::PropertyPartShape' or len(parts)!=1:
                    fail('VERIFICATION_FAILED','Draft base shape property differs',identity)
                # Native Shape also contains an ElementMap sibling; no map or
                # object-restoration record is submitted to the geometry reader.
                member=parts[0].get('file')
                if not isinstance(member,str) or not member:
                    fail('VERIFICATION_FAILED','Draft base has no saved shape payload',identity)
                data=read_member(archive,member,MEMBER_BYTES);size+=len(data)
                if not data or size>64*1024*1024:
                    fail('VERIFICATION_FAILED','Draft base geometry is empty or exceeds the 64 MiB measurement budget',identity)
                brep(data,identity,'VERIFICATION_FAILED',member)
                target=scratch/('base-'+str(index)+'.brp');target.write_bytes(data)
                requests.append({'id':identity,'file':target.name,'sha256':file_digest(target)})
        atomic_json(scratch/'draft-breps.json',requests)
        archive=scratch/'trusted-runtime.zip';archive.write_bytes(runtime_archive())
        code=('import sys\nsys.path.insert(0,'+repr(str(archive))+')\n'
            'from schemaxis.adaptors.freecad.draft_native import inspect_saved_breps\n'
            'from schemaxis.native_boundary import execute_guarded\n'
            'execute_guarded(inspect_saved_breps,'+repr(str(scratch))+')\n')
        try:submission=SubprocessRunner(Interpreter('freecad',str(Path(location).expanduser().absolute())),scratch,timeout=180)(code)
        except SchemaxisError as error:
            if error.fault.code in ('RUNNER_CANCELLED','RUNNER_TIMED_OUT'):raise
            fail('VERIFICATION_FAILED','Fresh Draft base geometry measurement failed',reason=str(error))
        if (scratch/'native-fault.json').is_file():
            fault=read_object(scratch/'native-fault.json',128*1024)
            if fault.get('code') in ('RUNNER_CANCELLED','RUNNER_TIMED_OUT'):raise SchemaxisError(Fault(**fault))
            fail('VERIFICATION_FAILED','Fresh Draft base geometry measurement refused the saved BREP',fault=fault)
        if not (scratch/'draft-inventories.json').is_file():
            fail('VERIFICATION_FAILED','Fresh Draft base geometry measurement produced no evidence',submission=submission.to_dict())
        result=read_object(scratch/'draft-inventories.json')
        if not isinstance(result,dict) or set(result)!={r['id'] for r in requests}:
            fail('VERIFICATION_FAILED','Fresh Draft base inventory membership differs')
    remaining_timeout(180)
    return result


def verify(path,prepared,built,reopened,saved):
    from .draft import selected
    from .history import equivalent
    inventories=fresh_inventories(path,prepared)
    for node in prepared['nodes']:
        if node['filter']!='bodyDraft':continue
        remaining_timeout(180)
        identity=node['id'];inventory=inventories[node['inputs']['base']]
        indices=selected(node['options'],inventory,identity)
        if saved['features'][identity]['base'][1]!=indices:
            fail('VERIFICATION_FAILED','Saved Draft face links differ from authored intent on freshly measured base geometry',identity)
        for stage,observed in [('build',built),('reopen',reopened)]:
            record=observed['features'][identity]
            if record['base'][1]!=indices or not equivalent(record.get('faceInventory'),inventory):
                fail('VERIFICATION_FAILED','Draft selection witness differs from freshly measured saved base geometry',identity,stage=stage)
    remaining_timeout(180)
