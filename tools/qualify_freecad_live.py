"""Native bounded acceptance: PYTHONPATH=src python tools/qualify_freecad_live.py.

Uses the installed GUI/display and freecadcmd. Artifacts and logs are retained in
a fresh temporary directory (or --directory). No existing FreeCAD is attached.
This is serial qualification, not exhaustive feature or platform coverage.
"""
import argparse
import copy
import json
import os
from pathlib import Path
import signal
import subprocess
import sys
import tempfile
import threading
import time

from schemaxis.core.faults import SchemaxisError
from schemaxis.adaptors.freecad.live import LiveSession


def document(nodes, output):
    return {'version': 'schemaxis.freecad/1', 'nodes': nodes, 'output': output}


def process_exited(pid):
    try:
        fields = Path(f'/proc/{pid}/stat').read_text().rsplit(')', 1)[1].split()
        return fields[0] == 'Z'
    except FileNotFoundError:
        return True


def owner_exit_probe(executable, directory):
    """A separate host exits without close(); only its own worker must exit."""
    target = directory/'owner-exit'
    source = ('import json,os\nfrom schemaxis.adaptors.freecad.live import LiveSession\n'
              's=LiveSession('+repr(executable)+','+repr(str(target))+')\n'
              's.request("apply",document={"version":"schemaxis.freecad/1","nodes":[{"id":"box","filter":"box"}],"output":"box"})\n'
              'print(json.dumps({"worker":s.request("status"),"launcherPid":s.process.pid}),flush=True)\n'
              'os._exit(0)\n')
    child = subprocess.run([sys.executable, '-c', source], capture_output=True, text=True, check=True, timeout=60)
    result = json.loads(child.stdout)
    started = time.monotonic()
    try:
        while not process_exited(result['worker']['pid']) and time.monotonic()-started < 12:
            time.sleep(.05)
        assert process_exited(result['worker']['pid']), 'Native worker outlived its owner'
        assert (target/'owner-exited.json').is_file(), 'Missing watchdog exit receipt'
    finally:
        # Failure cleanup targets only the launcher process group created here.
        try:
            os.killpg(result['launcherPid'], signal.SIGKILL)
        except ProcessLookupError:
            pass
    return {'workerPid': result['worker']['pid'], 'workerExited': True,
            'secondsAfterHostExit': time.monotonic()-started, 'modelWasApplied': True}


def cancellation_probe(executable, directory):
    from schemaxis.dispatch import allocation
    event = threading.Event()
    with LiveSession(executable, directory/'cancelled-session') as session:
        native_pid = session.request('status')['pid']
        event.set()
        with allocation({}, event):
            try:
                session.request('status')
            except SchemaxisError as error:
                assert error.fault.code == 'RUNNER_CANCELLED'
            else:
                raise AssertionError('Cancelled request succeeded')
        assert session._closed and session.process.poll() is not None
    deadline = time.monotonic()+5
    while not process_exited(native_pid) and time.monotonic() < deadline:
        time.sleep(.05)
    assert process_exited(native_pid), 'Cancelled native worker survived cleanup'
    return {'workerPid': native_pid, 'workerExited': True, 'faultCode': 'RUNNER_CANCELLED'}


