#!/usr/bin/env python3
# Copyright (C) 2026 David L F Gaden
"""Actual FreeCAD GUI qualification of a verified sourced assembly, on copies only.

PYTHONPATH=src python3 tools/qualify_freecad_assembly_sources_gui.py --assembly RUN --directory OUT \\
    --gui-executable FREECAD_GUI --xvfb XVFB

Two GUI processes run serially on a private Xvfb display with private settings.
The first opens a copy of the published FCStd and checks first-open visibility,
restored joint view providers and a rendered model. It then opens the native
joint task editor through its double-click handler, cancels it, edits an embedded
source sketch, applies a native edit (shared part thickness and the authored
parent offset), solves and saves another copy. The second process reopens that
copy, checks the persisted state before recompute, opens the editor again and uses
its simple Offset field, which FreeCAD binds to the child connector (Offset2).
The host judges every pose against the independent analytic oracle. No camera,
style or reverse-synchronization claim is made.
"""
import argparse
import copy
import hashlib
import json
import os
from pathlib import Path
import select
import signal
import subprocess
import time

from schemaxis.adaptors import registry
from schemaxis.adaptors.freecad import assembly_sources as sources
from schemaxis.adaptors.freecad.assembly_sources_saved import Saved
from schemaxis.adaptors.freecad.parameters import evaluate
from schemaxis.artifacts import atomic_json

