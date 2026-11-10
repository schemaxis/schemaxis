#!/usr/bin/env python3
"""Native IfcOpenShell wall-schedule qualification with an independent STEP oracle, literal expectations, controls and a Calc handoff.

Scope: original synthetic ASCII IFC4 fixtures (examples/schemaxis/fixtures/ifcopenshell, authored by tools/author_ifcopenshell_fixtures.py),
one private IfcOpenShell 0.9.0.post1 interpreter and, for the handoff, LibreOffice Calc. Every expected value below is a hand-stated literal;
the workbook cells are read back by the independent XML oracle of tools/qualify_calc_typed.py. Nothing here shows quantity accuracy, building
truth, geometry validity or whole-file IFC validity.
"""
import argparse
import copy
import hashlib
import json
import math
import os
from pathlib import Path
import shutil
import signal
import statistics
import subprocess
import sys
import threading
import time
from unittest.mock import patch

from schemaxis import workflow
from schemaxis.adaptor_conformance import qualify
from schemaxis.adaptors.ifcopenshell import adaptor as a, step
from schemaxis.artifacts import atomic_json
from schemaxis.core.faults import SchemaxisError
from schemaxis.dispatch import allocation
from schemaxis import publication_metadata
from qualify_calc_typed import check_workbook

ROOT = Path(__file__).resolve().parents[1]
FIXTURES = ROOT / 'examples/schemaxis/fixtures/ifcopenshell'
STAGING = Path('/tmp/schemaxis-ifcopenshell-acceptance')
EXAMPLES = ROOT / 'examples/schemaxis'
BASELINE_CSV = ('"GUID","Name","Fire rating","External","Note","Length (m)","Height (m)"\n'
                '"0SYN000000000000000011","North wall","2HR","true",\\N,2.5,3.0\n'
                '"0SYN000000000000000014","Core wall","1HR","true","+reviewed =later",4.0,\\N\n'
                '"0SYN000000000000000021",\\N,"0123",\\N,"007",1.8,2.7\n')
AREAS_CSV = ('"GUID","Name","External","Count","Length (m)","Side area (m2)","Volume (m3)"\n'
             '"0SYN000000000000000011","Metric A","false",0.0,2.5,7.5,1.5\n'
             '"0SYN000000000000000014","Metric B","false",0.0,0.0,1.5,0.25\n')
METRE_CSV = '"GUID","Name","Length (m)","Height (m)"\n"0SYN000000000000000011","Metre A",2.5,3.0\n"0SYN000000000000000014","Metre B",4.0,2.4\n'
HEADER = ['GUID', 'Name', 'Fire rating', 'External', 'Note', 'Length (m)', 'Height (m)']
# A property-only schedule over a project whose UnitsInContext is `$`: the baseline fixture with exactly that one reference changed.
UNITS_PRESENT = "'Synthetic wall schedule',$,$,$,$,$,#2)"
UNITS_ABSENT = "'Synthetic wall schedule',$,$,$,$,$,$)"
PROPERTY_ONLY_CSV = ('"GUID","Name","Fire rating","External"\n'
                     '"0SYN000000000000000011","North wall","2HR","true"\n'
                     '"0SYN000000000000000014","Core wall","1HR","true"\n'
                     '"0SYN000000000000000021",\\N,"0123",\\N\n')
HEADER_PROPERTY_ONLY = HEADER[:4]
ROWS = [HEADER,
        ['0SYN000000000000000011', 'North wall', '2HR', 'true', None, 2.5, 3.0],
        ['0SYN000000000000000014', 'Core wall', '1HR', 'true', '+reviewed =later', 4.0, None],
        ['0SYN000000000000000021', None, '0123', None, '007', 1.8, 2.7]]


def summary_for(rows):
    out = []
    for index, label in ((5, 'Length (m)'), (6, 'Height (m)')):
        values = [r[index] for r in rows[1:] if r[index] is not None]
        out.append([label, len(values), sum(values), sum(values) / len(values), min(values), max(values), statistics.stdev(values), len(rows) - 1 - len(values), 'ABCDEFG'[index]])
    return out


def sha256(data): return hashlib.sha256(data).hexdigest()


def expect_fault(action, code, message, location):
    """Require the exact intended fault code, message and location; a similar error is a failure."""
    try: action()
    except SchemaxisError as error:
        fault = error.fault
        if (fault.code, fault.message, fault.location) != (code, message, location):
            raise AssertionError(f'wrong fault {fault.code}: {fault.message} at {fault.location}; expected {code}: {message} at {location}') from error
        return {'fault': fault.code, 'message': fault.message, 'location': fault.location}
    raise AssertionError('expected a structured fault ' + code)


def property_only_source(directory):
    """The baseline fixture with UnitsInContext replaced by `$`, written to directory; the replacement must apply exactly once."""
    text = (FIXTURES / 'walls-baseline.ifc').read_text()
    assert text.count(UNITS_PRESENT) == 1, 'the baseline fixture no longer has the expected IfcProject line'
    target = Path(directory) / 'walls-property-only-no-units.ifc'
    target.write_text(text.replace(UNITS_PRESENT, UNITS_ABSENT))
    return target


def document(name, source, **change):
    value = json.loads((EXAMPLES / f'ifcopenshell-{name}.json').read_text())
    value['source']['path'] = str(source)
    value.update(change)
    return value


def refresh(target):
    """Make every ordinary binding, digest, receipt and publication metadata consistent with the bytes now present."""
    p = a.plan(a.read(target, 'authored.json'))
    data = (target / a.SOURCE_FILE).read_bytes()
    atomic_json(target / 'captures.json', {'source': p['source']['path'], 'sha256': sha256(data), 'bytes': len(data)})
    atomic_json(target / 'host-expected.json', step.resolve(step.parse(data), p))
    for stage in a.STAGES: atomic_json(target / (stage + '-inputs.json'), {'files': {n: a.digest(target, n, a.SOURCE_LIMIT) for n in a.stage_inputs(stage)}})
    receipt = a.read(target, 'verification.json')
    receipt['artifacts'] = a.artifacts(target, p)
    receipt['evidence'] = {n: a.digest(target, n, a.SOURCE_LIMIT) for n in sorted(a.evidence_names())}
    atomic_json(target / 'verification.json', receipt)
    for name in ('ifc-schedule.csv.metadata.json', 'ifc-schedule.json.metadata.json'): (target / name).unlink()
    (target / 'publication-metadata.json').unlink()
    publication_metadata.finalise(target)


def tamper(target, changes, code, message, location, results, label, kind):
    """kind is 'semantic' (a refreshed, ordinary-looking record whose meaning is false) or 'integrity' (a retained identity or code changed)."""
    saved = {n: (target / n).read_bytes() for n in {*changes, *(f.name for f in target.iterdir() if f.is_file())}}
    try:
        for name, change in changes.items(): (target / name).write_bytes(change((target / name).read_bytes()))
        assert any((target / n).read_bytes() != b for n, b in saved.items() if (target / n).exists()), label + ': tamper changed nothing'
        refresh(target)
        metadata = publication_metadata.verify(target)
        assert metadata['verified'], label + ': refreshed publication metadata does not verify, so the fault below would not be semantic'
        results.append({'case': label, 'kind': kind, 'publicationMetadataVerifiedFirst': True,
                        **expect_fault(lambda: a.verify(target), code, message, location)})
    finally:
        for f in list(target.iterdir()):
            if f.is_file() and f.name not in saved: f.unlink()
        for name, payload in saved.items(): (target / name).write_bytes(payload)
    a.verify(target)