def divergence_probe(executable, directory):
    """Trusted acceptance macro simulates an out-of-band GUI property edit.

    This is test code, never an authored IPC command or a public execution hook.
    It also retains a complete native application-window screenshot.
    """
    macro = directory/'divergence.FCMacro'
    macro.write_text('import sys\nsys.path.insert(0, '+repr(str(directory/'session/runtime.zip'))+')\n'
        'import FreeCAD as App, FreeCADGui as Gui\n'
        'from PySide import QtCore\n'
        'from PySide.QtGui import QImage\n'
        'from schemaxis.adaptors.freecad.live_native import Worker\n'
        'from schemaxis.artifacts import atomic_json\n'
        'from schemaxis.core.faults import SchemaxisError\n'
        'Gui.activateWorkbench("PartWorkbench")\n'
        'worker=Worker('+repr(str(directory))+',App,Gui,QtCore)\n'
        'def probe():\n'
        ' try:\n'
        '  declaration={"version":"schemaxis.freecad/1","nodes":[{"id":"b","filter":"box"}],"output":"b"}\n'
        '  worker.dispatch("apply",{"document":declaration})\n'
        '  Gui.updateGui()\n'
        '  Gui.getMainWindow().grab().save('+repr(str(directory/'native-window.png'))+')\n'
        '  other=App.newDocument("UnrelatedDocument")\n'
        '  sphere=other.addObject("Part::Sphere","UnrelatedSphere")\n'
        '  sphere.Radius=30\n'
        '  other.recompute()\n'
        '  Gui.getDocument(other.Name).activeView().fitAll()\n'
        '  assert Gui.activeDocument()==Gui.getDocument(other.Name)\n'
        '  Gui.getDocument(worker.doc.Name).activeView().saveImage('+repr(str(directory/'owned-reference.png'))+',960,720,"White")\n'
        '  worker.dispatch("image",{"path":'+repr(str(directory/'owned-after-switch.png'))+'})\n'
        '  Gui.getDocument(other.Name).activeView().saveImage('+repr(str(directory/'unrelated.png'))+',960,720,"White")\n'
        '  owned=QImage('+repr(str(directory/'owned-after-switch.png'))+')\n'
        '  assert not owned.isNull()\n'
        '  assert owned==QImage('+repr(str(directory/'owned-reference.png'))+')\n'
        '  assert owned!=QImage('+repr(str(directory/'unrelated.png'))+')\n'
        '  App.closeDocument(other.Name)\n'
        '  atomic_json('+repr(str(directory/'capture-ownership.json'))+',{"unrelatedDocumentWasActive":True,"matchesExplicitOwnedView":True,"unrelatedImageDifferent":True})\n'
        '  worker.objects["b"].Length=11\n'
        '  worker.doc.recompute()\n'
        '  rejected=[]\n'
        '  for command,args in [("apply",{"document":declaration}),("geometry",{}),'
        '("save",{"path":'+repr(str(directory/'diverged.FCStd'))+'}),("image",{"path":'+repr(str(directory/'diverged.png'))+'})]:\n'
        '   try: worker.dispatch(command,args)\n'
        '   except SchemaxisError as error:\n'
        '    assert error.fault.code=="NATIVE_DIVERGENCE",str(error)\n'
        '    rejected.append(command)\n'
        '   else: raise AssertionError("Divergent command succeeded: "+command)\n'
        '  atomic_json('+repr(str(directory/'divergence.json'))+',{"rejected":rejected})\n'
        ' finally:\n'
        '  worker.timer.stop()\n'
        '  for document_name in list(App.listDocuments()): App.closeDocument(document_name)\n'
        '  QtCore.QTimer.singleShot(100,Gui.getMainWindow().close)\n'
        'QtCore.QTimer.singleShot(1000,probe)\n')
    with (directory/'divergence.log').open('wb') as log:
        process = subprocess.Popen([executable, str(macro)], stdout=log, stderr=subprocess.STDOUT, start_new_session=True)
        try:
            assert process.wait(timeout=60) == 0
        finally:
            try:
                os.killpg(process.pid, signal.SIGKILL)
            except ProcessLookupError:
                pass
            process.wait(timeout=5)
    result = json.loads((directory/'divergence.json').read_text())
    result['captureOwnership'] = json.loads((directory/'capture-ownership.json').read_text())
    assert (directory/'native-window.png').stat().st_size > 1000
    return result