MACRO = r'''
import json, os, traceback
from pathlib import Path
import FreeCAD as App
import FreeCADGui as Gui
from PySide import QtCore, QtWidgets
root = Path(os.environ['QUALIFY_GUI_DIR']); mode = os.environ['QUALIFY_GUI_MODE']
request = json.loads((root/'request.json').read_text())
report = {'mode': mode, 'pid': os.getpid(), 'version': App.Version(), 'ok': False}
doc = None
def save(): (root/('gui-'+mode+'.json')).write_text(json.dumps(report, indent=2, default=str)+'\n')
def matrices(): return {k: [float(v) for v in doc.getObject(n).Placement.toMatrix().A] for k, n in request['components'].items()}
def visibility(): return {o.Name: bool(o.ViewObject.Visibility) for o in doc.Objects if o.ViewObject is not None}
def providers():
    out = {}
    for name in request['providers']:
        v = doc.getObject(name).ViewObject; proxy = getattr(v, 'Proxy', None)
        out[name] = {'class': type(proxy).__name__ if proxy is not None else None, 'attached': hasattr(proxy, 'app_obj')}
    return out
def shot(name):
    Gui.updateGui(); Gui.getMainWindow().grab().save(str(root/(mode+'-'+name+'.png')))
    area = Gui.getMainWindow().findChild(QtWidgets.QMdiArea)
    if area is None or area.activeSubWindow() is None: return None
    image = area.activeSubWindow().widget().grab().toImage()
    return len({image.pixelColor(x, y).rgba() for x in range(0, image.width(), max(1, image.width()//30)) for y in range(0, image.height(), max(1, image.height()//30))})
def finish():
    save()
    for n in list(App.listDocuments()): App.closeDocument(n)
    QtCore.QTimer.singleShot(200, QtWidgets.QApplication.instance().quit)
def guarded(fn):
    def inner():
        try: fn()
        except Exception:
            report['error'] = traceback.format_exc(); finish()
    return inner
def open_task():
    joint = doc.getObject(request['joint'])
    report[mode+'BeforeTask'] = matrices()
    report[mode+'DoubleClicked'] = joint.ViewObject.Proxy.doubleClicked(joint.ViewObject)
def inspect_task():
    import JointObject, UtilsAssembly
    panel = JointObject.activeTask
    record = {'activeDialog': bool(Gui.Control.activeDialog()),
              'activeAssembly': UtilsAssembly.activeAssembly().Name if UtilsAssembly.activeAssembly() else None,
              'editingJoint': panel.joint.Name if panel is not None and getattr(panel, 'joint', None) else None,
              'jointType': panel.jForm.jointType.currentText() if panel else None,
              'listedReferences': sorted(item.text() for widget in panel.form.findChildren(QtWidgets.QListWidget)
                                          for item in (widget.item(i) for i in range(widget.count()))) if panel else [],
              'viewportColours': shot('joint-editor')}
    return panel, record
@guarded
def first_open():
    global doc
    Gui.activateWorkbench('AssemblyWorkbench')
    doc = App.openDocument(str(root/'first-open.FCStd'))
    report['documents'] = sorted(App.listDocuments())
    report['visibilityAfterOpen'] = visibility(); report['providersAfterOpen'] = providers(); report['posesAfterOpen'] = matrices()
    Gui.getMainWindow().resize(1280, 900)
    Gui.activeDocument().activeView().viewAxonometric(); Gui.activeDocument().activeView().fitAll()
    QtCore.QTimer.singleShot(1200, guarded(first_model))
@guarded
def first_model():
    report['modelColours'] = shot('model')
    open_task(); QtCore.QTimer.singleShot(1500, guarded(first_task))
@guarded
def first_task():
    panel, record = inspect_task()
    Gui.Control.activeTaskDialog().reject(); Gui.updateGui()
    record['dialogAfterCancel'] = bool(Gui.Control.activeDialog()); record['posesAfterCancel'] = matrices()
    if Gui.activeDocument().getInEdit() is not None: Gui.activeDocument().resetEdit()
    report['firstTask'] = record
    report['sketchSetEdit'] = Gui.activeDocument().setEdit(request['sketch'])
    QtCore.QTimer.singleShot(1200, guarded(first_sketch))
@guarded
def first_sketch():
    report['inSketchEdit'] = Gui.activeDocument().getInEdit() is not None
    report['sketchColours'] = shot('sketch-edit')
    Gui.activeDocument().resetEdit()
    sketch = doc.getObject(request['sketch'])
    report['sketchFullyConstrained'] = bool(sketch.FullyConstrained) and sketch.solve() == 0
    setattr(doc.getObject(request['varset']), 'dim_'+request['parameter'], request['value'])
    joint = doc.getObject(request['joint'])
    p = joint.Offset1; p.Base = App.Vector(*request['offset']); joint.Offset1 = p
    doc.recompute()
    report['solveAfterEdit'] = doc.getObject('Assembly').solve()
    doc.recompute()
    report['posesAfterEdit'] = matrices(); report['visibilityBeforeSave'] = visibility()
    report['editedColours'] = shot('edited-model')
    doc.saveAs(str(root/'gui-edited.FCStd'))
    report['ok'] = True; finish()
@guarded
def second_open():
    global doc
    Gui.activateWorkbench('AssemblyWorkbench')
    doc = App.openDocument(str(root/'gui-edited.FCStd'))
    report['documents'] = sorted(App.listDocuments())
    report['visibilityAfterOpen'] = visibility(); report['providersAfterOpen'] = providers(); report['posesAfterOpen'] = matrices()
    Gui.getMainWindow().resize(1280, 900)
    Gui.activeDocument().activeView().viewAxonometric(); Gui.activeDocument().activeView().fitAll()
    QtCore.QTimer.singleShot(1200, guarded(second_model))
@guarded
def second_model():
    report['modelColours'] = shot('model')
    open_task(); QtCore.QTimer.singleShot(1500, guarded(second_task))
@guarded
def second_task():
    panel, record = inspect_task()
    record['offsetField'] = panel.jForm.offsetSpinbox.property('rawValue')
    panel.jForm.offsetSpinbox.setProperty('rawValue', request['widgetOffset']); Gui.updateGui()
    joint = doc.getObject(request['joint'])
    record['offset2AfterField'] = [float(v) for v in joint.Offset2.Base]
    record['accepted'] = panel.accept(); Gui.Control.closeDialog(); Gui.updateGui()
    if Gui.activeDocument().getInEdit() is not None: Gui.activeDocument().resetEdit()
    doc.recompute(); record['solve'] = doc.getObject('Assembly').solve()
    record['offset1'] = [float(v) for v in joint.Offset1.Base]; record['offset2'] = [float(v) for v in joint.Offset2.Base]
    record['poses'] = matrices()
    report['secondTask'] = record; report['ok'] = True; finish()
QtCore.QTimer.singleShot(1000, first_open if mode == 'first' else second_open)
'''