def edit_native(change):
    def apply(data):
        value = json.loads(data);change(value);return (json.dumps(value, sort_keys=True, allow_nan=False, indent=1) + '\n').encode()
    return apply


def mutants(target, results):
    both = lambda change: {'native-extract.json': edit_native(change), 'native-reopen.json': edit_native(change)}
    wall = lambda t, i=0: t['rows'][i]
    S, I = 'semantic', 'integrity'
    disagrees = 'NATIVE_DISAGREES'
    guid = ('native GlobalId differs from the independent walk', 'native-extract.json.rows[0].guid')
    origin = 'native value origin differs from the independent walk'
    conversion = 'native quantity or unit conversion differs from the exact independent conversion'
    tamper(target, both(lambda t: wall(t).update(guid='0SYN000000000000000099')), disagrees, *guid, results, 'native GUID swapped, extract and reopen agree', S)
    tamper(target, both(lambda t: wall(t)['cells'][0].update(origin='occurrence')), disagrees, origin, 'native-extract.json.rows[0].cells[0].origin', results, 'type default reported as occurrence', S)
    tamper(target, both(lambda t: wall(t)['cells'][0].update(raw='1HR', value='1HR')), disagrees, 'native text differs', 'native-extract.json.rows[0].cells[0].value', results, 'inherited value replaced', S)
    tamper(target, both(lambda t: wall(t, 1)['cells'][4].update(origin='occurrence', raw=0.0, value=0.0)), disagrees, origin, 'native-extract.json.rows[1].cells[4].origin', results, 'missing height reported as occurrence zero', S)
    tamper(target, both(lambda t: wall(t, 1)['cells'][4].update(raw=0.0, value=0.0)), disagrees, 'native reports a value where the independent walk found none', 'native-extract.json.rows[1].cells[4]', results, 'missing height reported as zero with missing origin', S)
    tamper(target, both(lambda t: wall(t)['cells'][3].update(value=2.5000001)), disagrees, conversion, 'native-extract.json.rows[0].cells[3].value', results, 'quantity conversion drift', S)
    tamper(target, both(lambda t: wall(t)['cells'][3].update(value=2500.0)), disagrees, conversion, 'native-extract.json.rows[0].cells[3].value', results, 'quantity left unconverted', S)
    tamper(target, both(lambda t: wall(t, 2).update(name='Renamed')), disagrees, 'native wall Name differs', 'native-extract.json.rows[2].name', results, 'wall name changed', S)
    tamper(target, both(lambda t: wall(t, 1)['cells'][1].update(value=False, raw=False)), disagrees, 'native boolean differs', 'native-extract.json.rows[1].cells[1].value', results, 'explicit true replaced by false', S)
    tamper(target, both(lambda t: t['rows'].reverse()), disagrees, *guid, results, 'row order reversed consistently', S)
    tamper(target, {'native-reopen.json': edit_native(lambda t: wall(t)['cells'][3].update(value=2.6))}, 'NATIVE_REOPEN_DIFFERS', 'a fresh native reopen produced a different raw table', 'native-reopen.json', results, 'reopen-only drift', S)
    tamper(target, {'source.ifc': lambda b: b.replace(b'IFCQUANTITYLENGTH(\'Length\',$,$,2500.,$)', b'IFCQUANTITYLENGTH(\'Length\',$,$,2600.,$)')}, disagrees, conversion, 'native-extract.json.rows[0].cells[3].value', results, 'source changed after native extraction, host oracle refreshed (reaches the source oracle)', S)
    tamper(target, both(lambda t: t['scales'].update(LENGTHUNIT=1.0)), disagrees, 'native unit scale differs from the SI prefix power of the independent walk', 'native-extract.json.scales.LENGTHUNIT', results, 'unit scale forged to 1.0 (true 0.001), both tables refreshed', S)
    tamper(target, both(lambda t: t['scales'].update(AREAUNIT=1e-06)), disagrees, 'native unit scales cover different unit types than the independent walk', 'native-extract.json.scales', results, 'extra native unit scale member', S)
    tamper(target, both(lambda t: [r.update(typeGuid='0SYN0000000000000000ZZ') for r in t['rows']]), disagrees, 'native wall type GlobalId differs from the independent walk', 'native-extract.json.rows[0].typeGuid', results, 'fake type GlobalId on every row', S)
    tamper(target, both(lambda t: wall(t)['cells'][0].update(raw='9HR')), disagrees, 'native raw text differs from the declared value', 'native-extract.json.rows[0].cells[0].raw', results, 'property raw text replaced, value kept', S)
    tamper(target, both(lambda t: wall(t)['cells'][1].update(raw=1)), disagrees, 'native raw boolean differs from the declared value', 'native-extract.json.rows[0].cells[1].raw', results, 'property raw boolean replaced by integer 1', S)
    tamper(target, both(lambda t: wall(t)['cells'][3].update(raw=2500.5)), disagrees, conversion, 'native-extract.json.rows[0].cells[3].value', results, 'quantity raw replaced', S)
    published = 'published schedule file differs from independently checked evidence'
    tamper(target, {'ifc-schedule.csv': lambda b: b.replace(b'2.5,3.0', b'2.6,3.0')}, 'VERIFICATION_FAILED', published, 'ifc-schedule.csv', results, 'published CSV length edited, digests and metadata refreshed', S)
    tamper(target, {'ifc-schedule.json': lambda b: b.replace(b'"geometryAssessed": false', b'"geometryAssessed": true')}, 'VERIFICATION_FAILED', published, 'ifc-schedule.json', results, 'schedule claims geometry assessed', S)
    tamper(target, {'worker.py': lambda b: b + b'\n# edited\n'}, 'VERIFICATION_FAILED', 'retained native worker differs from the packaged worker', 'worker.py', results, 'native worker edited', I)
    tamper(target, {'extract-launcher.py': lambda b: b.replace(b'RLIMIT_AS', b'RLIMIT_DATA')}, 'VERIFICATION_FAILED', 'trusted native launcher differs', 'extract', results, 'launcher edited', I)
    tamper(target, {'version.stdout': lambda b: b.replace(b'0.9.0.post1', b'0.9.1')}, 'VERIFICATION_FAILED', 'configure the qualified IfcOpenShell 0.9.0.post1 interpreter', 'version', results, 'runtime version identity replaced', I)
    tamper(target, {'intent.json': lambda b: b.replace(b'occurrence-overrides-type', b'occurrence-only')}, 'VERIFICATION_FAILED', 'retained native intent differs from the plan', 'intent.json', results, 'native intent differs from plan', I)
    tamper(target, {'version.stdout': lambda b: b.replace(json.loads(b)['modules']['util/unit.py'].encode(), b'0' * 64)}, 'VERIFICATION_FAILED', 'the native util.element or util.unit module differs from the qualified release', 'version.modules', results, 'pinned native util.unit module hash replaced', I)