def qualify(executable, command_executable, directory):
    directory = Path(directory).absolute()
    directory.mkdir(parents=True, exist_ok=True)
    box = document([{'id': 'block', 'filter': 'box'}], 'block')
    with LiveSession(executable, directory/'session') as session:
        initial = session.request('status')
        assert initial['mainThread'] and initial['revision'] == 0
        first = session.request('apply', document=box)
        geometry = session.request('geometry')
        assert len(geometry['objects'][0]['faces']) == 6 and abs(geometry['volume']-1000) < 1e-7
        assert {f['id'] for f in geometry['objects'][0]['faces']} == {'Face'+str(i) for i in range(1, 7)}
        for face in geometry['objects'][0]['faces']:
            assert face['triangles'] and all(0 <= i < len(face['vertices']) for t in face['triangles'] for i in t)
        changed = copy.deepcopy(box)
        changed['nodes'][0]['options'] = {'length': 20, 'origin': [3, 4, 5]}
        updated = session.request('apply', document=changed)
        assert updated['pid'] == initial['pid'] and updated['objects'] == first['objects']
        assert session.request('geometry')['bounds'] == [3, 23, 4, 14, 5, 15]
        selected = session.request('select', object='block', subelement='Face1')
        assert selected['selection'] == [{'object': 'block', 'subelements': ['Face1']}]
        try:
            session.request('select', object='block', subelement='Face999')
        except SchemaxisError as error:
            assert error.fault.code == 'INVALID_SELECTION'
        else:
            raise AssertionError('Invalid topology selection succeeded')
        # Failure occurs natively after changing an existing object and adding two.
        broken = copy.deepcopy(changed)
        broken['nodes'][0]['options']['length'] = 30
        broken['nodes'] += [{'id': 'distant', 'filter': 'box', 'options': {'origin': [100, 100, 100]}},
                            {'id': 'intersection', 'filter': 'common', 'inputs': {'base': 'block', 'tool': 'distant'}}]
        broken['output'] = 'intersection'
        try:
            session.request('apply', document=broken)
        except SchemaxisError as error:
            assert error.fault.code in ('INVALID_GEOMETRY', 'NATIVE_ERROR')
        else:
            raise AssertionError('Empty common unexpectedly succeeded')
        rollback = session.request('status')
        assert rollback['revision'] == updated['revision'] and rollback['objects'] == updated['objects']
        assert rollback['selection'] == selected['selection']
        assert session.request('geometry')['bounds'] == [3, 23, 4, 14, 5, 15]
        # Roll back a full replacement which has already deleted the old object.
        replacement = document([
            {'id': 'left', 'filter': 'box'},
            {'id': 'right', 'filter': 'box', 'options': {'origin': [100, 0, 0]}},
            {'id': 'empty', 'filter': 'common', 'inputs': {'base': 'left', 'tool': 'right'}}], 'empty')
        try:
            session.request('apply', document=replacement)
        except SchemaxisError as error:
            assert error.fault.code == 'INVALID_GEOMETRY', error
        else:
            raise AssertionError('Invalid replacement succeeded')
        restored = session.request('status')
        assert restored['objects'] == updated['objects'] and restored['revision'] == updated['revision']
        assert restored['selection'] == selected['selection']
        assert session.request('geometry')['bounds'] == [3, 23, 4, 14, 5, 15]
        polygon = document([{'id': 'profile', 'filter': 'polygon', 'options': {
            'points': [[0, 0], [10, 0], [10, 10], [0, 10]], 'origin': [2, 3, 4]}}], 'profile')
        preview = session.request('apply', document=polygon)
        wire = session.request('geometry')
        assert not wire['objects'][0]['faces'] and len(wire['objects'][0]['edges']) == 4
        assert wire['bounds'] == [2, 12, 3, 13, 4, 4]
        polygon['nodes'][0]['options']['points'] = [[0, 0], [20, 0], [20, 10], [0, 10]]
        second_preview = session.request('apply', document=polygon)
        assert second_preview['objects'] == preview['objects']
        polygon['nodes'].append({'id': 'solid', 'filter': 'extrude', 'inputs': {'profile': 'profile'}, 'options': {'length': 5}})
        polygon['output'] = 'solid'
        session.request('apply', document=polygon)
        extruded = session.request('geometry')
        assert abs(extruded['volume']-1000) < 1e-7 and len(extruded['objects'][0]['faces']) == 6
        session.request('select', object='solid', subelement='Edge1')
        session.request('image', path=str(directory/'view.png'))
        assert (directory/'view.png').read_bytes().startswith(b'\x89PNG\r\n\x1a\n')
        session.request('save', path=str(directory/'model.FCStd'))
        final = session.request('status')
        # New shared Sketcher declarations must also support preview and reuse.
        from schemaxis.adaptors.freecad.adaptor import DECLARATIONS
        profile_evidence = {}
        for kind, options, changed_options in [('rectangle', {'width': 8, 'height': 6}, {'width': 12, 'height': 6}),
                                               ('circle', {'radius': 4}, {'radius': 6})]:
            if kind not in DECLARATIONS:
                continue
            profile_doc = document([{'id': kind, 'filter': kind, 'options': options}], kind)
            before = session.request('apply', document=profile_doc)
            profile_doc['nodes'][0]['options'] = changed_options
            after = session.request('apply', document=profile_doc)
            assert before['objects'] == after['objects']
            assert after['pid'] == initial['pid']
            assert session.request('geometry')['objects'][0]['edges']
            profile_evidence[kind] = {'objectReused': True, 'pid': after['pid']}
        final = session.request('status')
    assert session.process.poll() is not None
    session.close()  # Idempotent.
    # Independent command-line interpreter verifies persisted native geometry.
    script = directory/'reopen.py'
    script.write_text('import FreeCAD as App, json\n'
        'd=App.openDocument('+repr(str(directory/'model.FCStd'))+')\n'
        'd.recompute()\n'
        'o=next(o for o in d.Objects if o.Label=="solid")\n'
        'assert o.Shape.isValid() and len(o.Shape.Solids)==1\n'
        'assert abs(o.Shape.Volume-1000)<1e-7\n'
        'with open('+repr(str(directory/'reopened.json'))+',"w") as f:\n'
        ' json.dump({"volume":o.Shape.Volume,"objects":len(d.Objects)},f)\n'
        'App.closeDocument(d.Name)\n')
    with (directory/'freecadcmd.log').open('wb') as log:
        subprocess.run([command_executable, str(script)], stdout=log, stderr=subprocess.STDOUT, check=True, timeout=60)
    reopened = json.loads((directory/'reopened.json').read_text())
    assert reopened['objects'] == 2
    divergence = divergence_probe(executable, directory)
    owner_exit = owner_exit_probe(executable, directory)
    cancelled = cancellation_probe(executable, directory)
    receipt = {'qualified': True, 'runtime': initial['runtime'], 'pid': initial['pid'],
               'pidEvidence': {name: state['pid'] for name, state in [('initial', initial), ('firstApply', first),
                    ('updated', updated), ('rollback', rollback), ('replacementRollback', restored), ('final', final)]},
               'finalRevision': final['revision'], 'rollbackVerified': True,
               'profiles': profile_evidence, 'divergence': divergence,
               'ownerExit': owner_exit, 'cancellation': cancelled,
               'mainThread': initial['mainThread'], 'reopened': reopened,
               'directory': str(directory), 'limits': 'Serial local GUI; box/common/polygon/extrude plus available rectangle/circle profiles.'}
    (directory/'qualification.json').write_text(json.dumps(receipt, indent=2)+'\n')
    return receipt


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--executable', required=True)
    parser.add_argument('--command-executable', required=True)
    parser.add_argument('--directory')
    args = parser.parse_args()
    directory = args.directory or tempfile.mkdtemp(prefix='schemaxis-freecad-live-')
    print('Qualification artifacts: '+directory, flush=True)
    print(json.dumps(qualify(args.executable, args.command_executable, directory), indent=2))