def alive(pid):
    try:
        os.kill(pid, 0)
        return True
    except ProcessLookupError:
        return False


def launch(directory, mode, gui_executable, xvfb, timeout):
    settings = directory/('settings-'+mode)
    settings.mkdir()
    entry = {'mode': mode}
    read, write = os.pipe()
    with (directory/('xvfb-'+mode+'.log')).open('wb') as log:
        server = subprocess.Popen([xvfb, '-displayfd', str(write), '-screen', '0', '1280x960x24', '-nolisten', 'tcp'],
                                  pass_fds=(write,), stdout=log, stderr=log, start_new_session=True)
    os.close(write)
    entry['xvfbPid'] = server.pid
    try:
        if not select.select([read], [], [], 10)[0]:
            raise RuntimeError('Xvfb did not provide a display within ten seconds')
        display = ':'+os.read(read, 100).decode().strip()
        environment = dict(os.environ, DISPLAY=display, OMP_NUM_THREADS='1', LIBGL_ALWAYS_SOFTWARE='1',
                           PYTHONDONTWRITEBYTECODE='1', QUALIFY_GUI_DIR=str(directory), QUALIFY_GUI_MODE=mode)
        for key, name in (('FREECAD_USER_HOME', 'home'), ('FREECAD_USER_DATA', 'data'), ('FREECAD_USER_TEMP', 'temp'),
                          ('XDG_CONFIG_HOME', 'config'), ('XDG_DATA_HOME', 'xdg-data'), ('XDG_CACHE_HOME', 'cache')):
            (settings/name).mkdir()
            environment[key] = str(settings/name)
        for key in ('PYTHONHOME', 'PYTHONPATH', 'QT_PLUGIN_PATH', 'QT_QPA_PLATFORM_PLUGIN_PATH', 'LD_PRELOAD'):
            environment.pop(key, None)
        command = [gui_executable, '--user-cfg', str(settings/'user.cfg'), '--system-cfg', str(settings/'system.cfg'),
                   str(directory/'qualify.FCMacro')]
        with (directory/('gui-'+mode+'.log')).open('wb') as log:
            process = subprocess.Popen(command, env=environment, cwd=directory, stdout=log, stderr=log,
                                       stdin=subprocess.DEVNULL, start_new_session=True)
            entry.update(display=display, guiPid=process.pid, started=time.time())
            atomic_json(directory/('process-'+mode+'.json'), {**entry, 'status': 'running'})
            try:
                entry['exitCode'] = process.wait(timeout=timeout)
                entry['status'] = 'exited'
            except subprocess.TimeoutExpired:
                entry['status'] = 'timed-out'
                os.killpg(process.pid, signal.SIGTERM)
                try:
                    process.wait(timeout=5)
                except subprocess.TimeoutExpired:
                    os.killpg(process.pid, signal.SIGKILL)
                    process.wait()
    finally:
        os.close(read)
        server.terminate()
        try:
            server.wait(timeout=5)
        except subprocess.TimeoutExpired:
            server.kill()
            server.wait()
    result = json.loads((directory/('gui-'+mode+'.json')).read_text()) if (directory/('gui-'+mode+'.json')).exists() else {}
    entry.update(nativePid=result.get('pid'), guiAliveAfter=alive(entry['guiPid']), xvfbAliveAfter=alive(server.pid),
                 nativeAliveAfter=alive(result['pid']) if result.get('pid') else None, ok=result.get('ok') is True,
                 seconds=time.time()-entry['started'])
    atomic_json(directory/('process-'+mode+'.json'), entry)
    if not entry['ok'] or entry['guiAliveAfter'] or entry['xvfbAliveAfter'] or entry['nativeAliveAfter']:
        raise RuntimeError('GUI stage failed or left a process: '+json.dumps(entry)+' '+str(result.get('error')))
    return result, entry