def area_mutants(target, results):
    """Powered unit scales and the strict integer cell type, on the area/volume case (External boolean, Count integer, Length, Side area, Volume)."""
    both = lambda change: {'native-extract.json': edit_native(change), 'native-reopen.json': edit_native(change)}
    S = 'semantic'
    scale = 'native unit scale differs from the SI prefix power of the independent walk'
    tamper(target, both(lambda t: t['scales'].update(AREAUNIT=1e-03)), 'NATIVE_DISAGREES', scale, 'native-extract.json.scales.AREAUNIT', results, 'area scale without the square (true 1e-06), both tables refreshed', S)
    tamper(target, both(lambda t: t['scales'].update(VOLUMEUNIT=1e-06)), 'NATIVE_DISAGREES', scale, 'native-extract.json.scales.VOLUMEUNIT', results, 'volume scale with the wrong power (true 1e-09)', S)
    tamper(target, both(lambda t: t['scales'].pop('VOLUMEUNIT')), 'NATIVE_DISAGREES', 'native unit scales cover different unit types than the independent walk', 'native-extract.json.scales', results, 'native unit scale member missing', S)
    tamper(target, both(lambda t: t['rows'][0]['cells'][1].update(raw=0.0, value=0.0)), 'NATIVE_DISAGREES', 'native number differs', 'native-extract.json.rows[0].cells[1].value', results, 'IfcInteger 0 reported as real 0.0', S)
    tamper(target, both(lambda t: t['rows'][0]['cells'][1].update(raw=False)), 'NATIVE_DISAGREES', 'native raw number differs from the declared value or its integer/real type', 'native-extract.json.rows[0].cells[1].raw', results, 'IfcInteger 0 raw reported as False, value kept', S)
    tamper(target, both(lambda t: t['rows'][0]['cells'][0].update(raw=0)), 'NATIVE_DISAGREES', 'native raw boolean differs from the declared value', 'native-extract.json.rows[0].cells[0].raw', results, 'explicit .F. raw reported as integer 0', S)


class Launches:
    """Owned callback count of every native process the runner starts while this context is active."""
    def __init__(self): self.argv = []
    def __enter__(self):
        real = subprocess.Popen
        def record(*args, **kwargs):
            command = args[0] if args else kwargs.get('args')
            self.argv.append([str(c) for c in (command if isinstance(command, (list, tuple)) else [command])])
            return real(*args, **kwargs)
        self._patch = patch('schemaxis.dispatch.subprocess.Popen', side_effect=record)
        self._patch.start()
        return self
    def __exit__(self, *exc): self._patch.stop()


def pre_native_controls(out, python, results):
    text = (FIXTURES / 'walls-baseline.ifc').read_text()
    cases = [('duplicate-guid', text.replace("IFCWALL('0SYN000000000000000014'", "IFCWALL('0SYN000000000000000011'"), 'DUPLICATE_GLOBAL_ID', 'two walls share one GlobalId', '#13.GlobalId'),
             ('duplicate-entity-id', text.replace('#9=IFCQUANTITYLENGTH', '#8=IFCQUANTITYLENGTH'), 'DUPLICATE_ENTITY_ID', 'entity #8 is defined more than once', '#8'),
             ('dangling-reference', text.replace('(#9,#10)', '(#9,#99)'), 'DANGLING_REFERENCE', '#99 is not defined', '#11.members[1]'),
             ('ifc2x3-schema', text.replace("('IFC4')", "('IFC2X3')"), 'UNSUPPORTED_SCHEMA', "only FILE_SCHEMA(('IFC4')) is supported; IFC2X3, IFC4X3 and multiple schemas are refused", 'header.FILE_SCHEMA'),
             ('unicode-escape', text.replace("'North wall'", "'N\\X2\\00E9\\X0\\'"), 'UNSUPPORTED_STEP_ESCAPE', 'backslash text and Unicode escape sequences (\\X\\, \\X2\\, \\S\\) are unsupported; use plain ASCII', '$.source.path'),
             ('wall-standard-case', text.replace('#8=IFCWALL(', '#8=IFCWALLSTANDARDCASE('), 'UNSUPPORTED_ENTITY_CLASS', 'IFCWALLSTANDARDCASE is a wall subtype or variant that the IfcWall schedule does not select; remove it or use a plain IfcWall', 'data'),
             ('ambiguous-types', text.replace('ENDSEC;\nEND', "#40=IFCRELDEFINESBYTYPE('0SYN000000000000000040',$,$,$,(#8),#7);\nENDSEC;\nEND"), 'AMBIGUOUS_TYPE', 'a wall has more than one IfcRelDefinesByType', '#8'),
             ('duplicate-property', text.replace('(#4,#5)', '(#4,#4)'), 'DUPLICATE_PROPERTY_NAME', "Pset_WallCommon lists 'FireRating' more than once", '#4'),
             ('missing-unit', text.replace('.LENGTHUNIT.', '.TIMEUNIT.'), 'UNIT_MISSING', 'the project declares no LENGTHUNIT; the length quantity cannot be converted', '$.columns[3]'),
             ('conversion-unit', text.replace('#1=IFCSIUNIT(*,.LENGTHUNIT.,.MILLI.,.METRE.)', "#1=IFCCONVERSIONBASEDUNIT(*,.LENGTHUNIT.,'INCH',$)"), 'UNSUPPORTED_UNIT', 'LENGTHUNIT is declared by IFCCONVERSIONBASEDUNIT; only plain SI units are supported', '#2.Units[0]'),
             ('negative-quantity', text.replace('2500.', '-2500.'), 'QUANTITY_NEGATIVE', 'a physical quantity cannot be negative', '#9'),
             ('unselected-huge-exponent', text.replace('ENDSEC;\nEND', '#50=IFCCARTESIANPOINT((1.E30000000));\nENDSEC;\nEND'), 'STEP_RESOURCE_LIMIT', 'a numeric exponent is longer than 4 digits or larger than 400 in magnitude', '$.source.path'),
             ('unselected-4301-digit-integer', text.replace('ENDSEC;\nEND', '#50=IFCCARTESIANPOINT((' + '9' * 4301 + '));\nENDSEC;\nEND'), 'STEP_RESOURCE_LIMIT', 'a numeric token has more than 40 mantissa digits', '$.source.path'),
             ('4301-digit-entity-id', text.replace('ENDSEC;\nEND', '#' + '9' * 4301 + '=IFCCARTESIANPOINT((0.));\nENDSEC;\nEND'), 'STEP_RESOURCE_LIMIT', 'an entity reference has more than 10 digits', 'data'),
             ('selected-quantity-malformed-real', text.replace('2500.', '25E2'), 'STEP_SYNTAX', 'a number must be a Part 21 INTEGER or REAL: a REAL needs a decimal point and an upper-case E exponent', '$.source.path')]
    for name, content, code, message, location in cases:
        source = out / 'inputs' / (name + '.ifc');source.write_text(content)
        target = out / ('refused-' + name)
        with Launches() as launches:
            outcome = expect_fault(lambda: a.run(document('baseline', source), target, executable=python, timeout=60), code, message, location)
        submissions = sorted(p.name for p in target.glob('*-submission.json'))
        assert not launches.argv and not submissions and not (target / 'ifc-schedule.csv').exists(), (name, launches.argv, submissions)
        assert json.loads((target / 'result.json').read_text())['status'] == 'failed'
        results.append({'case': name, **outcome, 'nativeProcessesLaunched': len(launches.argv), 'submissionFiles': len(submissions)})
    missing = out / 'refused-missing-refuse'
    with Launches() as launches:
        outcome = expect_fault(lambda: a.run(document('baseline', FIXTURES / 'walls-baseline.ifc', missing='refuse'), missing, executable=python, timeout=60), 'MISSING_VALUE',
                               'the wall has no value for the column under the declared inheritance policy', '#8.columns[2]')
    assert not launches.argv and not list(missing.glob('*-submission.json'))
    results.append({'case': 'missing-refuse', **outcome, 'nativeProcessesLaunched': len(launches.argv), 'submissionFiles': 0})


