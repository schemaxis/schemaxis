"""Fresh geometry-only NC verification using trusted current code and locations."""
import json
import tempfile
from pathlib import Path
from schemaxis.artifacts import runtime_archive
from schemaxis.configuration import executable
from schemaxis.core.runners import Interpreter
from schemaxis.core.faults import SchemaxisError,Fault
from schemaxis.dispatch import remaining_timeout
from .process import SubprocessRunner
from schemaxis.errors import fail


def fresh_material(directory):
    remaining_timeout(180)
    from .cam_evidence2 import read
    version=read(Path(directory)/'plan.json').get('version')
    if version not in ('schemaxis.freecad.cam.plan/1','schemaxis.freecad.cam.plan/2','schemaxis.freecad.cam.plan/3'):
        fail('VERIFICATION_FAILED','Unknown finite machining plan family')
    module='cam_material3' if version=='schemaxis.freecad.cam.plan/3' else 'cam_material'
    location=executable('freecad')
    if not location:fail('VERIFICATION_RUNTIME_REQUIRED','Machining verification needs a configured FreeCAD command executable; receipt paths are not executable authority')
    with tempfile.TemporaryDirectory(prefix='schemaxis-cam-verify-') as temporary:
        scratch=Path(temporary);archive=scratch/'trusted-runtime.zip';archive.write_bytes(runtime_archive())
        runner=SubprocessRunner(Interpreter('freecad',str(Path(location).expanduser().absolute())),scratch,timeout=180)
        script='import sys\nsys.path.insert(0,'+repr(str(archive))+')\nfrom schemaxis.adaptors.freecad.'+module+' import material\nfrom schemaxis.native_boundary import execute_guarded\nexecute_guarded(lambda _:material('+repr(str(directory))+','+repr(str(scratch))+'),'+repr(str(scratch))+')\n'
        try:runner(script)
        except SchemaxisError as error:
            if error.fault.code in ('RUNNER_CANCELLED','RUNNER_TIMED_OUT'):raise
            fail('VERIFICATION_FAILED','Fresh independent cutter replay refused machining outputs',reason=str(error))
        except Exception as error:fail('VERIFICATION_FAILED','Fresh independent cutter replay refused machining outputs',reason=str(error))
        if (scratch/'native-fault.json').exists():
            fault=json.loads((scratch/'native-fault.json').read_text())
            if fault.get('code') in ('RUNNER_CANCELLED','RUNNER_TIMED_OUT'):raise SchemaxisError(Fault(**fault))
            fail('VERIFICATION_FAILED','Fresh independent cutter replay refused machining outputs',fault=fault)
        if not (scratch/'material.json').is_file():fail('VERIFICATION_FAILED','Fresh independent cutter replay produced no evidence')
        result=json.loads((scratch/'material.json').read_text())
    remaining_timeout(180)
    return result
