"""Bounded host inspection of immutable text/CSV snapshots and typed selections.

Workspace owners serialise calls. No native imports, extraction engine, authored
code, or inferred physical units are involved.
"""
import copy
import csv
import hashlib
import io
import math
from pathlib import Path
import re
import uuid
from .storage import atomic, encoded, load, digest, AtomicPublicationError
from .errors import fail, keys
from .observations import bounded
from .console_references import ReferenceStore
from . import workspaces

LIMIT = 1024 * 1024
BUDGET = 65536
SYNTHETIC_TEXT = ('SYNTHETIC INSPECTION FIXTURE — not extraction output\n'
                  'iteration=0 residual=1.0\niteration=1 residual=0.25\n'
                  'iteration=2 residual=0.0625\niteration=3 residual=0.015625\n')
SYNTHETIC_TABLE = 'sample,value\n0,1\n1,0.25\n2,0.0625\n3,0.015625\n'


def sha(data):
    return hashlib.sha256(data).hexdigest()


def page(offset, limit, maximum):
    if type(offset) is not int or offset < 0 or type(limit) is not int or not 1 <= limit <= maximum:
        fail('INVALID_PAGE', 'use a nonnegative offset and a bounded positive limit', maximum=maximum)


def table(text):
    try:
        rows = list(csv.reader(io.StringIO(text, newline=''), strict=True))
    except csv.Error as error:
        fail('INVALID_TABLE', str(error))
    if not rows or not 1 <= len(rows[0]) <= 128:
        fail('INVALID_TABLE', 'CSV needs a header of 1..128 columns')
    if any(not name or len(name) > 256 for name in rows[0]) or len(set(rows[0])) != len(rows[0]):
        fail('INVALID_TABLE', 'column names must be unique, nonempty and at most 256 characters')
    if len(rows) > 50001 or any(len(row) != len(rows[0]) for row in rows[1:]):
        fail('INVALID_TABLE', 'CSV must be rectangular and contain at most 50000 data rows')
    return rows[0], rows[1:]


