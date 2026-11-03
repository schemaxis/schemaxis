# Copyright (C) 2026 David L F Gaden
"""Run trusted argument arrays with shared cancellation, resource and log ownership."""
import hashlib
from pathlib import Path
import sys
from schemaxis.core.runners import Interpreter
from .artifacts import atomic_json
from .dispatch import SubprocessRunner


def execute(command, directory, stage, timeout, environment=None):
    from .errors import fail
    if timeout <= 0:
        fail('RUNNER_TIMED_OUT', 'native job exhausted its total timeout', stage)
    directory = Path(directory)
    source = ('import os\n' + f'os.chdir({str(directory)!r})\n'
              + f'command = {list(map(str, command))!r}\n'
              + 'os.execvpe(command[0], command, os.environ)\n')
    workspace = directory/'.dispatch'/stage
    script = workspace/('replay-'+hashlib.sha256(source.encode()).hexdigest()[:16]+'.py')
    runner = SubprocessRunner(Interpreter('native', sys.executable), workspace,
                              timeout=timeout, environment=environment)
    try:
        report = runner(source)
        atomic_json(directory/(stage+'-submission.json'), {**report.to_dict(), 'nativeCommand': list(map(str, command))})
    finally:
        for suffix, target in (('.stdout.log', '.stdout'), ('.stderr.log', '.stderr')):
            path = script.with_suffix(suffix)
            if path.is_file():
                (directory/(stage+target)).write_bytes(path.read_bytes())
    return report
