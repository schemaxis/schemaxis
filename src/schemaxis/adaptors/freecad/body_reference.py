"""Bounded exact SDK lifecycle of a freshly compiled Body reference.

A submitted archive is read only by the host binder. Native transitions receive
only the private reference constructed from typed intent and admitted originals.
An observed repeated state is a conservative stopping condition, not a proof of
universal SDK convergence or exhaustion of every possible valid native save.
"""
from contextlib import contextmanager
from datetime import datetime
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import stat
import struct
from zipfile import ZipFile

from schemaxis.artifacts import atomic_json
from schemaxis.core.faults import SchemaxisError,Fault
from schemaxis.dispatch import remaining_timeout
from schemaxis.errors import fail
from .process import SubprocessRunner


def private_path(root,path,*,directory=False):
    """No-follow host-owned rolling paths; receipts never supply a pathname.

    This checks the fixed private tree at each use. It is not an arbitrary
    same-UID race-elimination guarantee between a check and a native open.
    """
    root=Path(root);path=Path(path)
    if not stat.S_ISDIR(root.lstat().st_mode) or root.is_symlink():
        raise ValueError('Trusted Body scratch root must be a real directory')
    relative=path.relative_to(root)
    current=root
    for piece in relative.parts:
        if piece in ('.','..'):raise ValueError('Trusted Body scratch path escapes its root')
        current=current/piece
        mode=current.lstat().st_mode
        if stat.S_ISLNK(mode):raise ValueError('Trusted Body scratch path is a symlink')
    resolved=path.resolve(strict=True);resolved.relative_to(root.resolve(strict=True))
    mode=path.lstat().st_mode
    if not (stat.S_ISDIR(mode) if directory else stat.S_ISREG(mode)):
        raise ValueError('Trusted Body scratch path has the wrong file type')
    if path.stat().st_dev!=root.stat().st_dev:
        raise ValueError('Trusted Body rolling paths must stay on the scratch filesystem')
    return path


@contextmanager
def bounded_archive(path):
    """Size/count-only preflight before lifecycle XML, with no member decoding.

    The same limits also enclose streamed key reads after validated geometry.
    Bad ZIP/name/type syntax remains a verification fault, not a size fault.
    """
    from .assembly_sources import SOURCE_BYTES,ZIP_MEMBERS,ZIP_EXPANDED
    from .source_envelope import MEMBER_BYTES
    from .document_xml import ARCHIVE_ERRORS
    try:
        remaining_timeout(120)
        if not stat.S_ISREG(Path(path).lstat().st_mode):
            raise ValueError('Trusted Body reference archive is not a regular no-follow file')
        with Path(path).open('rb') as handle:
            metadata=os.fstat(handle.fileno())
            if not stat.S_ISREG(metadata.st_mode):
                raise ValueError('Trusted Body reference archive file type changed')
            if metadata.st_size>SOURCE_BYTES:
                fail('RESOURCE_LIMIT','Trusted Body reference archive exceeds 64 MiB')
            with ZipFile(handle) as archive:
                remaining_timeout(120)
                infos=archive.infolist();names=[i.filename for i in infos]
                if len(infos)>ZIP_MEMBERS or sum(i.file_size for i in infos)>ZIP_EXPANDED:
                    fail('RESOURCE_LIMIT','Trusted Body reference exceeds archive inventory or expanded-size bounds')
                if any(i.file_size>MEMBER_BYTES for i in infos):
                    fail('RESOURCE_LIMIT','Trusted Body reference member exceeds 32 MiB')
                if (len(set(names))!=len(names) or names.count('Document.xml')!=1
                        or any(i.is_dir() or i.filename.startswith('/') or '..' in i.filename.split('/')
                               or '\\' in i.filename for i in infos)):
                    raise ValueError('Trusted Body reference archive membership differs')
                yield archive,infos
                remaining_timeout(120)
    except (OSError,ValueError,KeyError,RuntimeError,NotImplementedError)+ARCHIVE_ERRORS as error:
        fail('VERIFICATION_FAILED','Trusted Body reference archive cannot be decoded safely',detail=str(error))


