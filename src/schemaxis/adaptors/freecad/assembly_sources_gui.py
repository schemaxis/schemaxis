"""Judge finite GUI readback after mandatory complete sourced-assembly admission."""
import json,math,re
from pathlib import Path
from schemaxis.artifacts import atomic_json,runtime_archive
from schemaxis.dispatch import remaining_timeout
from schemaxis.errors import fail


def inspect_verified(directory,prepared,executable,timeout,*,verified_sha256):
    # Called only by assembly_sources.run after verify(require_result=False)
    # has checked EVERY retained input and the complete submitted assembly.
    from .assembly_sources import digest,check_snapshot,visibility,proxies,close
    from .assembly_sources_saved import Saved
    from .gui_process import run
    directory=Path(directory);path=directory/'model.FCStd'
    # Carry the exact digest already checked by full host verification. A fresh
    # digest here cannot turn a concurrent unverified save into admitted bytes.
    if (not isinstance(verified_sha256,str) or re.fullmatch('[0-9a-f]{64}',verified_sha256) is None
            or digest(path)!=verified_sha256):
        fail('INPUT_CHANGED','Sourced assembly changed after complete verification',str(path))
    before=verified_sha256
    built=json.loads((directory/'built.json').read_text());renames=built['renames']
    captured=json.loads((directory/'capture.json').read_text())
    centres={p['id']:captured['parts'][p['id']]['shape']['centreOfMass'] for p in prepared['parts']}
    saved=Saved(path)
    # Installed host code is authority; a retained runtime.zip is editable run
    # evidence and must never select the code executed by this GUI stage.
    remaining_timeout(timeout)
    (directory/'source-gui-runtime.zip').write_bytes(runtime_archive())
    remaining_timeout(timeout)
    if digest(path)!=before:fail('INPUT_CHANGED','Sourced assembly changed before GUI launch',str(path))
    # A zero-exit launcher that never executes the worker cannot reuse an old
    # inspection. Each attempt must produce fresh native readback.
    (directory/'inspect.json').unlink(missing_ok=True)
    atomic_json(directory/'source-gui-request.json',{'sha256':before,'prepared':prepared,'renames':renames})
    result=run(directory,executable,'inspect',family='sourceAssembly',timeout=remaining_timeout(timeout))
    remaining_timeout(timeout)
    def require(value,message,**observed):
        if not value:fail('VERIFICATION_FAILED',message,str(path),**observed)
    require(digest(path)==before,'Read-only sourced assembly GUI changed its native publication')
    actual=result['observed']
    require(actual.get('sha256')==before,'GUI observed another sourced assembly')
    check_snapshot(prepared,actual.get('snapshot',{}),renames,centres,require,'GUI first-open')
    require(actual.get('visibility')==visibility(prepared,saved.xml.types,renames),'First-open sourced assembly visibility differs')
    require(actual.get('providers')=={name:{'class':kind,'attached':True} for name,kind in proxies(prepared).items()},
            'First-open sourced assembly joint view providers differ')
    require(isinstance(actual.get('bodies'),dict) and set(actual['bodies'])==set(renames),'GUI source Body membership differs')
    for part in prepared['parts']:
        remaining_timeout(timeout);identity=part['id'];facts=part['source'];body=actual['bodies'][identity]
        source=Saved(directory/prepared['native']['retained'][identity]);expected=source.placement(facts['body'],'Placement')
        matrix=body.get('placement')
        require(isinstance(matrix,list) and len(matrix)==len(expected) and all(type(x) in (int,float) and math.isfinite(x)
                and abs(x-y)<=64*max(math.ulp(x),math.ulp(y),math.ulp(1.0)) for x,y in zip(matrix,expected)),
                'GUI copied Body layout differs from its admitted source',part=identity)
        shape=body.get('shape',{})
        require(shape.get('valid') is True and shape.get('solids')==1 and all(close(shape.get(k),facts[k]) for k in ('volume','area','bounds'))
                and close(shape.get('centreOfMass'),centres[identity]),'GUI Body-local geometry differs from admitted history',part=identity)
    image=directory/'source-first-open.png'
    require(image.is_file() and 1000<image.stat().st_size<=8*1024*1024,'Native assembly GUI did not publish a bounded view image')
    remaining_timeout(timeout)
    return {'completed':True,'sha256':before,'image':image.name,'isolation':result['isolation']}
