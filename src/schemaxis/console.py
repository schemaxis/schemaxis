"""JSON console front end; the caller owns and closes the session."""
import json
import sys
from contextlib import contextmanager
from .console_session import ConsoleSession, AdaptorConsoleSession, COMMANDS, PROVIDER_VERSIONS
from .console_session import atomic


def completions(session, text):
    """Command names, active authored IDs, document UUIDs and providers."""
    from .console_session import CONSOLE_TYPES
    choices = {command.split()[0] for command in COMMANDS}
    choices.update(node['id'] for node in session.nodes)
    choices.update(session.status()['documents'])
    choices.update(CONSOLE_TYPES)
    return sorted(choice for choice in choices if choice.startswith(text))


@contextmanager
def terminal_editor(session, enabled):
    if not enabled:
        yield False
        return
    try:
        import readline
    except ImportError:
        yield False
        return
    previous = readline.get_completer()
    delimiters = readline.get_completer_delims()
    history = [readline.get_history_item(i) for i in range(1, readline.get_current_history_length() + 1)]
    path = session.workspace / 'console-history.txt'
    def complete(text, index):
        options = completions(session, text)
        return options[index] if index < len(options) else None
    try:
        readline.clear_history()
        if path.is_file():
            for line in path.read_text().splitlines()[-500:]: readline.add_history(line)
        readline.set_completer(complete)
        readline.set_completer_delims(' \t\n')
        readline.parse_and_bind('bind ^I rl_complete' if 'libedit' in (readline.__doc__ or '') else 'tab: complete')
        yield True
    finally:
        retained = [readline.get_history_item(i) for i in range(max(1, readline.get_current_history_length() - 499), readline.get_current_history_length() + 1)]
        try: atomic(path, ('\n'.join(retained) + ('\n' if retained else '')).encode())
        except OSError: pass
        readline.set_completer(previous)
        readline.set_completer_delims(delimiters)
        readline.clear_history()
        for line in history: readline.add_history(line)


def run_console(session, stream=sys.stdin, output=sys.stdout, *, prompt=True):
    interactive = prompt and stream is sys.stdin and output is sys.stdout and stream.isatty() and output.isatty()
    with terminal_editor(session, interactive) as editing:
        return _run_console(session, stream, output, prompt=prompt, editing=editing)


def _run_console(session, stream, output, *, prompt, editing):
    while True:
        if editing:
            try: line = input('schemaxis> ')
            except EOFError: break
            except KeyboardInterrupt:
                print(file=output)
                continue
        else:
            if prompt and stream.isatty():
                print('schemaxis> ', end='', flush=True, file=output)
            line = stream.readline()
        if editing and not line: continue
        if not line or line.strip().lower() in ('quit', 'exit'):
            break
        try:
            result = {'ok': True, 'result': session.execute(line)}
        except Exception as error:
            from schemaxis.core.faults import SchemaxisError
            result = {'ok': False, 'fault': error.to_dict() if isinstance(error, SchemaxisError) else {'code': 'CONSOLE_ERROR', 'message': str(error)}}
        print(json.dumps(result), file=output)
    return session