class InspectionStore:
    def __init__(self, workspace, references=None):
        self.root = Path(workspace)/'inspection'
        self.path = self.root/'state.json'
        self.references = references if references is not None else ReferenceStore(workspace)
        self.closed = False
        self.state = {'resources': {}, 'presentation': {'preset': 'geometry-study', 'resource': None}}
        if self.path.exists():
            value = load(self.path.read_text())
            if (not isinstance(value, dict) or value.get('version') != 1
                    or value.get('digest') != digest(value.get('state'))):
                fail('RECOVERY_FAILED', 'inspection state checksum or version differs')
            self.state = value['state']
            try:
                assert isinstance(self.state['resources'], dict)
                workspaces.preset(self.state['presentation']['preset'])
                for identity, record in self.state['resources'].items():
                    assert record['id'] == identity and record['revision'] in record['snapshots']
            except (AssertionError, KeyError, TypeError):
                fail('RECOVERY_FAILED', 'inspection state relationships are invalid')

    def _commit(self, state):
        if self.closed: fail('SESSION_CLOSED', 'reopen the inspection owner')
        payload = encoded({'version': 1, 'state': state, 'digest': digest(state)})
        try:
            atomic(self.path, payload)
        except AtomicPublicationError:
            try: matches = self.path.read_bytes() == payload
            except OSError: matches = False
            if matches: self.state = state
            else: self.closed = True
            raise
        self.state = state

    def workspace(self, preset=None, resource_id=None):
        if preset is not None or resource_id is not None:
            state = copy.deepcopy(self.state)
            if preset is not None:
                workspaces.preset(preset)
                state['presentation']['preset'] = preset
            if resource_id is not None:
                self._record(resource_id)
                state['presentation']['resource'] = resource_id
            self._commit(state)
        return {**workspaces.catalogue(), 'presentation': copy.deepcopy(self.state['presentation'])}

    def _record(self, identity):
        if self.closed: fail('SESSION_CLOSED', 'reopen the inspection owner')
        if not isinstance(identity, str) or identity not in self.state['resources']:
            fail('UNKNOWN_RESOURCE', 'unknown inspection snapshot resource')
        return self.state['resources'][identity]

    def revisions(self):
        return {key: value['revision'] for key, value in self.state['resources'].items()}

    def resources(self, **paging):
        return bounded([{k: copy.deepcopy(v) for k, v in item.items() if k != 'snapshots'}
                        for item in self.state['resources'].values()], 'inspection-resources', **paging)

    def capture(self, filename, kind, resource_id=None, expected_revision=None):
        path = Path(filename).resolve()
        try:
            with path.open('rb') as stream: data = stream.read(LIMIT+1)
        except OSError as error:
            fail('RESOURCE_NOT_FOUND', str(error), str(path))
        return self.capture_bytes(data, kind, path.name, {'kind': 'local-file', 'path': str(path),
            'verification': 'captured bytes only; no extraction or native verification'}, resource_id, expected_revision)

    def capture_bytes(self, data, kind, name, provenance, resource_id=None, expected_revision=None):
        if kind not in ('text', 'table'): fail('UNSUPPORTED_INSPECTION', 'choose text or table')
        if not isinstance(data, bytes) or len(data) > LIMIT:
            fail('INSPECTION_LIMIT', 'snapshot input is limited to one MiB')
        try: text = data.decode('utf-8')
        except UnicodeDecodeError: fail('INVALID_ENCODING', 'snapshot must be UTF-8')
        if kind == 'table': table(text)
        if resource_id is not None:
            previous = self._record(resource_id)
            if expected_revision != previous['revision']:
                fail('STALE_RESOURCE', 'snapshot changed; inspect the current revision')
            if previous['kind'] != kind: fail('TYPE_MISMATCH', 'a resource cannot change its inspection kind')
        elif expected_revision is not None:
            fail('INVALID_REQUEST', 'expected_revision requires a resource_id')
        identity = resource_id or 'snapshot-'+uuid.uuid4().hex
        metadata = {'sha256': sha(data), 'bytes': len(data), 'encoding': 'UTF-8',
                    'kind': kind, 'provenance': copy.deepcopy(provenance)}
        revision = digest(metadata)
        blob = self.root/'blobs'/metadata['sha256']
        if blob.exists():
            if blob.is_symlink() or sha(blob.read_bytes()) != metadata['sha256']:
                fail('RESOURCE_CHANGED', 'retained snapshot bytes differ')
        else: atomic(blob, data, exclusive=True)
        state = copy.deepcopy(self.state)
        item = state['resources'].setdefault(identity, {'id': identity, 'snapshots': {}})
        item.update(name=name, kind=kind, revision=revision, bytes=len(data), units='unknown',
                    provenance=copy.deepcopy(provenance))
        item['snapshots'][revision] = metadata
        self._commit(state)
        return {k: copy.deepcopy(v) for k, v in item.items() if k != 'snapshots'}

    def demo(self):
        # Stable names avoid duplicate fixture resources on repeated button clicks.
        result = []
        for kind, name, text in [('text', 'Synthetic solver log', SYNTHETIC_TEXT),
                                 ('table', 'Synthetic sample table', SYNTHETIC_TABLE)]:
            existing = next((r for r in self.state['resources'].values()
                             if r['name'] == name and r['provenance'].get('kind') == 'synthetic'), None)
            result.append(self.capture_bytes(text.encode(), kind, name,
                {'kind': 'synthetic', 'verification': 'UI fixture; no extraction run or real solver data'},
                existing['id'] if existing else None, existing['revision'] if existing else None))
        return result

    def _read(self, identity, revision):
        record = self._record(identity)
        if not isinstance(revision, str) or revision not in record['snapshots']:
            fail('STALE_RESOURCE', 'unknown resource snapshot revision')
        metadata = record['snapshots'][revision]
        path = self.root/'blobs'/metadata['sha256']
        try:
            if path.is_symlink() or not path.resolve().is_relative_to(self.root.resolve()): raise OSError('invalid snapshot path')
            with path.open('rb') as stream: data = stream.read(LIMIT+1)
        except OSError: fail('RESOURCE_CHANGED', 'retained snapshot is missing or inaccessible')
        if sha(data) != metadata['sha256'] or len(data) != metadata['bytes']:
            fail('RESOURCE_CHANGED', 'retained snapshot bytes changed')
        return record, metadata, data.decode('utf-8')

    def inspect(self, resource_id, revision, view, offset=0, limit=50, columns=None, x_column=None, y_column=None):
        if view not in ('text', 'table', 'series'): fail('UNKNOWN_VIEW', 'choose a trusted text, table or series view')
        page(offset, limit, 16384 if view == 'text' else 200 if view == 'series' else 100)
        record, meta, text = self._read(resource_id, revision)
        if record['kind'] not in workspaces.PANELS[view]['accepts']:
            fail('TYPE_MISMATCH', 'resource kind is not accepted by this view', kind=record['kind'], view=view)
        base = {'version': 'schemaxis.observation/1', 'resource': resource_id, 'revision': revision,
                'view': view, 'stale': record['revision'] != revision, 'units': 'unknown',
                'provenance': copy.deepcopy(meta['provenance'])}
        if view == 'text':
            if offset > len(text): fail('INVALID_PAGE', 'offset exceeds source length')
            end = min(len(text), offset+limit)
            while True:
                result = {**base, 'text': text[offset:end], 'offset': offset, 'end': end,
                    'byteStart': len(text[:offset].encode()), 'byteEnd': len(text[:end].encode()),
                    'line': text.count('\n', 0, offset)+1, 'totalCharacters': len(text),
                    'nextOffset': end if end < len(text) else None, 'encoding': 'UTF-8'}
                if len(encoded(result)) <= BUDGET: return result
                if end <= offset: fail('OBSERVATION_TOO_LARGE', 'snapshot metadata exceeds response limit')
                end = offset+(end-offset)//2
        headers, rows = table(text)
        if offset > len(rows): fail('INVALID_PAGE', 'offset exceeds table rows')
        if view == 'series':
            points = self._series(headers, rows, x_column, y_column)
            end = min(len(points), offset+limit)
            while True:
                result = {**base, 'columns': headers, 'xColumn': x_column, 'yColumn': y_column,
                          'axisUnits': {'x': 'unknown', 'y': 'unknown'}, 'mapping': 'explicit finite numeric columns; original row order',
                          'points': [{'row': i, 'x': x, 'y': y} for i, (x,y) in enumerate(points[offset:end], offset)],
                          'offset': offset, 'nextOffset': end if end < len(rows) else None, 'totalRows': len(rows)}
                if len(encoded(result)) <= BUDGET: return result
                if end <= offset+1: fail('OBSERVATION_TOO_LARGE', 'complete series metadata exceeds response budget')
                end -= 1
        selected = list(range(min(16, len(headers)))) if columns is None else columns
        if (not isinstance(selected, list) or not 1 <= len(selected) <= 16
                or any(type(i) is not int or not 0 <= i < len(headers) for i in selected)
                or len(set(selected)) != len(selected)):
            fail('INVALID_COLUMNS', 'choose 1..16 distinct zero-based column indices')
        end = min(len(rows), offset+limit)
        while True:
            result = {**base, 'columns': headers, 'selectedColumns': selected, 'valueType': 'string',
                      'rows': [{'row': i, 'values': [row[j] for j in selected]} for i,row in enumerate(rows[offset:end],offset)],
                      'offset': offset, 'nextOffset': end if end < len(rows) else None, 'totalRows': len(rows)}
            if len(encoded(result)) <= BUDGET: return result
            if end <= offset+1: fail('OBSERVATION_TOO_LARGE', 'one complete row exceeds the inspection budget; select fewer columns')
            end -= 1

    @staticmethod
    def _series(headers, rows, x, y):
        if any(type(i) is not int or not 0 <= i < len(headers) for i in (x,y)) or x == y:
            fail('INVALID_COLUMNS', 'choose distinct zero-based x and y columns')
        points = []
        for index, row in enumerate(rows):
            pair = []
            for col in (x,y):
                token = row[col].strip()
                if not re.fullmatch(r'[+-]?(?:\d+(?:\.\d*)?|\.\d+)(?:[eE][+-]?\d+)?', token):
                    fail('NON_NUMERIC_SERIES', 'selected columns must contain finite decimal numbers', row=index, column=col)
                value = float(token)
                if not math.isfinite(value): fail('NON_NUMERIC_SERIES', 'numeric value is not finite', row=index, column=col)
                pair.append(value)
            if points and pair[0] <= points[-1][0]:
                fail('UNSUPPORTED_DOMAIN', 'x values must be strictly increasing; no sorting or deduplication is implied', row=index)
            points.append(pair)
        return points

    def reference(self, resource_id, revision, kind, selection):
        record, meta, text = self._read(resource_id, revision)
        if revision != record['revision']: fail('STALE_REFERENCE', 'capture a selection from the current resource revision')
        payload = self._selection(record, text, kind, selection)
        ref = {'version': 'schemaxis.reference/1', 'kind': kind,
               'target': {'resource': resource_id, 'revision': revision}, 'payload': payload,
               'provenance': copy.deepcopy(meta['provenance']), 'replayable': False,
               'label': record['name']+' · '+kind, 'units': 'unknown',
               'selectionScope': 'historical evidence selection in this snapshot; not an executable selector'}
        return {**self.references._append(ref), 'stale': False}

    def _selection(self, record, text, kind, selection):
        if kind == 'text-span':
            if record['kind'] != 'text': fail('TYPE_MISMATCH', 'text spans require a text snapshot')
            keys(selection, ('start','end'), 'selection')
            start,end = selection.get('start'),selection.get('end')
            if any(type(i) is not int for i in (start,end)) or not 0 <= start < end <= len(text):
                fail('INVALID_SELECTION', 'choose a nonempty code-point span inside the snapshot')
            return {'start': start, 'end': end, 'byteStart': len(text[:start].encode()),
                    'byteEnd': len(text[:end].encode()), 'startLine': text.count('\n',0,start)+1,
                    'endLine': text.count('\n',0,end-1)+1, 'encoding': 'UTF-8'}
        if kind not in ('table-range','series-interval'):
            fail('UNSUPPORTED_SELECTION', 'choose text-span, table-range or series-interval')
        if record['kind'] != 'table': fail('TYPE_MISMATCH', 'table selections require a table snapshot')
        fields = ('rowStart','rowEnd','columnStart','columnEnd') if kind == 'table-range' else ('rowStart','rowEnd','xColumn','yColumn')
        keys(selection, fields, 'selection')
        headers,rows = table(text)
        start,end = selection.get('rowStart'),selection.get('rowEnd')
        if any(type(i) is not int for i in (start,end)) or not 0 <= start < end <= len(rows):
            fail('INVALID_SELECTION', 'choose a nonempty half-open range of zero-based data rows')
        if kind == 'table-range':
            a,b = selection.get('columnStart'),selection.get('columnEnd')
            if any(type(i) is not int for i in (a,b)) or not 0 <= a < b <= len(headers):
                fail('INVALID_SELECTION', 'choose a nonempty half-open column range')
            return dict(selection)
        x,y = selection.get('xColumn'),selection.get('yColumn')
        points = self._series(headers,rows,x,y)
        return {**selection, 'domain': [points[start][0],points[end-1][0]], 'axisUnits': {'x':'unknown','y':'unknown'}}

    def inspect_reference(self, reference_id, **paging):
        ref = next((r for r in self.references.data['references'] if r['id'] == reference_id), None)
        if ref is None: fail('UNKNOWN_REFERENCE', 'unknown evidence selection')
        target = ref.get('target', {})
        if 'resource' not in target:
            return bounded(ref, reference_id, **paging)
        record,meta,text = self._read(target['resource'],target['revision'])
        payload = ref['payload']
        if ref['kind'] == 'text-span': value = text[payload['start']:payload['end']]
        else:
            headers,rows = table(text)
            start,end = payload['rowStart'],payload['rowEnd']
            if ref['kind'] == 'table-range':
                a,b=payload['columnStart'],payload['columnEnd']
                value={'columns':headers[a:b], 'rows':rows[start:end], 'columnRange':[a,b]}
                value['rows']=[row[a:b] for row in value['rows']]
            else:
                value={'points':self._series(headers,rows,payload['xColumn'],payload['yColumn'])[start:end],
                       'rowStart':start,'axisUnits':payload['axisUnits']}
        return bounded({'reference': ref, 'stale': record['revision'] != target['revision'], 'evidence': value}, reference_id, **paging)

    def check_references(self, identities):
        for ref in self.references.data['references']:
            target=ref.get('target', {})
            if ref['id'] in identities and 'resource' in target:
                record,_,_=self._read(target['resource'],target['revision'])
                if record['revision'] != target['revision']: fail('STALE_REFERENCE', 'selected resource snapshot has been replaced')