def group_members(pgid):
    """Live processes whose process group is pgid, from /proc (no pgrep and no name matching)."""
    members = []
    for stat in Path('/proc').glob('[0-9]*/stat'):
        try: fields = stat.read_text().rsplit(')', 1)[1].split()
        except (OSError, IndexError): continue
        if int(fields[2]) == pgid: members.append(int(stat.parent.name))
    return sorted(members)


def watch_native(target, processes, observed, hold, stage_marker):
    """Find the real native interpreter once it runs the extract worker; record its process group, then optionally hold it with SIGSTOP."""
    deadline = time.monotonic() + 20
    while time.monotonic() < deadline:
        for process in list(processes):
            try: command = Path('/proc', str(process.pid), 'cmdline').read_bytes()
            except FileNotFoundError: continue
            if process.poll() is None and stage_marker in command and b'worker.py' in command and b'-I' in command:
                pgid = os.getpgid(process.pid)
                members = group_members(pgid)
                if hold:
                    os.kill(process.pid, signal.SIGSTOP)
                    for _ in range(1000):
                        if Path('/proc', str(process.pid), 'stat').read_text().rsplit(')', 1)[1].split()[0] == 'T': break
                        time.sleep(.001)
                observed.append({'pid': process.pid, 'pgid': pgid, 'groupMembersBeforeHold': members, 'command': [c.decode() for c in command.split(b'\0') if c], 'heldWithSigstop': hold,
                                 'inputsBound': (target / 'extract-inputs.json').is_file()})
                return
        time.sleep(.001)


def live_lifecycle(out, python, mode):
    target = out / ('live-' + mode)
    launch = subprocess.Popen
    processes, observed, errors = [], [], []
    cancel = threading.Event()
    def capture(*args, **kwargs):
        process = launch(*args, **kwargs);processes.append(process);return process
    def watcher():
        try:
            watch_native(target, processes, observed, True, b'native-extract.json')
            if mode == 'cancel': cancel.set()
        except Exception as error:
            errors.append(str(error));cancel.set()
    thread = threading.Thread(target=watcher);thread.start()
    states = {}
    code, message = ('RUNNER_CANCELLED', 'native execution did not complete') if mode == 'cancel' else ('RUNNER_TIMED_OUT', 'native execution did not complete')
    try:
        with patch('schemaxis.dispatch.subprocess.Popen', side_effect=capture):
            with allocation({'threads': 1, 'ranks': 1}, cancel):
                # The exact location is the single retained replay script of the extract stage, which the runner names.
                def run(): return a.run(document('baseline', FIXTURES / 'walls-baseline.ifc'), target, executable=python, timeout=20 if mode == 'cancel' else 6)
                try: run()
                except SchemaxisError as error: fault = error.fault
                else: raise AssertionError('expected a structured fault ' + code)
        # Return codes as the runner left them, before this qualifier's own safety-net kill below can touch anything.
        states = {p.pid: p.poll() for p in processes}
    finally:
        thread.join(timeout=25)
        fallback = []
        for process in processes:
            if process.poll() is None:
                fallback.append(process.pid)
                try: os.killpg(process.pid, signal.SIGKILL)
                except ProcessLookupError: pass
                process.wait(timeout=5)
    assert not thread.is_alive() and not errors, errors
    assert observed, 'did not observe the native IfcOpenShell interpreter running the extract worker'
    watched = observed[0]
    victim = next(p for p in processes if p.pid == watched['pid'])
    replay = sorted((target / '.dispatch/extract').glob('replay-*.py'))
    assert len(replay) == 1, replay
    assert (fault.code, fault.message, fault.location) == (code, message, str(replay[0])), (fault.code, fault.message, fault.location, str(replay[0]))
    assert not fallback and all(state is not None for state in states.values()), ('the runner itself did not terminate every owned process', fallback, states)
    assert all(type(p.returncode) is int for p in processes), [p.returncode for p in processes]
    assert victim.returncode in (-15, -9), victim.returncode
    assert watched['pgid'] == victim.pid, 'the native interpreter was expected to lead its own runner-owned process group'
    assert not Path('/proc', str(victim.pid)).exists(), 'terminated native process still present'
    try: os.killpg(watched['pgid'], 0)
    except ProcessLookupError: pass
    else: raise AssertionError('owned process group still exists')
    assert group_members(watched['pgid']) == [], group_members(watched['pgid'])
    result = json.loads((target / 'result.json').read_text())
    assert result['status'] == 'failed' and result['verified'] is False and result['fault']['code'] == code and result['fault']['observed']['exitCode'] == victim.returncode, result
    logs = sorted(p.name for p in (target / '.dispatch/extract').glob('replay-*.std*.log'))
    assert len(logs) == 2, logs
    published = sorted(n.name for n in target.iterdir() if n.name.startswith(('ifc-schedule', 'native-', 'publication-')) or n.name.endswith('.metadata.json') or n.name == 'verification.json')
    assert not published, published
    return {'fault': {'fault': fault.code, 'message': fault.message, 'location': fault.location}, **watched, 'returnCode': victim.returncode,
            'allOwnedProcessReturnCodes': {str(p.pid): p.returncode for p in processes}, 'returnCodesBeforeSafetyNet': {str(k): v for k, v in states.items()},
            'ownedProcessGone': True, 'ownedProcessGroupGone': True, 'groupMembersAfter': [], 'retainedLogs': logs, 'successPublications': published,
            'scope': 'the real native interpreter was held with SIGSTOP after it started the extract worker with captured inputs bound; this is not a claim about the middle of an IfcOpenShell library call'}


def calc_launch(argv, root):
    """A launched command belongs to the Calc consumer when it names the consumer's directory or the soffice executable."""
    return any(str(root / 'typed') in part or 'soffice' in part for part in argv)


def pair_cells(directory, rows):
    """Cells read back by the independent oracle in each of the XLSX and ODS workbooks; the pair total is the sum, not a per-file count."""
    counts = {e: check_workbook(directory / ('analysis.' + e), rows, summary_for(rows), odf=odf) for e, odf in (('xlsx', False), ('ods', True))}
    return {**counts, 'pairTotal': sum(counts.values())}


