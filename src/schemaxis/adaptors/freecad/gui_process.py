"""Isolated native GUI execution for trusted FreeCAD adaptor entry points."""
import json
import os
from pathlib import Path
import select
import shutil
import subprocess
import tempfile
import time

from schemaxis.errors import fail


def run(directory, executable, stage, *, timeout=120, family='mechanism'):
    """Run a finite adaptor worker, with private preferences and display.

    The stage is an internal enum, never authored Python or a native object path.
    """
    from schemaxis.dispatch import cancellation_requested, remaining_timeout, terminate_tree
    stages={'mechanism':{'build':'build','reopen':'reopen','edit':'edit'},
            'assembly':{'gui_finish':'gui','gui_reopen':'gui-reopened'},
            'drawing':{'publish':'publication'},'part':{'inspect':'inspect'},'sourceAssembly':{'inspect':'inspect'}}
    if family not in stages or stage not in stages[family]:raise ValueError('unknown native GUI family/stage')
    receipt=stages[family][stage]
    directory=Path(directory).absolute()
    executable=Path(executable).expanduser().absolute()
    xvfb=shutil.which('Xvfb');dbus=shutil.which('dbus-run-session')
    if not executable.is_file() or not os.access(executable,os.X_OK):
        fail('INTERPRETER_NOT_FOUND','Provide an absolute FreeCAD GUI executable')
    if not xvfb:fail('GUI_RUNTIME_REQUIRED','FreeCAD mechanism execution requires Xvfb')
    if not dbus:fail('GUI_RUNTIME_REQUIRED','FreeCAD mechanism execution requires a private D-Bus session')
    timeout=remaining_timeout(timeout);deadline=time.monotonic()+timeout
    read,write=os.pipe();server=None;process=None
    with tempfile.TemporaryDirectory(prefix='schemaxis-freecad-gui-') as temporary:
        settings=Path(temporary)
        environment=dict(os.environ,OMP_NUM_THREADS='1',LIBGL_ALWAYS_SOFTWARE='1',PYTHONDONTWRITEBYTECODE='1',QT_QPA_PLATFORM='xcb')
        for key in ('PYTHONHOME','PYTHONPATH','QT_PLUGIN_PATH','QT_QPA_PLATFORM_PLUGIN_PATH','LD_PRELOAD',
                    'DISPLAY','WAYLAND_DISPLAY','XAUTHORITY','DBUS_SESSION_BUS_ADDRESS','DBUS_SESSION_BUS_PID','SESSION_MANAGER'):
            environment.pop(key,None)
        for key,name in (('FREECAD_USER_HOME','home'),('FREECAD_USER_DATA','data'),('FREECAD_USER_TEMP','temp'),
                         ('XDG_CONFIG_HOME','config'),('XDG_DATA_HOME','xdg-data'),('XDG_CACHE_HOME','cache'),
                         ('XDG_RUNTIME_DIR','runtime'),('TMPDIR','tmp')):
            (settings/name).mkdir(mode=0o700);environment[key]=str(settings/name)
        environment['SCHEMAXIS_FREECAD_ISOLATION_ROOT']=str(settings)
        environment['TMP']=environment['TEMP']=environment['TMPDIR']
        # A finite private profile suppresses the first-run CAM migration offer.
        # It never reads or changes the user's CAM assets or preferences.
        (settings/'user.cfg').write_text('<?xml version="1.0" encoding="UTF-8"?>\n'
            '<!DOCTYPE FCParameters><FCParameters><FCParamGroup Name="Root">'
            '<FCParamGroup Name="BaseApp">'
            '<FCParamGroup Name="Preferences"><FCParamGroup Name="Mod">'
            '<FCParamGroup Name="CAM"><FCParamGroup Name="Migration">'
            '<FCText Name="OfferedToMigrateCAMAssets">v1-1</FCText></FCParamGroup>'
            '</FCParamGroup></FCParamGroup></FCParamGroup></FCParamGroup>'
            '</FCParamGroup></FCParameters>')
        runtime=directory/({'mechanism':'trusted-runtime.zip','sourceAssembly':'source-gui-runtime.zip'}.get(family,'runtime.zip'))
        macro=directory/(stage+'.FCMacro')
        macro.write_text('import sys\nsys.path.insert(0,'+repr(str(runtime))+')\n'
                         'from schemaxis.adaptors.freecad.gui_native import entry\n'
                         'entry('+repr(str(directory))+','+repr(stage)+','+repr(family)+')\n')
        try:
            with (directory/(stage+'-xvfb.log')).open('wb') as log:
                server=subprocess.Popen([xvfb,'-displayfd',str(write),'-screen','0','1280x960x24','-nolisten','tcp'],
                    pass_fds=(write,),stdout=log,stderr=log,start_new_session=True)
            os.close(write);write=None
            display_deadline=min(deadline,time.monotonic()+10)
            while True:
                remaining_timeout(timeout)
                if time.monotonic()>=deadline:fail('RUNNER_TIMED_OUT','FreeCAD mechanism GUI deadline expired before display startup')
                ready=select.select([read],[],[],min(.05,max(0,display_deadline-time.monotonic())))[0]
                # Waiting can consume the total budget or receive cancellation.
                # Preserve that fault before classifying a display-start failure.
                remaining_timeout(timeout)
                if time.monotonic()>=deadline:fail('RUNNER_TIMED_OUT','FreeCAD GUI deadline expired during display startup')
                if ready:break
                if time.monotonic()>=display_deadline or server.poll() is not None:
                    fail('GUI_PUBLICATION_FAILED','The private display did not start')
            environment['DISPLAY']=':'+os.read(read,100).decode().strip()
            environment['SCHEMAXIS_FREECAD_EXPECTED_DISPLAY']=environment['DISPLAY']
            remaining_timeout(timeout)
            if time.monotonic()>=deadline:fail('RUNNER_TIMED_OUT','FreeCAD mechanism GUI deadline expired before launch')
            command=[dbus,'--',str(executable),'--user-cfg',str(settings/'user.cfg'),'--system-cfg',str(settings/'system.cfg'),str(macro)]
            with (directory/(stage+'-gui.log')).open('wb') as log:
                process=subprocess.Popen(command,env=environment,cwd=directory,stdout=log,stderr=log,
                    stdin=subprocess.DEVNULL,start_new_session=True)
                from schemaxis.artifacts import atomic_json
                atomic_json(directory/(stage+'-launch.json'),{'xvfbPid':server.pid,'guiPid':process.pid,
                    'display':environment['DISPLAY'],'privateSettings':str(settings),
                    'userParameter':str(settings/'user.cfg'),'systemParameter':str(settings/'system.cfg')})
                while process.poll() is None:
                    if cancellation_requested():fail('RUNNER_CANCELLED','FreeCAD mechanism GUI execution cancelled')
                    if time.monotonic()>=deadline:fail('RUNNER_TIMED_OUT','FreeCAD mechanism GUI deadline expired')
                    time.sleep(.05)
            remaining_timeout(timeout)
            if time.monotonic()>=deadline:fail('RUNNER_TIMED_OUT','FreeCAD mechanism GUI deadline expired after native observation')
            if (directory/'native-fault.json').is_file():
                from schemaxis.core.faults import SchemaxisError,Fault
                raise SchemaxisError(Fault(**json.loads((directory/'native-fault.json').read_text())))
            if process.returncode or not (directory/(receipt+'.json')).is_file():
                fail('GUI_PUBLICATION_FAILED','Native mechanism stage did not finish; inspect its GUI log',stage)
            result=json.loads((directory/(receipt+'.json')).read_text())
            if family in ('assembly','drawing'):
                transport=json.loads((directory/(stage+'-transport.json')).read_text())
                if transport.get('completed') is not True or (family=='assembly' and result.get('nativeJointEditors') is not True):
                    fail('GUI_PUBLICATION_FAILED','Native '+family+' GUI stage did not complete in private isolation',stage)
                result['isolation']=transport['isolation']
            elif result.get('completed') is not True:
                fail('NATIVE_EXECUTION_FAILED','Native mechanism stage failed',stage,detail=result.get('error'))
            remaining_timeout(timeout)
            if time.monotonic()>=deadline:fail('RUNNER_TIMED_OUT','FreeCAD mechanism GUI deadline expired before publication')
            return result
        finally:
            os.close(read)
            if write is not None:os.close(write)
            for child in (process,server):
                if child is not None:terminate_tree(child,{})
