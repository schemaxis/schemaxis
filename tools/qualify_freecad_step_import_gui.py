#!/usr/bin/env python3
"""Actual FreeCAD GUI check of an imported, refined part's editable placement, on copies only.

PYTHONPATH=src python3 tools/qualify_freecad_step_import_gui.py --run RUN --directory OUT \\
    --gui-executable FREECAD_GUI --xvfb XVFB --executable FREECADCMD

RUN is a verified schemaxis.freecad/1 run whose output is an importSTEP node with
refine. One GUI process runs on a private Xvfb display with private settings. It
opens a copy of the published FCStd, records the first-open state and a
screenshot, checks that the Part::Refine output is linked to the imported source
and keeps identity placement, then edits the source Placement through the
document property (as the property editor does) and recomputes. It checks that
the refined output follows, saves, closes, reopens and checks again, with
screenshots at each step. A separate command-line process then reopens the
GUI-saved file fresh. No human pointer interaction, camera or style contract is
claimed; the edit is not synchronised back into authored JSON.
"""
import argparse
import hashlib
import json
import os
from pathlib import Path
import select
import signal
import subprocess
import time

from schemaxis.adaptors import registry
from schemaxis.artifacts import atomic_json

MACRO = r'''
import json, os, traceback
from pathlib import Path
import FreeCAD as App
import FreeCADGui as Gui
from PySide import QtCore, QtWidgets
root = Path(os.environ['QUALIFY_GUI_DIR'])
request = json.loads((root/'request.json').read_text())
report = {'pid': os.getpid(), 'version': App.Version(), 'ok': False}
doc = None
def save(): (root/'gui.json').write_text(json.dumps(report, indent=2, default=str)+'\n')
def facts(name):
    o = doc.getObject(name); b = o.Shape.BoundBox
    return {'type': o.TypeId, 'placement': [float(v) for v in o.Placement.toMatrix().A], 'volume': o.Shape.Volume,
            'bounds': [b.XMin, b.XMax, b.YMin, b.YMax, b.ZMin, b.ZMax], 'faces': len(o.Shape.Faces),
            'visible': bool(o.ViewObject.Visibility) if o.ViewObject is not None else None,
            'source': o.Source.Name if hasattr(o, 'Source') and o.Source is not None else None}
def state(): return {'source': facts(request['source']), 'refined': facts(request['refined'])}
def shot(name):
    """Fraction of sampled pixels in the central 60 percent of the 3D view that differ from its background."""
    Gui.updateGui(); Gui.getMainWindow().grab().save(str(root/(name+'.png')))
    area = Gui.getMainWindow().findChild(QtWidgets.QMdiArea)
    if area is None or area.activeSubWindow() is None: return None
    image = area.activeSubWindow().widget().grab().toImage()
    w, h = image.width(), image.height()
    background = image.pixelColor(w//2, h-5)
    samples = [image.pixelColor(x, y) for x in range(int(0.2*w), int(0.8*w), max(1, w//60)) for y in range(int(0.2*h), int(0.8*h), max(1, h//60))]
    differ = [c for c in samples if abs(c.red()-background.red())+abs(c.green()-background.green())+abs(c.blue()-background.blue()) > 40]
    return len(differ)/max(1, len(samples))
def view():
    Gui.getMainWindow().resize(1280, 900)
    Gui.activeDocument().activeView().viewAxonometric(); Gui.activeDocument().activeView().fitAll()
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
@guarded
def first_open():
    global doc
    Gui.activateWorkbench('PartWorkbench')
    doc = App.openDocument(str(root/'first-open.FCStd'))
    report['documents'] = sorted(App.listDocuments()); report['firstOpen'] = state()
    view(); QtCore.QTimer.singleShot(1200, guarded(edit))
@guarded
def edit():
    report['firstOpenColours'] = shot('1-first-open')
    source = doc.getObject(request['source'])
    moved = App.Placement(App.Vector(*request['translation']), App.Rotation(App.Vector(0, 0, 1), request['degrees'])).multiply(source.Placement)
    source.Placement = moved
    doc.recompute()
    report['afterEdit'] = state(); report['expectedPlacement'] = [float(v) for v in moved.toMatrix().A]
    view(); QtCore.QTimer.singleShot(1200, guarded(saved))
@guarded
def saved():
    global doc
    report['afterEditColours'] = shot('2-after-placement-edit')
    doc.saveAs(str(root/'gui-edited.FCStd')); App.closeDocument(doc.Name)
    doc = App.openDocument(str(root/'gui-edited.FCStd'))
    report['reopenedBeforeRecompute'] = state()
    doc.recompute(); report['reopenedAfterRecompute'] = state()
    view(); QtCore.QTimer.singleShot(1200, guarded(done))
@guarded
def done():
    report['reopenedColours'] = shot('3-reopened')
    report['ok'] = True; finish()
QtCore.QTimer.singleShot(500, guarded(first_open))
'''

