"""Trusted native-mutation qualification, isolated from companion hash guards."""
import hashlib
import json
from pathlib import Path
import subprocess
import tempfile
from schemaxis.adaptors.blender.adaptor import verify,_verify as verify_native
from schemaxis.configuration import location_context
from schemaxis.core.faults import SchemaxisError

NATIVE_GUARDS={
    'current native project/production output differs from retained readback',
    'fresh native production readback refused current project',
}


def qualify(blender,projects,mutations,preamble=''):
    """Prove no-op saves pass the same fresh native path that rejects attacks.

    Whole-run baseline verification includes schema and publication companions.
    After a native save, only the saved project's receipt hash is refreshed;
    companion metadata deliberately still describes the baseline. Calling the
    provider verifier isolates actual current native data/intent checks from that
    separate framework metadata guard. The product verifier is not modified.
    """
    outcomes=[];controls=[]
    for case,directory in projects:
        directory=Path(directory).absolute();blend=directory/'0000.blend';receipt_path=directory/'verification.json'
        original=blend.read_bytes();receipt_bytes=receipt_path.read_bytes()
        with location_context({'blender':blender}):assert verify(directory)['verified']
        try:
            for name,mutation in [('unchangedSave',''),*mutations.items()]:
                print(case,name,flush=True)
                blend.write_bytes(original);receipt_path.write_bytes(receipt_bytes)
                with tempfile.TemporaryDirectory(prefix='schemaxis-native-mutation-') as temp:
                    script=Path(temp)/'change.py'
                    script.write_text('import bpy\n'+f'bpy.ops.wm.open_mainfile(filepath={str(blend)!r},use_scripts=False)\n'+preamble+'\n'+mutation+f'\nbpy.ops.wm.save_as_mainfile(filepath={str(blend)!r})\n')
                    native=subprocess.run([blender,'--background','--factory-startup','--disable-autoexec','--python-exit-code','1','--python',str(script)],timeout=60,capture_output=True,text=True)
                    assert native.returncode==0,(case,name,native.stdout,native.stderr)
                receipt=json.loads(receipt_bytes);changed=0
                for artifact in receipt['artifacts']:
                    if artifact['file']==str(blend):artifact['sha256']=hashlib.sha256(blend.read_bytes()).hexdigest();changed+=1
                assert changed==1,(case,name,'saved artifact membership')
                receipt_path.write_text(json.dumps(receipt,indent=2)+'\n');fault=None
                with location_context({'blender':blender}):
                    try:verify_native(directory,require_result=True)
                    except SchemaxisError as error:fault=error.fault
                if name=='unchangedSave':
                    assert fault is None,(case,name,fault)
                    controls.append({'case':case,'nativeOpenSaveWithoutChange':'verified','nativeHashRefreshed':True})
                else:
                    assert fault and fault.code=='VERIFICATION_FAILED' and fault.message in NATIVE_GUARDS,(case,name,fault)
                    outcomes.append({'case':case,'mutation':name,'fault':fault.code,'message':fault.message,'observed':dict(fault.observed),'nativeHashRefreshed':True})
        finally:blend.write_bytes(original);receipt_path.write_bytes(receipt_bytes)
    return {'status':'passed','cases':outcomes,'controls':controls,'trustedRuntime':True}
