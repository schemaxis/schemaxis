# Copyright (C) 2026 David L F Gaden
"""Qualify built-in fixed Assembly joints, links, solver and editable FCStd.

PYTHONPATH=src python tools/qualify_freecad_assembly.py
Evidence remains under evidence/assembly-20260920 by default; never overwrites
an earlier completed qualification or its qualified model directory.
"""
import argparse
import json
from pathlib import Path

from schemaxis.core.faults import SchemaxisError, Fault
from schemaxis.core.runners import Interpreter
from schemaxis.artifacts import atomic_json
from schemaxis.dispatch import SubprocessRunner
from schemaxis.adaptors.freecad.assembly import gui_stage, plan, run, verify


def qualify(directory, executable, gui_executable):
    directory = Path(directory).absolute()
    directory.mkdir(parents=True, exist_ok=True)
    if (directory/'qualification.json').exists() or (directory/'qualified').exists():
        raise FileExistsError('Choose a fresh qualification directory; existing evidence is preserved')
    document = json.loads(Path('examples/schemaxis/freecad-assembly.json').read_text())
    result = run(document, directory/'qualified', executable=executable, gui_executable=gui_executable)
    target = directory/'qualified'
    # The common runtime retains a single analytic visit in state-00000.
    if (target/'state-00000').is_dir() and not (target/'built.json').exists():
        target = target/'state-00000'
    runner = SubprocessRunner(Interpreter('freecad', executable), target, timeout=60)
    for stage in ('edit_probe', 'edit_reopen'):
        source = ('import sys\nsys.path.insert(0,'+repr(str(target/'runtime.zip'))+')\n'
            'from schemaxis.adaptors.freecad.assembly_native import '+stage+'\n'
            'from schemaxis.native_boundary import execute_guarded\n'
            'execute_guarded('+stage+','+repr(str(target))+')\n')
        submission = runner(source)
        atomic_json(target/(stage+'-submission.json'), submission.to_dict())
        if (target/'native-fault.json').exists():
            raise SchemaxisError(Fault(**json.loads((target/'native-fault.json').read_text())))
    edited = json.loads((target/'edit.json').read_text())
    reopened = json.loads((target/'edit-reopened.json').read_text())
    assert edited['pid'] != reopened['pid']
    expected = plan(json.loads((target/'edited-authored.json').read_text()))
    assert expected['parts'][0]['options']['height'] == 7
    for receipt in (edited, reopened):
        assert receipt['definition'] == expected
        assert receipt['solver']['returnCode'] == 0
        for component in receipt['components']:
            from schemaxis.adaptors.freecad.adaptor import close
            analytic = expected['expected'][component['id']]
            for measure in ('position', 'xAxis', 'zAxis', 'bounds', 'volume'):
                assert close(component[measure], analytic[measure]), (component['id'], measure)
    assert verify(target)['verified']
    native = json.loads((target/'verification.json').read_text())
    shared = {component['id']: component['linkedNativeName'] for component in native['components']}
    assert shared['base'] == shared['lid'] and shared['postLeft'] == shared['postRight']
    if gui_executable:
        gui_stage(gui_executable, target, 60, stage='gui_reopen')
        assert (target/'assembly.png').read_bytes().startswith(b'\x89PNG\r\n\x1a\n')
        assert json.loads((target/'gui.json').read_text())['nativeJointEditors'] is True
        assert json.loads((target/'gui-reopened.json').read_text())['nativeJointEditors'] is True
    # The common single-visit aggregate omits native identity; the receipt has it.
    verified = verify(target)
    receipt = {'qualified': True, 'version': document['version'], 'runtime': native['runtime'],
        'nativeAssemblyType': native['assemblyType'], 'components': verified['components'], 'fixedJoints': verified['joints'],
        'sharedLinks': shared, 'solverReturnCode': native['solver']['returnCode'],
        'displacedAndRestored': native['solver']['displacedComponents'], 'analyticPlacementsVerified': True,
        'freshReopenPid': native['pid'], 'editPid': edited['pid'], 'editReopenPid': reopened['pid'],
        'sharedPlateHeightBeforeMM': 5, 'sharedPlateHeightAfterMM': 7, 'nativeJointEditors': bool(gui_executable),
        'nativeFile': str(target/'model.FCStd'), 'editedNativeFile': str(target/'edited.FCStd'),
        'limitations': 'Fixed trees only; no revolute joint, motion simulation, collision or dynamic multibody qualification.'}
    atomic_json(directory/'qualification.json', receipt)
    return receipt


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--directory', default='evidence/assembly-20260920')
    parser.add_argument('--executable', required=True)
    parser.add_argument('--gui-executable', required=True)
    parser.add_argument('--headless', action='store_true')
    args = parser.parse_args()
    print(json.dumps(qualify(args.directory, args.executable, None if args.headless else args.gui_executable), indent=2))
