# Copyright (C) 2026 David L. F. Gaden.
"""Explicit, session-owned Live Data for Studio, console and Python/AI clients.

Native handles never leave their process. Observations are retained in memory,
keyed by the actual upstream recipe and visit, independently of editor windows.
"""
import copy
from contextlib import contextmanager
import operator
import threading
import uuid
from pathlib import Path
from .core.faults import SchemaxisError
from .errors import fail
from schemaxis.identity_policy import policy_request
from .identity_transition import binding, checked_transition, replay
from .pipeline import digest
from .storage import digest as input_digest
from .spatial_actions import Draft, Visit, Expression, spatial_eval
from .spatial_load import Closure, wanted_nodes
from .live_transport import ProcessSession, owner_matches


class DataProcess(ProcessSession):
    worker_module = 'schemaxis.live_data_worker'

    def __init__(self, provider, executable, directory, timeout):
        self.provider = provider
        super().__init__(getattr(executable, 'executable', executable), directory, timeout=timeout, startup_timeout=timeout)


def memory_bytes(pid):
    """Resident process memory, including the application; not a mesh-size claim."""
    try:
        for line in Path(f'/proc/{pid}/status').read_text().splitlines():
            if line.startswith('VmRSS:'): return int(line.split()[1]) * 1024
    except (OSError, ValueError): pass
    return None


MAX_TRANSITIONS = 32
EXPECTED = ('inputDigest', 'outputDigest', 'policyDigest')


def alive(client):
    process = getattr(client, 'process', None)
    if process is not None:
        return process.poll() is None and not getattr(client, '_closed', False)
    return not getattr(client, 'closed', False)


def registry_relabel(provider):
    """Whether the adaptor declares a safe resident relabel operation."""
    from .adaptors import registry
    return bool(registry.metadata(provider)['extents'].get('relabel'))


