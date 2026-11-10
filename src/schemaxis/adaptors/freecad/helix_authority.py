"""Fresh geometry authority and checked private inputs for Helix reopening."""
from contextlib import contextmanager
from contextvars import ContextVar
from dataclasses import dataclass
import copy
import json
from pathlib import Path
import tempfile

from schemaxis.artifacts import atomic_json
from schemaxis.errors import fail
from schemaxis.run_paths import owned_path
from .export_payloads import capture

_active=ContextVar('schemaxis_freecad_helix_authority',default=None)
NATIVE_BYTES=64*1024*1024


@dataclass(frozen=True)
class Admission:
    original: Path
    private: Path
    prepared: dict
    captured: dict
    private_captured: dict
    snapshots: dict
    metadata: dict
    trusted: dict

    def check_current(self,prepared,captured):
        if prepared!=self.prepared or captured!=self.captured:
            fail('VERIFICATION_FAILED','Helix declaration or captured-source records changed after admission')
        for filename,snapshot in self.snapshots.items():
            current=capture(owned_path(self.original,filename),location=filename)
            if current.sha256!=snapshot.sha256 or current.size!=snapshot.size:
                fail('VERIFICATION_FAILED','Helix publication changed after complete admission',filename)
        for filename,snapshot in self.metadata.items():
            if snapshot is None:
                path=self.original/filename
                if path.exists() or path.is_symlink():fail('VERIFICATION_FAILED','Helix evidence appeared after admission',filename)
                continue
            path=owned_path(self.original,filename)
            current=capture(path,location=filename)
            if current.sha256!=snapshot.sha256:
                fail('VERIFICATION_FAILED','Helix evidence changed after complete admission',filename)
        for identity,record in captured.items():
            current=capture(owned_path(self.original,record['retained']),location=identity)
            if current.sha256!=record['sha256']:
                fail('INPUT_CHANGED','Captured Helix source changed after complete admission',identity)

    def publish_reopen(self):
        from .saved_checks import read_json
        from .adaptor import output_files
        self.check_current(self.prepared,self.captured)
        for filename,snapshot in self.snapshots.items():
            current=capture(self.private/filename,location=filename)
            if current.sha256!=snapshot.sha256:
                fail('VERIFICATION_FAILED','Checked private native input changed during reopening',filename)
        receipt=read_json(self.private,'verification.json')
        files=output_files(self.prepared);artifacts=receipt.get('artifacts')
        if not isinstance(artifacts,list) or len(artifacts)!=len(files):
            fail('VERIFICATION_FAILED','Private Helix artifact membership differs')
        for artifact,(filename,kind) in zip(artifacts,files):
            if (artifact.get('file')!=str(self.private/filename) or artifact.get('kind')!=kind
                    or artifact.get('sha256')!=self.snapshots[filename].sha256):
                fail('VERIFICATION_FAILED','Private Helix artifact binding differs',filename)
            artifact['file']=str(self.original/filename)
        data=(json.dumps(receipt,indent=2,allow_nan=False)+'\n').encode('utf-8')
        self.metadata['verification.json']=capture(data)
        atomic_json(self.private/'verification.json',receipt)
        atomic_json(self.original/'verification.json',receipt)
        self.check_current(self.prepared,self.captured)


def current(directory,prepared,captured):
    value=_active.get()
    if value is None or value.original!=Path(directory).absolute():return None
    value.check_current(prepared,captured)
    return value


@contextmanager
def admit(directory,prepared,captured):
    from schemaxis.dispatch import execution_deadline
    # One enclosing host deadline covers every reference process and the
    # checked submitted reopening, while preserving any shorter caller limit.
    with execution_deadline(240):
        with _admit(directory,prepared,captured) as value:yield value


