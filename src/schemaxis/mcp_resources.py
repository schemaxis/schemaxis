"""Owned, bounded MCP resource pages and immutable deferred service results."""
import base64
import hashlib
import json
from pathlib import Path
import re
import threading
import time
import uuid
from urllib.parse import parse_qsl, quote, unquote, urlencode, urlsplit

from .storage import atomic, encoded, load
from .observations import at_pointer, bounded, fail

MAX_RESULT = 16 * 1024 * 1024
QUOTA = 64 * 1024 * 1024
TTL = 86400
SECTIONS = {'document', 'plan', 'result', 'verification', 'resources', 'fault'}
PAGE = {'pointer', 'offset', 'limit', 'max_bytes', 'revision'}


class ResponseStore:
    def __init__(self, workspace, *, quota=QUOTA, clock=time.time):
        self.root = Path(workspace)/'mcp-responses'
        if self.root.is_symlink():
            fail('MCP_RESOURCE_CHANGED', 'response store must be owned regular storage')
        self.root.mkdir(parents=True, exist_ok=True)
        self.quota, self.clock = quota, clock
        self.lock = threading.RLock()
        self.reserved = 0
        # Compact cancellation/status/errors never allocate from snapshot quota.
        self.control_buffer = bytearray(16384)
        self.path = self.root/'index.json'
        if self.path.exists():
            self.index = self._read_json(self.path)
        else:
            self.index = {'namespace': uuid.uuid4().hex, 'responses': {}}
            self._save()
        if (not isinstance(self.index, dict) or set(self.index) != {'namespace', 'responses'}
                or not isinstance(self.index['namespace'], str)
                or not re.fullmatch('[a-f0-9]{32}', self.index['namespace'])
                or not isinstance(self.index['responses'], dict)):
            fail('MCP_RESOURCE_CHANGED', 'response index is invalid')
        for key, record in self.index['responses'].items():
            if (not re.fullmatch('[a-f0-9]{64}', key) or not isinstance(record, dict)
                    or set(record) != {'bytes', 'expiresAt'} or type(record['bytes']) is not int
                    or not 0 <= record['bytes'] <= MAX_RESULT or type(record['expiresAt']) not in (int, float)):
                fail('MCP_RESOURCE_CHANGED', 'response index record is invalid')

    @staticmethod
    def _read_json(path):
        if path.is_symlink() or not path.is_file():
            fail('MCP_RESOURCE_CHANGED', 'resource storage is not a regular file')
        return load(path.read_text(encoding='utf-8'))

    @property
    def namespace(self):
        return self.index['namespace']

    def _save(self):
        atomic(self.path, encoded(self.index))

    def _expire(self):
        expired = [key for key, item in self.index['responses'].items()
                   if item['expiresAt'] <= self.clock()]
        for key in expired:
            path = self.root/(key+'.json')
            path.unlink(missing_ok=True)
            del self.index['responses'][key]
        if expired:
            self._save()

    def reserve(self):
        with self.lock:
            self._expire()
            used = sum(item['bytes'] for item in self.index['responses'].values())
            if used + self.reserved + MAX_RESULT > self.quota:
                fail('MCP_RESPONSE_QUOTA', 'response storage is full; cancellation and status remain available')
            self.reserved += MAX_RESULT

    def release(self):
        with self.lock:
            self.reserved -= MAX_RESULT

    def capture(self, value, *, reserved=False):
        data = encoded(value)
        if len(data) > MAX_RESULT:
            fail('MCP_RESULT_TOO_LARGE', 'complete result exceeds the retained response bound')
        key = hashlib.sha256(data).hexdigest()
        with self.lock:
            self._expire()
            used = sum(item['bytes'] for item in self.index['responses'].values())
            held = self.reserved - (MAX_RESULT if reserved else 0)
            if key not in self.index['responses'] and used + held + len(data) > self.quota:
                fail('MCP_RESPONSE_QUOTA', 'response storage is full')
            path = self.root/(key+'.json')
            if path.exists():
                self.read(key)
            else:
                atomic(path, data, exclusive=True)
            self.index['responses'][key] = {'bytes': len(data), 'expiresAt': self.clock()+TTL}
            self._save()
            return {'uri': self.uri('responses', key), 'sha256': 'sha256:'+key,
                    'bytes': len(data), 'expiresAt': self.index['responses'][key]['expiresAt']}

    def read(self, key):
        if not isinstance(key, str) or not re.fullmatch('[a-f0-9]{64}', key):
            fail('MCP_INVALID_URI', 'invalid response digest')
        with self.lock:
            self._expire()
            record = self.index['responses'].get(key)
            if record is None:
                fail('MCP_RESOURCE_EXPIRED', 'response is absent or expired')
            path = self.root/(key+'.json')
            if path.is_symlink() or not path.is_file() or path.stat().st_size > MAX_RESULT:
                fail('MCP_RESOURCE_CHANGED', 'retained response changed')
            data = path.read_bytes()
            if len(data) != record['bytes'] or hashlib.sha256(data).hexdigest() != key:
                fail('MCP_RESOURCE_CHANGED', 'retained response digest differs')
            return load(data.decode('utf-8'))

    def uri(self, *parts, **query):
        base = 'schemaxis://workspace/'+self.namespace+'/'+ '/'.join(quote(str(p), safe='') for p in parts)
        return base + ('?'+urlencode(query) if query else '')

    def parse(self, uri):
        if not isinstance(uri, str) or len(uri) > 8192 or re.search(r'%(?![0-9a-fA-F]{2})', uri):
            fail('MCP_INVALID_URI', 'use a bounded Schemaxis resource URI')
        try:
            value = urlsplit(uri)
        except ValueError:
            fail('MCP_INVALID_URI', 'malformed resource URI')
        if value.scheme != 'schemaxis' or value.netloc != 'workspace' or value.fragment:
            fail('MCP_INVALID_URI', 'only owned Schemaxis resource URIs are readable')
        parts = [unquote(part, errors='strict') for part in value.path.split('/')[1:]]
        if (not parts or parts[0] != self.namespace or any(not part or part in {'.', '..'}
                or '/' in part or '\\' in part or '\x00' in part for part in parts)):
            fail('MCP_INVALID_URI', 'resource does not belong to this namespace')
        pairs = parse_qsl(value.query, keep_blank_values=True, strict_parsing=True)
        if len({key for key, _ in pairs}) != len(pairs):
            fail('MCP_INVALID_URI', 'duplicate resource query fields')
        query = dict(pairs)
        for key in {'offset', 'length', 'limit', 'max_bytes'} & query.keys():
            if not re.fullmatch('0|[1-9][0-9]{0,8}', query[key]):
                fail('MCP_INVALID_URI', 'resource page bounds must be decimal integers')
            query[key] = int(query[key])
        return parts[1:], query

    def resource(self, service, uri):
        parts, query = self.parse(uri)
        if len(parts) == 2 and parts[0] == 'responses':
            if set(query) - PAGE:
                fail('MCP_INVALID_URI', 'unknown observation query field')
            return bounded(self.read(parts[1]), parts[1], **query)
        if len(parts) == 3 and parts[0] == 'responses' and parts[2] == 'scalars':
            if set(query) - {'pointer', 'offset', 'length'}:
                fail('MCP_INVALID_URI', 'unknown scalar query field')
            value = at_pointer(self.read(parts[1]), query.get('pointer', ''))
            if not isinstance(value, str):
                fail('MCP_INVALID_URI', 'scalar byte pages require a string')
            data = encoded(value)
            offset, length = query.get('offset', 0), query.get('length', 4096)
            if offset > len(data) or not 1 <= length <= 16384:
                fail('INVALID_PAGE', 'invalid scalar byte range')
            chunk = data[offset:offset+length]
            return {'encoding': 'base64', 'data': base64.b64encode(chunk).decode(),
                    'offset': offset, 'returnedBytes': len(chunk), 'bytes': len(data),
                    'sha256': 'sha256:'+hashlib.sha256(data).hexdigest(),
                    'nextOffset': offset+len(chunk) if offset+len(chunk) < len(data) else None}
        if len(parts) in {3, 4} and parts[0] in {'jobs', 'plans'}:
            if set(query) - PAGE:
                fail('MCP_INVALID_URI', 'unknown observation query field')
            if len(parts) == 3 and parts[0] == 'jobs' and parts[2] == 'receipt':
                section = 'verification'
            elif len(parts) == 4 and parts[2] == 'observations' and parts[3] in SECTIONS:
                section = parts[3]
            else:
                fail('MCP_INVALID_URI', 'unknown observation resource')
            return service.observe(**{'job_id' if parts[0] == 'jobs' else 'plan_id': parts[1]}, section=section, **query)
        if len(parts) == 3 and parts[0] == 'resources':
            if parts[2] == 'bytes' and not set(query) - {'offset', 'length'}:
                return service.resource(parts[1], **query)
            if parts[2] == 'metadata' and not set(query) - PAGE:
                return service.inspect_resource_metadata(parts[1], **query)
        fail('MCP_INVALID_URI', 'unknown resource template')
