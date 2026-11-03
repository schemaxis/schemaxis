#!/usr/bin/env python3
# Copyright (C) 2026 David L F Gaden
"""Run release evidence workflows through the native applications and summarise them.

Each manifest workflow runs three times through the ordinary Schemaxis CLI: an
initial run (then ``schemaxis verify``, independent checks and any matching
qualifier), an unchanged ``--resume`` rerun into the same output directory, and a
fresh variant run with one authored parameter changed. ``summary.json`` and
``index.json`` record only run-relative paths, application names and versions.

Dependency-free: Python 3.10+ standard library only. Schemaxis and the native
applications run in subprocesses. Nothing here estimates or invents a value; a
check that cannot read its source records a failure instead.
"""
import argparse
import copy
import csv
import datetime as dt
import fnmatch
import hashlib
import json
import math
import os
from pathlib import Path
import platform
import re
import shutil
import sqlite3
import struct
import subprocess
import sys
import time
from xml.etree import ElementTree as ET
from zipfile import ZipFile

ROOT = Path(__file__).resolve().parents[1]
MANIFEST = Path(__file__).resolve().with_name('release_evidence_manifest.json')
SUMMARY_SCHEMA = 'schemaxis.release-evidence.summary/1'
INDEX_SCHEMA = 'schemaxis.release-evidence.index/1'
CASE_LABEL = 'coupe case (not distributed)'
GAS_CONSTANT = 8.314462618  # J/(mol K), exact SI value
ARGON_MOLAR_MASS = 39.95e-3  # kg/mol, CIAAW conventional atomic weight
SUMMARY_KEYS = ('schema', 'workflowId', 'title', 'status', 'apps', 'inputs', 'variant', 'steps',
                'artifacts', 'verification', 'independentChecks', 'reuse', 'showcase',
                'failures', 'startedAt', 'endedAt', 'wallSeconds', 'machine', 'code')


# ---------------------------------------------------------------- pure helpers

def relativise(value, base):
    """Return ``value`` relative to ``base`` as a POSIX string, or None if outside."""
    try:
        return Path(os.path.abspath(value)).relative_to(os.path.abspath(base)).as_posix()
    except ValueError:
        return None


def scrub_text(text, replacements):
    """Replace known private prefixes, then any remaining absolute filesystem path."""
    for prefix, label in sorted(replacements.items(), key=lambda item: -len(item[0])):
        if prefix:
            text = text.replace(prefix, label)
    return re.sub(r'(?<![\w.<>])/(?:home|tmp|usr|opt|mnt|media|root|var|etc|srv|run)(?:/[^\s"\',;:)\]]+)+',
                  '<absolute-path>', text)


def absolute_paths(value, private=()):
    """List string leaves that look like absolute filesystem paths or private words."""
    found = []
    pattern = re.compile(r'(?<![\w.<>])/(?:home|tmp|usr|opt|mnt|media|root|var|etc|srv|run)/')
    def walk(item, where):
        if isinstance(item, dict):
            for key, child in item.items():
                walk(key, where + '/' + str(key))
                walk(child, where + '/' + str(key))
        elif isinstance(item, list):
            for index, child in enumerate(item):
                walk(child, where + '/' + str(index))
        elif isinstance(item, str):
            if pattern.search(item) or any(word and word in item for word in private):
                found.append(where)
    walk(value, '')
    return found


def json_pointer_get(document, pointer):
    item = document
    for part in pointer.split('/')[1:]:
        part = part.replace('~1', '/').replace('~0', '~')
        item = item[int(part)] if isinstance(item, list) else item[part]
    return item


def json_pointer_set(document, pointer, value):
    parts = [p.replace('~1', '/').replace('~0', '~') for p in pointer.split('/')[1:]]
    parent = json_pointer_get(document, '/' + '/'.join(p.replace('~', '~0').replace('/', '~1') for p in parts[:-1])) if len(parts) > 1 else document
    if isinstance(parent, list):
        parent[int(parts[-1])] = value
    else:
        if parts[-1] not in parent:
            raise KeyError(pointer)
        parent[parts[-1]] = value


def apply_patch(document, operations):
    """Apply a JSON Patch subset (test, replace, add) to a copy of ``document``."""
    document = copy.deepcopy(document)
    for operation in operations:
        kind, pointer = operation['op'], operation['path']
        if kind == 'test':
            if json_pointer_get(document, pointer) != operation['value']:
                raise ValueError('patch test failed at ' + pointer)
        elif kind == 'replace':
            json_pointer_get(document, pointer)
            json_pointer_set(document, pointer, copy.deepcopy(operation['value']))
        elif kind == 'add':
            head, _, last = pointer.rpartition('/')
            parent = json_pointer_get(document, head) if head else document
            if isinstance(parent, list):
                parent.insert(len(parent) if last == '-' else int(last), copy.deepcopy(operation['value']))
            else:
                parent[last] = copy.deepcopy(operation['value'])
        else:
            raise ValueError('unsupported patch operation ' + kind)
    return document


def replace_strings(value, replacements):
    if isinstance(value, dict):
        return {k: replace_strings(v, replacements) for k, v in value.items()}
    if isinstance(value, list):
        return [replace_strings(v, replacements) for v in value]
    if isinstance(value, str):
        for prefix, label in sorted(replacements.items(), key=lambda item: -len(item[0])):
            if prefix and prefix in value:
                value = value.replace(prefix, label)
    return value


def compare(name, observed, reference, *, units=None, relative=None, absolute=None,
            source=None, reference_source=None, note=None):
    """A check record. Passing needs a finite observation within either tolerance."""
    record = {'name': name, 'observed': observed, 'reference': reference, 'units': units,
              'source': source, 'referenceSource': reference_source}
    finite = all(isinstance(v, (int, float)) and math.isfinite(v) for v in (observed, reference))
    if finite:
        difference = observed - reference
        record['difference'] = difference
        record['relativeDifference'] = abs(difference)/abs(reference) if reference else None
        tolerance = {}
        if relative is not None: tolerance['relative'] = relative
        if absolute is not None: tolerance['absolute'] = absolute
        record['tolerance'] = tolerance
        record['passed'] = bool((relative is not None and abs(difference) <= relative*abs(reference)) or
                                (absolute is not None and abs(difference) <= absolute))
    else:
        record.update(difference=None, relativeDifference=None, tolerance=None, passed=False)
    if note: record['note'] = note
    return record


def equal(name, observed, reference, *, source=None, reference_source=None, note=None):
    record = {'name': name, 'observed': observed, 'reference': reference, 'source': source,
              'referenceSource': reference_source, 'passed': observed == reference}
    if note: record['note'] = note
    return record


def tally(checks):
    """Count passes and failures; records with ``passed: None`` are informational."""
    return {'passed': sum(1 for c in checks if c.get('passed') is True),
            'failed': sum(1 for c in checks if c.get('passed') is False or 'passed' not in c),
            'informational': sum(1 for c in checks if 'passed' in c and c['passed'] is None)}


def validate_summary(summary):
    """Return schema problems; an empty list means the summary is well formed."""
    problems = ['missing ' + key for key in SUMMARY_KEYS if key not in summary]
    if summary.get('schema') != SUMMARY_SCHEMA:
        problems.append('schema must be ' + SUMMARY_SCHEMA)
    if summary.get('status') not in ('passed', 'failed', 'partial'):
        problems.append('status must be passed, failed or partial')
    for item in summary.get('showcase', {}).get('files', []):
        for key in ('path', 'sha256', 'bytes'):
            if key not in item: problems.append('showcase file missing ' + key)
        if str(item.get('path', '/')).startswith('/'): problems.append('showcase path is absolute')
    for step in summary.get('steps', []):
        for key in ('name', 'seconds', 'exitCode'):
            if key not in step: problems.append('step missing ' + key)
    for where in absolute_paths(summary):
        problems.append('absolute path at ' + where)
    return problems


def sha256(path):
    digest = hashlib.sha256()
    with open(path, 'rb') as stream:
        for block in iter(lambda: stream.read(1 << 20), b''):
            digest.update(block)
    return digest.hexdigest()


def now():
    return dt.datetime.now().astimezone().isoformat(timespec='seconds')


def png_size(path):
    with open(path, 'rb') as stream:
        head = stream.read(24)
    if head[:8] != b'\x89PNG\r\n\x1a\n':
        raise ValueError('not a PNG')
    return list(struct.unpack('>II', head[16:24]))


def sample_stdev(values):
    if len(values) < 2: return None
    mean = sum(values)/len(values)
    return math.sqrt(sum((v-mean)**2 for v in values)/(len(values)-1))


def householder_least_squares(rows, response):
    """Solve min ||A x - b|| by Householder QR (independent of R and Calc)."""
    a = [list(map(float, r)) for r in rows]
    b = list(map(float, response))
    m, n = len(a), len(a[0])
    for k in range(n):
        norm = math.sqrt(sum(a[i][k]**2 for i in range(k, m)))
        if norm == 0: raise ValueError('rank deficient')
        alpha = -norm if a[k][k] >= 0 else norm
        v = [0.0]*m
        v[k] = a[k][k] - alpha
        for i in range(k+1, m): v[i] = a[i][k]
        vv = sum(x*x for x in v[k:])
        if vv == 0: continue
        for j in range(k, n):
            s = 2*sum(v[i]*a[i][j] for i in range(k, m))/vv
            for i in range(k, m): a[i][j] -= s*v[i]
        s = 2*sum(v[i]*b[i] for i in range(k, m))/vv
        for i in range(k, m): b[i] -= s*v[i]
    x = [0.0]*n
    for k in reversed(range(n)):
        x[k] = (b[k] - sum(a[k][j]*x[j] for j in range(k+1, n)))/a[k][k]
    return x


