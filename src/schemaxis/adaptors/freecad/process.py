"""Private configuration and application data for every batch FreeCAD worker."""
from dataclasses import dataclass
from pathlib import Path
import tempfile

from schemaxis.dispatch import SubprocessRunner as Runner, remaining_timeout


@dataclass
class SubprocessRunner:
    interpreter: object
    workspace: Path
    arguments: tuple = ()
    timeout: float = 300
    environment: dict = None

    def __call__(self, source):
        remaining_timeout(self.timeout)
        with tempfile.TemporaryDirectory(prefix='schemaxis-freecad-batch-') as temporary:
            # FreeCAD canonicalizes its configuration/data locations. Resolve
            # our newly created private root once so a symlinked TMPDIR still
            # passes the exact isolation prelude against that same directory.
            root=Path(temporary).resolve(strict=True)
            environment=dict(self.environment or {})
            for key,name in (('FREECAD_USER_HOME','home'),('FREECAD_USER_DATA','data'),
                             ('FREECAD_USER_TEMP','temp'),('XDG_CONFIG_HOME','config'),
                             ('XDG_DATA_HOME','xdg-data'),('XDG_CACHE_HOME','cache'),
                             ('XDG_RUNTIME_DIR','runtime'),('TMPDIR','tmp')):
                (root/name).mkdir(mode=0o700);environment[key]=str(root/name)
            environment['TMP']=environment['TEMP']=environment['TMPDIR']
            environment.update(DISPLAY='',WAYLAND_DISPLAY='',XAUTHORITY='',
                               DBUS_SESSION_BUS_ADDRESS='',DBUS_SESSION_BUS_PID='',
                               SESSION_MANAGER='',QT_QPA_PLATFORM='offscreen')
            user,system=root/'user.cfg',root/'system.cfg'
            if '--user-cfg' in self.arguments or '--system-cfg' in self.arguments:
                raise ValueError('Batch FreeCAD configuration is owned by its isolated launcher')
            # Fail before the submitted operation if the installed launcher
            # redirects an explicit private configuration to desktop settings.
            prelude=('import FreeCAD as _isolated_app\nfrom pathlib import Path as _isolated_path\n'
                     'assert _isolated_path(_isolated_app.ConfigGet("UserParameter")) == _isolated_path('+repr(str(user))+')\n'
                     'assert _isolated_path(_isolated_app.ConfigGet("SystemParameter")) == _isolated_path('+repr(str(system))+')\n'
                     'assert _isolated_path(_isolated_app.getUserAppDataDir()) == _isolated_path('+repr(environment['FREECAD_USER_DATA'])+')\n')
            result=Runner(self.interpreter,self.workspace,
                          ('--user-cfg',str(user),'--system-cfg',str(system),*self.arguments),
                          remaining_timeout(self.timeout),environment)(prelude+source)
        remaining_timeout(self.timeout)
        return result