def handoff(out, python, calc, report):
    work = out / 'handoff-inputs'
    work.mkdir()
    source = work / 'model.ifc'
    shutil.copyfile(FIXTURES / 'walls-baseline.ifc', source)
    schedule = document('baseline', source)
    columns = [{'name': c, 'kind': k, 'nullable': n} for c, k, n in (('GUID', 'text', False), ('Name', 'text', True), ('Fire rating', 'text', True), ('External', 'text', True), ('Note', 'text', True), ('Length (m)', 'number', True), ('Height (m)', 'number', True))]
    graph = {'version': 'schemaxis.workflow/1', 'operations': [
        {'id': 'schedule', 'document': schedule},
        {'id': 'typed', 'document': {'version': 'schemaxis.calc/1', 'nodes': [{'id': 'walls', 'filter': 'readTypedCSV', 'options': {'file': {'$artifact': 'schedule', 'index': 0}, 'nullToken': '\\N', 'columns': columns}}]}}]}
    locations = {'ifcopenshell': python, 'calc': calc}
    target = out / 'workflow'
    with Launches() as launches:
        workflow.execute(graph, target, locations=locations, timeout=240)
    assert workflow.verify(target)['verified']
    # Positive control for the launch counter used by the consumer refusals below: the same predicate must see the Calc stage of a valid run.
    report['calcLaunchPositiveControl'] = {'processesLaunched': len(launches.argv), 'calcProcessesSeen': len([c for c in launches.argv if calc_launch(c, target)])}
    assert report['calcLaunchPositiveControl']['calcProcessesSeen'] >= 1, launches.argv
    def produced(): return sorted(target.joinpath('schedule').glob('*/attempt-*/ifc-schedule.csv'))[-1]
    def consumed(): return sorted(target.joinpath('typed').glob('*/attempt-*/analysis.xlsx'))[-1].parent
    assert produced().read_bytes() == BASELINE_CSV.encode() and (consumed() / 'source.csv').read_bytes() == BASELINE_CSV.encode(), 'consumer capture differs from producer bytes'
    cells = pair_cells(consumed(), ROWS)
    report['baseline'] = {'cells': cells, 'capturedBytesExact': True, 'consumerHeaderTypesNulls': 'declared columns; null token \\N; missing Height is a blank cell, not 0'}
    resumed = workflow.execute(graph, target, locations=locations, timeout=240, resume=True)
    assert all(j.get('reused') for j in resumed['jobs']), resumed['jobs']
    report['unchangedReuse'] = {'bothReused': True}
    base = (FIXTURES / 'walls-baseline.ifc').read_text()
    changes = [('occurrence-property', base.replace("IFCLABEL('1HR')", "IFCLABEL('3HR')"), lambda rows: rows[2].__setitem__(2, '3HR')),
               ('type-property', base.replace("IFCLABEL('2HR')", "IFCLABEL('4HR')"), lambda rows: rows[1].__setitem__(2, '4HR')),
               ('quantity', base.replace('2500.', '2600.'), lambda rows: rows[1].__setitem__(5, 2.6)),
               ('si-prefix', base.replace('.MILLI.,.METRE.', '.CENTI.,.METRE.'), lambda rows: [r.__setitem__(i, r[i] * 10 if False else {2.5: 25.0, 4.0: 40.0, 1.8: 18.0, 3.0: 30.0, 2.7: 27.0}[r[i]]) for r in rows[1:] for i in (5, 6) if r[i] is not None])]
    report['invalidation'] = {}
    for name, text, edit in changes:
        source.write_text(text)
        rerun = workflow.execute(graph, target, locations=locations, timeout=240, resume=True)
        assert not any(j.get('reused') for j in rerun['jobs']), (name, rerun['jobs'])
        assert workflow.verify(target)['verified']
        rows = copy.deepcopy(ROWS);edit(rows)
        csv = produced().read_bytes()
        assert csv != BASELINE_CSV.encode() and (consumed() / 'source.csv').read_bytes() == csv
        report['invalidation'][name] = {'bothRerun': True, 'cells': pair_cells(consumed(), rows)}
    source.write_text(base)
    workflow.execute(graph, target, locations=locations, timeout=240, resume=True)
    # source gone: the standalone captured run still verifies offline; the workflow policy is whatever the scheduler does, recorded as observed
    moved = work / 'model.moved'
    source.rename(moved)
    try:
        offline = a.verify(sorted(target.joinpath('schedule').glob('*/attempt-*'))[-1])
        try:
            gone = workflow.execute(graph, target, locations=locations, timeout=240, resume=True)
            policy = {'outcome': 'completed', 'reused': [bool(j.get('reused')) for j in gone['jobs']]}
        except SchemaxisError as error: policy = {'outcome': 'fault', 'fault': error.fault.code, 'location': error.fault.location}
    finally: moved.rename(source)
    report['sourceGone'] = {'standaloneCapturedVerifyOffline': offline['verified'], 'workflowResume': policy,
                            'scope': 'observed behaviour only; no general reuse rule is claimed'}
    # controls: each must be refused by the host before any Calc process starts, shown by the owned launch count and the absence of a consumer submission
    def faulted(label, mutate, code, message, location):
        case = copy.deepcopy(graph);mutate(case)
        bad = out / ('bad-' + label)
        with Launches() as launches:
            outcome = expect_fault(lambda: workflow.execute(case, bad, locations=locations, timeout=240), code, message, location)
        consumer = [argv for argv in launches.argv if calc_launch(argv, bad)]
        submissions = [p.name for p in bad.joinpath('typed').rglob('*submission*')] if bad.joinpath('typed').exists() else []
        assert not consumer and not submissions, (label, consumer, submissions)
        assert not list(bad.rglob('analysis.xlsx')) and not list(bad.rglob('analysis.ods')), 'workbook published for ' + label
        return {'case': label, **outcome, 'calcProcessesLaunched': len(consumer), 'consumerSubmissionFiles': len(submissions), 'otherProcessesLaunched': len(launches.argv)}
    opts = lambda g: g['operations'][1]['document']['nodes'][0]['options']
    number = 'CSV number cell is not a plain ASCII decimal (spaces, separators, currency, percent and words are not accepted)'
    report['consumerControls'] = [faulted('header-differs', lambda g: opts(g)['columns'][5].update(name='Length'), 'INVALID_TABLE', 'CSV header differs from the declared column name', 'columns[5].name'),
        faulted('required-column-has-null', lambda g: opts(g)['columns'][6].update(nullable=False), 'INVALID_TABLE', 'null token in a column declared nullable: false', 'rows[1][6]'),
        faulted('number-kind-for-text', lambda g: opts(g)['columns'][2].update(kind='number'), 'INVALID_TABLE', number, 'rows[0][2]'),
        faulted('incompatible-artifact-json', lambda g: opts(g)['file'].update(index=1), 'TYPE_MISMATCH', 'artifact kind is incompatible with consumer', 'schedule'),
        faulted('wrong-null-token', lambda g: opts(g).update(nullToken='NULL'), 'INVALID_TABLE', number, 'rows[1][6]')]


GUIDS = ('0SYN000000000000000011', '0SYN000000000000000014', '0SYN000000000000000021')
NULL = '\\N'
HEADER_AREAS = ['GUID', 'Name', 'External', 'Count', 'Length (m)', 'Side area (m2)', 'Volume (m3)']


def json_rows(spec):
    """spec is [(guid, name, [(origin, value), ...]), ...]; the published JSON stores one {origin, value} per non-identity column."""
    return [{'cells': [{'origin': o, 'value': v} for o, v in cells], 'guid': g, 'name': n} for g, n, cells in spec]


def csv_rows(text):
    import csv, io
    return list(csv.reader(io.StringIO(text, newline=''), strict=True))