def read_csv(path):
    with open(path, newline='') as stream:
        rows = list(csv.reader(stream))
    return rows[0], rows[1:]


def vtu_cell_arrays(path):
    """Read named CellData arrays from a VTK XML file (ASCII or raw appended, uncompressed)."""
    data = Path(path).read_bytes()
    marker = data.find(b'<AppendedData')
    head = data if marker < 0 else data[:marker]
    root_tag = re.search(rb'<VTKFile[^>]*>', head).group(0).decode()
    if 'compressor=' in root_tag:
        raise ValueError('compressed VTK XML is not supported by this checker')
    wide = 'header_type="UInt64"' in root_tag
    binary = None
    if marker >= 0:
        start = data.index(b'_', data.index(b'>', marker)) + 1
        binary = data[start:]
    kinds = {'Float64': 'd', 'Float32': 'f', 'Int64': 'q', 'Int32': 'i', 'UInt8': 'B', 'UInt64': 'Q', 'UInt32': 'I'}
    arrays = {}
    for match in re.finditer(rb'<DataArray([^>]*?)/>|<DataArray([^>]*)>(.*?)</DataArray>', head, re.S):
        attributes = (match.group(1) or match.group(2)).decode()
        get = lambda key: (re.search(key + r'="([^"]*)"', attributes) or [None, None])[1]
        name, kind, form = get('Name'), get('type'), get('format')
        if form == 'ascii':
            body = match.group(3).decode()
            body = re.sub(r'<InformationKey.*?</InformationKey>', '', body, flags=re.S)
            arrays[name] = [float(v) for v in body.split()]
        elif form == 'appended':
            offset = int(get('offset'))
            size = struct.unpack('<Q' if wide else '<I', binary[offset:offset+(8 if wide else 4)])[0]
            begin = offset + (8 if wide else 4)
            code = kinds[kind]
            count = size // struct.calcsize(code)
            arrays[name] = list(struct.unpack('<' + code*count, binary[begin:begin+size]))
    return arrays


def tetra_volume_sum(path):
    """Sum of |det|/6 over VTK_TETRA (type 10) cells of an ASCII unstructured grid."""
    arrays = vtu_cell_arrays(path)
    points = arrays['Points']
    connectivity = [int(v) for v in arrays['connectivity']]
    offsets = [int(v) for v in arrays['offsets']]
    types = [int(v) for v in arrays['types']]
    total, count, start = 0.0, 0, 0
    for end, kind in zip(offsets, types):
        if kind == 10:
            p = [points[3*i:3*i+3] for i in connectivity[start:end]]
            u = [p[1][k]-p[0][k] for k in range(3)]
            v = [p[2][k]-p[0][k] for k in range(3)]
            w = [p[3][k]-p[0][k] for k in range(3)]
            det = (u[0]*(v[1]*w[2]-v[2]*w[1]) - u[1]*(v[0]*w[2]-v[2]*w[0]) + u[2]*(v[0]*w[1]-v[1]*w[0]))
            total += abs(det)/6
            count += 1
        start = end
    return total, count


def ods_sheet(path, name):
    ns = {'t': 'urn:oasis:names:tc:opendocument:xmlns:table:1.0',
          'o': 'urn:oasis:names:tc:opendocument:xmlns:office:1.0'}
    with ZipFile(path) as archive:
        tree = ET.fromstring(archive.read('content.xml'))
    sheet = next(s for s in tree.findall('.//t:table', ns) if s.get('{%s}name' % ns['t']) == name)
    rows = []
    for row in sheet.findall('t:table-row', ns):
        cells = []
        for cell in row.findall('t:table-cell', ns):
            repeat = int(cell.get('{%s}number-columns-repeated' % ns['t'], '1'))
            value = cell.get('{%s}value' % ns['o'])
            text = ''.join(cell.itertext())
            cells.extend([float(value) if value is not None else text] * min(repeat, 64))
        rows.append(cells)
    return rows


def xlsx_cells(path, sheet_index=2):
    ns = {'s': 'http://schemas.openxmlformats.org/spreadsheetml/2006/main'}
    with ZipFile(path) as archive:
        tree = ET.fromstring(archive.read('xl/worksheets/sheet%d.xml' % sheet_index))
    cells = {}
    for cell in tree.findall('.//s:c', ns):
        value = cell.findtext('s:v', namespaces=ns)
        if value is not None and cell.get('t') not in ('s', 'str', 'inlineStr'):
            cells[cell.get('r')] = float(value)
    return cells


def calc_summary_checks(label, csv_path, workbook_directory):
    """Recompute COUNT/SUM/AVERAGE/MIN/MAX/STDEV per CSV column and compare with Calc caches."""
    header, rows = read_csv(csv_path)
    ods = ods_sheet(Path(workbook_directory)/'analysis.ods', 'Summary')
    xlsx = xlsx_cells(Path(workbook_directory)/'analysis.xlsx')
    checks = []
    names = [r[0] if r else None for r in ods[1:]]
    checks.append(equal(label + ': Summary column order', names[:len(header)], header,
                        source='analysis.ods Summary sheet', reference_source='CSV header'))
    for index, column in enumerate(header):
        try:
            values = [float(r[index]) for r in rows]
        except ValueError:
            continue
        expected = {'COUNT': len(values), 'SUM': math.fsum(values), 'AVERAGE': math.fsum(values)/len(values),
                    'MIN': min(values), 'MAX': max(values), 'STDEV': sample_stdev(values)}
        row = ods[index+1]
        for offset, statistic in enumerate(('COUNT', 'SUM', 'AVERAGE', 'MIN', 'MAX', 'STDEV'), start=1):
            reference = expected[statistic]
            if reference is None: continue
            scale = max(1.0, max(abs(v) for v in values)) * len(values)
            address = 'ABCDEFG'[offset] + str(index+2)
            for workbook, observed in (('ODS', row[offset] if offset < len(row) else None),
                                       ('XLSX', xlsx.get(address))):
                checks.append(compare('%s: %s %s(%s) [%s]' % (label, workbook, statistic, column, address),
                                      observed, reference, relative=1e-9, absolute=1e-12*scale,
                                      source='Calc cached value in analysis.' + workbook.lower(),
                                      reference_source='recomputed from the producer CSV'))
    return checks


# ---------------------------------------------------------------- environment

def machine():
    info = {'architecture': platform.machine(), 'os': None, 'kernel': os.uname().release,
            'cpuModel': None, 'logicalCpus': os.cpu_count(), 'physicalCores': None,
            'sockets': None, 'memoryGiB': None, 'python': platform.python_version()}
    try:
        lscpu = subprocess.run(['lscpu'], capture_output=True, text=True, timeout=20,
                               env={**os.environ, 'LC_ALL': 'C'}).stdout
        fields = dict(line.split(':', 1) for line in lscpu.splitlines() if ':' in line)
        fields = {k.strip(): v.strip() for k, v in fields.items()}
        info['cpuModel'] = fields.get('Model name')
        if fields.get('Core(s) per socket') and fields.get('Socket(s)'):
            info['sockets'] = int(fields['Socket(s)'])
            info['physicalCores'] = int(fields['Core(s) per socket']) * info['sockets']
    except (OSError, subprocess.SubprocessError, ValueError):
        pass
    try:
        for line in Path('/proc/meminfo').read_text().splitlines():
            if line.startswith('MemTotal:'):
                info['memoryGiB'] = round(int(line.split()[1])/1024/1024, 1)
    except OSError:
        pass
    try:
        release = dict(line.split('=', 1) for line in Path('/etc/os-release').read_text().splitlines() if '=' in line)
        info['os'] = release.get('PRETTY_NAME', '').strip('"') or None
    except OSError:
        info['os'] = platform.system()
    return info


def code_identity(runner=Path(__file__), manifest=MANIFEST):
    def git(*args):
        try:
            return subprocess.run(['git', '-C', str(ROOT), *args], capture_output=True, text=True,
                                  timeout=30).stdout.strip()
        except (OSError, subprocess.SubprocessError):
            return None
    status = git('status', '--porcelain', '--untracked-files=no')
    return {'repositoryCommit': git('rev-parse', 'HEAD'),
            'trackedChangesUncommitted': bool(status) if status is not None else None,
            'runnerSHA256': sha256(runner), 'manifestSHA256': sha256(manifest)}


# ---------------------------------------------------------------- runner

class Context:
    def __init__(self, args, manifest):
        self.manifest = manifest
        self.config = Path(args.config).resolve()
        self.locations = json.loads(self.config.read_text())['locations']
        self.output = Path(args.output_root).resolve()
        self.case = args.case
        self.python = sys.executable
        self.machine = machine()
        self.code = code_identity()
        private = {str(ROOT): '<repository>', str(self.config): '<runtime-config>',
                   str(Path.home()): '~'}
        if self.case:
            private[str(Path(self.case).resolve().parent)] = '<' + CASE_LABEL + '>'
            private[self.case] = '<' + CASE_LABEL + '>'
        self.private = private
        self.words = [w for w in (os.environ.get('USER'), platform.node()) if w]

    def ffprobe(self):
        return Path(self.locations['ffmpeg']).with_name('ffprobe')


