# Copyright (C) 2026 David L F Gaden
"""Bounded KiCad board inspection, DRC and drill export through isolated kicad-cli."""
import hashlib
import json
import math
import os
from pathlib import Path
import re
import shutil
import stat
import time

from schemaxis.artifacts import atomic_json, file_digest
from schemaxis.core.declarations import validate_arguments
from schemaxis.core.faults import SchemaxisError
from schemaxis.dispatch import cancellation_requested
from schemaxis.errors import fail, keys
from schemaxis.native_command import execute
from . import board as boards, drc, drill
from .board import check

VERSION = 'schemaxis.kicad/1'
BOARD = {'type': 'string', 'minLength': 1, 'maxLength': 4096, 'required': True}
COUNT = {'type': 'integer', 'minimum': 0, 'maximum': 100000, 'default': 0}
GATES = {'maximumErrors': COUNT, 'maximumWarnings': COUNT, 'maximumUnconnected': COUNT}
OPTIONS = {
    'inspectBoard': {'board': BOARD},
    'designRuleCheck': {'board': BOARD, **GATES},
    'drillExport': {'board': BOARD, **GATES, 'units': {'type': 'enum', 'values': ['mm', 'in'], 'default': 'mm'},
                    'separatePlating': {'type': 'boolean', 'default': True}}}
NATIVE = {'inspectBoard': 'kicad-cli pcb export stats', 'designRuleCheck': 'kicad-cli pcb drc',
          'drillExport': 'kicad-cli pcb export drill'}
KINDS = {'inspectBoard': ['text'], 'designRuleCheck': ['text'], 'drillExport': ['drill', 'text']}
DECLARATIONS = {op: {'native': NATIVE[op], 'kinds': KINDS[op], 'inputs': {},
                     'options': {k: {'value': v} for k, v in opts.items()}} for op, opts in OPTIONS.items()}
STEM = 'board'
SIBLINGS = ('.kicad_pro', '.kicad_dru')
MAX_SIBLING_BYTES = 1024*1024
SUPPORTED_RUNTIME = re.compile(r'^(10)\.(0)\.(\d+)$')
LOSSES = [
    'Reads a saved two-copper-layer KiCad 8.0-10.0 board; no board authoring, schematic parity or zone refill',
    'Host cross-checks model straight tracks, through vias, simple pads and one netclass clearance; other DRC findings are native-only',
    'Drill export is decimal absolute Excellon of round holes; no slots, offsets, backdrills, blind/buried vias or drill maps',
    'Global footprint/symbol library tables are not used; library checks reflect the isolated run unless the project ignores them']


def plan(document):
    keys(document, ('version', 'operation', 'board', 'maximumErrors', 'maximumWarnings', 'maximumUnconnected',
                    'units', 'separatePlating'), '$')
    if document.get('version') != VERSION:
        fail('UNSUPPORTED_VERSION', 'expected '+VERSION)
    operation = document.get('operation')
    if not isinstance(operation, str) or operation not in OPTIONS:
        fail('UNKNOWN_FILTER', 'select inspectBoard, designRuleCheck or drillExport', '$.operation')
    options = validate_arguments(OPTIONS[operation], {k: v for k, v in document.items() if k not in ('version', 'operation')},
                                 location='$')
    board = options['board']
    if any(ord(c) < 32 for c in board) or not Path(board).is_absolute() or not board.endswith('.kicad_pcb'):
        fail('INVALID_RESOURCE', 'board must be an absolute path to a .kicad_pcb file', '$.board', board=board)
    publications = ['board-summary.json', 'board-statistics.json']
    if operation != 'inspectBoard':
        publications.append('drc-report.json')
    if operation == 'drillExport':
        publications += ['drill/'+name for name in drill.files(STEM, options['separatePlating'])]
    stages = ['version', 'about', 'stats']+(['drc'] if operation != 'inspectBoard' else [])+(['drill'] if operation == 'drillExport' else [])
    return {'version': 'schemaxis.kicad.plan/1', 'operation': operation, **options, 'stages': stages,
            'publications': publications, 'project': [Path(board).with_suffix(s).name for s in SIBLINGS],
            'limits': {'boardBytes': boards.MAX_BOARD_BYTES, 'copperItems': boards.MAX_COPPER_ITEMS,
                       'holes': boards.MAX_HOLES, 'formats': list(boards.FORMATS)},
            'losses': LOSSES}


