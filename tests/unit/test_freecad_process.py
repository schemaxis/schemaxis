"""Batch workers cannot reuse desktop preferences or display/IPC endpoints."""
from pathlib import Path
import unittest
from unittest.mock import patch
import threading
import tempfile

from schemaxis.adaptors.freecad.process import SubprocessRunner
from schemaxis.core.runners import Interpreter
from schemaxis.core.faults import SchemaxisError


class FreeCADProcessTests(unittest.TestCase):
    def test_symlinked_temporary_parent_uses_the_same_private_real_root(self):
        observed={}
        temporary_directory=tempfile.TemporaryDirectory
        with temporary_directory() as directory:
            root=Path(directory);parent=root/'actual';parent.mkdir()
            alias=root/'alias';alias.symlink_to(parent,target_is_directory=True)
            def temporary(**kwargs):return temporary_directory(dir=alias,**kwargs)
            class Native:
                def __init__(self,interpreter,workspace,arguments,timeout,environment):
                    observed['data']=Path(environment['FREECAD_USER_DATA'])
                    self.assertion=observed['data'].is_relative_to(parent.resolve())
                    assert self.assertion
                    assert str(alias) not in str(arguments)
                def __call__(self,source):
                    assert str(alias) not in source
                    return 'native-result'
            with patch('schemaxis.adaptors.freecad.process.tempfile.TemporaryDirectory',temporary),patch('schemaxis.adaptors.freecad.process.Runner',Native):
                self.assertEqual(SubprocessRunner(Interpreter('freecad','/native/freecadcmd'),root)('pass\n'),'native-result')
            self.assertFalse(observed['data'].exists())

    def test_worker_overrides_desktop_paths_and_removes_its_private_directories(self):
        observed={}
        class Native:
            def __init__(self,interpreter,workspace,arguments,timeout,environment):
                observed.update(environment=environment,arguments=arguments)
                for key in ('FREECAD_USER_HOME','FREECAD_USER_DATA','FREECAD_USER_TEMP',
                            'XDG_CONFIG_HOME','XDG_DATA_HOME','XDG_CACHE_HOME','XDG_RUNTIME_DIR','TMPDIR'):
                    path=Path(environment[key])
                    assert path.is_dir() and path.stat().st_mode & 0o777 == 0o700
            def __call__(self,source):
                observed['source']=source
                return 'native-result'
        with patch('schemaxis.adaptors.freecad.process.Runner',Native):
            result=SubprocessRunner(Interpreter('freecad','/native/freecadcmd'),Path('/unused'),
                environment={'FREECAD_USER_DATA':'/desktop/data','DISPLAY':':0'} )('print("operation")\n')
        self.assertEqual(result,'native-result')
        for key in ('DISPLAY','WAYLAND_DISPLAY','XAUTHORITY','DBUS_SESSION_BUS_ADDRESS','SESSION_MANAGER'):
            self.assertEqual(observed['environment'][key],'')
        self.assertFalse(Path(observed['environment']['FREECAD_USER_DATA']).exists())
        self.assertIn('ConfigGet("UserParameter")',observed['source'])
        self.assertIn('ConfigGet("SystemParameter")',observed['source'])
        self.assertIn('getUserAppDataDir()',observed['source'])
        self.assertTrue(observed['source'].endswith('print("operation")\n'))

    def test_caller_cannot_override_configuration_owned_by_the_worker(self):
        for option in ('--user-cfg','--system-cfg'):
            with self.subTest(option=option),self.assertRaises(ValueError):
                SubprocessRunner(Interpreter('freecad','/native/freecadcmd'),Path('/unused'),
                                 arguments=(option,'/desktop/settings'))('pass\n')

    def test_serial_calls_share_the_outer_deadline_and_gate_return(self):
        from schemaxis.dispatch import execution_deadline
        clock=[100.];budgets=[]
        class Native:
            def __init__(self,interpreter,workspace,arguments,timeout,environment):budgets.append(timeout)
            def __call__(self,source):clock[0]+=4;return 'native-result'
        runner=SubprocessRunner(Interpreter('freecad','/native/freecadcmd'),Path('/unused'),timeout=240)
        with patch('schemaxis.dispatch._clock',side_effect=lambda:clock[0]),patch('schemaxis.adaptors.freecad.process.Runner',Native),execution_deadline(10):
            self.assertEqual(runner('pass'),'native-result');self.assertEqual(runner('pass'),'native-result')
            with self.assertRaises(SchemaxisError) as caught:runner('pass')
        self.assertEqual(caught.exception.fault.code,'RUNNER_TIMED_OUT')
        self.assertEqual(budgets,[10,6,2])

    def test_invalid_timeout_and_prelaunch_cancellation_never_launch(self):
        from schemaxis.dispatch import allocation
        with patch('schemaxis.adaptors.freecad.process.Runner') as native:
            for timeout in (True,0,-1,None,float('nan'),float('inf')):
                with self.subTest(timeout=timeout),self.assertRaises(SchemaxisError) as caught:
                    SubprocessRunner(Interpreter('freecad','/native/freecadcmd'),Path('/unused'),timeout=timeout)('pass')
                self.assertEqual(caught.exception.fault.code,'INVALID_TIMEOUT')
            cancel=threading.Event();cancel.set()
            with allocation({},cancel),self.assertRaises(SchemaxisError) as caught:
                SubprocessRunner(Interpreter('freecad','/native/freecadcmd'),Path('/unused'))('pass')
            self.assertEqual(caught.exception.fault.code,'RUNNER_CANCELLED');native.assert_not_called()