class Workflow:
    def __init__(self, context, spec):
        self.ctx, self.spec = context, spec
        self.dir = context.output / spec['id']
        self.steps, self.failures, self.notes = [], [], list(spec.get('notes', []))
        self.private = {str(self.dir) + '/': '', str(self.dir): '.', **context.private}

    # -- paths and logging
    def rel(self, path):
        value = relativise(path, self.dir)
        if value is None:
            raise ValueError('path outside the workflow directory')
        return value

    def scrub(self, text):
        text = scrub_text(text, self.private)
        for word in self.ctx.words:
            text = text.replace(word, '<redacted>')
        return text

    def public_command(self, command):
        return [self.scrub(str(Path(part).name if part == self.ctx.python else part)) for part in command]

    def execute(self, name, command, *, part=None, phase=None, display=False, timeout=None, cwd=ROOT):
        log = self.dir/'logs'/(name + ('-' + part if part else '') + '.log')
        log.parent.mkdir(parents=True, exist_ok=True)
        if display:
            command = ['xvfb-run', '-a', '-s', '-screen 0 1280x1024x24', *command]
        env = {**os.environ, 'PYTHONPATH': str(ROOT/'src'), 'SCHEMAXIS_CONFIG': str(self.ctx.config),
               'PYTHONUNBUFFERED': '1'}
        started, clock = now(), time.monotonic()
        try:
            with log.open('w') as stream:
                process = subprocess.run([str(c) for c in command], cwd=cwd, env=env, stdout=stream,
                                         stderr=subprocess.STDOUT, timeout=timeout or 3600)
            code = process.returncode
        except subprocess.TimeoutExpired:
            code = 'timeout'
        seconds = round(time.monotonic() - clock, 3)
        step = {'name': name, 'part': part, 'phase': phase, 'startedAt': started, 'endedAt': now(),
                'seconds': seconds, 'exitCode': code, 'log': self.rel(log),
                'command': self.public_command(command)}
        self.steps.append(step)
        text = log.read_text(errors='replace')
        if code != 0:
            self.failures.append({'step': name, 'part': part, 'exitCode': code,
                                  'faultCode': fault_code(text),
                                  'logExcerpt': self.scrub('\n'.join(text.splitlines()[-40:]))})
        return code, text, step

    # -- documents
    def document(self, part):
        source = part['input']
        if 'example' in source:
            document = json.loads((ROOT/source['example']).read_text())
            origin = source['example']
        else:
            demo = ROOT/self.ctx.manifest['demoDirectory']/'demo.py'
            command = [self.ctx.python, demo, 'export', source['demo']]
            if self.ctx.case:
                command += ['--case', self.ctx.case]
            result = subprocess.run([str(c) for c in command], cwd=ROOT, capture_output=True, text=True,
                                    timeout=120, check=True)
            document = json.loads(Path(result.stdout.strip().splitlines()[-1]).read_text())
            origin = self.ctx.manifest['demoDirectory'] + '/demo.py export ' + source['demo']
        if source.get('wrapOperation'):
            # The demo's own workflow resources; an execution block selects the
            # scheduled engine, which records per-job reuse.
            document = {'version': 'schemaxis.workflow/1',
                        'execution': {'maxWorkers': 1, 'cpus': 4, 'memoryMB': 12000, 'gpus': 0},
                        'operations': [{'id': source['wrapOperation'], 'document': document}]}
            origin += ' (wrapped as workflow operation ' + source['wrapOperation'] + ')'
        if part.get('adjustments'):
            document = apply_patch(document, part['adjustments']['operations'])
            origin += ' with authored adjustments (see adjustments)'
        return document, origin

    def variant(self, part, document):
        changed = copy.deepcopy(document)
        for change in self.spec['variant']['changes']:
            if change['part'] != part['id']: continue
            current = json_pointer_get(changed, change['pointer'])
            if current != change['from']:
                raise ValueError('variant base value differs at ' + change['pointer'])
            json_pointer_set(changed, change['pointer'], change['to'])
        return changed

    def write_input(self, name, document):
        private = self.dir/'work'/(name + '.json')
        private.parent.mkdir(parents=True, exist_ok=True)
        private.write_text(json.dumps(document, indent=2) + '\n')
        public = self.dir/'input'/(name + '.json')
        public.parent.mkdir(parents=True, exist_ok=True)
        public.write_text(json.dumps(replace_strings(document, self.private), indent=2) + '\n')
        return private, public

    # -- schemaxis
    def schemaxis_run(self, name, part, phase, document_path, target, *, resume=False):
        command = [self.ctx.python, '-m', 'schemaxis', 'run', document_path, '--output-directory', target,
                   '--timeout', str(self.spec.get('timeout', self.ctx.manifest.get('timeout', 600)))]
        if resume: command.append('--resume')
        code, text, step = self.execute(name, command, part=part, phase=phase,
                                        display=self.spec.get('display', False))
        result = None
        if (Path(target)/'result.json').is_file():
            result = json.loads((Path(target)/'result.json').read_text())
        return code, result, step

    def schemaxis_verify(self, part, phase, target):
        code, text, step = self.execute('verify-' + phase, [self.ctx.python, '-m', 'schemaxis', 'verify', target],
                                        part=part, phase=phase)
        parsed = last_json(text) or {}
        return {'part': part, 'phase': phase, 'verified': code == 0 and parsed.get('verified') is True,
                'jobs': parsed.get('jobs'), 'operations': parsed.get('operations'),
                'artifacts': parsed.get('artifacts'), 'seconds': step['seconds']}

    def jobs(self, result):
        if not result: return []
        out = []
        for item in result.get('operations', []) if 'jobs' not in result else []:
            # Sequential (unscheduled) workflows record operations, not jobs.
            out.append({'job': item['id'], 'operation': item['id'], 'status': item.get('status'),
                        'reused': False, 'seconds': None,
                        'directory': self.rel(item['directory']) if item.get('directory') else None})
        for job in result.get('jobs', []):
            directory = job.get('directory')
            out.append({'job': job['id'], 'operation': job['operation'], 'status': job.get('status'),
                        'reused': bool(job.get('reused')), 'seconds': job.get('seconds'),
                        'directory': self.rel(directory) if directory else None})
        return out

    def artifacts(self, jobs):
        files = []
        for job in jobs:
            if not job['directory']: continue
            for artifact in receipt_artifacts(self.dir/job['directory']):
                path = relativise(artifact['file'], self.dir)
                if path is None: continue
                files.append({'operation': job['operation'], 'path': path,
                              'kind': artifact.get('kind', artifact.get('identity', {}).get('kind')),
                              'sha256': artifact.get('sha256')})
        return files

    def versions(self, jobs, documents):
        found = {}
        for job in jobs:
            if not job['directory']: continue
            app = application(operation_version(documents, job['operation']))
            version = runtime_version(self.dir/job['directory'], app)
            if version: found.setdefault(app, set()).add(self.scrub(version))
        return [{'name': app, 'version': sorted(values)[0] if len(values) == 1 else sorted(values)}
                for app, values in sorted(found.items())]


def fault_code(text):
    parsed = last_json(text)
    if isinstance(parsed, dict) and isinstance(parsed.get('fault'), dict):
        return parsed['fault'].get('code')
    match = re.findall(r'"code":\s*"([A-Z_]+)"', text)
    return match[-1] if match else None


def last_json(text):
    """Parse the final top-level JSON object printed by the CLI."""
    for start in [m.start() for m in re.finditer(r'(?m)^\{', text)][::-1]:
        try:
            return json.loads(text[start:])
        except ValueError:
            continue
    return None


def receipt_artifacts(directory):
    receipt = Path(directory)/'verification.json'
    if not receipt.is_file(): return []
    data = json.loads(receipt.read_text())
    artifacts = list(data.get('artifacts', []))
    # Isolated-visit adaptors publish per-state receipts listed in the parent.
    if not artifacts:
        for child in sorted(Path(directory).glob('state-*/verification.json')):
            artifacts.extend(json.loads(child.read_text()).get('artifacts', []))
    return artifacts


def operation_version(documents, operation):
    for document in documents:
        for item in document.get('operations', []):
            if item['id'] == operation:
                return item['document'].get('version')
    return None


def application(version):
    if version == 'schemaxis/1': return 'paraview'
    match = re.fullmatch(r'schemaxis\.([a-z]+)(?:\.[a-z]+)?/\d+', version or '')
    return match.group(1) if match else 'unknown'


def runtime_version(directory, app):
    """The version string recorded from the native application itself."""
    def text(value):
        if isinstance(value, dict):
            name, version = value.get('name'), value.get('version')
            return ' '.join(str(v) for v in (name, version) if v) or None
        if isinstance(value, list) and value and all(isinstance(v, str) for v in value):
            # FreeCAD reports (major, minor, patch, revision, ...).
            return 'FreeCAD ' + '.'.join(value[:3]) + (' (' + value[3] + ')' if len(value) > 3 else '')
        if isinstance(value, str): return value.strip() or None
        return None
    candidates = [directory/'verification.json', directory/'result.json', directory/'runtime.json', directory/'built.json']
    candidates += sorted(directory.glob('state-*/verification.json')) + sorted(directory.glob('state-*/built.json'))
    for path in candidates:
        if path.is_file():
            data = json.loads(path.read_text())
            value = text(data.get('runtime') or (data if path.name == 'runtime.json' else None))
            if value:
                value = re.sub(r'^This is Version\s*', '', value)
                value = re.sub(r'\s+Copyright.*$', '', value)
                return value if app_label(app).lower() in value.lower() else app_label(app) + ' ' + value
    for path in sorted(directory.glob('**/*.metrics.json')):
        interpreter = json.loads(path.read_text()).get('interpreter', {})
        if interpreter.get('version'):
            return app_label(interpreter.get('kind', app)) + ' ' + interpreter['version']
    return None


