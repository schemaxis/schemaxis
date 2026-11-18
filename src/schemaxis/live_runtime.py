# Copyright (C) 2026 David L. F. Gaden.
"""Native-neutral persistent graph lifecycle, shared by the live workers."""
import copy
from schemaxis.identity_policy import policy_request
import hashlib
import os
from pathlib import Path

from schemaxis.artifacts import atomic_json
from schemaxis.pipeline import RuntimeClosure, digest
from .live_transport import fault, reply_budget

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
        self.geometry_objects = None

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
        """Whether ``master`` keeps the exact resident selection and every construction."""
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

    def build(self, prepared):
        master, selection, _, _ = prepared
        self.reset()
        self.active = RuntimeClosure(master, self.backend())
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

    def prepare_transition(self, document, preserve=()):
        """Native-free preflight of an ordinary change to the resident graph.

        ``preserve`` names resident nodes that must keep their exact handle and be
        neither configured nor updated; an ineligible change is refused here.
        """
        if self.uncertain:
            fault('UNCERTAIN_STATE', 'Previous native state could not be restored; restart this session', uncertain=True)
        prepared = self.prepare(document)
        if self.active is None or self.document is None:
            fault('NO_RESIDENT_DATA', 'A resident graph is required for an incremental transition')
        plan = self.active.prepare_transition(prepared[0], prepared[1].roots, next(prepared[1].visits()), preserve)
        return prepared, plan

    def apply(self, document, preserve=None):
        """Apply a document; a resident graph changes incrementally and is never rebuilt wholesale.

        Without a resident graph this builds one. With one, the shared transition
        keeps unaffected handles; a native failure is reverted by the reverse
        transition and verified, otherwise the session becomes uncertain with its
        remaining ownership kept for reset. ``preserve`` requires the named
        resident nodes to stay unchanged and refuses before any native call.
        """
        if self.uncertain:
            fault('UNCERTAIN_STATE', 'Previous native state could not be restored; restart this session', uncertain=True)
        if self.active is None and preserve is None:
            return self.apply_fresh(document)
        return self.apply_transition(document, () if preserve is None else preserve)

    def apply_fresh(self, document):
        prepared = self.prepare(document)  # Validate before native mutation.
        try:
            state = self.build(prepared)
            self.prepared = prepared
            geometry_objects = self.geometry()
            geometry_digest = digest(geometry_objects)
        except Exception as error:
            try:
                self.reset()
                self.prepared = self.document = self.geometry_digest = self.geometry_objects = None
            except Exception as recovery:
                self.uncertain = True
                fault('UNCERTAIN_STATE', 'Apply failed and native state could not be released',
                      applyError=str(error), rollbackError=str(recovery), uncertain=True)
            fault('APPLY_FAILED', 'Native apply failed; no resident state remains',
                  cause=str(error), rolledBack=True, revision=self.revision)
        self.document = copy.deepcopy(document)
        self.geometry_digest = geometry_digest
        self.geometry_objects = copy.deepcopy(geometry_objects)
        self.revision += 1
        return {**self.status(), 'updated': state['updated'], 'reused': False}

    def apply_transition(self, document, preserve):
        prepared, plan = self.prepare_transition(document, preserve)
        previous = self.prepared
        handles = dict(self.active.handles)
        try:
            state = self.active.transition(plan)
            self.prepared = prepared
            self.present(prepared)
            geometry_objects = self.geometry()
            geometry_digest = digest(geometry_objects)
            reply = {**self.status(), 'revision': self.revision + 1, 'documentDigest': digest(document),
                     'geometryDigest': geometry_digest, 'updated': state['updated'],
                     'reused': bool(plan.retained), 'transition': plan.report()}
            reply_budget(reply)
        except Exception as error:
            self.prepared = previous
            try:
                self.active.revert(plan)
                self.present(previous)
                if digest(self.geometry()) != self.geometry_digest:
                    fault('ROLLBACK_MISMATCH', 'Restored native geometry differs')
            except Exception as recovery:
                self.uncertain = True
                fault('UNCERTAIN_STATE', 'Apply failed and the prior native state could not be verified',
                      applyError=str(error), rollbackError=str(recovery), uncertain=True,
                      owned=sorted(self.active.handles), abandoned=sorted(self.active.abandoned),
                      unknown=copy.deepcopy(self.active.unknown))
            fault('APPLY_FAILED', 'Native apply failed; the previous state was restored incrementally and verified',
                  cause=str(error), rolledBack=True, revision=self.revision,
                  kept=sorted(k for k, h in handles.items() if self.active.handles.get(k) is h))
        self.document = copy.deepcopy(document)
        self.prepared = prepared
        self.geometry_digest = geometry_digest
        self.geometry_objects = copy.deepcopy(geometry_objects)
        self.revision += 1
        return reply

    @policy_request(fresh=True)
    def prepare_identity(self, expected, proofs):
        """Read-only proof of the authored history and the independently replayed native plan."""
        from .adaptors import registry
        from .identity_transition import verify, replay
        from .live_transport import validate
        validate('graph-prepare-identity', {'expected': expected, 'proofs': proofs})
        if self.uncertain or self.active is None or self.active.failed or self.document is None:
            fault('NO_RESIDENT_DATA', 'A usable resident graph is required for an identity transition')
        actual = {key: self.status()[key] for key in ('documentDigest', 'revision', 'geometryDigest')}
        if actual != expected:
            fault('STALE_IDENTITY_TRANSITION', 'The resident graph revision or geometry changed')
        metadata = registry.metadata(self.provider)
        projector = metadata.get('liveIdentityGeometry')
        relabel = metadata.get('extents', {}).get('relabel')
        if not projector or not relabel:
            fault('UNSUPPORTED_IDENTITY_TRANSITION', 'The adaptor has no qualified graph identity projection')
        document, steps = self.document, []
        for item in proofs:
            if not isinstance(item, dict) or set(item) != {'proof', 'reverse'}:
                fault('INVALID_IDENTITY_TRANSITION', 'Use directed checked forward evidence')
            before, after, directed = verify(item['proof'], reverse=item['reverse'])
            if before != document:
                fault('STALE_IDENTITY_TRANSITION', 'Identity evidence does not start at this exact authored graph')
            document = after
            steps.extend(directed)
        source = self.prepare(self.document)
        target = self.prepare(document)
        current_plan = self.active.master.document
        # A prior inverse may retain canonical backtick spelling. Only a checked
        # rename of the very same bound tokens may reconcile that spelling.
        replayed = replay(current_plan, steps)
        if replay(source[0].document, steps) != replayed:
            fault('IDENTITY_TRANSITION_MISMATCH', 'The current active plan differs from the authored source')
        inverse = [[new, old] for old, new in reversed(steps)]
        if replay(target[0].document, inverse) != replay(replayed, inverse):
            fault('IDENTITY_TRANSITION_MISMATCH', 'The target active plan differs from checked identity replay')
        names = {key: key for key in self.active.master.nodes}
        for old, new in steps:
            names = {key: new if value == old else value for key, value in names.items()}
        if ([names[key] for key in self.prepared[3]] != list(target[3])
                or tuple(names[key] for key in self.active.selection.roots) != tuple(target[1].roots)):
            fault('IDENTITY_TRANSITION_MISMATCH', 'The geometry selection differs from the checked rename')
        # Reuse the exact strict transfer proof without publishing or touching native objects.
        _, _, names, _, _ = self.active.prepare_reidentify(steps, lambda value: self.prepare(value)[0], relabel)
        from .live_transport import MAX_BYTES, reply_budget
        from .wire_json import Budget
        fields = metadata.get('liveIdentityStatusFields')
        if (metadata.get('liveIdentityGeometryBudget') is not True or not isinstance(fields, list)
                or any(not isinstance(field, str) for field in fields)
                or not {'id', 'label'} <= set(fields) or len(fields) != len(set(fields))):
            fault('UNSUPPORTED_IDENTITY_TRANSITION', 'The adaptor has no bounded identity reply projection')
        projected = registry.binding(projector)(self.geometry_objects, steps, budget=Budget(MAX_BYTES))
        observations = {names[key]: value for key, value in self.active.observations.items()}
        reply_budget(self.geometry_reply(projected, observations, self.revision + 1, document))
        status = self.status()
        objects, budget = [], Budget(MAX_BYTES)
        for original in status['objects']:
            identity = original.get('id')
            if identity not in names:
                fault('NATIVE_DIVERGENCE', 'Status object does not name an owned graph node')
            item = dict(original)
            for field in fields:
                if item.get(field) != identity:
                    fault('NATIVE_DIVERGENCE', 'Declared status identity field differs from its owner')
                budget.add(names[identity])
                item[field] = names[identity]
            objects.append(item)
        status.update(objects=objects, revision=self.revision + 1,
                      documentDigest=digest(document), geometryDigest=digest(projected))
        reply_budget(status)
        reply_budget({**status, 'reidentified': steps})
        reply_budget(self.identity_reply(document, projected, steps))
        return document, steps, target, projected, registry.binding(relabel)

    @policy_request(fresh=True)
    def reidentify(self, expected, proofs):
        """Adopt a prepared identity without applying, rebuilding or updating any native object."""
        document, steps, target, projected, relabel = self.prepare_identity(expected, proofs)
        previous = self.prepared
        backend = self.active.backend
        label = lambda handle, old, new: relabel(backend, handle, old, new)
        planner = lambda value: self.prepare(value)[0]
        rebound = False
        try:
            self.active = self.active.reidentify(steps, planner, label)
            rebound = True
            self.prepared = (self.active.master, self.active.selection, target[2], target[3])
            observed = self.geometry()
            if observed != projected:
                fault('IDENTITY_GEOMETRY_MISMATCH', 'Native geometry differs from the identity-only projection')
        except Exception as error:
            if not rebound:
                if self.active.failed:
                    self.uncertain = True
                raise
            try:
                inverse = [[new, old] for old, new in reversed(steps)]
                self.active = self.active.reidentify(inverse, planner, label)
                self.prepared = (self.active.master, self.active.selection, previous[2], previous[3])
                if self.geometry() != self.geometry_objects:
                    fault('IDENTITY_GEOMETRY_MISMATCH', 'Restored geometry differs from its original content')
            except Exception as recovery:
                self.uncertain = True
                fault('IDENTITY_TRANSITION_UNCERTAIN', 'Identity alignment failed and restoration could not be verified',
                      cause=str(error), rollbackError=str(recovery), uncertain=True)
            fault('IDENTITY_TRANSITION_FAILED', 'Identity alignment failed; original handles and geometry were restored',
                  cause=str(error), rolledBack=True)
        self.document = copy.deepcopy(document)
        self.geometry_objects = copy.deepcopy(observed)
        self.geometry_digest = digest(observed)
        self.revision += 1
        return {**self.status(), 'reidentified': steps}

    @staticmethod
    def identity_reply(document, projected, steps):
        return {'documentDigest': digest(document), 'geometryDigest': digest(projected), 'steps': steps}

    @staticmethod
    def geometry_reply(objects, observations, revision, document):
        return {'objects': objects, 'units': 'native', 'revision': revision,
                'faceIds': 'revision-scoped', 'documentDigest': digest(document), 'observations': observations}

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

    @policy_request(fresh=True)
    def dispatch(self, command, args):
        if command == 'status':
            return self.status()
        if command == 'shutdown':
            self.close()
            return {'closed': True}
        if command == 'graph-prepare-identity':
            document, steps, _, projected, _ = self.prepare_identity(args['expected'], args['proofs'])
            return self.identity_reply(document, projected, steps)
        if command == 'graph-reidentify':
            return self.reidentify(args['expected'], args['proofs'])
        if command == 'apply':
            return self.apply(args['document'])
        if self.uncertain:
            fault('UNCERTAIN_STATE', 'Restart the session before reading native geometry', uncertain=True)
        if self.prepared is None:
            fault('NO_DOCUMENT', 'Apply an authored document first')
        if command == 'geometry':
            return self.geometry_reply(self.geometry(), copy.deepcopy(self.active.observations), self.revision, self.document)
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
        self.geometry_objects = None