class LiveDataSession:
    def __init__(self, directory, factory=DataProcess):
        self.directory = Path(directory)
        self.factory = factory
        self.workers = {}
        self.cache = {}
        self.cache_owners = {}
        self.visits = {}
        # Witnessed identity views form one tree per (provider, sessionDocument,
        # operation) family. Requests without one of its views claim its root.
        self.views = {}
        self.roots = {}
        self.edges = {}
        self.accepted = {}
        self.ambiguous = {}
        self.closed = False
        self.lock = threading.RLock()

    @contextmanager
    def identity_stage(self):
        """Stage metadata under the session lock; install only after durable publication.

        The stage shares native clients; use only metadata adoption on it. Install replaces
        host metadata only. Holding this lock through publication prevents another
        request from consuming view limits or changing client ownership meanwhile.
        """
        with self.lock:
            if self.closed:
                fail('SESSION_CLOSED', 'Open a new Live Data session')
            staged = LiveDataSession(self.directory, self.factory)
            fields = ('cache', 'cache_owners', 'visits', 'views', 'roots', 'edges', 'accepted', 'ambiguous')
            for name in fields:
                setattr(staged, name, copy.deepcopy(getattr(self, name)))
            staged.workers = {key: {**copy.deepcopy({k: v for k, v in worker.items() if k != 'client'}),
                                   'client': worker['client']} for key, worker in self.workers.items()}
            installed = False
            def install():
                nonlocal installed
                if installed:
                    return
                for name in (*fields, 'workers'):
                    setattr(self, name, getattr(staged, name))
                installed = True
            yield staged, install

    def needs_identity(self, request):
        """Whether this exact family has resident, observed or witnessed ownership."""
        family = self.family(request, Draft(request))
        return (family in self.views.values() or any(key[:3] == family for key in self.workers)
                or any(family in self.cache_owners.get(key, ()) for key in self.cache))

    @staticmethod
    def signature(draft, closure, node, state):
        nodes = closure.upstream([node])
        # Only dependencies participate. Adding a name or editing a downstream
        # output must not invalidate an expensive reader's observations.
        document = closure.document(nodes, draft.envelope)
        for item in document['nodes']:
            for key in ('options', 'inputs'):
                if item.get(key) == {}: item.pop(key)
        return digest([document, node, state])

    @staticmethod
    def family(request, draft):
        return (draft.selected.scope.adaptor.name, request.get('sessionDocument'), draft.operation)

    def view_of(self, request, draft):
        """The explicit witnessed view a request names, validated against its scope."""
        view = request.get('view')
        if view is None:
            return None
        if not isinstance(view, str) or view not in self.views:
            fail('UNKNOWN_IDENTITY_VIEW', 'Use a view returned by an accepted identity transition', '$.view')
        if self.views[view] != self.family(request, draft):
            fail('IDENTITY_VIEW_MISMATCH', 'This view belongs to another document, operation or adaptor', '$.view')
        return view

    def claim(self, family, view, closure):
        """The view of ``family``'s lineage a request occupies and the names it cannot own.

        A request carrying one of its views owns that view's names. A request
        without one claims the root. A root identity is contested when the draft
        also holds a name that a witnessed view gives to it: that input cannot be
        the witnessed original for it, so the identity, that name and everything
        downstream of either are excluded. Unaffected nodes stay claimable.
        """
        if view is not None and self.views[view] == family:
            return view, set()
        root = self.roots.get(family)
        if root is None:
            return None, set()
        names = set()
        for origin, current in self.pairs(family):
            if current in closure.by_id:
                names.update((origin, current))
        excluded = set(names)
        if names:
            for node in closure.by_id:
                try:
                    if names & set(closure.upstream([node])):
                        excluded.add(node)
                except Exception:
                    excluded.add(node)
        return root, excluded

    def pairs(self, family):
        """(root identity, other name) for every rename a witnessed view of this lineage holds."""
        if family not in self.ambiguous:
            root, found = self.roots[family], set()
            for view, owner in self.views.items():
                if owner != family:
                    continue
                pairs = []
                for edge, forward in self.path(root, view):
                    mapping = edge['mapping'] if forward else {new: old for old, new in edge['mapping'].items()}
                    for old, new in mapping.items():
                        index = next((i for i, (_, name) in enumerate(pairs) if name == old), None)
                        if index is None:
                            pairs.append((old, new))
                        else:
                            pairs[index] = (pairs[index][0], new)
                found.update(pair for pair in pairs if pair[0] != pair[1])
            self.ambiguous[family] = found
        return self.ambiguous[family]

    def renamed(self, family):
        """Names that some witnessed view of this lineage gives to a different identity."""
        return {current for _, current in self.pairs(family)}

    def path(self, start, goal):
        """The unique witnessed tree path between two views, as (edge, forward) pairs."""
        previous, pending = {start: None}, [start]
        while pending:
            view = pending.pop(0)
            for edge in self.edges.values():
                for here, there, forward in ((edge['from'], edge['to'], True), (edge['to'], edge['from'], False)):
                    if here == view and there not in previous:
                        previous[there] = (view, edge, forward)
                        pending.append(there)
        if goal not in previous:
            return None
        found = []
        while previous[goal] is not None:
            view, edge, forward = previous[goal]
            found.append((edge, forward))
            goal = view
        return found[::-1]

    @staticmethod
    def sides(edge, forward):
        """(source draft, source closure), (target draft, target closure) and the name mapping."""
        source, target = edge['sides'] if forward else edge['sides'][::-1]
        mapping = edge['mapping'] if forward else {new: old for old, new in edge['mapping'].items()}
        return source, target, mapping

    def carry(self, evidence, target, state):
        """A handle's name and exact signature in ``target`` from where its recipe was measured.

        Returns (name, signature, known). The signature is None once a witness's
        recipe differs from the measured one; known is False when some witness
        never held the node, so its lineage in ``target`` is unknown.
        """
        name, signature = evidence['name'], evidence['signature']
        if evidence['view'] == target:
            return name, signature, True
        found = self.path(evidence['view'], target) if evidence['view'] is not None else None
        if found is None:
            return name, None, False
        for edge, forward in found:
            (source, source_closure), (other, other_closure), mapping = self.sides(edge, forward)
            renamed = mapping.get(name, name)
            if name not in source_closure.by_id or renamed not in other_closure.by_id:
                return renamed, None, False
            try:
                same = signature is not None and self.signature(source, source_closure, name, state) == signature
                signature = self.signature(other, other_closure, renamed, state) if same else None
            except Exception:
                signature = None
            name = renamed
        return name, signature, True

    def resident(self, worker, view, closure):
        """A worker's handles named and proved as the request's view needs them, or None.

        Unlineaged workers keep the existing content-compatible sharing. A lineaged
        worker's physical names follow the witnessed path to the view the request
        occupies (``steps`` is the native alignment). Each handle's signature is
        carried exactly from its own measurement; ``excluded`` lists names the
        request may not own (contested or of unknown lineage).
        """
        evidence, state = worker.get('evidence', {}), worker.get('state')
        sources = set(worker.get('sources', ()))
        owner = worker.get('view')
        if owner is None:
            signatures = {node: item['signature'] for node, item in evidence.items()}
            return {'state': state, 'signatures': signatures, 'sources': sources & set(signatures),
                    'nodes': list(worker.get('nodes', [])), 'steps': [], 'excluded': set(), 'names': {n: n for n in evidence}}
        target, contested = self.claim(self.views[owner], view, closure)
        found = self.path(owner, target) if target is not None else None
        if found is None:
            return None
        names, steps = {node: node for node in evidence}, []
        for edge, forward in found:
            _, _, mapping = self.sides(edge, forward)
            current = set(names.values())
            steps.extend([old, new] for old, new in mapping.items() if old in current)
            names = {node: mapping.get(name, name) for node, name in names.items()}
            if len(set(names.values())) != len(names):
                return None
        signatures, unknown = {}, set()
        for node, item in evidence.items():
            name, signature, known = self.carry(item, target, state)
            signatures[names[node]] = signature if known and name == names[node] else None
            if not known or name != names[node]:
                unknown.add(names[node])
        return {'state': state, 'signatures': signatures, 'sources': {names[n] for n in sources if n in names},
                'nodes': [names.get(n, n) for n in worker.get('nodes', [])], 'steps': steps, 'view': target,
                'excluded': contested | unknown, 'names': names}

    def ready(self, worker, record):
        """Whether native state can serve the record without an unsupported relabel."""
        return not worker.get('uncertain') and (not record['steps'] or registry_relabel(worker['provider']))

    def align(self, key, worker, record):
        """Move native identities along the witnessed path after required admission."""
        if record['steps']:
            plan = replay(worker['plan'], record['steps'])
            expected_owner = {**worker['owner'], 'generation': worker['owner']['generation'] + 1,
                              'documentDigest': digest(plan),
                              'roots': [record['names'][n] for n in worker['owner']['roots']]}
            response = self.preserving_request(worker, 'data-owned-identity', expected_owner=expected_owner, owner=worker['owner'],
                                                expected=digest(worker['plan']), steps=record['steps'], result=digest(plan))
            worker.update(plan=plan, nodes=response['nodes'], pid=response['pid'], owner=response['owner'],
                          transitions=worker.get('transitions', 0) + 1)
        # Physical names move; each handle keeps the evidence of where its recipe was measured.
        names = record['names']
        worker.update(evidence={names[node]: item for node, item in worker.get('evidence', {}).items()},
                      sources=sorted(names.get(node, node) for node in worker.get('sources', ())),
                      view=record.get('view', worker.get('view')))

    @policy_request
    def prepare_identity_transition(self, request, identity_pointer, new_name, expected_input_digest):
        """Preview one checked rename for a Live Data view. Nothing in the session changes."""
        if self.closed: fail('SESSION_CLOSED', 'Open a new Live Data session')
        transition = checked_transition(request, identity_pointer, new_name, expected_input_digest)
        draft = Draft(request)
        with self.lock:
            view = self.view_of(request, draft)
        return {'transition': binding(transition), 'input': transition['input'], 'view': view,
                'changedPointers': transition['changedPointers'], 'identityChanges': transition['identityChanges']}

    @policy_request
    def accept_identity_transition(self, request, identity_pointer, new_name, expected):
        """Adopt a previewed checked rename as a new unsaved view of this session.

        The rename is recomputed and must reproduce every expected digest. No file,
        session document or selection is written and no source is loaded. Matching
        observations are copied (never moved) to the new recipes; resident workers
        exactly in the original view join its lineage and are relabelled only when a
        request for another view needs them. Repeating an accepted transition from
        the same view returns the same views.
        """
        if self.closed: fail('SESSION_CLOSED', 'Open a new Live Data session')
        if not isinstance(expected, dict) or set(expected) != set(EXPECTED) or not all(
                isinstance(expected[k], str) for k in EXPECTED):
            fail('INVALID_REQUEST', 'Give the inputDigest, outputDigest and policyDigest of the preview', '$.expected')
        transition = checked_transition(request, identity_pointer, new_name, expected['inputDigest'])
        if any(transition[k] != expected[k] for k in EXPECTED):
            fail('STALE_IDENTITY_TRANSITION', 'The recomputed rename differs from the preview; preview again', '$.expected')
        return self._adopt_identity(request, transition)

    @policy_request
    def accept_history_identity(self, request, evidence, *, reverse=False):
        """Adopt exact directed durable proof, including a fresh owner's recovered Undo.

        The original forward proof is recomputed. An inverse restores its original
        spelling; native alignment still uses independently replayed plan steps.
        No handles from an earlier session are inferred or recovered.
        """
        from .identity_transition import verify
        before, after, steps = verify(evidence, reverse=reverse)
        if request.get('input') != before:
            fail('STALE_IDENTITY_TRANSITION', 'Directed history does not start at this exact input')
        transition = {**evidence['binding'], 'input': after,
                      'inputDigest': input_digest(before), 'outputDigest': input_digest(after),
                      'old': steps[0][0], 'new': steps[0][1]}
        draft = Draft(request)
        if draft.operation != transition['operation'] or draft.selected.base != transition['scope']:
            fail('IDENTITY_SCOPE_MISMATCH', 'History belongs to another operation scope')
        return self._adopt_identity(request, transition)

    def prepare_worker_identity(self, worker, steps):
        if not steps:
            return
        plan = replay(worker['plan'], steps)
        result = digest(plan)
        response = self.preserving_request(worker, 'data-prepare-owned-identity', owner=worker['owner'],
                                            expected=digest(worker['plan']), steps=steps, result=result)
        if not isinstance(response, dict) or response.get('prepared') is not True or response.get('documentDigest') != result:
            fail('IDENTITY_TRANSITION_MISMATCH', 'Resident reply admission differs from the checked plan')

    def check_cached_identity(self, draft, extra=None):
        """Budget retained measured replies at their exact visits, without loading."""
        from .live_transport import MAX_BYTES, reply_budget
        from .wire_json import Budget
        closure = Closure(draft.selected)
        cache = {**self.cache, **(extra or {})}
        states = {digest(state): state for state in self.visits.values()}
        for state in states.values():
            extents, budget = [], Budget(MAX_BYTES)
            for node in closure.by_id:
                try: key = self.signature(draft, closure, node, state)
                except Exception: continue
                for item in cache.get(key, []):
                    budget.add(item)
                    extents.append(item)
            if extents:
                reply_budget(self.observation_reply(draft, state, extents))

    def check_identity_view(self, request, target):
        """Check an existing witnessed destination without loading or relabelling."""
        draft = Draft(request)
        closure = Closure(draft.selected)
        family = self.family(request, draft)
        if self.views.get(target) != family:
            fail('IDENTITY_VIEW_REQUIRED', 'The destination view belongs to another document or operation')
        self.check_cached_identity(draft)
        for key, worker in self.workers.items():
            if key[:3] != family:
                continue
            record = self.resident(worker, target, closure)
            if record and not self.ready(worker, record):
                fail('UNSUPPORTED_IDENTITY_TRANSITION', 'Resident data cannot adopt this history view safely')
            if record:
                self.prepare_worker_identity(worker, record['steps'])

    def _adopt_identity(self, request, transition):
        """Install host metadata only after the caller independently checked its transition."""
        before = Draft(request)
        after = Draft({**request, 'input': transition['input']})
        sides = ((before, Closure(before.selected)), (after, Closure(after.selected)))
        mapping = {transition['old']: transition['new']}
        family = self.family(request, before)
        with self.lock:
            if self.closed: fail('SESSION_CLOSED', 'Open a new Live Data session')
            view = self.view_of(request, before)
            source, contested = self.claim(family, view, sides[0][1])
            if contested:
                fail('IDENTITY_VIEW_REQUIRED', 'This draft reuses a witnessed renamed name; pass the view it belongs to', '$.view')
            key = (source, *(transition[k] for k in EXPECTED))
            if key in self.accepted:
                return copy.deepcopy(self.edges[self.accepted[key]]['result'])
            if len(self.edges) >= MAX_TRANSITIONS:
                fail('IDENTITY_LIMIT', 'This Live Data session holds at most 32 identity transitions; close it to release them')
            adopted, relabel = [], False
            (before_draft, before_closure), (after_draft, after_closure) = sides
            for worker_key, worker in self.workers.items():
                if worker_key[:3] != family:
                    continue
                if worker.get('view') is None:
                    # Only a worker exactly in the original view joins its lineage.
                    try:
                        exact = worker.get('state') is not None and all(
                            item['view'] is None and node in before_closure.by_id
                            and self.signature(before_draft, before_closure, node, worker['state']) == item['signature']
                            for node, item in worker.get('evidence', {}).items())
                    except Exception:
                        exact = False
                    if not exact:
                        continue
                    adopted.append(worker)
                    moves = transition['old'] in worker.get('evidence', {})
                    steps = [[transition['old'], transition['new']]] if moves else []
                else:
                    record = self.resident(worker, source, before_closure) if source else None
                    moves = bool(record) and (bool(record['steps']) or transition['old'] in record['nodes'])
                    steps = ([] if not record else [*record['steps'], *([[transition['old'], transition['new']]]
                             if transition['old'] in record['nodes'] else [])])
                if moves and (worker.get('uncertain') or not registry_relabel(worker['provider'])):
                    relabel = True
                elif moves:
                    self.prepare_worker_identity(worker, steps)
            if relabel:
                fail('UNSUPPORTED_IDENTITY_TRANSITION', 'Resident data of this adaptor cannot be relabelled safely; disable it first')
            copies, budgets = {}, {}
            from .wire_json import Budget
            from .live_transport import MAX_BYTES
            for cache_key, items in self.cache.items():
                state, node = self.visits.get(cache_key), items[0]['node'] if items else None
                renamed = mapping.get(node, node)
                if state is None or node not in before_closure.by_id or renamed not in after_closure.by_id:
                    continue
                try:
                    if self.signature(before_draft, before_closure, node, state) != cache_key:
                        continue
                    target = self.signature(after_draft, after_closure, renamed, state)
                except Exception:
                    continue
                if target != cache_key and target not in self.cache:
                    projected = []
                    budget = budgets.setdefault(digest(state), Budget(MAX_BYTES))
                    for item in items:
                        candidate = {**item, 'node': renamed}
                        budget.add(candidate)
                        projected.append(copy.deepcopy(candidate))
                    copies[target] = (projected, state)
            self.check_cached_identity(after_draft, {key: items for key, (items, _) in copies.items()})
            if source is None:
                source = uuid.uuid4().hex
                self.views[source] = family
                self.roots[family] = source
                key = (source, *key[1:])
            destination = uuid.uuid4().hex
            self.views[destination] = family
            edge = uuid.uuid4().hex
            result = {'from': source, 'to': destination, 'transition': binding(transition),
                      'input': transition['input'], 'retainedObservations': len(copies), 'adoptedWorkers': len(adopted)}
            self.edges[edge] = {'from': source, 'to': destination, 'mapping': mapping, 'sides': sides,
                                'transition': binding(transition), 'result': result}
            self.accepted[key] = edge
            self.ambiguous.pop(family, None)
            for worker in adopted:
                worker['view'] = source
                for item in worker.get('evidence', {}).values():
                    item['view'] = source
            for cache_key, (items, state) in copies.items():
                self.cache[cache_key] = items
                self.cache_owners.setdefault(cache_key, set()).add(family)
                self.visits[cache_key] = copy.deepcopy(state)
            return copy.deepcopy(result)

    def observations(self, request):
        draft = Draft(request)
        if not draft.selected.scope.nodes: return None
        closure = Closure(draft.selected)
        state = Visit(draft, False).state
        extents = []
        with self.lock:
            for node in closure.by_id:
                try: key = self.signature(draft, closure, node, state)
                except Exception: continue  # The ordinary evaluator reports invalid drafts.
                extents.extend(copy.deepcopy(self.cache.get(key, [])))
                if self.cache.get(key):
                    self.cache_owners.setdefault(key, set()).add(self.family(request, draft))
        if not extents: return None
        return self.observation_reply(draft, state, extents)

    @staticmethod
    def observation_reply(draft, state, extents):
        return {'inputDigest': draft.digest, 'state': state, 'extents': extents,
                **({'operation': draft.operation} if draft.operation is not None else {})}

    def evaluate(self, request):
        observations = self.observations(request)
        return spatial_eval({**request, **({'observations': observations} if observations else {})})

    def selection(self, request):
        draft = Draft(request)
        scope = draft.selected.scope
        readers = set(scope.loaders() or []) if scope.adaptor.extents else set()
        observed = self.observations(request)
        known = {e['node'] for e in (observed or {}).get('extents', [])}
        closure = Closure(draft.selected)
        state = Visit(draft, False).state
        status = self.status()
        with self.lock:
            view = self.view_of(request, draft)
            resident = set()
            for worker in self.workers.values():
                record = self.resident(worker, view, closure)
                if record is not None and self.ready(worker, record):
                    resident.update((node, key) for node, key in record['signatures'].items()
                                    if key is not None and node not in record['excluded'])
        nodes = []
        for node in closure.raw:
            try: loaded = (node['id'], self.signature(draft, closure, node['id'], state)) in resident
            except Exception: loaded = False
            nodes.append({'id': node['id'], 'filter': node.get('filter'), 'reader': node['id'] in readers,
                          'source': not node.get('inputs'), 'loaded': loaded, 'observed': node['id'] in known})
        return {'supported': scope.adaptor.extents is True, 'nodes': nodes, **status}

    def refresh(self, request, *, locations=None, timeout=300, missing_only=False):
        """Resolve requested volumes from resident sources, without enabling new sources.

        Cached observations remain usable after unload. A changed source recipe
        requires explicit selection/loading; refresh never rereads files from disk.
        """
        if self.closed: fail('SESSION_CLOSED', 'Open a new Live Data session')
        draft = Draft(request)
        if draft.selected.scope.adaptor.extents is not True:
            return self.evaluate(request)
        closure = Closure(draft.selected)
        state = Visit(draft, False).state
        expression = Expression(draft.selected, request['expression'], request.get('destination')) if 'expression' in request else None
        roots = request.get('nodes')
        if roots is None: roots = wanted_nodes(draft, draft.selected, request.get('entries'), expression)
        if not isinstance(roots, list) or any(not isinstance(n, str) or n not in closure.by_id for n in roots):
            fail('UNKNOWN_NODE', 'Choose existing nodes to refresh from Live Data')
        with self.lock:
            self.status()  # Remove exited workers before deciding what is resident.
            for node in roots:
                if missing_only and self.signature(draft, closure, node, state) in self.cache: continue
                self.load({**request, 'nodes': [node]}, locations=locations, timeout=timeout, resident_only=True)
        return {**self.evaluate(request), 'observations': self.observations(request), 'liveData': self.status()}

    def load(self, request, *, locations=None, timeout=300, resident_only=False):
        if self.closed: fail('SESSION_CLOSED', 'Open a new Live Data session')
        from .adaptors import registry
        from .configuration import locations as configured_locations
        draft = Draft(request)
        member = draft.selected
        if member.scope.adaptor.extents is not True:
            fail('EXTENTS_UNSUPPORTED', 'This adaptor does not report spatial extents')
        closure = Closure(member)
        state = Visit(draft, False).state
        expression = Expression(member, request['expression'], request.get('destination')) if 'expression' in request else None
        roots = request.get('nodes')
        if roots is None: roots = wanted_nodes(draft, member, request.get('entries'), expression)
        if not isinstance(roots, list) or any(not isinstance(n, str) or n not in closure.by_id for n in roots):
            fail('UNKNOWN_NODE', 'Choose existing nodes for Live Data')
        if not roots: return self.evaluate(request)
        requested = set(roots)
        provider = member.scope.adaptor.name
        family = (provider, request.get('sessionDocument'), draft.operation)
        with self.lock:
            view = self.view_of(request, draft)
            # Documents with different sources keep separate resident pipelines.
            # Prefer the one sharing the most unchanged upstream sources.
            candidates, blocked, contested = [], False, set()
            current_sources = [n for n in closure.by_id if not closure.by_id[n].get('inputs')]
            source_keys = {}
            for n in current_sources:
                try: source_keys[n] = self.signature(draft, closure, n, state)
                except Exception: continue
            needed = closure.upstream(roots)
            wanted = set(needed)
            for key, worker in self.workers.items():
                if key[:3] != family and not (resident_only and key[0] == provider): continue
                record = self.resident(worker, view, closure)
                if record is None: continue
                excluded = record['excluded']
                if excluded & wanted:
                    contested.update(excluded & wanted)
                    continue
                matching = set()
                for n in record['nodes']:
                    try:
                        if (n not in excluded and record['signatures'].get(n) is not None
                                and record['signatures'][n] == self.signature(draft, closure, n, state)):
                            matching.add(n)
                    except Exception: continue
                # Only needed resident sources must match; a changed one belongs to another pipeline.
                if any(n in record['sources'] and n not in matching for n in wanted): continue
                shared = len(matching & record['sources'])
                if resident_only:
                    required = [n for n in needed if n in current_sources]
                    if not required or any(n not in matching or n not in record['sources'] for n in required): continue
                if not shared: continue
                # Handles this request neither needs nor owns stay untouched on the worker.
                kept = [n for n in record['nodes'] if n not in matching and n not in wanted]
                in_place = all(n in matching for n in needed)
                if not self.ready(worker, record):
                    blocked = True
                    continue
                candidates.append((shared, key, worker, record, matching, kept, in_place))
            if candidates:
                _, worker_key, retained, record, matching, kept, in_place = max(candidates, key=operator.itemgetter(0))
                if in_place:
                    self.align(worker_key, retained, record)
                    self.serve(worker_key, retained, draft, closure, state, needed)
                    return {**self.evaluate(request), 'observations': self.observations(request), 'liveData': self.status()}
            else:
                if resident_only: return self.evaluate(request)
                if contested:
                    fail('IDENTITY_VIEW_REQUIRED', 'This draft reuses a witnessed renamed name for resident nodes; '
                         'pass the view it belongs to', '$.view', nodes=sorted(contested))
                if blocked:
                    fail('IDENTITY_TRANSITION_UNAVAILABLE', 'Matching resident data cannot be relabelled safely; '
                         'disable Live Data before loading it again')
                worker_key, retained, record, matching, kept = (*family, uuid.uuid4().hex), None, None, set(), []
            # Keep previously requested roots when their recipe still matches.
            roots = [*roots, *(n for n in record['nodes'] if n in matching and n not in roots)] if retained else roots
            nodes = closure.upstream(roots)
            document = closure.document(nodes, draft.envelope)
            projected_plan = replay(retained['plan'], record['steps']) if retained and record['steps'] else (
                retained['plan'] if retained else None)
            if kept:
                document = self.carried({**retained, 'plan': projected_plan}, kept, document)
                if document is None:
                    if resident_only: return self.evaluate(request)
                    fail('LIVE_DATA_CONFLICT', 'Loading this would retire resident nodes another view still uses; '
                         'disable Live Data or use that view', nodes=sorted(kept))
            setup = registry.binding(registry.metadata(provider)['extents']['setup'])
            master, interpreter, arguments = setup(document, configured_locations(locations or {}))
            mapped = {'timeIndex': state['timeIndex'], 'indices': closure.indices(nodes, state['indices'])}
            from .spatial_load import visit_of
            concrete = visit_of(master, master.select([*roots, *kept]), mapped)
            if retained is None:
                client = self.factory(provider, interpreter, self.directory / uuid.uuid4().hex, timeout)
                target, owned = self.claim(family, view, closure)
                retained = {'client': client, 'evidence': {}, 'sources': [], 'nodes': [], 'provider': provider,
                            'view': None if owned else target}
                self.workers[worker_key] = retained
            plan = {**master.document, 'version': document['version']}
            try:
                if record is None:
                    response = retained['client'].request('data-load', document=plan, roots=[*roots, *kept], state=mapped)
                    if not owner_matches(response.get('owner'), {'documentDigest': digest(plan),
                            'roots': [*roots, *kept], 'visit': concrete}):
                        fail('RESIDENT_OWNER_MISMATCH', 'Initial load returned a different resident owner')
                else:
                    protected = sorted(set(kept) | (matching & record['sources']))
                    predicted = ({**retained['owner'], 'generation': retained['owner']['generation'] + 1,
                                  'documentDigest': digest(projected_plan),
                                  'roots': [record['names'][n] for n in retained['owner']['roots']]}
                                 if record['steps'] else retained['owner'])
                    arguments = {'expected': predicted, 'document': plan, 'roots': [*roots, *kept],
                                 'state': mapped, 'preserve': protected, 'request': uuid.uuid4().hex}
                    from .live_transport import validate
                    prepared_digest = digest(arguments)
                    validate('data-transition', {**arguments, 'prepared': prepared_digest}, provider)
                    if record['steps']:
                        identity = {'owner': retained['owner'], 'expected': digest(retained['plan']),
                                    'steps': record['steps'], 'result': digest(projected_plan)}
                        prepared = self.preserving_request(retained, 'data-prepare-aligned-transition',
                            identity=identity, transition=arguments, expected_prediction=predicted,
                            expected_prepared=prepared_digest)
                    else:
                        prepared = self.preserving_request(retained, 'data-prepare-transition', **arguments,
                                                           expected_prepared=prepared_digest)
                    self.align(worker_key, retained, record)
                    response = self.preserving_request(retained, 'data-transition', **arguments,
                                                       prepared=prepared['prepared'], expected_owner={**retained['owner'],
                                                           'generation': retained['owner']['generation'] + 1,
                                                           'documentDigest': digest(plan),
                                                           'roots': [*roots, *kept], 'visit': concrete})
            except BaseException:
                if record is not None:
                    raise  # The preserving path retains the actual owner, including uncertainty.
                self.workers.pop(worker_key, None)
                retained['client'].close()
                # A failed refresh must not silently reuse older measurements.
                for node in requested:
                    key = self.signature(draft, closure, node, state)
                    self.cache.pop(key, None)
                    self.cache_owners.pop(key, None)
                    self.visits.pop(key, None)
                raise
            grouped = {}
            for item in response['extents']:
                if item['node'] in nodes: grouped.setdefault(item['node'], []).append(item)
            signatures = {node: self.signature(draft, closure, node, state) for node in nodes}
            for node, items in grouped.items():
                self.cache[signatures[node]] = copy.deepcopy(items)
                self.cache_owners.setdefault(signatures[node], set()).add(family)
                self.visits[signatures[node]] = copy.deepcopy(state)
            # This request measured its own nodes in its view; kept handles keep their evidence.
            measured = record['view'] if record and 'view' in record else retained.get('view')
            evidence = {n: item for n, item in retained.get('evidence', {}).items() if n in kept}
            for n in set(evidence) & set(response['updated']):  # Recomputed from a changed upstream.
                evidence[n] = {**evidence[n], 'signature': None}
            evidence.update({n: {'view': measured, 'name': n, 'signature': signatures[n]} for n in nodes})
            sources = {n for n in nodes if n in current_sources} | {n for n in kept if n in record['sources']}
            retained.update(evidence={n: evidence[n] for n in response['nodes']}, sources=sorted(sources & set(response['nodes'])),
                            nodes=response['nodes'], pid=response['pid'], owner=response['owner'], plan=copy.deepcopy(plan), state=copy.deepcopy(state),
                            mapped=copy.deepcopy(mapped), lastLoad={k: response[k] for k in ('reused', 'updated', 'created')})
        observations = self.observations(request)
        return {**self.evaluate(request), 'observations': observations, 'liveData': self.status()}

    @staticmethod
    def carried(worker, kept, document):
        """The request's plan plus the worker's own definitions of kept handles, or None on conflict.

        Kept nodes and the sections they read are copied verbatim from the plan
        the worker holds; any differing shared entry or swept kept node refuses.
        """
        plan = worker['plan']
        if worker.get('mapped', {}).get('indices'):
            return None
        result = copy.deepcopy(document)
        names = {node['id'] for node in result['nodes']}
        extra = [copy.deepcopy(node) for node in plan['nodes'] if node['id'] in kept]
        if names & {node['id'] for node in extra} or len(extra) != len(kept):
            return None
        result['nodes'] = result['nodes'] + extra
        for key, value in plan.items():
            if key in ('nodes', 'version'):
                continue
            if key not in result:
                result[key] = copy.deepcopy(value)
            elif isinstance(value, dict) and isinstance(result[key], dict):
                for entry, item in value.items():
                    if entry in result[key] and result[key][entry] != item:
                        return None
                    result[key].setdefault(entry, copy.deepcopy(item))
            elif result[key] != value:
                return None
        return result

    def preserving_request(self, worker, command, *, expected_owner=None, expected_prediction=None,
                           expected_prepared=None, **args):
        """Keep the actual owner on refusal/uncertainty; never retry an unacknowledged mutation."""
        client = worker['client']
        request = getattr(client, 'request_retained', None)
        if not callable(request):
            fail('UNSUPPORTED_RESIDENT_CLIENT', 'This client does not declare preserving request ownership')
        previous = copy.deepcopy(worker['owner'])
        expected_owner = previous if expected_owner is None else expected_owner
        try:
            result = request(command, **args)
            if not owner_matches(result.get('owner'), expected_owner):
                fail('RESIDENT_OWNER_MISMATCH', 'The response differs from the exact resident transition')
            if expected_prediction is not None and not owner_matches(result.get('predictedOwner'), expected_prediction):
                fail('RESIDENT_OWNER_MISMATCH', 'Preparation predicts a different resident owner')
            if expected_prepared is not None and result.get('prepared') != expected_prepared:
                fail('RESIDENT_OWNER_MISMATCH', 'Preparation does not bind the complete ordinary candidate')
            worker.pop('fault', None)
            return result
        except BaseException as error:
            detail = error.fault if isinstance(error, SchemaxisError) else None
            if detail and detail.observed.get('rolledBack') is True and not detail.observed.get('uncertain'):
                try:
                    status = request('status')
                    owner = status['owner']
                    if (status.get('uncertain') or not owner_matches(owner,
                            {**previous, 'generation': previous['generation'] + 1})):
                        raise ValueError('Rollback ownership does not match the prior resident state')
                    worker['owner'] = owner
                except BaseException:
                    worker['uncertain'] = True
                else:
                    raise
            elif detail and not detail.observed.get('uncertain') and detail.code not in (
                    'NATIVE_ERROR', 'NATIVE_EXIT', 'LIVE_TIMEOUT', 'IPC_ERROR', 'SESSION_CLOSED',
                    'STALE_RESIDENT_OWNER', 'RESIDENT_OWNER_MISMATCH', 'UNCERTAIN_STATE', 'IDENTITY_TRANSITION_UNCERTAIN'):
                raise  # Checked preparation/read-only admission refusal; nothing mutated.
            else:
                worker['uncertain'] = True
            worker['fault'] = {'code': detail.code if detail else 'NATIVE_TRANSPORT_FAILED', 'message': str(error)}
            # Relabel uncertainty cannot change measured geometry. Retained cached
            # observations remain valid in their original exact authored views.
            invalid = worker.get('evidence', {}).values() if command == 'data-transition' else ()
            for item in invalid:
                signature = item.get('signature')
                self.cache.pop(signature, None)
                self.cache_owners.pop(signature, None)
                self.visits.pop(signature, None)
            raise

    def serve(self, key, worker, draft, closure, state, needed):
        """Project already measured owned nodes without applying any native branch."""
        response = self.preserving_request(worker, 'data-measure', expected=worker['owner'], nodes=list(needed))
        for node in needed:
            items = [item for item in response['extents'] if item['node'] == node]
            if items:
                signature = self.signature(draft, closure, node, state)
                self.cache[signature] = copy.deepcopy(items)
                self.cache_owners.setdefault(signature, set()).add(key[:3])
                self.visits[signature] = copy.deepcopy(state)
        worker.update(nodes=response['nodes'], pid=response['pid'], owner=response['owner'],
                      lastLoad={k: response[k] for k in ('reused', 'updated', 'created')})

    def inspect(self, request, node, *, port=0, geometry=False, locations=None):
        """Inspect the same native objects used for extent calculations."""
        with self.lock:
            self.load({**request, 'nodes': [node]}, locations=locations)
            draft = Draft(request)
            closure = Closure(draft.selected)
            key = self.signature(draft, closure, node, Visit(draft, False).state)
            view = self.view_of(request, draft)
            worker = None
            for candidate in self.workers.values():
                record = self.resident(candidate, view, closure)
                if (record is not None and not record['steps'] and node not in record['excluded']
                        and record['signatures'].get(node) == key):
                    worker = candidate
                    break
            if worker is None:
                fail('UNKNOWN_NODE', 'No resident worker holds this node in this view', node)
            result = self.preserving_request(worker, 'data-inspect', node=node, port=port, geometry=geometry)
            return {**result, 'liveData': self.status()}

    def unload(self):
        with self.lock:
            workers, self.workers = self.workers, {}
            errors = []
            for worker in workers.values():
                try: worker['client'].close()
                except Exception as error: errors.append(error)
            if errors: raise errors[0]
        return self.status()

    def status(self):
        # Never wait behind a lengthy native read just to paint an indicator.
        if not self.lock.acquire(blocking=False): return {'enabled': True, 'loading': True, 'bytes': None}
        try:
            sessions = []
            for key, worker in list(self.workers.items()):
                process = getattr(worker['client'], 'process', None)
                if process is not None and process.poll() is not None:
                    worker['client'].close()
                    del self.workers[key]
                    continue
                sessions.append({'provider': worker['provider'], 'operation': key[2], 'nodes': worker['nodes'],
                                 'pid': worker.get('pid'), 'lastLoad': worker.get('lastLoad'), 'bytes': memory_bytes(worker.get('pid')),
                                 'view': worker.get('view'), 'transitions': worker.get('transitions', 0),
                                 **({'uncertain': True} if worker.get('uncertain') else {})})
            sizes = [item['bytes'] for item in sessions]
            return {'enabled': bool(sessions), 'loading': False, 'sessions': sessions,
                    'bytes': sum(sizes) if all(n is not None for n in sizes) else None,
                    'observations': len(self.cache)}
        finally: self.lock.release()

    def close(self):
        try: self.unload()
        finally:
            self.cache.clear()
            self.cache_owners.clear()
            self.visits.clear()
            self.views.clear()
            self.roots.clear()
            self.edges.clear()
            self.accepted.clear()
            self.ambiguous.clear()
            self.closed = True

    def __enter__(self): return self
    def __exit__(self, *exc): self.close()