def app_label(app):
    return {'paraview': 'ParaView', 'qgis': 'QGIS', 'godot': 'Godot', 'blender': 'Blender',
            'aseprite': 'Aseprite', 'ffmpeg': 'FFmpeg', 'calc': 'LibreOffice', 'r': 'R',
            'gmsh': 'Gmsh', 'cantera': 'Cantera', 'ngspice': 'ngspice', 'calculix': 'CalculiX',
            'inkscape': 'Inkscape', 'shotcut': 'Shotcut', 'freecad': 'FreeCAD'}.get(app, app)


# ---------------------------------------------------------------- independent checks

class Phase:
    """Native outputs of one phase (initial or variant) for check functions."""
    def __init__(self, workflow, name, parts):
        self.workflow, self.name, self.parts = workflow, name, parts  # part -> {document, jobs}

    def job_dir(self, part, operation):
        for job in self.parts[part]['jobs']:
            if job['operation'] == operation and job['directory']:
                return self.workflow.dir/job['directory']
        raise FileNotFoundError(operation)

    def operation(self, part, operation):
        for item in self.parts[part]['document']['operations']:
            if item['id'] == operation: return item['document']
        raise KeyError(operation)

    def artifacts(self, part, operation=None, pattern='*'):
        return [self.workflow.dir/a['path'] for a in self.parts[part]['artifacts']
                if (operation is None or a['operation'] == operation)
                and fnmatch.fnmatch(Path(a['path']).name, pattern)]


def ffprobe_video(context, path):
    command = [str(context.ffprobe()), '-v', 'error', '-count_frames', '-select_streams', 'v:0',
               '-show_entries', 'stream=width,height,r_frame_rate,nb_read_frames,codec_name,pix_fmt',
               '-of', 'json', str(path)]
    stream = json.loads(subprocess.run(command, capture_output=True, text=True, timeout=300,
                                       check=True).stdout)['streams'][0]
    numerator, denominator = stream['r_frame_rate'].split('/')
    return {'width': stream['width'], 'height': stream['height'], 'frames': int(stream['nb_read_frames']),
            'fps': float(numerator)/float(denominator), 'codec': stream['codec_name'],
            'pixelFormat': stream.get('pix_fmt')}


def video_checks(context, label, path, frames, fps, size):
    probe = ffprobe_video(context, path)
    source = 'ffprobe (configured FFmpeg sibling) decoding ' + path.name
    return [equal(label + ': decoded frame count', probe['frames'], frames, source=source,
                  reference_source='authored frame list'),
            compare(label + ': frame rate', probe['fps'], fps, units='frames/s', absolute=1e-9, source=source,
                    reference_source='authored fps'),
            equal(label + ': frame size', [probe['width'], probe['height']], size, source=source,
                  reference_source='authored size')]


def image_checks(label, paths, size):
    sizes = {}
    for path in paths:
        sizes.setdefault(tuple(png_size(path)), []).append(path.name)
    return [equal(label + ': PNG header sizes of %d images' % len(paths), sorted(list(k) for k in sizes), [size],
                  source='PNG IHDR headers', reference_source='authored image size')]


def check_beam(context, phase):
    beam = phase.operation('main', 'beam')
    length, width, height = beam['beam']['length_m'], beam['beam']['width_m'], beam['beam']['height_m']
    modulus, force = beam['material']['youngsModulus_Pa'], beam['load']['tipForceZ_N']
    inertia = width*height**3/12
    theory = force*length**3/(3*modulus*inertia)
    directory = phase.job_dir('main', 'beam')
    assessment = json.loads((directory/'beam-assessment.json').read_text())
    checks = []
    for mesh in ('coarse', 'axial', 'fine'):
        native = assessment['native'][mesh]
        checks.append(compare('tip deflection, %s mesh %s' % (mesh, 'x'.join(map(str, native['cells']))),
                              native['tipAreaMeanDisplacement_m'][2], theory, units='m', relative=0.006,
                              source='CalculiX 2.23 tip-face area-mean Uz (beam-assessment.json)',
                              reference_source='Euler-Bernoulli F L^3/(3 E I) from the authored input',
                              note='Tolerance as in tools/qualify_beam_workbook.py; shear deformation is not in the reference.'))
    fine = assessment['native']['fine']
    checks.append(compare('root reaction Fz (fine)', fine['rootReaction_N'][2], -force, units='N', relative=1e-4,
                          source='CalculiX reaction sum', reference_source='static equilibrium'))
    checks.append(compare('root moment My (fine)', fine['rootMomentAboutClampCentre_Nm'][1], force*length,
                          units='N m', relative=1e-4, source='CalculiX reaction moment',
                          reference_source='static equilibrium F L'))
    stress_csv = directory/'interior-stress.csv'
    checks += calc_summary_checks('workbook', stress_csv, phase.job_dir('main', 'workbook'))
    return checks


def check_rlc(context, phase):
    circuit = phase.operation('main', 'circuit')
    spec = circuit['circuit']
    resistance = spec['resistors'][0]['resistance']
    inductance = spec['inductors'][0]['inductance']
    capacitance = spec['capacitors'][0]['capacitance']
    amplitude = circuit.get('amplitude', 1)
    directory = phase.job_dir('main', 'circuit')
    header, rows = read_csv(directory/'results.csv')
    column = {name: i for i, name in enumerate(header)}
    worst, worst_magnitude, worst_phase = 0.0, 0.0, 0.0
    for row in rows:
        frequency = float(row[column['frequency_Hz']])
        omega = 2*math.pi*frequency
        expected = amplitude/complex(1 - omega**2*inductance*capacitance, omega*resistance*capacitance)
        observed = complex(float(row[column['out_real_V']]), float(row[column['out_imag_V']]))
        worst = max(worst, abs(observed - expected))
        worst_magnitude = max(worst_magnitude, abs(float(row[column['out_magnitude_V']]) - abs(expected)))
        phase_difference = (float(row[column['out_phase_deg']]) - math.degrees(math.atan2(expected.imag, expected.real)) + 180) % 360 - 180
        worst_phase = max(worst_phase, abs(phase_difference))
    reference = 'closed form V_out/V_in = 1/(1 - w^2 L C + j w R C) from the authored R, L, C'
    resonance = 1/(2*math.pi*math.sqrt(inductance*capacitance))
    checks = [compare('max |complex V_out - closed form| over %d points' % len(rows), worst, 0.0, units='V',
                      absolute=1e-9, source='ngspice AC sweep (results.csv)', reference_source=reference),
              compare('max |magnitude - closed form|', worst_magnitude, 0.0, units='V', absolute=1e-9,
                      source='ngspice AC sweep (results.csv)', reference_source=reference),
              compare('max |phase - closed form|', worst_phase, 0.0, units='degree', absolute=1e-6,
                      source='ngspice AC sweep (results.csv)', reference_source=reference)]
    nearest = min(rows, key=lambda r: abs(float(r[column['frequency_Hz']]) - resonance))
    q_reference = math.sqrt(inductance/capacitance)/resistance
    checks.append(compare('|V_out| at the swept point nearest resonance (%.6g Hz)' % float(nearest[column['frequency_Hz']]),
                          float(nearest[column['out_magnitude_V']]),
                          abs(amplitude/complex(1 - (2*math.pi*float(nearest[column['frequency_Hz']]))**2*inductance*capacitance,
                                                2*math.pi*float(nearest[column['frequency_Hz']])*resistance*capacitance)),
                          units='V', absolute=1e-9, source='ngspice', reference_source=reference,
                          note='Resonance f0 = %.6g Hz; series Q = sqrt(L/C)/R = %.6g.' % (resonance, q_reference)))
    checks += calc_summary_checks('workbook', directory/'results.csv', phase.job_dir('main', 'workbook'))
    return checks


def check_regression(context, phase):
    model = phase.operation('main', 'regression')
    training, heldout = model['training'], model['heldout']
    width = len(training[0]) - 1
    coefficients = householder_least_squares([[1.0, *r[:width]] for r in training], [r[width] for r in training])
    predict = lambda r: coefficients[0] + sum(c*x for c, x in zip(coefficients[1:], r[:width]))
    train_residuals = [r[width] - predict(r) for r in training]
    held_residuals = [r[width] - predict(r) for r in heldout]
    rmse = math.sqrt(sum(e*e for e in train_residuals)/len(train_residuals))
    held_max = max(abs(e) for e in held_residuals)
    directory = phase.job_dir('main', 'regression')
    summary = json.loads((directory/'regression-summary.json').read_text())
    source = 'R ' + 'lm()-based adaptor regression-summary.json'
    reference = 'independent Householder QR least squares on the authored rows'
    checks = []
    for term, value in zip(summary['coefficients'], coefficients):
        checks.append(compare('coefficient ' + term['term'], term['estimate'], value, relative=1e-10,
                              absolute=1e-12, source=source, reference_source=reference))
    checks.append(compare('training RMSE', summary['metrics']['training']['rmse'], rmse, units=model['response'].get('unit'),
                          relative=1e-9, absolute=1e-12, source=source, reference_source=reference))
    checks.append(compare('held-out max absolute error', summary['metrics']['heldout']['maxAbsoluteError'], held_max,
                          units=model['response'].get('unit'), relative=1e-9, absolute=1e-12,
                          source=source, reference_source=reference))
    header, rows = read_csv(directory/'heldout.csv')
    predicted = [float(r[header.index('prediction')]) for r in rows]
    for index, (value, row) in enumerate(zip(predicted, heldout)):
        checks.append(compare('held-out prediction %d' % index, value, predict(row), relative=1e-10, absolute=1e-12,
                              source='R heldout.csv', reference_source=reference))
    checks += calc_summary_checks('workbook', directory/'heldout.csv', phase.job_dir('main', 'workbook'))
    return checks