class Public:
    """Only the supported local agent protocol: no implementation imports, no private inspection of the native work directory."""
    def __init__(self, client, report):
        self.client, self.report = client, report
        self.checks = []
        self.pages = 0

    def check(self, label, actual, expected):
        assert actual == expected, (label, actual, expected)
        self.checks.append(label)

    def walk(self, resource_id, pointer='', revision=None, max_bytes=4096):
        """Follow exact bounded members of inspect_resource, bound to the first response's revision."""
        page = self.client.call('inspect_resource', resource_id=resource_id, pointer=pointer, max_bytes=max_bytes, revision=revision)
        self.pages += 1
        stamp = page['revision']
        if page['mode'] == 'value': return page['value'], stamp
        result = {} if page['container'] == 'object' else []
        while True:
            for item in page['items']:
                value = item['value'] if 'value' in item else self.walk(resource_id, item['pointer'], stamp, max_bytes)[0]
                if isinstance(result, dict): result[item['key']] = value
                else: result.append(value)
            offset = page['page']['nextOffset']
            if offset is None: return result, stamp
            page = self.client.call('inspect_resource', resource_id=resource_id, pointer=pointer, max_bytes=max_bytes, revision=stamp, offset=offset)
            self.pages += 1

    def resources(self, job):
        found = self.client.call('observe', job_id=job['id'], section='resources')['value']
        return {Path(r['file']).name: r for r in found}

    def run(self, task, draft, revision):
        planned = self.client.call('plan_draft', task_id=task['id'], expected_revision=revision, document_id=draft['document'], draft_revision=draft['revision'])
        job = self.client.call('execute', plan_id=planned['id'], expected_revision=planned['revision'])
        status = self.client.wait(job, 240)
        assert status['status'] == 'succeeded', (status, self.client.call('observe', job_id=job['id'], section='fault'))
        assert self.client.call('verify', job_id=job['id'])['value']['verified']
        return planned['revision'], job


def public_schedule(pub, label, job, source, header, rows, spec, columns_units, selection, units):
    """Inspect the published CSV and JSON of one job through resources and check every GUID, value, origin, unit and absence against hand literals."""
    resources = pub.resources(job)
    assert {'ifc-schedule.csv', 'ifc-schedule.json'} <= set(resources), sorted(resources)
    table, _ = pub.walk(resources['ifc-schedule.csv']['id'])
    pub.check(label + ' CSV columns', table['columns'], header)
    pub.check(label + ' CSV rows (every cell, null token for absence)', table['rows'], rows)
    pub.check(label + ' CSV is only strings with unknown units (units come from the JSON resource)', (table['valueType'], table['units']), ('string', 'unknown'))
    value, stamp = pub.walk(resources['ifc-schedule.json']['id'])
    pub.check(label + ' JSON version/status', (value['version'], value['status']), ('schemaxis.ifcopenshell.schedule/1', 'host-checked-schedule'))
    pub.check(label + ' JSON rows (guid, name, origin and value per cell, missing is null)', value['rows'], json_rows(spec))
    pub.check(label + ' JSON column headers and units', [(c['header'], c.get('unit')) for c in value['columns']], columns_units)
    pub.check(label + ' JSON canonical units', value['units']['canonical'], {'area': 'm2', 'length': 'm', 'volume': 'm3'})
    pub.check(label + ' JSON project units', value['units']['projectUnits'], units)
    pub.check(label + ' JSON selection', value['selection'], selection)
    pub.check(label + ' JSON source identity binds the captured file', (value['source']['sha256'], value['source']['bytes'], value['source']['schema']), (sha256(source.read_bytes()), source.stat().st_size, 'IFC4'))
    pub.check(label + ' JSON review limits', {k: value['review'][k] for k in ('geometryAssessed', 'modelCertified', 'quantityAccuracyCertified')}, {'geometryAssessed': False, 'modelCertified': False, 'quantityAccuracyCertified': False})
    pub.check(label + ' JSON runtime identity', value['runtime'], 'ifcopenshell 0.9.0.post1')
    # The same revision must still be current: a bound re-read of the whole resource proves the pages came from one value.
    again = pub.client.call('inspect_resource', resource_id=resources['ifc-schedule.json']['id'], revision=stamp, max_bytes=65536)
    assert again['revision'] == stamp
    return {'label': label, 'csvResource': resources['ifc-schedule.csv']['id'], 'jsonResource': resources['ifc-schedule.json']['id'], 'jsonRevision': stamp}


