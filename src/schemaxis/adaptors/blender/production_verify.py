"""Fresh production verification from trusted code and caller-owned locations."""
import json
import os
from pathlib import Path
import tempfile
from schemaxis.errors import fail
from schemaxis.artifacts import runtime_archive
from schemaxis.core.runners import Interpreter
from schemaxis.dispatch import SubprocessRunner
from schemaxis.dispatch import remaining_timeout
from schemaxis.errors import SchemaxisError,Fault


def fresh_reopen(directory,trusted_input=None,trusted_digest=None):
    remaining_timeout(300)
    from schemaxis.configuration import executable
    location=executable('blender') or os.environ.get('SCHEMAXIS_BLENDER')
    if not location:fail('VERIFICATION_RUNTIME_REQUIRED','scene verification needs a configured Blender executable; receipt paths are not executable authority')
    try:runtime=Interpreter('blender',str(Path(location).expanduser().absolute())).probe(timeout=remaining_timeout(120))
    except Exception:
        remaining_timeout(300)  # Preserve an enclosing deadline/cancel fault.
        raise
    if runtime.version!='5.2.3':fail('UNSUPPORTED_RUNTIME','production verification requires Blender5.2.3',version=runtime.version)
    directory=Path(directory).absolute()
    if trusted_input is None and trusted_digest is None:
        from .adaptor import plan
        from .verification_input import lowered,verify_lowered
        master,_,prepared=plan(json.loads((directory/'authored.json').read_text()))
        trusted_input=lowered(master);trusted_digest=prepared['pipeline']['digest']
        verify_lowered(directory,trusted_input)
    if not isinstance(trusted_input,dict) or not isinstance(trusted_digest,str):
        fail('VERIFICATION_FAILED','fresh reader needs a complete trusted authored projection')
    receipt=json.loads((directory/'verification.json').read_text())
    for i,state in enumerate(receipt['states']):
        if state.get('blend')!=str(directory/f'{i:04d}.blend'):fail('VERIFICATION_FAILED','saved scene path differs from planned membership')
    with tempfile.TemporaryDirectory(prefix='schemaxis-blender-production-') as temporary:
        scratch=Path(temporary);(scratch/'trusted-runtime.zip').write_bytes(runtime_archive());output=scratch/'observed.json'
        staged=scratch/'trusted-input.json';staged.write_text(json.dumps(trusted_input,allow_nan=False))
        runner=SubprocessRunner(runtime,scratch,arguments=('--background','--factory-startup','--disable-autoexec','--python-exit-code','1','--python'),timeout=remaining_timeout(300,use_parent_budget=True),environment={'PYTHONDONTWRITEBYTECODE':'1'})
        # Fault receipts belong to private verifier scratch, never the packet.
        script=f'import sys\nsys.path.insert(0,{str(scratch/"trusted-runtime.zip")!r})\nfrom schemaxis.adaptors.blender.native import reopen\nfrom schemaxis.native_boundary import execute_guarded\ndef check(_):\n    reopen({str(directory)!r},{str(output)!r},trusted_input={str(staged)!r},trusted_digest={trusted_digest!r})\nexecute_guarded(check,{str(scratch)!r})\n'
        try:runner(script)
        except Exception as error:
            if isinstance(error,SchemaxisError) and error.fault.code in ('RUNNER_CANCELLED','RUNNER_TIMED_OUT'):raise
            fault=scratch/'native-fault.json'
            if fault.is_file():raise SchemaxisError(Fault(**json.loads(fault.read_text()))) from error
            fail('VERIFICATION_FAILED','fresh native scene readback did not complete',reason=str(error),
                 recovery='Preserve the failed packet and original inputs. Inspect native diagnostics. Rerun trusted authored intent into a NEW output for deliberate changes; do not resnapshot the submitted consumer as its source.')
        remaining_timeout(300)
        fault=scratch/'native-fault.json'
        if fault.is_file():raise SchemaxisError(Fault(**json.loads(fault.read_text())))
        return json.loads(output.read_text())