def schema():
    from schemaxis.schema import DRAFT, object_schema, argument_schema
    variants = []
    for op, options in OPTIONS.items():
        fields = {'version': {'const': VERSION}, 'operation': {'const': op}, **{k: argument_schema(v) for k, v in options.items()}}
        variants.append(object_schema(fields, ['version', 'operation', 'board']))
    fields = {}
    for variant in variants:
        for key, value in variant['properties'].items():
            if value not in fields.setdefault(key, []):
                fields[key].append(value)
    properties = {key: (values[0] if len(values) == 1 else {'anyOf': values}) for key, values in fields.items()}
    return {'$schema': DRAFT, **object_schema(properties, ['version', 'operation', 'board']), 'oneOf': variants}


def query(document):
    return [plan(document)['operation']], {}


def inputs(prepared):
    board = Path(prepared['board'])
    return [board]+[p for p in (board.with_suffix(s) for s in SIBLINGS) if os.path.lexists(p)]


def regular_bytes(path):
    """Read a board input through a nonblocking, non-following descriptor with a size bound."""
    limit = boards.MAX_BOARD_BYTES if path.suffix == '.kicad_pcb' else MAX_SIBLING_BYTES
    if path.is_symlink():
        fail('UNSUPPORTED_RESOURCE', 'board inputs may not be symbolic links', '$.board', file=str(path))
    try:
        descriptor = os.open(path, os.O_RDONLY | os.O_NONBLOCK | getattr(os, 'O_NOFOLLOW', 0))
    except OSError as error:
        fail('RESOURCE_NOT_FOUND', 'board input cannot be opened: '+error.strerror, '$.board', file=str(path))
    try:
        info = os.fstat(descriptor)
        if not stat.S_ISREG(info.st_mode):
            fail('UNSUPPORTED_RESOURCE', 'board inputs must be regular files', '$.board', file=str(path))
        if info.st_size > limit:
            fail('RESOURCE_LIMIT', path.suffix+' input exceeds its size limit', '$.board', file=str(path), bytes=limit)
        chunks, total = [], 0
        while total <= limit:
            chunk = os.read(descriptor, min(1024*1024, limit+1-total))
            if not chunk:
                break
            chunks.append(chunk); total += len(chunk)
        if total > limit:
            fail('RESOURCE_LIMIT', path.suffix+' input grew beyond its size limit', '$.board', file=str(path), bytes=limit)
        return b''.join(chunks)
    finally:
        os.close(descriptor)


def reusableInputs(document):
    return {str(p): hashlib.sha256(regular_bytes(p)).hexdigest() for p in inputs(plan(document))}


def resources(document, spec, identity):
    if spec.get('threads', 1) != 1:
        fail('INVALID_EXECUTION', 'this board slice uses one thread', identity)
    return {'threads': 1}


def capture(prepared, directory, digests):
    """Copy the board and its sibling project files into the run; the source is never opened by KiCad."""
    target = directory/'board'; target.mkdir()
    sources = {}
    for path in inputs(prepared):
        data = regular_bytes(path)
        if hashlib.sha256(data).hexdigest() != digests.get(str(path)):
            fail('INPUT_CHANGED', 'board input changed during capture', '$.board', file=str(path))
        name = STEM+path.suffix
        (target/name).write_bytes(data)
        sources[name] = {'file': str(path), 'sha256': digests[str(path)]}
    return sources


def project(directory):
    """Parse the retained project JSON and report whether custom rules exist."""
    path = directory/'board'/(STEM+'.kicad_pro')
    settings = None
    if path.is_file():
        try:
            settings = json.loads(path.read_text(encoding='utf-8'))
        except (UnicodeDecodeError, ValueError) as error:
            fail('INVALID_PROJECT', 'sibling .kicad_pro must be UTF-8 JSON: '+str(error), '$.board')
        if not isinstance(settings, dict):
            fail('INVALID_PROJECT', 'sibling .kicad_pro must contain a JSON object', '$.board')
    return settings, (directory/'board'/(STEM+'.kicad_dru')).is_file()


