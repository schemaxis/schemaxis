"""Trusted native GUI entry for finite FreeCAD adaptor worker families."""
import os
from pathlib import Path
import traceback


def frame_view(document,component_names):
    """Publish a deterministic isometric camera independent of widget timing."""
    import FreeCAD as App
    import FreeCADGui as Gui
    import math
    boxes=[document.getObject(name).Shape.BoundBox for name in component_names]
    minima=[min(getattr(box,key+'Min') for box in boxes) for key in ('X','Y','Z')]
    maxima=[max(getattr(box,key+'Max') for box in boxes) for key in ('X','Y','Z')]
    centre=[(a+b)/2 for a,b in zip(minima,maxima)]
    diagonal=math.sqrt(sum((b-a)**2 for a,b in zip(minima,maxima)))
    if not math.isfinite(diagonal) or diagonal<=0:raise ValueError('cannot frame invalid assembly geometry')
    view=Gui.activeDocument().activeView();view.setAnimationEnabled(False)
    view.setCameraType('Orthographic')
    camera=view.getCameraNode()
    rotation=App.Rotation(App.Vector(0,0,1),App.Vector(1,1,1))
    camera.orientation.setValue(*rotation.Q)
    distance=2*diagonal
    camera.position.setValue(*[value+distance/math.sqrt(3) for value in centre])
    camera.nearDistance.setValue(0);camera.farDistance.setValue(4*diagonal)
    camera.focalDistance.setValue(distance);camera.aspectRatio.setValue(1)
    camera.height.setValue(1.25*diagonal)


def entry(directory,stage,family):
    stages={'mechanism':{'build','reopen','edit'},'assembly':{'gui_finish','gui_reopen'},'drawing':{'publish'},'part':{'inspect'},'sourceAssembly':{'inspect'}}
    if family not in stages:raise ValueError('unknown native GUI family')
    if stage not in stages[family]:raise ValueError('unknown native GUI stage')
    import FreeCAD as App
    import FreeCADGui as Gui
    from PySide import QtCore, QtGui
    from schemaxis.artifacts import atomic_json
    def execute():
        result={'completed':False}
        try:
            root=Path(os.environ['SCHEMAXIS_FREECAD_ISOLATION_ROOT']).resolve()
            isolated=('FREECAD_USER_HOME','FREECAD_USER_DATA','FREECAD_USER_TEMP','XDG_CONFIG_HOME',
                      'XDG_DATA_HOME','XDG_CACHE_HOME','XDG_RUNTIME_DIR','TMPDIR')
            values={key:os.environ[key] for key in isolated}
            if any(not Path(value).resolve().is_relative_to(root) for value in values.values()):
                raise ValueError('native FreeCAD process lost its private directory isolation')
            if (not os.environ.get('DISPLAY') or os.environ.get('DISPLAY')!=os.environ.get('SCHEMAXIS_FREECAD_EXPECTED_DISPLAY')
                    or os.environ.get('WAYLAND_DISPLAY')):
                raise ValueError('native FreeCAD process does not have an isolated virtual display')
            values.update(display=os.environ['DISPLAY'],userParameter=App.ConfigGet('UserParameter'),
                          systemParameter=App.ConfigGet('SystemParameter'),
                          userAppData=App.getUserAppDataDir())
            if any(not Path(values[key]).resolve().is_relative_to(root) for key in ('userParameter','systemParameter','userAppData')):
                raise ValueError('native FreeCAD resolved configuration or application data outside its private directory')
            values['migrationOffer']=App.ParamGet('User parameter:BaseApp/Preferences/Mod/CAM/Migration').GetString('OfferedToMigrateCAMAssets')
            if values['migrationOffer']!='v1-1':raise ValueError('private CAM migration refusal preference was not loaded')
            if family=='mechanism':
                from .mechanism_native import main
                result.update(isolation=values,observed=main(directory,stage),completed=True)
            elif family=='part':
                from .part_gui_native import inspect
                result.update(isolation=values,observed=inspect(directory),completed=True)
            elif family=='sourceAssembly':
                from .assembly_sources_gui_native import inspect
                result.update(isolation=values,observed=inspect(directory),completed=True)
            elif family=='drawing':
                from .drawing_native import publish
                from schemaxis.native_boundary import execute_guarded
                execute_guarded(publish,directory)
                result.update(isolation=values,completed=True)
            else:
                # The installed assembly worker owns its delayed screenshot and
                # close callback. Record isolation before invoking its finite hook.
                atomic_json(Path(directory)/(stage+'-transport.json'),{'completed':True,'isolation':values})
                from . import assembly_native
                function=assembly_native.gui_finish if stage=='gui_finish' else assembly_native.gui_reopen
                function(directory)
                return
        except Exception:result['error']=traceback.format_exc()
        finally:
            if family in ('mechanism','drawing','part','sourceAssembly'):
                filename=stage+'.json' if family in ('mechanism','part','sourceAssembly') else stage+'-transport.json'
                atomic_json(Path(directory)/filename,result)
                for name in list(App.listDocuments()):App.closeDocument(name)
                Gui.getMainWindow().close()
            elif result.get('error'):
                atomic_json(Path(directory)/(stage+'-transport.json'),result)
                atomic_json(Path(directory)/'native-fault.json',{'code':'GUI_PUBLICATION_FAILED',
                    'message':result['error'],'location':stage,'phase':'native'})
                for name in list(App.listDocuments()):App.closeDocument(name)
                Gui.getMainWindow().close()
    def dismiss_startup():
        # Escape any first-run welcome/task dialog within this private display.
        application=QtGui.QApplication.instance()
        widget=application.activeModalWidget() or Gui.getMainWindow()
        for kind in (QtCore.QEvent.KeyPress,QtCore.QEvent.KeyRelease):
            application.sendEvent(widget,QtGui.QKeyEvent(kind,QtCore.Qt.Key_Escape,QtCore.Qt.NoModifier))
        QtCore.QTimer.singleShot(0,execute)
    QtCore.QTimer.singleShot(0,dismiss_startup)