def _key_members(path):
    """Stream bounded members; retain only the bounded XML needed for dates."""
    from .assembly_sources import ZIP_EXPANDED
    from .source_envelope import MEMBER_BYTES
    from .document_xml import METHODS,REFUSED_FLAGS,UnsupportedArchive
    values=[];document=None;expanded=0
    with bounded_archive(path) as (archive,infos):
        for info in sorted(infos,key=lambda i:i.filename):
            remaining_timeout(120)
            if info.flag_bits&REFUSED_FLAGS or info.compress_type not in METHODS:
                raise UnsupportedArchive('Trusted Body reference ZIP feature differs')
            archive.fp.seek(info.header_offset);header=archive.fp.read(30)
            if len(header)!=30 or header[:4]!=b'PK\x03\x04':
                raise UnsupportedArchive('Trusted Body reference local header differs')
            flags,method=struct.unpack_from('<HH',header,6)
            if flags&REFUSED_FLAGS or method!=info.compress_type:
                raise UnsupportedArchive('Trusted Body reference local ZIP features differ')
            hasher=hashlib.sha256();chunks=[];size=0
            with archive.open(info) as member:
                while True:
                    remaining_timeout(120);block=member.read(1<<20)
                    if not block:break
                    size+=len(block);expanded+=len(block)
                    if size>MEMBER_BYTES or expanded>ZIP_EXPANDED:
                        fail('RESOURCE_LIMIT','Trusted Body reference decoded bytes exceed their bounds')
                    hasher.update(block)
                    if info.filename=='Document.xml':chunks.append(block)
            if size!=info.file_size:raise ValueError('Trusted Body reference ZIP size differs')
            if info.filename=='Document.xml':document=b''.join(chunks)
            else:values.append((info.filename,hasher.hexdigest()))
    return document,values


def state_key(path):
    """Hash all uncompressed bytes, replacing only validated root date values.

    Keep raw IDs, aliases, flags, statuses, placements and every unused record.
    This is deliberately stricter than the successful whole-archive binder.
    The initial key describes the fresh host build; subsequent keys are read
    only after complete lifecycle receipt/geometry validation and binder failure.
    """
    from .document_xml import parse_xml
    remaining_timeout(120)
    data,values=_key_members(path);root=parse_xml(data,'trusted Document.xml')
    start=data.index(b'<Properties ');end=data.index(b'</Properties>',start)+len(b'</Properties>')
    properties=data[start:end]
    for name in ('CreationDate','LastModifiedDate'):
        entries=root.findall("./Properties/Property[@name='"+name+"']")
        if (len(entries)!=1 or len(entries[0])!=1 or entries[0][0].tag!='String'
                or entries[0].get('type')!='App::PropertyString'
                or set(entries[0][0].attrib)!={'value'} or len(entries[0][0])):
            raise ValueError('Trusted Body reference date record differs')
        value=entries[0][0].get('value');datetime.fromisoformat(value)
        pattern=rb'<Property\b[^>]*\bname="'+name.encode()+rb'"[^>]*>.*?</Property>'
        matches=list(re.finditer(pattern,properties,re.DOTALL))
        token=b'<String value="'+value.encode('ascii')+b'"/>'
        if len(matches)!=1 or matches[0].group().count(token)!=1:
            raise ValueError('Trusted Body reference date serialization differs')
        match=matches[0];replacement=match.group().replace(token,b'<String value="<native-date>"/>',1)
        properties=properties[:match.start()]+replacement+properties[match.end():]
    data=data[:start]+properties+data[end:]
    values.append(('Document.xml',hashlib.sha256(data).hexdigest()))
    values.sort()
    remaining_timeout(120)
    return hashlib.sha256(json.dumps(values,separators=(',',':')).encode()).digest()