def retained(directory):
    return sorted(str(p.relative_to(directory/'board')) for p in (directory/'board').iterdir()
                  if p.suffix in ('.kicad_pcb',)+SIBLINGS)


def environment(directory):
    """Isolate KiCad configuration, caches and library tables inside the run."""
    home = directory/'native-home'
    return {'HOME': str(home), 'XDG_CONFIG_HOME': str(home/'config'), 'XDG_CACHE_HOME': str(home/'cache'),
            'XDG_DATA_HOME': str(home/'data'), 'XDG_STATE_HOME': str(home/'state'),
            'KICAD_CONFIG_HOME': str(home/'config'/'kicad'), 'LC_NUMERIC': 'C', 'OMP_NUM_THREADS': '1'}


def runtime(text):
    lines = [line.strip() for line in text.splitlines() if line.strip()]
    found = SUPPORTED_RUNTIME.match(lines[-1]) if lines else None
    if not found:
        fail('UNSUPPORTED_RUNTIME', 'expected a KiCad 10.0.x kicad-cli executable', observed=lines[-1:] if lines else [])
    return {'name': 'kicad-cli', 'version': lines[-1]}


def commands(prepared, executable, directory):
    board = str(directory/'board'/(STEM+'.kicad_pcb'))
    result = {'version': [executable, 'version'], 'about': [executable, 'version', '--format', 'about'],
              'stats': [executable, 'pcb', 'export', 'stats', '--format', 'json', '--units', 'mm',
                        '-o', str(directory/'board-statistics.json'), board],
              'drc': [executable, 'pcb', 'drc', '--format', 'json', '--severity-all', '--units', 'mm',
                      '-o', str(directory/'drc-report.json'), board]}
    if prepared['operation'] == 'drillExport':
        result['drill'] = [executable, 'pcb', 'export', 'drill', '--format', 'excellon', '--drill-origin', 'absolute',
                           '--excellon-zeros-format', 'decimal', '--excellon-oval-format', 'alternate',
                           '--excellon-units', prepared['units']]+(['--excellon-separate-th'] if prepared['separatePlating'] else [])+[
                           '-o', str(directory/'drill')+os.sep, board]
    return {stage: result[stage] for stage in prepared['stages']}


def evidence_names(prepared, directory):
    names = ['sources.json', 'runtime.json']
    for stage in prepared['stages']:
        names += [stage+'-submission.json', stage+'.stdout', stage+'.stderr']
    return names+['board/'+name for name in retained(directory)]


def submissions(prepared, directory, executable):
    """Bind every native stage record to its exact recipe command, success and retained log."""
    expected = commands(prepared, '<kicad-cli>', Path('<run>'))
    root = str(directory)
    def portable(argument, index):
        if index == 0:
            return '<kicad-cli>' if argument == executable else argument
        return '<run>'+argument[len(root):] if argument == root or argument.startswith(root+os.sep) else argument
    for stage, command in expected.items():
        record = json.loads((directory/(stage+'-submission.json')).read_text(encoding='utf-8'))
        check(isinstance(record, dict) and record.get('exitCode') == 0, 'native stage did not exit successfully: '+stage)
        recorded = record.get('nativeCommand')
        check(isinstance(recorded, list) and all(isinstance(a, str) for a in recorded)
              and [portable(a, i) for i, a in enumerate(recorded)] == command,
              'native stage command differs from the plan recipe: '+stage)
        script = Path(str(record.get('scriptPath', '')))
        check(script.parent == directory/'.dispatch'/stage and script.name.startswith('replay-'),
              'native stage record does not belong to this run: '+stage)
        # The shared runner records the last 4000 characters of each retained log.
        for stream in ('stdout', 'stderr'):
            log = (directory/(stage+'.'+stream)).read_text(errors='replace')
            check(record.get(stream) == log[-4000:], 'native stage '+stream+' log differs from its record: '+stage)
    return list(expected)


def manifest(prepared, directory):
    kinds = {'.json': 'text', '.drl': 'drill'}
    return [{'file': str(directory/name), 'kind': kinds[Path(name).suffix], 'sha256': file_digest(directory/name)}
            for name in prepared['publications']]