FRESH = r'''
import json
import FreeCAD as App
root = %r
request = json.load(open(root+'/request.json'))
doc = App.openDocument(root+'/gui-edited.FCStd')
def facts(name):
    o = doc.getObject(name); b = o.Shape.BoundBox
    return {'placement': [float(v) for v in o.Placement.toMatrix().A], 'volume': o.Shape.Volume,
            'bounds': [b.XMin, b.XMax, b.YMin, b.YMax, b.ZMin, b.ZMax],
            'source': o.Source.Name if hasattr(o, 'Source') and o.Source is not None else None}
out = {'before': {'source': facts(request['source']), 'refined': facts(request['refined'])}}
doc.recompute()
out['after'] = {'source': facts(request['source']), 'refined': facts(request['refined'])}
json.dump(out, open(root+'/fresh-reopen.json', 'w'), indent=1)
'''


def alive(pid):
    try:
        os.kill(pid, 0)
        return True
    except ProcessLookupError:
        return False


def launch(directory, gui_executable, xvfb, timeout):
    settings = directory/'settings'
    settings.mkdir()
    entry = {}
    read, write = os.pipe()
    with (directory/'xvfb.log').open('wb') as log:
        server = subprocess.Popen([xvfb, '-displayfd', str(write), '-screen', '0', '1280x960x24', '-nolisten', 'tcp'],
                                  pass_fds=(write,), stdout=log, stderr=log, start_new_session=True)
    os.close(write)
    entry['xvfbPid'] = server.pid
    try:
        if not select.select([read], [], [], 10)[0]:
            raise RuntimeError('Xvfb did not provide a display within ten seconds')
        display = ':'+os.read(read, 100).decode().strip()
        environment = dict(os.environ, DISPLAY=display, OMP_NUM_THREADS='1', LIBGL_ALWAYS_SOFTWARE='1',
                           PYTHONDONTWRITEBYTECODE='1', QUALIFY_GUI_DIR=str(directory))
        for key, name in (('HOME', 'home'), ('FREECAD_USER_HOME', 'freecad-home'), ('FREECAD_USER_DATA', 'data'),
                          ('FREECAD_USER_TEMP', 'temp'), ('XDG_CONFIG_HOME', 'config'), ('XDG_DATA_HOME', 'xdg-data'),
                          ('XDG_CACHE_HOME', 'cache')):
            (settings/name).mkdir()
            environment[key] = str(settings/name)
        for key in ('PYTHONHOME', 'PYTHONPATH', 'QT_PLUGIN_PATH', 'QT_QPA_PLATFORM_PLUGIN_PATH', 'LD_PRELOAD'):
            environment.pop(key, None)
        command = [gui_executable, '--user-cfg', str(settings/'user.cfg'), '--system-cfg', str(settings/'system.cfg'),
                   str(directory/'qualify.FCMacro')]
        entry['command'] = command
        with (directory/'gui.log').open('wb') as log:
            process = subprocess.Popen(command, env=environment, cwd=directory, stdout=log, stderr=log,
                                       stdin=subprocess.DEVNULL, start_new_session=True)
            entry.update(display=display, guiPid=process.pid, started=time.time())
            atomic_json(directory/'process-gui.json', {**entry, 'status': 'running'})
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
    result = json.loads((directory/'gui.json').read_text()) if (directory/'gui.json').exists() else {}
    entry.update(nativePid=result.get('pid'), guiAliveAfter=alive(entry['guiPid']), xvfbAliveAfter=alive(server.pid),
                 nativeAliveAfter=alive(result['pid']) if result.get('pid') else None, ok=result.get('ok') is True,
                 seconds=time.time()-entry['started'])
    atomic_json(directory/'process-gui.json', entry)
    if not entry['ok'] or entry['guiAliveAfter'] or entry['xvfbAliveAfter'] or entry['nativeAliveAfter']:
        raise RuntimeError('GUI stage failed or left a process: '+json.dumps(entry)+' '+str(result.get('error')))
    return result, entry


def close(a, b, tolerance=1e-6):
    return len(a) == len(b) and all(abs(x-y) <= tolerance*(1+abs(y)) for x, y in zip(a, b))


IDENTITY = [1, 0, 0, 0, 0, 1, 0, 0, 0, 0, 1, 0, 0, 0, 0, 1]


