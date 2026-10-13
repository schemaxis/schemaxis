#!/usr/bin/env python3
"""Exercise the shared console against five actual installed native adaptors."""
import argparse
import json
from pathlib import Path
import shlex

from schemaxis.core.faults import SchemaxisError
from schemaxis.artifacts import atomic_json
from schemaxis.console import AdaptorConsoleSession


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output-directory', type=Path, required=True)
    for provider in ('freecad', 'blender', 'paraview', 'godot', 'aseprite'):
        parser.add_argument('--' + provider, required=True)
    args = parser.parse_args()
    root = args.output_directory.absolute()
    if root.exists():
        parser.error('output directory must be fresh')
    root.mkdir(parents=True)
    examples = Path(__file__).resolve().parents[1] / 'examples/schemaxis'
    transcript, checks, documents, processes = [], {}, {}, {}
    result = {'status': 'running', 'checks': checks, 'transcript': transcript}
    atomic_json(root / 'qualification.json', result)
    with AdaptorConsoleSession(root / 'workspace') as session:
        def command(line):
            response = session.execute(line)
            entry = {'command': line, 'provider': session.provider, 'revision': session.status()['revision'],
                     'status': response.get('status', 'ok') if isinstance(response, dict) else 'ok'}
            if isinstance(response, dict):
                for key in ('preview', 'artifacts', 'saved', 'native'):
                    if key in response:
                        entry[key] = response[key]
            transcript.append(entry)
            print('schemaxis> ' + line, flush=True)
            print(json.dumps(entry, sort_keys=True), flush=True)
            atomic_json(root / 'qualification.json', result)
            return response

        for provider in ('freecad', 'blender', 'paraview'):
            command('new ' + provider.title() + ' ' + provider)
            documents[provider] = session.active_document
            if provider == 'freecad':
                command('rectangle plate 80 50')
                command('extrude solid 6')
            elif provider == 'blender':
                command('add paint material')
                command("add block cube '{}' '{\"material\":{\"$object\":\"paint\"}}'")
            else:
                command('add ball sphere')
            command('live ' + shlex.quote(getattr(args, provider)))
            first = command('preview')
            assert first['native'] is True
            geometry = session.geometry()
            assert geometry['objects'] and geometry['revision'] == session.status()['revision']
            processes[provider] = session.live.process.pid
            suffix = {'freecad': '.FCStd', 'blender': '.blend', 'paraview': '.pvsm'}[provider]
            command('save ' + shlex.quote(str(root / (provider + suffix))))
            command('image ' + shlex.quote(str(root / (provider + '.png'))))
            edit = {'freecad': 'set plate width 90', 'blender': 'set block size 3', 'paraview': 'set ball radius 2'}[provider]
            command(edit)
            try:
                session.save(root / ('stale-' + provider + suffix))
                raise AssertionError('stale native save was accepted')
            except SchemaxisError as error:
                checks[provider + 'StaleSaveRejected'] = error.fault.code
            command('preview')
            assert session.live.process.pid == processes[provider]
            checks[provider] = {'native': True, 'sameProcessAcrossEdits': True, 'pid': processes[provider]}

        for provider in ('godot', 'aseprite'):
            command('new ' + provider.title() + ' ' + provider)
            documents[provider] = session.active_document
            command('configure ' + provider + ' ' + shlex.quote(getattr(args, provider)))
            filename = 'godot-primitives.json' if provider == 'godot' else 'aseprite-animation.json'
            command('open ' + shlex.quote(str(examples / filename)))
            if provider == 'godot':
                command('set document preview true')
            preview = command('preview')
            assert preview['native'] is True
            command('image ' + shlex.quote(str(root / (provider + '.png'))))
            if provider == 'aseprite':
                command('save ' + shlex.quote(str(root / 'animation.aseprite')))
            checks[provider] = {'native': True, 'checkpoint': preview['preview']}

        for provider, pid in processes.items():
            command('use ' + documents[provider])
            assert session.live.process.pid == pid
            assert session.geometry()['revision'] == session.status()['revision']
        checks['residentClientsSurviveDocumentSwitch'] = True
        before = session.status()
    with AdaptorConsoleSession(root / 'workspace') as recovered:
        assert recovered.status()['activeDocument'] == before['activeDocument']
        def durable_records(state):
            return {identity: {k: v for k, v in record.items() if k not in ('resident', 'nativeState', 'nativeFault')}
                    for identity, record in state['documents'].items()}
        assert durable_records(recovered.status()) == durable_records(before)
        assert not recovered.status()['resident']
        checks['durableRestart'] = True
    result['status'] = 'succeeded'
    atomic_json(root / 'qualification.json', result)
    print(json.dumps({'status': 'succeeded', 'checks': checks}, indent=2))


if __name__ == '__main__':
    main()