def derive(prepared, directory, observed):
    """Recompute every published conclusion from retained native files and the retained board."""
    model = boards.read(directory/'board'/(STEM+'.kicad_pcb'))
    facts = boards.summary(model)
    if prepared['operation'] == 'drillExport' and facts['unsupportedForDrill']:
        fail('UNSUPPORTED_BOARD', 'drilled pads on back-side footprints are outside this drill slice', '$.board',
             flags=facts['unsupportedForDrill'])
    statistics = json.loads((directory/'board-statistics.json').read_text(encoding='utf-8'))
    details = {'version': 'schemaxis.kicad.summary/1', 'operation': prepared['operation'], 'runtime': observed['version'],
               'board': facts, 'statistics': boards.compare_statistics(facts, statistics), 'losses': LOSSES}
    if prepared['operation'] != 'inspectBoard':
        settings, custom = project(directory)
        prediction = drc.predict(model, drc.rules(settings, custom))
        report = drc.read(directory/'drc-report.json', observed['version'], STEM+'.kicad_pcb')
        drc.console((directory/'drc.stdout').read_text(errors='replace'), report)
        details['drc'] = {'project': settings is not None, 'customRules': custom, 'prediction': prediction,
                          'crossCheck': drc.cross_check(report, prediction), 'assessment': drc.assess(report, prepared),
                          **{k: report[k] for k in ('errors', 'warnings', 'exclusions', 'unconnected', 'byType',
                                                     'ignoredChecks', 'findings')}}
    return model, details


def drilling(prepared, directory, model):
    folder = directory/'drill'
    names = drill.files(STEM, prepared['separatePlating'])
    present = {p.name for p in folder.iterdir()} if folder.is_dir() else set()
    # Shared publication metadata companions are the only other permitted files.
    check(set(names) <= present <= set(names) | {n+'.metadata.json' for n in names},
          'drill export produced unexpected or missing files')
    readings = [drill.read(folder/name, prepared['units']) for name in names]
    return {'units': prepared['units'], 'origin': 'absolute', 'format': 'Excellon decimal',
            **drill.compare(model['holes'], readings, prepared['units'], prepared['separatePlating'])}


def run(document, directory, *, executable=None, timeout=300):
    prepared = plan(document)
    executable = executable or os.environ.get('KICAD_CLI') or shutil.which('kicad-cli')
    if not executable or not Path(executable).is_absolute() or not Path(executable).is_file() or not os.access(executable, os.X_OK):
        fail('INTERPRETER_NOT_FOUND', 'configure an absolute KiCad 10.0 kicad-cli executable or pass --kicad')
    if type(timeout) not in (int, float) or not math.isfinite(timeout) or not 0 < timeout <= 3600:
        fail('INVALID_ARGUMENT', 'timeout must be in (0,3600]')
    directory = Path(directory).absolute()
    if directory.exists() or directory.is_symlink():
        fail('OUTPUT_EXISTS', 'choose a fresh output directory', str(directory))
    digests = reusableInputs(document)
    directory.mkdir(parents=True)
    atomic_json(directory/'authored.json', document); atomic_json(directory/'plan.json', prepared)
    atomic_json(directory/'result.json', {'status': 'incomplete', 'verified': False})
    try:
        atomic_json(directory/'sources.json', capture(prepared, directory, digests))
        # Validate the supported board subset before any native process starts.
        model = boards.read(directory/'board'/(STEM+'.kicad_pcb'))
        if prepared['operation'] == 'drillExport' and boards.summary(model)['unsupportedForDrill']:
            fail('UNSUPPORTED_BOARD', 'drilled pads on back-side footprints are outside this drill slice', '$.board')
        if prepared['operation'] != 'inspectBoard':
            project(directory)
        frozen = {name: file_digest(directory/'board'/name) for name in retained(directory)}
        deadline = time.monotonic()+timeout
        native, observed = environment(directory), None
        for stage, command in commands(prepared, executable, directory).items():
            if stage == 'drill':
                (directory/'drill').mkdir()
            execute(command, directory, stage, deadline-time.monotonic(), native)
            if {name: file_digest(directory/'board'/name) for name in retained(directory)} != frozen:
                fail('NATIVE_MUTATED_INPUT', 'kicad-cli changed the retained board or project', stage)
            if stage == 'version':
                observed = {**runtime((directory/'version.stdout').read_text(errors='replace')), 'executable': executable}
                atomic_json(directory/'runtime.json', observed)
            if stage == 'drc':
                _, details = derive(prepared, directory, observed)
                if not details['drc']['assessment']['accepted']:
                    atomic_json(directory/'board-summary.json', details)
                    fail('DRC_VIOLATIONS', 'native KiCad DRC findings exceed the authored maximum counts', '$',
                         assessment=details['drc']['assessment'])
        model, details = derive(prepared, directory, observed)
        if prepared['operation'] == 'drillExport':
            details['drill'] = drilling(prepared, directory, model)
        atomic_json(directory/'board-summary.json', details)
        atomic_json(directory/'verification.json', {'artifacts': manifest(prepared, directory),
                    'evidence': {n: file_digest(directory/n) for n in evidence_names(prepared, directory)}})
        result = verify(directory, require_result=False)
        if cancellation_requested():
            fail('RUNNER_CANCELLED', 'board publication cancelled')
        if time.monotonic() >= deadline:
            fail('RUNNER_TIMED_OUT', 'board verification exhausted the total timeout')
        result.update(status='succeeded'); atomic_json(directory/'result.json', result); return result
    except Exception as error:
        if not isinstance(error, SchemaxisError):
            try:
                fail('NATIVE_EXECUTION_FAILED', str(error))
            except SchemaxisError as wrapped:
                error = wrapped
        atomic_json(directory/'result.json', {'status': 'failed', 'verified': False, 'fault': error.fault.to_dict()})
        raise error


