# Copyright (C) 2026 David L F Gaden
"""Provider-aware native observations without geometry publication or rendering."""
import json
import os
from pathlib import Path
from schemaxis.core.runners import SubprocessRunner
from .errors import fail
from .artifacts import atomic_json, runtime_archive
from .adaptors.registry import route_hook, resolve


def inspect(document, node, directory, *, locations=None, roots=None, blender=None, visit=0, timeout=300):
    from .configuration import locations as configured_locations
    locations = configured_locations({'roots': roots, 'blender': blender, **(locations or {})})
    resolve(document)
    from .adaptor_runtime import InputProgram, requires_common
    route = resolve(document)[1]
    if requires_common(document, route):
        states = list(InputProgram(document, route).visits())
        if type(visit) is not int or not 0 <= visit < len(states):
            fail('INVALID_SELECTION', 'inspection visit is outside the input study', count=len(states))
        document, visit = states[visit]['document'], 0
    custom = route_hook(document, 'inspect')
    if custom:
        result = custom(document, node, directory, locations=locations, timeout=timeout, visit=visit)
        from .publication_metadata import publish_artifacts
        root = Path(directory).absolute()
        publish_artifacts(root, [{'file': str(path), 'kind': 'observation'}
                                for path in sorted(root.iterdir()) if path.is_file()
                                and path.suffix == '.json' and not path.name.endswith('.metadata.json')
                                and path.name != 'publication-metadata.json'])
        return result
    setup = route_hook(document, 'inspectionSetup')
    if setup is None: fail('UNSUPPORTED_INSPECTION', 'adaptor does not support node inspection')
    master, interpreter, arguments = setup(document, locations)
    selected = master.select([node])
    if type(visit) is not int or not 0 <= visit < selected.count:
        fail('INVALID_SELECTION', 'inspection visit is outside the selected object sequence', node, count=selected.count)
    directory = Path(directory).absolute()
    if directory.exists() or directory.is_symlink():
        fail('OUTPUT_EXISTS', 'choose a new output directory', str(directory))
    directory.mkdir()
    atomic_json(directory / 'authored.json', document)
    atomic_json(directory / 'plan.json', master.to_dict())
    atomic_json(directory / 'result.json', {'status': 'incomplete', 'scope': 'native observation'})
    (directory / 'runtime.zip').write_bytes(runtime_archive())
    lowered = {**master.document, 'version': document['version']}
    runner = SubprocessRunner(interpreter, directory, arguments=arguments, timeout=timeout)
    prefix = f'import sys, json\nsys.path.insert(0, {str(directory / "runtime.zip")!r})\n'
    try:
        report = runner(prefix + 'from schemaxis.inspection import execute_native\n' +
                        f'execute_native(json.loads({json.dumps(lowered)!r}), {node!r}, {visit}, {str(directory)!r})\n')
        atomic_json(directory / 'submission.json', report.to_dict())
        result = json.loads((directory / 'inspection.json').read_text())
        result.update(status='succeeded', scope='native observation', runtime=interpreter.to_dict())
        from .publication_metadata import publish_artifacts
        publish_artifacts(directory, [{'file': str(directory/'inspection.json'), 'kind': 'observation'}])
        atomic_json(directory / 'result.json', result)
        return result
    except Exception as error:
        atomic_json(directory / 'result.json', {'status': 'failed', 'scope': 'native observation', 'message': str(error)})
        raise


def execute_native(document, node, index, directory):
    from itertools import islice
    from .pipeline import RuntimeClosure
    master, backend = route_hook(document, 'nativeInspection', required=True)(document)
    active = RuntimeClosure(master, backend)
    selected = active.activate([node])
    try:
        visit = next(islice(selected.visits(), index, index + 1))
        state = active.apply(visit)
        result = {'node': node, 'visit': visit, 'observation': state['observations'][node],
                  'effective': state['effective'], 'activeNodes': list(selected.order)}
        active.close()
        atomic_json(Path(directory) / 'inspection.json', result)
    finally:
        if not active.closed:
            active.close()