@contextmanager
def _admit(directory,prepared,captured):
    """Never restore a submitted native file while constructing its reference."""
    from .helix import active
    from .adaptor import output_files
    from .saved_checks import verify_sources,verify_saved_document
    from .part_reconstruction import verify as reconstruct
    if not active(prepared):fail('VERIFICATION_FAILED','Helix authority requires a recompiled Helix plan')
    directory=Path(directory).absolute();verify_sources(directory,prepared,captured)
    snapshots={}
    for filename,kind in output_files(prepared):
        value=capture(owned_path(directory,filename),kind='stl' if filename=='model.stl' else None,location=filename)
        if filename!='model.step' and filename!='model.stl' and value.size>NATIVE_BYTES:
            fail('RESOURCE_LIMIT','Helix native or report input exceeds 64 MiB',filename)
        snapshots[filename]=value
    metadata={}
    for filename in ('authored.json','plan.json','sources.json','built.json','verification.json'):
        path=directory/filename
        metadata[filename]=(None if filename=='verification.json' and not path.exists() and not path.is_symlink()
                            else capture(owned_path(directory,filename),location=filename))
        if metadata[filename] is not None and metadata[filename].size>NATIVE_BYTES:
            fail('RESOURCE_LIMIT','Helix evidence input exceeds 64 MiB',filename)
    with tempfile.TemporaryDirectory(prefix='schemaxis-helix-admitted-') as temporary:
        private=Path(temporary).resolve(strict=True);retained={};total=0
        for identity,record in captured.items():
            source=capture(owned_path(directory,record['retained']),location=identity);total+=source.size
            if source.sha256!=record['sha256']:fail('INPUT_CHANGED','Captured Helix source differs',identity)
            if total>NATIVE_BYTES:fail('RESOURCE_LIMIT','Helix captured-source budget exceeds 64 MiB')
            name=Path(record['retained']).name
            if name in snapshots or (private/name).exists():fail('VERIFICATION_FAILED','Helix source filename collision',identity)
            (private/name).write_bytes(source.data);retained[identity]={**record,'retained':str(private/name)}
        for filename,value in snapshots.items():(private/filename).write_bytes(value.data)
        for filename,value in metadata.items():
            if value is not None:(private/filename).write_bytes(value.data)
        atomic_json(private/'plan.json',prepared);atomic_json(private/'sources.json',retained)
        verify_saved_document(private/'model.FCStd',prepared,retained)
        if 'partDesign' in prepared:
            from .part_design_saved import verify as verify_body
            verify_body(prepared,private/'model.FCStd')
        trusted=reconstruct(private/'model.FCStd',prepared,retained,
                            exports={'step':snapshots['model.step'],'stl':snapshots['model.stl']})
        if trusted['exportDigests']!={key:snapshots['model.'+key].sha256 for key in ('step','stl')}:
            fail('VERIFICATION_FAILED','Helix reference bound different export snapshots')
        value=Admission(directory,private,copy.deepcopy(prepared),copy.deepcopy(captured),retained,snapshots,metadata,trusted)
        value.check_current(prepared,captured)
        token=_active.set(value)
        try:yield value
        finally:_active.reset(token)


def verify_observations(prepared,built,receipt,trusted):
    """Bind published facts to complete fresh records for their native state."""
    from .helix_evidence import exact
    for actual,reference in ((built,trusted['built']),(receipt,trusted['reopened'])):
        observed=actual.get('exportEvidence',{}).get('precision',{}).get('runtime')
        expected=reference.get('exportEvidence',{}).get('precision',{}).get('runtime')
        if observed!=expected:
            fail('RERUN_REQUIRED','Helix evidence needs the same qualified FreeCAD and OCCT runtime; rerun with this installation')
    for label,actual,reference in (('build',built,trusted['built']),
                                   ('reopen',receipt,trusted['reopened'])):
        keys={'definition','measurementObservations','selections','importObservations'}
        keys.update({'shape'} if label=='build' else {'native','step','mesh','runtime','units','freshProcess','status'})
        for optional in ('parameterObservations','partDesignObservations','bodyLocalExportEvidence'):
            if optional in reference:keys.add(optional)
        for key in keys:
            if key not in actual or key not in reference or not exact(actual[key],reference[key]):
                fail('VERIFICATION_FAILED','Helix published facts differ from fresh trusted observations',
                     label,observation=key)