def public_loop(out, python, calc, report):
    sys.path.insert(0, str(ROOT / 'tools'))
    from qualify_agent_service import Client
    work = out / 'public'
    work.mkdir()
    locations = {'ifcopenshell': python, **({'calc': str(calc)} if calc else {})}
    config = work / 'locations.json'
    config.write_text(json.dumps({'version': 1, 'locations': locations}, indent=2) + '\n');config.chmod(0o600)
    inputs = work / 'inputs'
    inputs.mkdir()
    for name in ('walls-baseline.ifc', 'walls-variant.ifc', 'walls-areas.ifc'): shutil.copyfile(FIXTURES / name, inputs / name)
    client = Client(work / 'session', config=config)
    pub = Public(client, report)
    loop = {'argv': [str(a) for a in client.process.args], 'steps': []}
    base_columns = [('GUID', None), ('Name', None), ('Fire rating', None), ('External', None), ('Note', None), ('Length (m)', 'm'), ('Height (m)', 'm')]
    mm = {'LENGTHUNIT': {'name': 'METRE', 'prefix': 'MILLI'}}
    try:
        client.call('methods')
        found = client.call('capabilities.search', query='IFC wall schedule')
        loop['search'] = 'capabilities.search "IFC wall schedule" ok'
        task = client.call('create_task', objective='Schedule IFC walls, vary the policy, quantity and source, and inspect the published schedules',
                           allowed_providers=['ifcopenshell'], budget={'maxAttempts': 5, 'maxElapsedSeconds': 600})
        draft = client.call('create_draft', provider='ifcopenshell', name='Wall schedule')
        revision = 0
        # 1 author the baseline, plan, run, verify, inspect
        baseline_source = inputs / 'walls-baseline.ifc'
        draft = client.call('edit_draft', document_id=draft['document'], expected_revision=draft['revision'], source=json.dumps(document('baseline', baseline_source)))
        revision, job = pub.run(task, draft, revision)
        spec = [(GUIDS[0], 'North wall', [('type', '2HR'), ('type', 'true'), ('missing', None), ('occurrence', 2.5), ('occurrence', 3.0)]),
                (GUIDS[1], 'Core wall', [('occurrence', '1HR'), ('type', 'true'), ('occurrence', '+reviewed =later'), ('occurrence', 4.0), ('missing', None)]),
                (GUIDS[2], None, [('occurrence', '0123'), ('missing', None), ('occurrence', '007'), ('occurrence', 1.8), ('occurrence', 2.7)])]
        selection = {'class': 'IfcWall', 'inheritance': 'occurrence-overrides-type', 'missing': 'null', 'order': 'GlobalId ascending', 'walls': 3, 'zeroQuantity': 'accept'}
        loop['steps'].append(public_schedule(pub, 'baseline', job, baseline_source, HEADER, csv_rows(BASELINE_CSV)[1:], spec, base_columns, selection, mm))
        # 2 edit the inheritance policy through an atomic patch; type-supplied values must become absent, occurrence values must stay
        draft = client.call('patch_draft', document_id=draft['document'], expected_revision=draft['revision'], edits=[{'op': 'replace', 'path': '/inheritance', 'value': 'occurrence-only'}])
        revision, job = pub.run(task, draft, revision)
        spec_only = [(GUIDS[0], 'North wall', [('missing', None), ('missing', None), ('missing', None), ('occurrence', 2.5), ('occurrence', 3.0)]),
                     (GUIDS[1], 'Core wall', [('occurrence', '1HR'), ('missing', None), ('occurrence', '+reviewed =later'), ('occurrence', 4.0), ('missing', None)]),
                     spec[2]]
        rows_only = [[GUIDS[0], 'North wall', NULL, NULL, NULL, '2.5', '3.0'], [GUIDS[1], 'Core wall', '1HR', NULL, '+reviewed =later', '4.0', NULL], [GUIDS[2], NULL, '0123', NULL, '007', '1.8', '2.7']]
        loop['steps'].append(public_schedule(pub, 'inheritance occurrence-only', job, baseline_source, HEADER, rows_only, spec_only, base_columns, {**selection, 'inheritance': 'occurrence-only'}, mm))
        # 3 edit the source to the variant file (one stored length differs) and restore the inheritance policy in one atomic group
        variant_source = inputs / 'walls-variant.ifc'
        draft = client.call('patch_draft', document_id=draft['document'], expected_revision=draft['revision'],
                            edits=[{'op': 'replace', 'path': '/inheritance', 'value': 'occurrence-overrides-type'}, {'op': 'replace', 'path': '/source/path', 'value': str(variant_source)}])
        revision, job = pub.run(task, draft, revision)
        spec_variant = [(GUIDS[0], 'North wall', [('type', '2HR'), ('type', 'true'), ('missing', None), ('occurrence', 2.6), ('occurrence', 3.0)]), spec[1], spec[2]]
        rows_variant = [[GUIDS[0], 'North wall', '2HR', 'true', NULL, '2.6', '3.0'], [GUIDS[1], 'Core wall', '1HR', 'true', '+reviewed =later', '4.0', NULL], rows_only[2]]
        loop['steps'].append(public_schedule(pub, 'variant source (length 2.6)', job, variant_source, HEADER, rows_variant, spec_variant, base_columns, selection, mm))
        # 4 replace the whole document with an area/volume schedule: different properties, quantities, units and powers
        areas_source = inputs / 'walls-areas.ifc'
        draft = client.call('edit_draft', document_id=draft['document'], expected_revision=draft['revision'], source=json.dumps(document('areas', areas_source)))
        revision, job = pub.run(task, draft, revision)
        spec_areas = [(GUIDS[0], 'Metric A', [('type', 'false'), ('type', 0.0), ('occurrence', 2.5), ('occurrence', 7.5), ('occurrence', 1.5)]),
                      (GUIDS[1], 'Metric B', [('type', 'false'), ('type', 0.0), ('occurrence', 0.0), ('occurrence', 1.5), ('occurrence', 0.25)])]
        areas_units = [('GUID', None), ('Name', None), ('External', None), ('Count', None), ('Length (m)', 'm'), ('Side area (m2)', 'm2'), ('Volume (m3)', 'm3')]
        area_selection = {'class': 'IfcWall', 'inheritance': 'occurrence-overrides-type', 'missing': 'refuse', 'order': 'GlobalId ascending', 'walls': 2, 'zeroQuantity': 'accept'}
        area_project_units = {'AREAUNIT': {'name': 'SQUARE_METRE', 'prefix': 'MILLI'}, 'LENGTHUNIT': {'name': 'METRE', 'prefix': 'MILLI'}, 'VOLUMEUNIT': {'name': 'CUBIC_METRE', 'prefix': 'MILLI'}}
        loop['steps'].append(public_schedule(pub, 'areas and volumes', job, areas_source, HEADER_AREAS, csv_rows(AREAS_CSV)[1:], spec_areas, areas_units, area_selection, area_project_units))
        # 4b the property-only schedule over a project with no units, replacing the whole document: no unit columns, no project units, same selection rules
        no_units_source = property_only_source(inputs)
        no_units_document = document('baseline', no_units_source, columns=json.loads((EXAMPLES / 'ifcopenshell-baseline.json').read_text())['columns'][:2])
        draft = client.call('edit_draft', document_id=draft['document'], expected_revision=draft['revision'], source=json.dumps(no_units_document))
        revision, job = pub.run(task, draft, revision)
        spec_no_units = [(GUIDS[0], 'North wall', [('type', '2HR'), ('type', 'true')]), (GUIDS[1], 'Core wall', [('occurrence', '1HR'), ('type', 'true')]), (GUIDS[2], None, [('occurrence', '0123'), ('missing', None)])]
        loop['steps'].append(public_schedule(pub, 'property-only, no project units', job, no_units_source, HEADER_PROPERTY_ONLY, csv_rows(PROPERTY_ONLY_CSV)[1:], spec_no_units, [(h, None) for h in HEADER_PROPERTY_ONLY], selection, {}))
        loop['draftRevisions'] = draft['revision']
        # 5 an invalid edit is refused by the public draft tool with its exact structured fault and is not retained as a revision
        refused = client.request('patch_draft', document_id=draft['document'], expected_revision=draft['revision'], edits=[{'op': 'replace', 'path': '/missing', 'value': 'zero'}])
        assert not refused['ok'], refused
        refusal = refused['fault']
        pub.check('public refusal of missing=zero', (refusal['code'], refusal['message'], refusal['location'], refusal['observed'], refusal['recovery']),
                  ('INVALID_ARGUMENT', 'value is not one of the declared choices', '$.arguments.missing', {'value': 'zero'}, "use one of: 'refuse', 'null'"))
        loop['publicInvalid'] = {'fault': refusal['code'], 'location': refusal['location']}
        if calc:
            loop['calcWorkflow'] = public_workflow(pub, client, python, calc, work, inputs, report)
        loop['literalChecks'] = list(pub.checks)
        loop['inspectResourcePages'] = pub.pages
    finally:
        records = list(client.records)
        loop['transport'] = {'requests': len(records), 'requestBytes': sum(r['requestBytes'] for r in records), 'responseBytes': sum(r['responseBytes'] for r in records),
                             'methods': sorted({r['method'] for r in records}), 'calls': [[r['method'], r['requestBytes'], r['responseBytes'], r['ok']] for r in records]}
        report['publicLoop'] = loop
        client.close()