def check_cantera(context, phase):
    directory = phase.job_dir('main', 'chemistry')
    header, rows = read_csv(directory/'results.csv')
    get = lambda row, name: float(row[header.index(name)])
    specific = GAS_CONSTANT/ARGON_MOLAR_MASS
    source = 'Cantera results.csv'
    reference = 'monatomic ideal gas: cp = 5/2 R/M, cv = 3/2 R/M, rho = p M/(R T); M(Ar) = 39.95 g/mol'
    checks = []
    for row in rows:
        temperature = get(row, 'temperature_K')
        checks.append(compare('cp at %g K' % temperature, get(row, 'cp_J_kg_K'), 2.5*specific, units='J/(kg K)',
                              relative=1e-4, source=source, reference_source=reference))
        checks.append(compare('cv at %g K' % temperature, get(row, 'cv_J_kg_K'), 1.5*specific, units='J/(kg K)',
                              relative=1e-4, source=source, reference_source=reference))
        checks.append(compare('density at %g K' % temperature, get(row, 'density_kg_m3'),
                              get(row, 'pressure_Pa')*ARGON_MOLAR_MASS/(GAS_CONSTANT*temperature),
                              units='kg/m^3', relative=1e-4, source=source, reference_source=reference))
    for first, second in zip(rows, rows[1:]):
        t0, t1 = get(first, 'temperature_K'), get(second, 'temperature_K')
        checks.append(compare('enthalpy rise %g K -> %g K' % (t0, t1),
                              get(second, 'enthalpy_J_kg') - get(first, 'enthalpy_J_kg'), 2.5*specific*(t1 - t0),
                              units='J/kg', relative=1e-4, source=source, reference_source=reference))
    checks += calc_summary_checks('workbook', directory/'results.csv', phase.job_dir('main', 'workbook'))
    return checks


def check_box_mesh(context, phase):
    options = phase.operation('main', 'cad')['nodes'][0]['options']
    length, width, height = options['length'], options['width'], options['height']
    analytic = length*width*height
    reference = 'analytic box volume L x W x H = %g x %g x %g mm' % (length, width, height)
    mesh = phase.job_dir('main', 'mesh')
    summary = json.loads((mesh/'mesh-summary.json').read_text())
    tetra, count = tetra_volume_sum(mesh/'volume.vtu')
    checks = [compare('Gmsh-reported mesh volume', summary['volume'], analytic, units='mm^3', relative=1e-9,
                      source='Gmsh mesh-summary.json', reference_source=reference),
              compare('sum of %d tetrahedron volumes recomputed from volume.vtu' % count, tetra, analytic,
                      units='mm^3', relative=1e-9, source='independent determinant sum over volume.vtu',
                      reference_source=reference)]
    integrals = [p for p in phase.artifacts('main', 'inspect', '*.vtu')
                 if 'Volume' in vtu_cell_arrays(p) and len(vtu_cell_arrays(p)['Volume']) == 1]
    if integrals:
        checks.append(compare('ParaView integrated volume', vtu_cell_arrays(integrals[0])['Volume'][0], analytic,
                              units='mm^3', relative=1e-9,
                              source='ParaView 5.13.3 IntegrateVariables output (' + integrals[0].name + ')',
                              reference_source=reference))
    else:
        checks.append({'name': 'ParaView integrated volume', 'passed': False, 'note': 'no single-cell Volume output found'})
    for group in summary['boundaryGroups']:
        if group['name'] in ('fixed', 'loaded'):
            checks.append(compare('face group "%s" area' % group['name'], group['area'], width*height, units='mm^2',
                                  relative=1e-9, source='Gmsh mesh-summary.json',
                                  reference_source='analytic end-face area W x H'))
    return checks


def check_pipe(context, phase):
    cad = phase.operation('main', 'cad')['dimensions']
    analytic = math.pi*(cad['outerRadius']**2 - cad['innerRadius']**2)*cad['bendRadius']*math.radians(cad['bendAngle'])
    receipts = sorted(phase.job_dir('main', 'cad').glob('**/verification.json'))
    volumes = [json.loads(p.read_text()).get('native', {}).get('volume') for p in receipts]
    volumes = [v for v in volumes if v is not None]
    reference = 'Pappus: pi (Ro^2 - Ri^2) x R_bend x angle'
    checks = [compare('FreeCAD solid volume', volumes[0] if volumes else None, analytic, units='mm^3',
                      relative=1e-9, source='FreeCAD 1.1.3 OCC solid volume (receipt)', reference_source=reference)]
    frames = len([a for a in phase.parts['main']['artifacts'] if a['operation'] == 'render' and a['path'].endswith('.png')])
    movie = phase.operation('main', 'movie')['nodes'][0]['options']
    checks += image_checks('Blender orbit frames', phase.artifacts('main', 'render', '*.png'),
                           phase.operation('main', 'render')['scenes'][0]['images'][0]['size'])
    videos = phase.artifacts('main', 'movie', '*.mp4') + phase.artifacts('main', 'movie', '*.mkv')
    checks += video_checks(context, 'orbit movie', videos[0], len(movie['files']), movie['fps'],
                           phase.operation('main', 'render')['scenes'][0]['images'][0]['size'])
    checks.append(equal('rendered frames equal authored orbit count', frames, len(movie['files']),
                        source='published receipts', reference_source='authored movie frame list'))
    return checks


def check_diagram(context, phase):
    edit = phase.operation('main', 'edit')['nodes'][0]['options']
    animation = phase.operation('main', 'animation')['nodes'][0]['options']
    size = [edit['width'], edit['height']]
    checks = video_checks(context, 'FFmpeg animation', phase.artifacts('main', 'animation', '*.mkv')[0],
                          len(animation['files']), animation['fps'], size)
    checks += video_checks(context, 'Shotcut/MLT edit', phase.artifacts('main', 'edit', 'video.mkv')[0],
                           sum(c['frameCount'] for c in edit['clips']), edit['fps'], size)
    project = phase.artifacts('main', 'edit', '*.mlt')[0]
    playlists = [p for p in ET.parse(project).getroot().iter('playlist') if p.get('id') == 'timeline']
    entries = [[int(e.get('in')), int(e.get('out'))] for e in playlists[0].findall('entry')] if playlists else None
    checks.append(equal('MLT timeline entry ranges', entries,
                        [[c['startFrame'], c['startFrame'] + c['frameCount'] - 1] for c in edit['clips']],
                        source='project.mlt XML', reference_source='authored clips'))
    for operation in ('baseline', 'variant'):
        dpi = phase.operation('main', operation)['dpi']
        document = phase.operation('main', operation)
        expected = [round(document['width']/25.4*dpi), round(document['height']/25.4*dpi)]
        checks.append(equal(operation + ' PNG size', png_size(phase.artifacts('main', operation, '*.png')[0]),
                            expected, source='PNG IHDR header', reference_source='authored mm size x dpi'))
    return checks


def check_coupe(context, phase):
    checks = []
    pv = phase.parts['slices']
    document = pv['document']['operations'][0]['document']
    run = phase.job_dir('slices', 'vehicle')
    selection = json.loads((run/'time-selection.json').read_text())
    inspected = json.loads((run/'inspection.json').read_text())['times']
    checks.append(equal('selected time is the latest inspected time', [t['value'] for t in selection['times']],
                        [max(inspected)], source='ParaView time-selection.json',
                        reference_source='times listed by native inspection'))
    size = document['settings']['imageSize']
    images = phase.artifacts('slices', 'vehicle', '*.png')
    checks += image_checks('ParaView slices/orbit/streamlines', images, size)
    slices = 3*document['settings']['sliceCount']*2
    expected = slices + document['settings']['orbitCount'] + len(document['dimensions']['stream']['sweepZ'])
    checks.append(equal('ParaView image count', len(images), expected, source='published receipts',
                        reference_source='3 slice axes x sliceCount x 2 colourings + orbitCount + seed heights'))
    render = phase.operation('presentation', 'render')
    movie = phase.operation('presentation', 'movie')['nodes'][0]['options']
    frames = phase.artifacts('presentation', 'render', '*.png')
    checks += image_checks('Blender orbit frames', frames, render['scenes'][0]['images'][0]['size'])
    checks.append(equal('Blender frame count', len(frames), len(movie['files']), source='published receipts',
                        reference_source='authored orbit frame count'))
    videos = phase.artifacts('presentation', 'movie', '*.mp4')
    checks += video_checks(context, 'orbit movie', videos[0], len(movie['files']), movie['fps'],
                           render['scenes'][0]['images'][0]['size'])
    if context.case:
        checks.append(case_cells(Path(context.case).parent))
    return checks


