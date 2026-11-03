# Copyright (C) 2026 David L F Gaden
"""Native-neutral persistent graph lifecycle, shared by the live workers."""
import copy
import hashlib
import os
from pathlib import Path

from schemaxis.artifacts import atomic_json
from schemaxis.pipeline import RuntimeClosure, digest
from .live_transport import fault

MAX_FACES = 100000
MAX_VERTICES = 500000


class GraphWorker:
    def __init__(self):
        self.active = None
        self.document = None
        self.prepared = None
        self.revision = 0
        self.uncertain = False
        self.geometry_digest = None

    def prepare(self, document):
        master, selection, scene, visible = self.prepare_graph(document)
        if selection.count != 1:
            fault('UNSUPPORTED_LIVE_INPUT', 'Live mode requires one geometry state; resolve batch axes/times first')
        if len(selection.order) > 200:
            fault('LIVE_LIMIT', 'Live mode supports at most 200 active nodes')
        if not visible:
            fault('UNSUPPORTED_LIVE_INPUT', 'Live mode requires visible geometry')
        for declaration in master.declarations.values():
            if declaration.get('nativeDependencies'):
                fault('UNSUPPORTED_LIVE_INPUT', 'Live mode does not load authored native plugins')
        return master, selection, scene, visible

    def prepare_graph(self, document):
        from .adaptors.registry import metadata, binding
        return binding(metadata(self.provider)['liveGraph'])(document)

    @staticmethod
    def compatible(active, master, selection):
        if active.selection.order != selection.order:
            return False
        for key in selection.order:
            old, new = active.master.nodes[key], master.nodes[key]
            if old['filter'] != new['filter'] or old['inputs'] != new['inputs']:
                return False
            declaration = master.declarations[new['filter']]
            if active.master.declarations[old['filter']] != declaration:
                return False
            for option, binding in declaration['options'].items():
                if binding.get('constructor') and old['options'].get(option) != new['options'].get(option):
                    return False
        return True

    def build(self, prepared, reuse=False):
        master, selection, _, _ = prepared
        if not reuse:
            self.reset()
            self.active = RuntimeClosure(master, self.backend())
        else:
            self.active.master = master
        self.active.activate(selection.roots)
        state = self.active.apply(next(selection.visits()))
        self.present(prepared)
        return state

    def reset(self):
        try:
            if self.active is not None:
                self.active.close()
        finally:
            self.active = None
            self.reset_native()

    def apply(self, document):
        if self.uncertain:
            fault('UNCERTAIN_STATE', 'Previous native state could not be restored; restart this session', uncertain=True)
        prepared = self.prepare(document)  # Validate before native mutation.
        previous = copy.deepcopy(self.document)
        observations = copy.deepcopy(self.active.observations) if self.active else None
        reuse = self.active is not None and self.compatible(self.active, prepared[0], prepared[1])
        try:
            state = self.build(prepared, reuse)
            self.prepared = prepared
            geometry_digest = digest(self.geometry())
        except Exception as error:
            try:
                restored = self.prepare(previous) if previous is not None else None
                if restored:
                    recovered = self.build(restored)
                    self.prepared = restored
                    if recovered['observations'] != observations:
                        fault('ROLLBACK_MISMATCH', 'Restored native observations differ')
                    if digest(self.geometry()) != self.geometry_digest:
                        fault('ROLLBACK_MISMATCH', 'Restored native geometry differs')
                else:
                    self.reset()
                self.prepared = restored
            except Exception as recovery:
                self.uncertain = True
                fault('UNCERTAIN_STATE', 'Apply failed and prior native state could not be verified',
                      applyError=str(error), rollbackError=str(recovery), uncertain=True)
            fault('APPLY_FAILED', 'Native apply failed; previous authored state was rebuilt and verified',
                  cause=str(error), rolledBack=True, revision=self.revision)
        self.document = copy.deepcopy(document)
        self.prepared = prepared
        self.geometry_digest = geometry_digest
        self.revision += 1
        return {**self.status(), 'updated': state['updated'], 'reused': reuse}

    def status(self):
        return {'provider': self.provider, 'pid': os.getpid(), 'revision': self.revision,
                'units': 'native', 'state': 'uncertain' if self.uncertain else 'ready',
                'documentDigest': digest(self.document) if self.document is not None else None,
                'geometryDigest': self.geometry_digest,
                'objects': self.object_ids() if self.active and not self.uncertain else [],
                'faceIds': 'revision-scoped', 'persistent': True, 'mode': 'headless',
                'publicationPolicy': 'explicit live image/save only; batch publications are not executed',
                'capabilities': ['apply', 'geometry', 'status', 'image', 'save']}

    def save_metadata(self):
        return {'provider': self.provider, 'revision': self.revision, 'units': 'native',
                'document': copy.deepcopy(self.document), 'documentDigest': digest(self.document),
                'geometryDigest': self.geometry_digest, 'objects': self.object_ids(),
                'observations': copy.deepcopy(self.active.observations), 'visible': self.prepared[3]}

    def save_receipt(self, path, result, metadata):
        receipt = str(path) + '.receipt.json'
        result = {**result, 'file': str(path), 'sha256': hashlib.sha256(Path(path).read_bytes()).hexdigest(),
                  'revision': self.revision, 'documentDigest': digest(self.document),
                  'geometryDigest': self.geometry_digest, 'receipt': receipt}
        atomic_json(receipt, {**metadata, **result})
        return result

    def dispatch(self, command, args):
        if command == 'status':
            return self.status()
        if command == 'shutdown':
            self.close()
            return {'closed': True}
        if command == 'apply':
            return self.apply(args['document'])
        if self.uncertain:
            fault('UNCERTAIN_STATE', 'Restart the session before reading native geometry', uncertain=True)
        if self.prepared is None:
            fault('NO_DOCUMENT', 'Apply an authored document first')
        if command == 'geometry':
            return {'objects': self.geometry(), 'units': 'native', 'revision': self.revision,
                    'faceIds': 'revision-scoped', 'documentDigest': digest(self.document),
                    'observations': copy.deepcopy(self.active.observations)}
        if command == 'image':
            return {**self.image(args['path']), 'revision': self.revision}
        if command == 'save':
            return self.save(args['path'])
        fault('UNKNOWN_COMMAND', 'Unsupported live command')

    def close(self):
        self.reset()
        self.prepared = None
        self.document = None
        self.geometry_digest = None