def qualify(run, directory, gui_executable, xvfb, executable, *, translation=(-200.0, 10.0, 5.0), degrees=180.0, timeout=120):
    run, directory = Path(run).absolute(), Path(directory).absolute()
    directory.mkdir(parents=True, exist_ok=False)
    verified = registry.verify(run)
    prepared = json.loads((run/'plan.json').read_text())
    index, node = next((i, n) for i, n in enumerate(prepared['nodes']) if n['filter'] == 'importSTEP' and n['options']['refine'])
    source = run/'model.FCStd'
    original = hashlib.sha256(source.read_bytes()).hexdigest()
    (directory/'first-open.FCStd').write_bytes(source.read_bytes())
    from schemaxis.adaptors.freecad.operations import output_names
    request = {'source': 'N'+str(index), 'refined': 'N'+str(index)+'Refined', 'output': output_names(prepared)[prepared['output']],
               'translation': list(translation), 'degrees': degrees}
    atomic_json(directory/'request.json', request)
    (directory/'qualify.FCMacro').write_text(MACRO)
    report = {'run': str(run), 'runVerified': verified['verified'], 'sourceSha256': original}
    gui, report['guiProcess'] = launch(directory, gui_executable, xvfb, timeout)
    from schemaxis.core.runners import Interpreter
    from schemaxis.dispatch import SubprocessRunner
    fresh = SubprocessRunner(Interpreter('freecad', executable), directory, timeout=90)(FRESH % str(directory))
    atomic_json(directory/'fresh-submission.json', fresh.to_dict())
    reopened = json.loads((directory/'fresh-reopen.json').read_text())
    first, edited = gui['firstOpen'], gui['afterEdit']
    checks = {
        'onlyDocument': gui['documents'] == ['first_open'],
        'refineLinkedToSource': first['refined']['type'] == 'Part::Refine' and first['refined']['source'] == request['source'],
        'refineIdentityPlacement': close(first['refined']['placement'], IDENTITY, 1e-12),
        'refineFollowsSourceAtOpen': close(first['refined']['bounds'], first['source']['bounds']),
        'firstOpenVisibleOutputOnly': all(first[key]['visible'] is (request[key] == request['output']) for key in ('source', 'refined')),
        'firstOpenRendered': (gui['firstOpenColours'] or 0) > 0.02,
        'placementEditApplied': close(edited['source']['placement'], gui['expectedPlacement'], 1e-9),
        'placementEditMovedPart': not close(edited['source']['bounds'], first['source']['bounds']),
        'refineFollowedEdit': close(edited['refined']['bounds'], edited['source']['bounds'])
                              and close([edited['refined']['volume']], [first['refined']['volume']]),
        'refineStillIdentityPlacement': close(edited['refined']['placement'], IDENTITY, 1e-12),
        'editRendered': (gui['afterEditColours'] or 0) > 0.02,
        'guiReopenPersistedBeforeRecompute': close(gui['reopenedBeforeRecompute']['source']['placement'], gui['expectedPlacement'], 1e-9)
                                              and close(gui['reopenedBeforeRecompute']['refined']['bounds'], edited['refined']['bounds']),
        'guiReopenStableAfterRecompute': close(gui['reopenedAfterRecompute']['refined']['bounds'], edited['refined']['bounds']),
        'reopenRendered': (gui['reopenedColours'] or 0) > 0.02,
        'freshProcessReopen': close(reopened['before']['source']['placement'], gui['expectedPlacement'], 1e-9)
                              and close(reopened['after']['refined']['bounds'], edited['refined']['bounds'])
                              and reopened['after']['refined']['source'] == request['source'],
    }
    report.update(checks=checks, gui=gui, freshReopen=reopened,
                  screenshots=sorted(p.name for p in directory.glob('*.png')),
                  sourcePreserved=hashlib.sha256(source.read_bytes()).hexdigest() == original)
    report['verified'] = all(checks.values()) and report['sourcePreserved']
    atomic_json(directory/'report.json', report)
    return report


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument('--run', required=True, help='verified run with an importSTEP refine output')
    parser.add_argument('--directory', required=True, help='fresh evidence directory')
    parser.add_argument('--gui-executable', required=True, help='absolute FreeCAD GUI launcher')
    parser.add_argument('--xvfb', required=True, help='absolute Xvfb executable')
    parser.add_argument('--executable', required=True, help='absolute FreeCAD command-line launcher for the fresh reopen')
    arguments = parser.parse_args()
    result = qualify(arguments.run, arguments.directory, arguments.gui_executable, arguments.xvfb, arguments.executable)
    print(json.dumps({'verified': result['verified'], 'checks': result['checks']}, indent=2))
