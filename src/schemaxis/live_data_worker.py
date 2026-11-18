# Copyright (C) 2026 David L. F. Gaden.
"""Persistent extent pipeline. Runs only inside the selected native application."""
import copy
from schemaxis.identity_policy import policy_request
import os
import uuid
from .adaptors import registry
from .core.faults import SchemaxisError
from .pipeline import RuntimeClosure, digest
from .spatial_load import visit_of
from . import expressions


class Worker:
    def __init__(self, provider):
        self.provider = provider
        self.active = None
        self.document = None
        self.uncertain = False
        self.nonce, self.generation = uuid.uuid4().hex, 0
        # Append-only provenance of applied identity transitions; the last 64 are kept.
        self.transitions, self.transition_count = [], 0

    def status(self):
        return {'provider': self.provider, 'pid': os.getpid(), 'uncertain': self.uncertain,
                'transitions': self.transition_count, 'nodes': list(self.active.handles) if self.active else [],
                'owner': self.owner()}

    def owner(self, document=None):
        """Exact process/epoch and concrete resident state; never a content-only identity."""
        current = self.document if document is None else document
        return {'nonce': self.nonce, 'generation': self.generation,
                'documentDigest': digest(current) if current is not None else None,
                'roots': list(self.active.selection.roots) if self.active and self.active.selection else [],
                'visit': copy.deepcopy(self.active.visit) if self.active else None}

    def check_owner(self, expected):
        from .live_transport import fault, owner_matches
        if self.uncertain or self.active is None or self.active.failed:
            fault('UNCERTAIN_STATE', 'Resident ownership is unavailable; explicitly release it', uncertain=True)
        if not owner_matches(expected, self.owner()):
            fault('STALE_RESIDENT_OWNER', 'The native owner changed after this request was prepared')

    def prepare_transition(self, expected, document, roots, state, preserve, request):
        self.check_owner(expected)
        self.prepare_load(document, roots, state, preserve)
        from .live_transport import reply_budget
        reply = {'owner': self.owner(), 'prepared': digest({'expected': expected, 'document': document,
                 'roots': roots, 'state': state, 'preserve': preserve, 'request': request})}
        reply_budget(reply)
        return reply

    def prepare_aligned_transition(self, identity, transition):
        """Admit both requested changes before changing the current native namespace."""
        from .live_transport import fault, owner_matches, validate, reply_budget
        self.check_owner(identity['owner'])
        _, relabel = self.prepare_identity(**{k: identity[k] for k in ('expected', 'steps', 'result')})
        master = self.plan(transition['document'])
        visit = visit_of(master, master.select(transition['roots']), transition['state'])
        report = self.active.preflight_reidentified_transition(identity['steps'], self.plan,
            master, transition['roots'], visit, transition['preserve'], relabel)
        predicted = {**self.owner(), 'generation': self.generation + 1,
                     'documentDigest': identity['result'], 'roots': report['roots']}
        if not owner_matches(transition['expected'], predicted):
            fault('STALE_RESIDENT_OWNER', 'Ordinary preparation does not start at the exact renamed owner')
        prepared = digest(transition)
        # Include each full future request, including the preparation digest.
        validate('data-owned-identity', identity, self.provider)
        validate('data-transition', {**transition, 'prepared': prepared}, self.provider)
        reply = {'owner': self.owner(), 'predictedOwner': predicted, 'prepared': prepared}
        reply_budget(reply)
        return reply

    def transition(self, expected, document, roots, state, preserve, request, prepared):
        from .live_transport import fault
        checked = self.prepare_transition(expected, document, roots, state, preserve, request)
        if prepared != checked['prepared']:
            fault('STALE_RESIDENT_TRANSITION', 'Prepared transition differs from the exact candidate')
        return self.load(document, roots, state, preserve=preserve)

    def measure(self, expected, nodes):
        """Return current measurements without executing any part of the owned plan."""
        from .live_transport import fault
        self.check_owner(expected)
        if any(n not in self.active.handles or n not in self.active.observations for n in nodes):
            fault('NO_RESIDENT_MEASUREMENT', 'The owner has no current measurement for a requested node')
        return self.measured_reply(self.status(), {n: self.active.observations[n] for n in nodes}, True, [], [])

    def plan(self, document):
        """This provider's resident planning of a lowered document."""
        return registry.binding(registry.metadata(self.provider)['extents']['native'])(document, initialise=False)[0]

    @policy_request(fresh=True)
    def prepare_identity(self, expected, steps, result):
        """Check current measured reply projections without touching native data."""
        from .live_transport import fault
        from .identity_transition import replay
        hook = registry.metadata(self.provider)['extents'].get('relabel')
        if self.active is None or self.document is None:
            fault('NO_RESIDENT_DATA', 'Load Live Data before changing resident identities')
        if hook is None:
            fault('UNSUPPORTED_IDENTITY_TRANSITION', 'This adaptor declares no safe resident relabel operation')
        if digest(self.document) != expected:
            fault('STALE_IDENTITY_TRANSITION', 'The resident plan differs from the witnessed plan')
        document = replay(self.document, steps)
        if digest(document) != result:
            fault('IDENTITY_TRANSITION_MISMATCH', 'The recomputed resident plan differs from the witnessed result')
        relabel = registry.binding(hook)
        _, _, names, _, _ = self.active.prepare_reidentify(steps, self.plan, relabel)
        from .live_transport import reply_budget
        status = {**self.status(), 'nodes': [names[n] for n in self.active.handles],
                  'transitions': self.transition_count + 1,
                  'owner': {**self.owner(), 'generation': self.generation + 1, 'documentDigest': result,
                            'roots': [names[n] for n in self.active.selection.roots]}}
        reply_budget(status)
        reply_budget({**status, 'documentDigest': result, 'reidentified': [list(step) for step in steps]})
        observations = {names[n]: value for n, value in self.active.observations.items()}
        self.measured_reply(status, observations, True, [], [])
        return document, relabel

    @policy_request(fresh=True)
    def reidentify(self, expected, steps, result):
        """Rename only after the same native-free reply admission succeeds."""
        document, relabel = self.prepare_identity(expected, steps, result)
        self.backend = self.active.backend
        self.relabel = relabel
        self.generation += 1
        try:
            self.active = self.active.reidentify(steps, self.plan, self.label)
        except SchemaxisError as error:
            if error.fault.code == 'IDENTITY_TRANSITION_UNCERTAIN' or self.active.failed:
                self.uncertain = True
                raise
            # The primitive reversed every completed label and the failing call
            # made a structured non-uncertain refusal; original ownership remains.
            from dataclasses import replace
            raise SchemaxisError(replace(error.fault, observed={**error.fault.observed, 'rolledBack': True})) from error
        self.document = document
        self.transition_count += 1
        self.transitions.append({'expected': expected, 'result': result, 'steps': [list(step) for step in steps]})
        del self.transitions[:-64]
        return {**self.status(), 'documentDigest': result, 'reidentified': [list(step) for step in steps]}

    def label(self, handle, old, new):
        return self.relabel(self.backend, handle, old, new)

    @policy_request(fresh=True)
    def dispatch(self, command, args):
        if command == 'status': return self.status()
        if command == 'shutdown':
            self.close()
            return {'closed': True}
        if self.uncertain:
            from .live_transport import fault
            fault('UNCERTAIN_STATE', 'Resident native labels are uncertain; disable Live Data to release them', uncertain=True)
        if command in ('data-owned-identity', 'data-prepare-owned-identity'):
            self.check_owner(args['owner'])
            values = {k: args[k] for k in ('expected', 'steps', 'result')}
            if command == 'data-owned-identity':
                return self.reidentify(**values)
            self.prepare_identity(**values)
            return {'owner': self.owner(), 'documentDigest': args['result'], 'prepared': True}
        if command == 'data-prepare-aligned-transition':
            return self.prepare_aligned_transition(**args)
        if command == 'data-prepare-transition':
            return self.prepare_transition(**args)
        if command == 'data-transition':
            return self.transition(**args)
        if command == 'data-measure':
            return self.measure(**args)
        if command == 'data-prepare-identity':
            self.prepare_identity(args['expected'], args['steps'], args['result'])
            return {'documentDigest': args['result'], 'prepared': True}
        if command == 'data-reidentify':
            return self.reidentify(args['expected'], args['steps'], args['result'])
        if command == 'data-inspect':
            hook = registry.metadata(self.provider)['extents'].get('inspect')
            if not hook or self.active is None:
                from .live_transport import fault
                fault('UNSUPPORTED_INSPECTION', 'Load data in an adaptor supporting resident inspection first')
            from .live_transport import inspection_reply
            return inspection_reply({**registry.binding(hook)(self.active, **args), 'owner': self.owner()})
        if command != 'data-load':
            from .live_transport import fault
            fault('UNKNOWN_COMMAND', 'Live Data accepts data-load, data-inspect, data-reidentify, status and shutdown')
        return self.load(args['document'], args['roots'], args['state'])

    def prepare_load(self, document, roots, state, preserve=()):
        """Native-free plan of a load; the shared transition when resident data can continue.

        Returns the target plan, its visit and the transition, or None without
        usable resident data. ``preserve`` names resident nodes that must keep their
        exact handle and be neither configured nor updated.
        """
        from .live_transport import fault
        if self.uncertain:
            fault('UNCERTAIN_STATE', 'Resident native labels are uncertain; disable Live Data to release them', uncertain=True)
        master, backend = registry.binding(registry.metadata(self.provider)['extents']['native'])(document, initialise=self.active is None)
        visit = visit_of(master, master.select(roots), state)  # Validate before mutating native state.
        if self.active is None or self.active.failed:
            if preserve:
                fault('NO_RESIDENT_DATA', 'Load Live Data before requiring resident nodes to stay unchanged')
            return master, backend, visit, None
        return master, backend, visit, self.active.prepare_transition(master, roots, visit, preserve)

    def load(self, document, roots, state, preserve=None):
        """Load ``roots`` at ``state``, keeping every resident handle the shared transition keeps.

        The measured reply is built and admitted before the document is adopted.
        A direct load (``preserve`` None) releases all resident data when it fails;
        the host then discards this process. With ``preserve`` an ineligible change
        is refused before any native call, and a later failure, including reply
        admission, is reverted and verified, otherwise this worker becomes
        uncertain and keeps its known ownership until shutdown.
        """
        from .live_transport import fault
        master, backend, visit, plan = self.prepare_load(document, roots, state, () if preserve is None else preserve)
        self.generation += 1
        if plan is None:
            self.close()
            self.active = RuntimeClosure(master, backend)
            try:
                self.active.activate(roots)
                result = self.active.apply(visit)
                reply = self.measured_reply({**self.status(), 'owner': self.owner(document)}, result['observations'], False, result['updated'],
                                            list(self.active.handles))
            except BaseException:
                self.close()
                raise
        else:
            handles = dict(self.active.handles)
            try:
                result = self.active.transition(plan)
                reply = self.measured_reply({**self.status(), 'owner': self.owner(document)}, result['observations'], True, result['updated'],
                                            [n for n in self.active.handles if n not in plan.retained])
            except BaseException as error:
                if preserve is None:
                    self.close()
                    raise
                try:
                    self.active.revert(plan)
                except BaseException as recovery:
                    self.uncertain = True
                    fault('UNCERTAIN_STATE', 'Load failed and the resident data could not be restored',
                          loadError=str(error), rollbackError=str(recovery), uncertain=True,
                          owned=sorted(self.active.handles), abandoned=sorted(self.active.abandoned),
                          unknown=copy.deepcopy(self.active.unknown))
                fault('LOAD_FAILED', 'Load failed; the resident data was restored incrementally and verified',
                      cause=str(error), rolledBack=True,
                      kept=sorted(k for k, h in handles.items() if self.active.handles.get(k) is h))
        self.document = copy.deepcopy(document)
        return reply

    @staticmethod
    def measured_reply(status, observations, compatible, updated, created):
        from .live_transport import MAX_BYTES, reply_budget
        from .wire_json import Budget
        budget, result = Budget(MAX_BYTES), []
        for node, observation in observations.items():
            ports = observation['extents'] if 'extents' in observation else [observation.get('bounds')]
            for port, bounds in enumerate(ports):
                budget.add(node)
                state = 'notSpatial' if bounds is None else 'empty' if expressions.is_invalid_box(bounds) else 'ok'
                result.append({'node': node, 'port': port, 'status': state,
                               **({'bounds': list(bounds)} if state == 'ok' else {})})
        reply = {**status, 'extents': result, 'reused': compatible, 'updated': updated, 'created': created}
        reply_budget(reply)
        return reply

    def close(self):
        self.generation += 1
        self.document = None
        if self.active is not None:
            try: self.active.close()
            finally: self.active = None


def start(directory, parent_pid=None, parent_start=None, provider=None):
    from .live_transport import serve
    serve(directory, Worker(provider), parent_pid, parent_start)