def bind_lifecycle(path,root,generated,runtime,interpreter,prepared,retained,source_names):
    """Accept only one complete reachable trusted state within the parent budget."""
    from .part_reconstruction import bind_payloads,body_reference_lifecycle
    from .draft_verify import read_object
    from .assembly_sources import SOURCE_BYTES
    remaining_timeout(120)
    generated=Path(generated)
    private_path(generated,generated,directory=True)
    private_path(generated,generated/'model.FCStd')
    reference=generated/'body-reference';reference.mkdir()
    private_path(generated,reference,directory=True)
    shutil.copyfile(generated/'model.FCStd',reference/'model.FCStd')
    atomic_json(reference/'plan.json',prepared);atomic_json(reference/'sources.json',retained)
    private_path(generated,reference/'model.FCStd')
    seen={state_key(reference/'model.FCStd')};baseline=None
    while True:
        remaining_timeout(120)
        private_path(generated,reference,directory=True)
        for name in ('model.FCStd','plan.json','sources.json'):
            private_path(generated,reference/name)
        if (reference/'resaved').exists() or (reference/'resaved').is_symlink():
            raise ValueError('Trusted Body next rolling slot already exists')
        code=('import sys\nsys.path.insert(0,'+repr(str(runtime))+')\n'
              'from schemaxis.adaptors.freecad.part_reference_native import resave\n'
              'from schemaxis.native_boundary import execute_guarded\n'
              'from functools import partial\n'
              'execute_guarded(partial(resave,body_local=True),'+repr(str(reference))+')\n')
        try:SubprocessRunner(interpreter,reference,timeout=remaining_timeout(120))(code)
        except SchemaxisError as error:
            if error.fault.code in ('RUNNER_CANCELLED','RUNNER_TIMED_OUT'):raise
            if (reference/'native-fault.json').exists() or (reference/'native-fault.json').is_symlink():
                private_path(generated,reference/'native-fault.json')
                value=read_object(reference/'native-fault.json',128*1024)
                if value.get('code') in ('RUNNER_CANCELLED','RUNNER_TIMED_OUT'):
                    raise SchemaxisError(Fault(**value))
            raise
        if (reference/'native-fault.json').exists() or (reference/'native-fault.json').is_symlink():
            private_path(generated,reference/'native-fault.json')
            value=read_object(reference/'native-fault.json',128*1024)
            if value.get('code') in ('RUNNER_CANCELLED','RUNNER_TIMED_OUT'):
                raise SchemaxisError(Fault(**value))
            raise ValueError('Trusted Body reference lifecycle failed')
        candidate=reference/'resaved'
        private_path(generated,candidate,directory=True)
        for name in ('model.FCStd','reference-lifecycle.json'):
            private_path(generated,candidate/name)
        # Metadata-only resource admission precedes even the bounded XML read
        # needed to validate receipt membership. No worker member is decoded.
        with bounded_archive(candidate/'model.FCStd'):pass
        baseline=body_reference_lifecycle(candidate,baseline)
        remaining_timeout(120)
        private_path(generated,candidate/'model.FCStd')
        key=state_key(candidate/'model.FCStd')
        try:bind_payloads(path,root,candidate,source_names)
        except ValueError:pass
        else:
            remaining_timeout(120)
            return
        if key in seen:
            fail('VERIFICATION_FAILED','Saved Body history did not match the observed trusted lifecycle',
                 reason='trusted-state-repeated')
        # This is a fixed byte budget for stopping metadata, not a submitted or
        # guessed native save count. Each SHA256 key's bookkeeping is bounded.
        if (len(seen)+1)*256>SOURCE_BYTES:
            fail('RESOURCE_LIMIT','Trusted Body lifecycle state bookkeeping exceeds its byte budget')
        seen.add(key);remaining_timeout(120)
        # Retain only the original build and two rolling private native files.
        # A previously checked failed candidate never becomes submitted input.
        # Recheck both slots immediately before the same-filesystem atomic
        # replace. Never delete current before the complete next file moves.
        for directory in (reference,candidate):private_path(generated,directory,directory=True)
        for member in (candidate/'model.FCStd',reference/'model.FCStd',candidate/'reference-lifecycle.json'):
            private_path(generated,member)
        (candidate/'model.FCStd').replace(reference/'model.FCStd')
        (candidate/'reference-lifecycle.json').unlink();candidate.rmdir()
        remaining_timeout(120)