def poses_with_child_offset(prepared, joint_id, offset2):
    """worldChild = worldParent * parentMount * Offset1 * inverse(childMount * Offset2)."""
    components = {c['id']: c for c in prepared['components']}
    mounts = {p['id']: {m['id']: sources.mount_frame(m) for m in p['mounts']} for p in prepared['parts']}
    root = components[prepared['grounded']]
    world = {root['id']: sources.frame(root['position'], sources.rot_z(root['rotation']))}
    for joint in prepared['joints']:
        parent, child = joint['parent'], joint['child']
        child_frame = mounts[components[child['component']]['part']][child['mount']]
        if joint['id'] == joint_id:
            child_frame = sources.mul(child_frame, sources.frame(offset2))
        world[child['component']] = sources.mul(sources.mul(sources.mul(world[parent['component']],
            mounts[components[parent['component']]['part']][parent['mount']]),
            sources.frame(joint['offset'], sources.rot_z(joint['clocking']))), sources.inverse(child_frame))
    return {k: sources.flat(v) for k, v in world.items()}


def edited(prepared, part_id, parameter, value, joint_id, offset):
    result = copy.deepcopy(prepared)
    target = next(p for p in result['parts'] if p['id'] == part_id)
    target['source']['parameters'][parameter]['value'] = value
    values = {k: v['value'] for k, v in target['source']['parameters'].items()}
    for mount in target['mounts']:
        for coordinate in mount['position']:
            if 'terms' in coordinate:
                coordinate['value'] = evaluate(coordinate, values)
        mount['value'] = [c['value'] if 'terms' in c else c['literal'] for c in mount['position']]
    next(j for j in result['joints'] if j['id'] == joint_id)['offset'] = list(offset)
    result['expected'] = sources.analytic(result)
    return result


def same(poses, wanted):
    return all(sources.close(poses[k], wanted[k]) for k in wanted)