def case_cells(case):
    """Cell count from the OpenFOAM owner-file header notes (metadata, not computed here)."""
    import gzip
    counts = []
    owners = sorted(case.glob('processor*/constant/polyMesh/owner*')) or sorted(case.glob('constant/polyMesh/owner*'))
    for owner in owners:
        opener = gzip.open if owner.suffix == '.gz' else open
        with opener(owner, 'rb') as stream:
            header = stream.read(4096).decode('latin-1')
        match = re.search(r'nCells:\s*(\d+)', header)
        counts.append(int(match.group(1)) if match else None)
    total = sum(counts) if counts and None not in counts else None
    return {'name': 'mesh cell count', 'observed': total, 'passed': None if total else False,
            'source': 'nCells in the polyMesh owner header notes of %d mesh pieces' % len(counts),
            'note': 'Case metadata written by the mesher; reported for context, not computed or checked by Schemaxis.'}


def check_media(context, phase):
    checks = []
    for part, info in phase.parts.items():
        for artifact in info['artifacts']:
            if artifact['path'].endswith('.png'):
                size = png_size(phase.workflow.dir/artifact['path'])
                checks.append({'name': '%s %s PNG decodes' % (artifact['operation'], Path(artifact['path']).name),
                               'observed': size, 'passed': size[0] > 0 and size[1] > 0, 'source': 'PNG IHDR header'})
        for path in [phase.workflow.dir/a['path'] for a in info['artifacts'] if a['path'].endswith(('.mp4', '.mkv'))]:
            probe = ffprobe_video(context, path)
            checks.append({'name': Path(path).name + ' decodes', 'observed': probe,
                           'passed': probe['frames'] > 0, 'source': 'ffprobe'})
    return checks


def check_site(context, phase):
    checks = check_media(context, phase)
    qgis = phase.operation('main', 'map')
    gpkg = phase.artifacts('main', 'map', '*.gpkg')
    if gpkg:
        bounds = qgis['dimensions']['studyBounds']
        polygons = geopackage_polygons(gpkg[0])
        inside = all(bounds[0] - 1e-6 <= x <= bounds[2] + 1e-6 and bounds[1] - 1e-6 <= y <= bounds[3] + 1e-6
                     for ring in polygons for x, y in ring)
        checks.append(equal('all clipped buffer vertices inside study bounds', inside, True,
                            source='GeoPackage WKB read with sqlite3', reference_source='authored studyBounds'))
        area = sum(abs(shoelace(r)) for r in polygons)
        checks.append({'name': 'clipped buffer area', 'observed': area, 'units': 'm^2', 'passed': None,
                       'source': 'shoelace over GeoPackage exterior rings',
                       'note': 'Informational; no analytic reference for overlapping clipped buffers.'})
    return checks


def shoelace(ring):
    return 0.5*sum(x0*y1 - x1*y0 for (x0, y0), (x1, y1) in zip(ring, ring[1:] + ring[:1]))


def geopackage_polygons(path):
    """Exterior rings of (multi)polygons from a GeoPackage, read with sqlite3 only."""
    rings = []
    with sqlite3.connect('file:' + str(path) + '?mode=ro', uri=True) as db:
        tables = [r[0] for r in db.execute("select table_name from gpkg_contents where data_type='features'")]
        for table in tables:
            column = db.execute('select column_name from gpkg_geometry_columns where table_name=?', (table,)).fetchone()[0]
            for (blob,) in db.execute('select "%s" from "%s"' % (column, table)):
                flags = blob[3]
                envelope = {0: 0, 1: 32, 2: 48, 3: 48, 4: 64}[(flags >> 1) & 7]
                rings.extend(wkb_rings(blob[8+envelope:]))
    return rings


def wkb_rings(data):
    rings = []
    def read(offset):
        order = '<' if data[offset] == 1 else '>'
        kind = struct.unpack(order + 'I', data[offset+1:offset+5])[0] % 1000
        offset += 5
        if kind == 3:
            count = struct.unpack(order + 'I', data[offset:offset+4])[0]; offset += 4
            for ring in range(count):
                points = struct.unpack(order + 'I', data[offset:offset+4])[0]; offset += 4
                coordinates = [struct.unpack(order + 'dd', data[offset+16*i:offset+16*i+16]) for i in range(points)]
                offset += 16*points
                if ring == 0: rings.append(coordinates[:-1])
        elif kind == 6:
            count = struct.unpack(order + 'I', data[offset:offset+4])[0]; offset += 4
            for _ in range(count): offset = read(offset)
        else:
            raise ValueError('unsupported WKB geometry %d' % kind)
        return offset
    read(0)
    return rings


CHECKS = {'beam': check_beam, 'rlc': check_rlc, 'regression': check_regression, 'cantera': check_cantera,
          'boxMesh': check_box_mesh, 'pipe': check_pipe, 'diagram': check_diagram, 'coupe': check_coupe,
          'media': check_media, 'site': check_site}


# ---------------------------------------------------------------- one workflow

def run_workflow(context, spec):
    flow = Workflow(context, spec)
    if flow.dir.exists():
        raise SystemExit('refusing to reuse existing directory for ' + spec['id'])
    flow.dir.mkdir(parents=True)
    started, clock = now(), time.monotonic()
    if spec.get('kind') == 'benchmark':
        summary = run_benchmark(flow)
    else:
        summary = run_three_phases(flow)
    summary.update(startedAt=started, endedAt=now(), wallSeconds=round(time.monotonic() - clock, 3))
    write_summary(flow, summary)
    return summary


def run_three_phases(flow):
    spec, ctx = flow.spec, flow.ctx
    parts = spec['parts']
    documents, inputs, origins = {}, {}, {}
    for part in parts:
        document, origin = flow.document(part)
        documents[part['id']] = {'initial': document, 'variant': flow.variant(part, document)}
        origins[part['id']] = origin
        for phase in ('initial', 'variant'):
            private, public = flow.write_input(part['id'] + ('-variant' if phase == 'variant' else ''),
                                               documents[part['id']][phase])
            inputs.setdefault(part['id'], {})[phase] = {'path': flow.rel(public), 'sha256': sha256(public),
                                                        'executed': private}
    phases = {'initial': {}, 'rerun': {}, 'variant': {}}
    verification, checks = [], {'initial': [], 'variant': []}
    reuse = {}
    # 1. initial, verify ------------------------------------------------------
    for part in parts:
        target = flow.dir/'runs'/part['id']
        code, result, step = flow.schemaxis_run('initial', part['id'], 'initial', inputs[part['id']]['initial']['executed'], target)
        jobs = flow.jobs(result)
        phases['initial'][part['id']] = {'exitCode': code, 'status': (result or {}).get('status'), 'seconds': step['seconds'],
                                         'jobs': jobs, 'artifacts': flow.artifacts(jobs),
                                         'document': documents[part['id']]['initial']}
        verification.append(flow.schemaxis_verify(part['id'], 'initial', target) if code == 0 else
                            {'part': part['id'], 'phase': 'initial', 'verified': False, 'skipped': 'run failed'})
    initial_ok = all(p['exitCode'] == 0 for p in phases['initial'].values())
    if initial_ok and spec.get('checks'):
        checks['initial'] = guarded(flow, 'checks-initial', CHECKS[spec['checks']], ctx, Phase(flow, 'initial', phases['initial']))
    qualification = run_qualifier(flow) if spec.get('qualify') else None
    # 2. unchanged rerun into the same directory ---------------------------------
    for part in parts:
        target = flow.dir/'runs'/part['id']
        if phases['initial'][part['id']]['exitCode'] != 0:
            continue
        code, result, step = flow.schemaxis_run('rerun', part['id'], 'rerun', inputs[part['id']]['initial']['executed'], target, resume=True)
        jobs = flow.jobs(result)
        phases['rerun'][part['id']] = {'exitCode': code, 'seconds': step['seconds'], 'jobs': jobs}
        verification.append(flow.schemaxis_verify(part['id'], 'rerun', target) if code == 0 else
                            {'part': part['id'], 'phase': 'rerun', 'verified': False, 'skipped': 'run failed'})
    # 3. changed document cannot resume the initial attempt ------------------------
    probes = []
    for part in parts:
        if part['id'] not in phases['rerun'] or documents[part['id']]['variant'] == documents[part['id']]['initial']:
            continue
        target = flow.dir/'runs'/part['id']
        code, result, step = flow.schemaxis_run('changed-resume-probe', part['id'], 'probe',
                                                inputs[part['id']]['variant']['executed'], target, resume=True)
        flow.failures = [f for f in flow.failures if f['step'] != 'changed-resume-probe']
        log = (flow.dir/step['log']).read_text()
        probes.append({'part': part['id'], 'exitCode': code, 'faultCode': fault_code(log),
                       'expected': 'RESUME_MISMATCH', 'passed': code != 0 and fault_code(log) == 'RESUME_MISMATCH'})
        verification.append(flow.schemaxis_verify(part['id'], 'after-probe', target))
    # 4. variant -------------------------------------------------------------------
    for part in parts:
        target = flow.dir/'variant'/part['id']
        code, result, step = flow.schemaxis_run('variant', part['id'], 'variant', inputs[part['id']]['variant']['executed'], target)
        jobs = flow.jobs(result)
        phases['variant'][part['id']] = {'exitCode': code, 'status': (result or {}).get('status'), 'seconds': step['seconds'],
                                         'jobs': jobs, 'artifacts': flow.artifacts(jobs),
                                         'document': documents[part['id']]['variant']}
        verification.append(flow.schemaxis_verify(part['id'], 'variant', target) if code == 0 else
                            {'part': part['id'], 'phase': 'variant', 'verified': False, 'skipped': 'run failed'})
    if spec.get('checks') and all(p['exitCode'] == 0 for p in phases['variant'].values()):
        checks['variant'] = guarded(flow, 'checks-variant', CHECKS[spec['checks']], ctx, Phase(flow, 'variant', phases['variant']))
    for phase in ('rerun', 'variant'):
        jobs = [job for part in phases[phase].values() for job in part['jobs']]
        reuse[phase] = {'jobs': len(jobs), 'reused': sum(j['reused'] for j in jobs),
                        'reran': sum(not j['reused'] for j in jobs),
                        'reusedJobs': [j['job'] for j in jobs if j['reused']],
                        'reranJobs': [j['job'] for j in jobs if not j['reused']]}
    reuse['variant']['mechanism'] = ('fresh output directory: --resume accepts only the unchanged authored '
                                     'workflow, so a changed document re-executes every job')
    reuse['rerun']['mechanism'] = 'schemaxis run --resume into the initial output directory'
    reuse['changedDocumentResume'] = probes
    known = [run_known_issue(flow, issue) for issue in spec.get('knownIssues', [])]
    showcase = build_showcase(flow, phases)
    all_jobs = [j for phase in phases.values() for part in phase.values() for j in part['jobs']]
    documents_list = [documents[p['id']][ph] for p in parts for ph in ('initial', 'variant')]
    passed_runs = all(p['exitCode'] == 0 for phase in phases.values() for p in phase.values()) and \
        all(len(phases[ph]) == len(parts) for ph in phases)
    verified = all(v['verified'] for v in verification)
    check_tally = {phase: tally(items) for phase, items in checks.items()}
    checks_ok = all(t['failed'] == 0 for t in check_tally.values())
    qualified = qualification is None or qualification.get('exitCode') == 0
    status = 'passed' if passed_runs and verified and checks_ok and qualified and all(p['passed'] for p in probes) else \
        ('failed' if not phases['initial'] or not initial_ok else 'partial')
    summary = base_summary(flow, status)
    summary.update({
        'apps': flow.versions(all_jobs, documents_list),
        'appsDeclared': spec['apps'],
        'inputs': {part: {phase: {k: v for k, v in item.items() if k != 'executed'} for phase, item in value.items()}
                   for part, value in inputs.items()},
        'inputOrigins': origins,
        'phases': {phase: {part: {k: v for k, v in item.items() if k not in ('document', 'artifacts')}
                           for part, item in value.items()} for phase, value in phases.items()},
        'artifacts': {phase: {'count': sum(len(p['artifacts']) for p in phases[phase].values()),
                              'files': [a for p in phases[phase].values() for a in p['artifacts']]}
                      for phase in ('initial', 'variant')},
        'verification': {'passed': sum(1 for v in verification if v['verified']),
                         'failed': sum(1 for v in verification if not v['verified']), 'runs': verification},
        'independentChecks': {'tally': check_tally, **checks},
        'qualification': qualification,
        'reuse': reuse,
        'knownIssues': known,
        'showcase': showcase,
    })
    return summary