def verify(directory, require_result=True):
    directory = Path(directory).absolute()
    try:
        def read(name):
            return json.loads((directory/name).read_text(encoding='utf-8'))
        for name in ('authored.json', 'plan.json', 'result.json', 'verification.json', 'sources.json', 'runtime.json'):
            path = directory/name
            check(path.is_file() and not path.is_symlink() and path.stat().st_size <= 8*1024*1024, 'missing/excessive evidence: '+name)
        prepared = plan(read('authored.json'))
        check(prepared == read('plan.json'), 'effective plan differs from authored input')
        if require_result:
            check(read('result.json').get('status') == 'succeeded' and read('result.json').get('verified') is True, 'execution incomplete')
        for name in prepared['publications']+evidence_names(prepared, directory):
            path = directory/name
            check(path.is_file() and not path.is_symlink() and path.stat().st_size <= 8*1024*1024,
                  'missing, linked or excessive publication or evidence: '+name)
        check(read('verification.json') == {'artifacts': manifest(prepared, directory),
              'evidence': {n: file_digest(directory/n) for n in evidence_names(prepared, directory)}},
              'publication/native evidence digest differs')
        sources = read('sources.json')
        check(sorted(sources) == retained(directory) and STEM+'.kicad_pcb' in sources and
              all(file_digest(directory/'board'/name) == entry['sha256'] for name, entry in sources.items()),
              'retained board inputs differ from their captured sources')
        observed = read('runtime.json'); identity = runtime((directory/'version.stdout').read_text(errors='replace'))
        check(observed.get('name') == identity['name'] and observed.get('version') == identity['version']
              and Path(observed.get('executable', '')).is_absolute(), 'native runtime identity differs')
        submissions(prepared, directory, observed['executable'])
        model, details = derive(prepared, directory, observed)
        if 'drc' in details and not details['drc']['assessment']['accepted']:
            fail('DRC_VIOLATIONS', 'native KiCad DRC findings exceed the authored maximum counts', '$',
                 assessment=details['drc']['assessment'])
        if prepared['operation'] == 'drillExport':
            details['drill'] = drilling(prepared, directory, model)
        check(read('board-summary.json') == details, 'summary differs from independently rechecked board evidence')
        result = {'verified': True, 'artifacts': len(prepared['publications']), 'runtime': observed,
                  'operation': prepared['operation'], 'holes': details['board']['counts']['holes']}
        if 'drc' in details:
            result['drc'] = details['drc']['assessment']
        return result
    except (OSError, ValueError, KeyError, TypeError, AttributeError, IndexError) as error:
        fail('VERIFICATION_FAILED', 'missing or invalid board evidence: '+str(error))


# Shared authored-input, analytic-visit and verification boundary.
from schemaxis.adaptor_runtime import bind as _bind_runtime
_bind_runtime(globals())
