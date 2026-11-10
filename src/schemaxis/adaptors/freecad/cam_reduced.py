"""Finite installed reduced-profile transport; safe to import on the host."""
import importlib
from pathlib import Path
import sys

MODULE='schemaxis_freecad_reduced_tool_v1'
FILENAME=MODULE+'.py'
LAUNCHER_NAME='open-cam.FCMacro'
LAUNCHER=('import sys\nfrom pathlib import Path\n'
          '_root=Path(__file__).resolve().parent\n'
          'sys.path.insert(0,str(_root))\n'
          'import '+MODULE+'\n'
          'import FreeCAD as App, FreeCADGui as Gui\n'
          'Gui.activateWorkbench("CAMWorkbench")\n'
          'App.openDocument(str(_root/"machining.FCStd"))\n'
          'Gui.activeDocument().activeView().viewAxonometric()\n'
          'Gui.activeDocument().activeView().fitAll()\n').encode('utf-8')


def needed(prepared):
    return (prepared.get('version')=='schemaxis.freecad.cam.plan/3' and
            any(t.get('kind')=='drill' and 'shankDiameter' in t for t in prepared['tools']))


def module_bytes():
    """Installed source only, never a module selected by a saved document."""
    # __file__ may name a runtime ZIP subdirectory inside native FreeCAD.
    # pkgutil delegates to the installed loader without importing the module.
    import pkgutil
    data=pkgutil.get_data(__package__,'native_tools/'+FILENAME)
    if not data or len(data)>128*1024:raise ValueError('Missing or oversized installed reduced-tool module')
    return data


def native_module():
    """Only the finite installed module path precedes SDK factory/restore."""
    directory=str(Path(__file__).parent/'native_tools')
    expected=directory+'/'+FILENAME
    previous=sys.modules.get(MODULE)
    if previous is not None and getattr(previous,'__file__',None)!=expected:
        raise ValueError('A foreign reduced-tool module is already loaded')
    if directory not in sys.path:sys.path.insert(0,directory)
    module=importlib.import_module(MODULE)
    if module.__file__!=expected:raise ValueError('Reduced-tool import left the installed native module path')
    return module