def guarded(flow, name, function, *args):
    try:
        return function(*args)
    except Exception as error:  # A checker that cannot read its source is a failed check.
        message = flow.scrub('%s: %s' % (type(error).__name__, error))
        flow.failures.append({'step': name, 'exitCode': None, 'faultCode': None, 'logExcerpt': message})
        return [{'name': name, 'passed': False, 'note': message}]


def base_summary(flow, status):
    return {'schema': SUMMARY_SCHEMA, 'workflowId': flow.spec['id'], 'title': flow.spec['title'],
            'description': flow.spec.get('description'), 'status': status,
            'apps': [], 'appsDeclared': flow.spec.get('apps', []), 'inputs': {},
            'privateInputs': flow.spec.get('privateInputs', []),
            'variant': {k: v for k, v in flow.spec.get('variant', {}).items()},
            'adjustments': {p['id']: p['adjustments'] for p in flow.spec.get('parts', []) if p.get('adjustments')},
            'steps': flow.steps, 'artifacts': {}, 'verification': {}, 'independentChecks': {},
            'reuse': {}, 'showcase': {'files': [], 'totalBytes': 0}, 'failures': flow.failures,
            'notes': flow.notes, 'machine': flow.ctx.machine, 'code': flow.ctx.code,
            'startedAt': None, 'endedAt': None, 'wallSeconds': None}


def substitute(argument, flow, output):
    locations = flow.ctx.locations
    def app(match):
        return str(locations[match.group(1)])
    value = re.sub(r'\{app:([a-z]+)\}', app, argument)
    return value.replace('{config}', str(flow.ctx.config)).replace('{output}', str(output)) \
        .replace('{repository}', str(ROOT)).replace('{workflow}', str(flow.dir))


def run_qualifier(flow):
    spec = flow.spec['qualify']
    output = flow.dir/'qualify'
    command = [flow.ctx.python, ROOT/spec['tool'], *[substitute(a, flow, output) for a in spec['arguments']]]
    code, text, step = flow.execute('qualify', command, display=spec.get('display', False),
                                    timeout=spec.get('timeout', 1800))
    reports = [p for name in ('qualification.json', 'report.json') for p in sorted(output.glob('**/' + name))]
    report = None
    for path in reports:
        data = json.loads(path.read_text())
        if isinstance(data, dict):
            report = {'path': flow.rel(path), 'verified': data.get('verified', data.get('passed'))}
            break
    values = {}
    if report:
        data = json.loads((flow.dir/report['path']).read_text())
        for key in spec.get('extract', []):
            try:
                values[key] = json_pointer_get(data, key)
            except (KeyError, IndexError, TypeError):
                values[key] = None
    return {'tool': spec['tool'], 'exitCode': code, 'seconds': step['seconds'], 'report': report,
            'values': replace_strings(values, flow.private), 'log': step['log'],
            'scope': 'separate native run by the existing qualifier; not the evidence run above'}


def run_known_issue(flow, issue):
    part = issue.get('part', 'main')
    document = flow.dir/'work'/(part + '.json')
    command = [flow.ctx.python, '-m', 'schemaxis', *issue['command'], document]
    code, text, step = flow.execute('known-issue-' + issue['id'], command, part=part, phase='probe')
    flow.failures = [f for f in flow.failures if f['step'] != 'known-issue-' + issue['id']]
    observed = fault_code(text)
    return {'id': issue['id'], 'description': issue['description'], 'command': step['command'],
            'exitCode': code, 'faultCode': observed, 'expectedFaultCode': issue.get('expectedFaultCode'),
            'reproduced': observed == issue.get('expectedFaultCode'), 'log': step['log']}


def build_showcase(flow, phases):
    target = flow.dir/'showcase'
    files = []
    for item in flow.spec.get('showcase', []):
        phase = phases[item.get('phase', 'initial')].get(item.get('part', 'main'))
        if not phase: continue
        matches = sorted((a for a in phase['artifacts'] if a['operation'] == item['operation']
                          and fnmatch.fnmatch(Path(a['path']).name, item['file'])), key=lambda a: natural(a['path']))
        if 'pick' in item:
            matches = [matches[i] for i in item['pick'] if i < len(matches)]
        for artifact in matches:
            source = flow.dir/artifact['path']
            target.mkdir(exist_ok=True)
            name = item.get('prefix', item['operation']) + '-' + source.name
            record = {'source': artifact['path'], 'caption': item.get('caption'), 'phase': item.get('phase', 'initial')}
            if item.get('derive') == 'web-mp4':
                destination = target/(Path(name).stem + '.mp4')
                arguments = ['-hide_banner', '-loglevel', 'error', '-y', '-i', source, '-an', '-c:v', 'libx264',
                             '-pix_fmt', 'yuv420p', '-preset', 'slow', '-crf', str(item.get('crf', 20)),
                             '-movflags', '+faststart', destination]
                code, text, step = flow.execute('derive-' + destination.stem,
                                                [flow.ctx.locations['ffmpeg'], *arguments])
                if code != 0: continue
                record['derived'] = {'from': artifact['path'], 'tool': runtime_ffmpeg(flow),
                                     'arguments': flow.public_command([str(a) for a in arguments]),
                                     'reason': item.get('reason', 'web-playable H.264/yuv420p copy of the native output')}
            else:
                destination = target/name
                shutil.copyfile(source, destination)
                record['nativeSHA256'] = artifact.get('sha256')
            record.update(path=flow.rel(destination), sha256=sha256(destination), bytes=destination.stat().st_size,
                          mediaType=media_type(destination))
            if destination.suffix == '.png':
                record['pixels'] = png_size(destination)
            files.append(record)
    return {'files': files, 'totalBytes': sum(f['bytes'] for f in files)}


def runtime_ffmpeg(flow):
    try:
        first = subprocess.run([flow.ctx.locations['ffmpeg'], '-hide_banner', '-version'], capture_output=True,
                               text=True, timeout=30).stdout.splitlines()[0]
        return ' '.join(first.split()[:3])
    except (OSError, IndexError, subprocess.SubprocessError):
        return 'FFmpeg (version unavailable)'