def public_workflow(pub, client, python, calc, work, inputs, report):
    """Author, run, verify and inspect the schedule-to-Calc workflow through the public protocol only."""
    source = inputs / 'workflow-model.ifc'
    shutil.copyfile(FIXTURES / 'walls-baseline.ifc', source)
    columns = [{'name': c, 'kind': k, 'nullable': n} for c, k, n in (('GUID', 'text', False), ('Name', 'text', True), ('Fire rating', 'text', True), ('External', 'text', True), ('Note', 'text', True), ('Length (m)', 'number', True), ('Height (m)', 'number', True))]
    graph = {'version': 'schemaxis.workflow/1', 'operations': [
        {'id': 'schedule', 'document': document('baseline', source)},
        {'id': 'typed', 'document': {'version': 'schemaxis.calc/1', 'nodes': [{'id': 'walls', 'filter': 'readTypedCSV', 'options': {'file': {'$artifact': 'schedule', 'index': 0}, 'nullToken': '\\N', 'columns': columns}}]}}]}
    task = client.call('create_task', objective='Hand the IFC wall schedule to Calc as a typed table', allowed_providers=['ifcopenshell', 'calc'],
                       budget={'maxAttempts': 2, 'maxElapsedSeconds': 600})
    draft = client.call('create_draft', provider='workflow', name='IFC schedule to Calc')
    draft = client.call('edit_draft', document_id=draft['document'], expected_revision=draft['revision'], source=json.dumps(graph))
    revision, job = pub.run(task, draft, 0)
    resources = pub.resources(job)
    names = sorted(resources)
    result = {'resourceNames': names}
    produced = next((r for n, r in resources.items() if n == 'ifc-schedule.csv'), None)
    if produced:
        table, _ = pub.walk(produced['id'])
        pub.check('workflow producer CSV rows', table['rows'], csv_rows(BASELINE_CSV)[1:])
    for name in ('analysis.xlsx', 'analysis.ods'):
        if name not in resources: continue
        data, offset, paged = b'', 0, 0
        while offset is not None:
            page = client.call('resource', resource_id=resources[name]['id'], offset=offset, length=16384)
            import base64
            data += base64.b64decode(page['data']);offset = page['nextOffset'];paged += 1
        copy_path = work / ('public-read-' + name)
        copy_path.write_bytes(data)
        result[name] = {'bytes': len(data), 'sha256': sha256(data), 'pages': paged,
                        'independentOracleCells': check_workbook(copy_path, ROWS, summary_for(ROWS), odf=name.endswith('.ods'))}
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--python', type=Path, required=True, help='absolute interpreter of the private IfcOpenShell 0.9.0.post1 environment (not resolved)')
    parser.add_argument('--calc', type=Path, help='LibreOffice soffice for the typed workbook handoff')
    parser.add_argument('--output-directory', type=Path, required=True)
    parser.add_argument('--conform', action='store_true', help='also run the shared native conformance kit on the committed examples (stages the fixtures at the fixed example path)')
    args = parser.parse_args()
    out = Path(os.path.abspath(args.output_directory))
    if out.exists(): raise SystemExit('select a fresh output directory')
    (out / 'inputs').mkdir(parents=True)
    python = os.path.abspath(args.python)
    report = {'scope': __doc__.split('\n\n')[0], 'cases': {}, 'verified': False, 'startedAt': time.time(), 'argv': sys.argv}
    try:
        def case(name, fixture, example, csv, **change):
            target = out / name
            result = a.run(document(example, FIXTURES / fixture, **change), target, executable=python, timeout=120)
            assert result['verified'] and a.verify(target)['verified']
            assert (target / 'ifc-schedule.csv').read_bytes() == csv.encode(), (name, (target / 'ifc-schedule.csv').read_text())
            report['cases'][name] = {'walls': result['walls'], 'columns': result['columns'], 'csvSha256': sha256(csv.encode())}
            return target
        baseline = case('baseline', 'walls-baseline.ifc', 'baseline', BASELINE_CSV)
        second = case('baseline-second', 'walls-baseline.ifc', 'baseline', BASELINE_CSV)
        assert (baseline / 'ifc-schedule.json').read_bytes() == (second / 'ifc-schedule.json').read_bytes()
        assert (baseline / 'native-extract.json').read_bytes() == (second / 'native-extract.json').read_bytes() == (baseline / 'native-reopen.json').read_bytes()
        variant = case('variant', 'walls-variant.ifc', 'variant', BASELINE_CSV.replace('2.5,3.0', '2.6,3.0'))
        case('areas', 'walls-areas.ifc', 'areas', AREAS_CSV)
        case('metre', 'walls-metre.ifc', 'metre', METRE_CSV)
        report['cases']['areas']['nativeScales'] = json.loads((out / 'areas/native-extract.json').read_text())['scales']
        # fresh native evidence for a property-only schedule with no project units (the source is written here, from the baseline fixture, in this run)
        no_units = property_only_source(out / 'inputs')
        columns = json.loads((EXAMPLES / 'ifcopenshell-baseline.json').read_text())['columns'][:2]
        assert [c['name'] for c in columns] == ['Fire rating', 'External'] and all(c['source'] == 'property' for c in columns), columns
        no_units_run = case('property-only-no-units', no_units, 'baseline', PROPERTY_ONLY_CSV, columns=columns)
        native = json.loads((no_units_run / 'native-extract.json').read_text())
        assert native['scales'] == {}, native['scales']
        assert [r['typeGuid'] for r in native['rows']] == ['0SYN000000000000000002', '0SYN000000000000000002', None], [r['typeGuid'] for r in native['rows']]
        assert [[(c['origin'], c['raw']) for c in r['cells']] for r in native['rows']] == [[('type', '2HR'), ('type', True)], [('occurrence', '1HR'), ('type', True)], [('occurrence', '0123'), ('missing', None)]]
        published = json.loads((no_units_run / 'ifc-schedule.json').read_text())
        assert published['units']['projectUnits'] == {}, published['units']
        report['cases']['property-only-no-units']['nativeScales'] = native['scales']
        report['cases']['property-only-no-units']['sourceSha256'] = sha256(no_units.read_bytes())
        report['runtimeIdentity'] = json.loads((baseline / 'runtime.json').read_text())
        with patch.object(a, 'execute', side_effect=AssertionError('offline verification launched a native process')): a.verify(baseline)
        report['offlineVerificationLaunchedNothing'] = True
        assert a.reusableInputs(document('baseline', FIXTURES / 'walls-baseline.ifc')) != a.reusableInputs(document('variant', FIXTURES / 'walls-variant.ifc'))
        report['preNativeControls'] = []
        pre_native_controls(out, python, report['preNativeControls'])
        report['mutants'] = []
        mutants(baseline, report['mutants'])
        area_mutants(out / 'areas', report['mutants'])
        report['lifecycle'] = {'cancel': live_lifecycle(out, python, 'cancel'), 'timeout': live_lifecycle(out, python, 'timeout')}
        report['handoff'] = {}
        # the supported-protocol loop runs after the direct host checks so a failure there is retained with them
        if args.calc: handoff(out, python, str(args.calc.absolute()), report['handoff'])
        else: report['handoff'] = {'status': 'unavailable', 'reason': 'no --calc executable supplied; not run, not qualified'}
        public_loop(out, python, args.calc.absolute() if args.calc else None, report)
        if args.conform:
            try: STAGING.mkdir(mode=0o700)
            except FileExistsError: raise SystemExit(f'refusing pre-existing staging path {STAGING}; inspect it and move it aside yourself')
            try:
                for name in ('walls-baseline.ifc', 'walls-variant.ifc', 'walls-areas.ifc', 'walls-metre.ifc'): shutil.copyfile(FIXTURES / name, STAGING / name)
                qualify(a.VERSION, out / 'kit', native=True, root=ROOT, locations={'ifcopenshell': python}, timeout=120, wall_timeout=300)
            finally: shutil.move(str(STAGING), str(out / 'conformance-staging-retained'))
            receipt = json.loads((out / 'kit/qualification.json').read_text())
            assert receipt['verified'] is True and receipt['mode'] == 'native', 'shared native conformance receipt did not verify'
            report['conformance'] = {'verified': receipt['verified'], 'mode': receipt['mode'], 'receipt': 'kit/qualification.json (written by the shared conformance kit; not registered)',
                                     'cases': [c.get('id') or c.get('name') for c in receipt['cases']] if all(isinstance(c, dict) for c in receipt['cases']) else receipt['cases']}
        report['verified'] = True
    finally:
        report['finishedAt'] = time.time();atomic_json(out / 'acceptance.json', report)
    print(json.dumps(report, ensure_ascii=False, indent=2))


if __name__ == '__main__': main()
