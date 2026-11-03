# Copyright (C) 2026 David L F Gaden
"""Framework hooks for ParaView execution, evidence and native inspection."""
import copy
import json
from pathlib import Path
from schemaxis.errors import fail
from schemaxis.core.faults import SchemaxisError


def verifyAttempt(directory, expected):
    directory = Path(directory)
    # Reuse the full authored-vs-lowered/time-selection verification, not just hashes.
    from schemaxis.pipeline import DefinitionGraph
    from .job import verify_receipt
    from .publication import scenes
    saved = json.loads((directory/'plan.json').read_text())
    master = DefinitionGraph(json.loads((directory/'input.json').read_text()), saved['pipeline']['declarations'])
    verify_receipt(directory, master, scenes(master))
    from schemaxis.documents import resolve_document
    effective, _ = resolve_document(copy.deepcopy(expected))
    if isinstance(effective.get('times'), dict):
        from schemaxis.core.times import resolve_times
        inspection = json.loads((directory/'inspection.json').read_text())
        effective['times'] = list(resolve_times(effective['times']['select'], inspection['times']).values)
    if DefinitionGraph(effective, saved['pipeline']['declarations']).to_dict()['digest'] != master.to_dict()['digest']:
        fail('VERIFICATION_FAILED', 'attempt plan differs from authored input', str(directory))


def verify(directory):
    try:
        return _verify(directory)
    except SchemaxisError:
        raise
    except (OSError, ValueError, TypeError, KeyError, IndexError) as error:
        fail('VERIFICATION_FAILED', 'Missing or malformed native evidence: ' + str(error), str(directory))


def _verify(directory):
    from schemaxis.pipeline import DefinitionGraph
    from .job import verify_receipt
    from .publication import scenes
    directory = Path(directory)
    saved = json.loads((directory/'plan.json').read_text())
    master = DefinitionGraph(json.loads((directory/'input.json').read_text()), saved['pipeline']['declarations'])
    receipt = verify_receipt(directory, master, scenes(master))
    verifyAttempt(directory, json.loads((directory/'authored.json').read_text()))
    return {'verified': True, 'artifacts': len(receipt['artifacts']),
            'runtime': json.loads((directory/'submission.json').read_text())['interpreter']}


def reusableInputs(document):
    from .job import plan
    if isinstance(document.get('times'), dict):
        return None
    master, scenes, _ = plan(document)
    active = {node for scene in scenes for node in scene['selection']['order']}
    # Companion files, case directories and writer resources need provider-specific manifests.
    generators = {'sphere', 'box', 'cone', 'cylinder', 'disk', 'plane', 'line', 'pointSource', 'wavelet'}
    for node in active:
        declaration = master.nodes[node]
        if not declaration['inputs'] and declaration['filter'] not in generators:
            return None
        options = declaration['options']
        if any(any(token in key.lower() for token in ('file', 'path', 'directory')) for key in options):
            return None
    paths = []

    return {}


def query(document):
    from schemaxis.schema import expand_input
    expanded = expand_input(document)
    nodes = expanded.get('nodes', [])
    if not isinstance(nodes, list) or any(not isinstance(n, dict) or not isinstance(n.get('filter'), str) for n in nodes):
        fail('INVALID_DOCUMENT', 'nodes require declared filter names')
    names = {n['filter'] for n in nodes}
    for scene in expanded.get('scenes', []):
        for export in scene.get('exports', []):
            if isinstance(export, dict) and isinstance(export.get('writer'), str):
                names.add(export['writer'])
                reader = export.get('readback')
                if isinstance(reader, dict) and isinstance(reader.get('operation'), str): names.add(reader['operation'])
    return names, {}


def inspectionSetup(document, locations):
    from .job import plan
    from schemaxis.adaptors.paraview.mvp.runners import require_paraview, PARAVIEW_OFFSCREEN
    return plan(document)[0], require_paraview(locations.get('paraview', locations.get('roots'))), PARAVIEW_OFFSCREEN


def nativeInspection(document):
    from .job import plan
    from .native import ParaViewBackend
    return plan(document)[0], ParaViewBackend()


def verifyLegacy(target, effective, outcome, identity):
    from schemaxis.pipeline import DefinitionGraph
    from .job import verify_receipt
    from .publication import scenes
    saved = json.loads((target / 'plan.json').read_text())
    master = DefinitionGraph(json.loads((target / 'input.json').read_text()), saved['pipeline']['declarations'])
    receipt = verify_receipt(target, master, scenes(master))
    # Recompile authored input to check retained effective settings. Native
    # inspection is recorded separately when a source-time selector is used.
    if isinstance(effective.get('times'), dict):
        selection = json.loads((target / 'time-selection.json').read_text())
        from schemaxis.core.times import resolve_times
        inspection = json.loads((target / 'inspection.json').read_text())
        resolved_times = resolve_times(effective['times']['select'], inspection['times'])
        if resolved_times.to_dict() != selection:
            fail('VERIFICATION_FAILED', 'time-selection evidence differs from requested selector', identity)
        effective['times'] = list(resolved_times.values)
    expected = DefinitionGraph(effective, saved['pipeline']['declarations'])
    if expected.to_dict()['digest'] != master.to_dict()['digest'] or outcome.get('planDigest') != master.to_dict()['digest']:
        fail('VERIFICATION_FAILED', 'operation plan differs from authored workflow', identity)
    return receipt


def liveGraph(document):
    from schemaxis.live_transport import fault
    from .job import plan
    master, scenes, _ = plan(document)
    if len(scenes) != 1:
        fault('UNSUPPORTED_LIVE_INPUT', 'Live mode requires exactly one scene')
    scene = scenes[0]
    selection = master.select(scene['selection']['roots'])
    visible = list(dict.fromkeys([*scene['visible'], *scene['geometry']]))
    return master, selection, scene, visible