def media_type(path):
    return {'.png': 'image/png', '.mp4': 'video/mp4', '.webm': 'video/webm', '.svg': 'image/svg+xml',
            '.fcstd': 'application/x-freecad', '.step': 'model/step', '.ods': 'application/vnd.oasis.opendocument.spreadsheet',
            '.xlsx': 'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet', '.zip': 'application/zip',
            '.mlt': 'application/xml', '.blend': 'application/x-blender', '.msh': 'text/plain',
            '.csv': 'text/csv', '.gpkg': 'application/geopackage+sqlite3', '.aseprite': 'application/octet-stream',
            '.vtu': 'application/xml'}.get(path.suffix.lower(), 'application/octet-stream')


def natural(text):
    return [int(t) if t.isdigit() else t for t in re.split(r'(\d+)', text)]


# ---------------------------------------------------------------- reproducibility benchmark

def run_benchmark(flow):
    spec = flow.spec
    package, proof, challenges = flow.dir/'package', flow.dir/'proof', flow.dir/'challenges'
    tool = ROOT/'tools/benchmark_workflows.py'
    flow.execute('prepare', [flow.ctx.python, tool, 'prepare', '--output-directory', package])
    code, text, _ = flow.execute('prove', [flow.ctx.python, tool, 'prove', '--package', package,
                                           '--config', flow.ctx.config, '--output-directory', proof],
                                 timeout=spec.get('timeout', 7200))
    flow.execute('challenges', [flow.ctx.python, ROOT/'tools/benchmark_challenges.py', '--package', package,
                                '--proof', proof, '--config', flow.ctx.config, '--output-directory', challenges],
                 timeout=spec.get('timeout', 7200))
    rounds, reuse, mutations = summarise_proof(proof), summarise_reuse(proof), summarise_challenges(challenges)
    passed = (all(s['exitCode'] == 0 for s in flow.steps) and rounds.get('failed', 1) == 0
              and mutations.get('accepted', 1) == 0)
    summary = base_summary(flow, 'passed' if passed else ('failed' if not rounds.get('passed') else 'partial'))
    summary.update({
        'apps': benchmark_versions(flow, proof),
        'inputs': {'cases': {'initial': {'path': 'package', 'note': 'generated by benchmark_workflows.py prepare'}}},
        'artifacts': {'initial': {'count': sum(1 for p in proof.rglob('*') if p.is_file()) if proof.exists() else 0,
                                  'files': []}},
        'verification': {'passed': rounds.get('passed', 0), 'failed': rounds.get('failed', 0),
                         'caseRounds': rounds},
        'independentChecks': {'falsification': mutations},
        'reuse': reuse,
        'timingsComparable': False,
        'timingsNote': 'Reference implementations, not AI trials: do not present these timings as a performance comparison (docs/benchmarks.md).',
    })
    summary['independentChecks']['tally'] = {'falsification': {'passed': mutations.get('rejected', 0),
                                                                'failed': mutations.get('accepted', 0)}}
    return summary


def summarise_proof(proof):
    """Case-round pass counts from the proof report: executed and graded correct."""
    path = proof/'report.json'
    if not path.is_file(): return {}
    report = json.loads(path.read_text())
    total = passed = 0
    rounds = []
    for run in report.get('runs', []):
        grades = {row['id']: row['passed'] for row in run.get('grade', {}).get('cases', [])}
        ok = [bool(case.get('executed') and grades.get(case['id'])) for case in run.get('cases', [])]
        total += len(ok); passed += sum(ok)
        rounds.append({'arm': run.get('arm'), 'round': run.get('round'), 'cases': len(ok), 'passed': sum(ok),
                       'caseSetMatches': run.get('grade', {}).get('caseSetMatches'),
                       'elapsedSeconds': round(sum(c.get('elapsedSeconds', 0) for c in run.get('cases', [])), 3)})
    return {'total': total, 'passed': passed, 'failed': total - passed, 'reportPassed': report.get('passed'),
            'rounds': rounds}


def summarise_reuse(proof):
    path = proof/'report.json'
    if not path.is_file(): return {}
    out = {}
    for run in json.loads(path.read_text()).get('runs', []):
        if run.get('arm') != 'schemaxis': continue
        jobs = [j for c in run.get('cases', []) for j in (c.get('jobs') or []) if isinstance(j, dict)]
        out[run.get('round')] = {'jobs': len(jobs), 'reused': sum(1 for j in jobs if j.get('reused')),
                                 'reran': sum(1 for j in jobs if not j.get('reused'))}
    out['mechanism'] = ('benchmark_workflows.py prove: each authored workflow hash has its own attempt; the '
                        'unchanged repeat round resumes it, revised documents start fresh')
    return out


def summarise_challenges(directory):
    path = directory/'report.json'
    if not path.is_file(): return {}
    rows = json.loads(path.read_text()).get('checks', [])
    rejected = sum(1 for r in rows if r.get('rejected'))
    return {'report': 'challenges/report.json', 'total': len(rows), 'rejected': rejected,
            'accepted': len(rows) - rejected,
            'mutations': [{k: r.get(k) for k in ('arm', 'family', 'mutation', 'rejected')} for r in rows]}


def benchmark_versions(flow, proof):
    found = {}
    for receipt in proof.glob('**/verification.json') if proof.exists() else []:
        directory = receipt.parent
        try:
            authored = json.loads((directory/'authored.json').read_text())
        except (OSError, ValueError):
            continue
        app = application(authored.get('version'))
        if app == 'unknown' or app == 'workflow': continue
        version = runtime_version(directory, app)
        if version: found.setdefault(app, set()).add(flow.scrub(version))
    return [{'name': app, 'version': sorted(v)[0] if len(v) == 1 else sorted(v)} for app, v in sorted(found.items())]


# ---------------------------------------------------------------- output

def write_summary(flow, summary):
    summary = replace_strings(summary, flow.private)
    problems = validate_summary(summary)
    leaks = absolute_paths(summary, flow.ctx.words)
    if problems or leaks:
        summary.setdefault('notes', []).append('summary audit problems: ' + '; '.join(problems + leaks))
        summary['status'] = 'failed' if summary['status'] == 'passed' else summary['status']
        summary = json.loads(scrub_text(json.dumps(summary), {}))
    (flow.dir/'summary.json').write_text(json.dumps(summary, indent=2) + '\n')


def write_index(context):
    entries, total = [], 0
    for path in sorted(context.output.glob('*/summary.json')):
        summary = json.loads(path.read_text())
        size = summary.get('showcase', {}).get('totalBytes', 0)
        total += size
        entries.append({'id': summary['workflowId'], 'title': summary['title'], 'status': summary['status'],
                        'wallSeconds': summary['wallSeconds'], 'summary': path.relative_to(context.output).as_posix(),
                        'showcaseBytes': size, 'apps': summary.get('apps'),
                        'startedAt': summary['startedAt'], 'endedAt': summary['endedAt']})
    order = {spec['id']: i for i, spec in enumerate(context.manifest['workflows'])}
    entries.sort(key=lambda e: order.get(e['id'], 1 << 20))
    index = {'schema': INDEX_SCHEMA, 'generatedAt': now(), 'machine': context.machine, 'code': context.code,
             'showcaseTotalBytes': total, 'showcaseBudgetBytes': context.manifest.get('showcaseBudgetBytes'),
             'workflows': entries,
             'publication': 'Publish only summary.json, input/ and showcase/ from each workflow; native run '
                            'directories contain workstation paths.'}
    leaks = absolute_paths(index, context.words)
    if leaks:
        raise SystemExit('index contains private paths: ' + ', '.join(leaks))
    (context.output/'index.json').write_text(json.dumps(index, indent=2) + '\n')
    return index


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument('action', choices=('run', 'index', 'list'))
    parser.add_argument('--config', help='private runtime configuration (schemaxis.local.json format)')
    parser.add_argument('--output-root', help='evidence root; each workflow writes <root>/<workflow-id>/')
    parser.add_argument('--workflow', action='append', help='workflow id (repeatable); default: all')
    parser.add_argument('--case', default=os.environ.get('SCHEMAXIS_RELEASE_CASE'),
                        help='absolute OpenFOAM .foam path for the coupe workflow (never recorded)')
    parser.add_argument('--manifest', default=str(MANIFEST))
    args = parser.parse_args(argv)
    manifest = json.loads(Path(args.manifest).read_text())
    if args.action == 'list':
        for spec in manifest['workflows']:
            print(spec['id'] + ': ' + spec['title'])
        return 0
    if not args.config or not args.output_root:
        parser.error('--config and --output-root are required')
    context = Context(args, manifest)
    context.output.mkdir(parents=True, exist_ok=True)
    if args.action == 'run':
        selected = [s for s in manifest['workflows'] if not args.workflow or s['id'] in args.workflow]
        unknown = set(args.workflow or ()) - {s['id'] for s in manifest['workflows']}
        if unknown: parser.error('unknown workflow: ' + ', '.join(sorted(unknown)))
        for spec in selected:
            if spec.get('requiresCase') and not context.case:
                print(spec['id'] + ': skipped; --case is required', flush=True)
                continue
            print('== ' + spec['id'], flush=True)
            summary = run_workflow(context, spec)
            print('   %s in %.1f s; showcase %d bytes' % (summary['status'], summary['wallSeconds'],
                                                         summary.get('showcase', {}).get('totalBytes', 0)), flush=True)
    index = write_index(context)
    print('index: %d workflows, showcase %d bytes' % (len(index['workflows']), index['showcaseTotalBytes']))
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