def qualify(assembly, directory, gui_executable, xvfb, *, part='plate', parameter='thickness', value=9.0,
            joint='spacerToCover', offset=(0.0, 0.0, 3.0), widget=1.0, timeout=120):
    assembly, directory = Path(assembly).absolute(), Path(directory).absolute()
    directory.mkdir(parents=True, exist_ok=False)
    verified = registry.verify(assembly)
    prepared = json.loads((assembly/'plan.json').read_text())
    renames = json.loads((assembly/'built.json').read_text())['renames']
    source = assembly/'model.FCStd'
    original = hashlib.sha256(source.read_bytes()).hexdigest()
    (directory/'first-open.FCStd').write_bytes(source.read_bytes())
    objects = list(Saved(source).xml.types)
    expected_visibility = sources.visibility(prepared, objects, renames)
    proxies = sources.proxies(prepared)
    target = next(p for p in prepared['parts'] if p['id'] == part)
    request = {'components': prepared['native']['components'], 'providers': sorted(proxies),
               'joint': prepared['native']['joints'][joint], 'sketch': renames[part]['N1'],
               'varset': renames[part]['SchemaxisParameters'], 'parameter': parameter, 'value': value,
               'offset': list(offset), 'widgetOffset': widget}
    atomic_json(directory/'request.json', request)
    (directory/'qualify.FCMacro').write_text(MACRO)
    report = {'assembly': str(assembly), 'assemblyVerified': verified['verified'], 'sourceSha256': original, 'checks': {}}
    first, report['firstProcess'] = launch(directory, 'first', gui_executable, xvfb, timeout)
    joint_spec = next(j for j in prepared['joints'] if j['id'] == joint)
    labels = sorted({target['id']+'.'+joint_spec['child']['mount'],
                     next(c['part'] for c in prepared['components'] if c['id'] == joint_spec['parent']['component'])+'.'+joint_spec['parent']['mount']})
    initial = {k: v['matrix'] for k, v in prepared['expected']['components'].items()}
    after_edit = edited(prepared, part, parameter, value, joint, offset)
    after = {k: v['matrix'] for k, v in after_edit['expected']['components'].items()}
    task = first['firstTask']
    checks = {
        'onlyDocument': first['documents'] == ['first_open'],
        'firstOpenVisibilityExact': first['visibilityAfterOpen'] == expected_visibility,
        'jointProvidersRestored': first['providersAfterOpen'] == {n: {'class': c, 'attached': True} for n, c in proxies.items()},
        'persistedPosesBeforeRecompute': same(first['posesAfterOpen'], initial),
        'modelRendered': (first['modelColours'] or 0) > 3,
        'jointEditorOpened': task['activeDialog'] and task['activeAssembly'] == 'Assembly' and task['editingJoint'] == request['joint']
                             and task['jointType'] == 'Fixed',
        'jointEditorListsMountLabels': all(label in task['listedReferences'] for label in labels),
        'cancelKeepsPoses': not task['dialogAfterCancel'] and same(task['posesAfterCancel'], initial),
        'embeddedSketchEditable': first['sketchSetEdit'] and first['inSketchEdit'] and first['sketchFullyConstrained'],
        'nativeEditSolved': first['solveAfterEdit'] == 0 and same(first['posesAfterEdit'], after),
        'nativeEditDiscriminated': not same(first['posesAfterEdit'], initial),
    }
    second, report['secondProcess'] = launch(directory, 'second', gui_executable, xvfb, timeout)
    task = second['secondTask']
    child_side = poses_with_child_offset(after_edit, joint, (0, 0, widget))
    checks.update({
        'reopenVisibilityPersisted': {k: v for k, v in second['visibilityAfterOpen'].items() if k in expected_visibility} == expected_visibility,
        'reopenProvidersRestored': second['providersAfterOpen'] == {n: {'class': c, 'attached': True} for n, c in proxies.items()},
        'reopenPersistedEditBeforeRecompute': same(second['posesAfterOpen'], after),
        'reopenRendered': (second['modelColours'] or 0) > 3,
        'reopenJointEditorOpened': task['activeDialog'] and task['jointType'] == 'Fixed' and task['editingJoint'] == request['joint'],
        'simpleOffsetFieldShowsChildSide': task['offsetField'] == 0,
        'simpleOffsetFieldEditsOffset2': sources.close(task['offset2'], [0, 0, widget]) and sources.close(task['offset1'], list(offset)),
        'childSideConventionSolved': task['solve'] == 0 and same(task['poses'], child_side),
        'notParentSideConvention': not same(task['poses'], after),
    })
    report['checks'] = checks
    report['sourcePreserved'] = hashlib.sha256(source.read_bytes()).hexdigest() == original
    report['verified'] = all(checks.values()) and report['sourcePreserved']
    atomic_json(directory/'report.json', report)
    return report


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument('--assembly', required=True, help='verified sourced assembly run directory')
    parser.add_argument('--directory', required=True, help='fresh evidence directory')
    parser.add_argument('--gui-executable', required=True, help='absolute FreeCAD GUI launcher')
    parser.add_argument('--xvfb', required=True, help='absolute Xvfb executable')
    arguments = parser.parse_args()
    result = qualify(arguments.assembly, arguments.directory, arguments.gui_executable, arguments.xvfb)
    print(json.dumps({'verified': result['verified'], 'checks': result['checks']}, indent=2))
