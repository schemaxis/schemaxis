# Copyright (C) 2026 David L. F. Gaden.
"""Checked identity transitions for resident data, recomputed from authored input.

A transition is never accepted from a caller's description of the change. Each
use recomputes the accepted pure rename against an exact digest and binds the
result, policy and operation scope. ``replay`` applies the same checked rename
to a lowered resident plan, so a host and a native worker independently derive
the identical replacement plan. No native imports and no state live here.
"""
from .errors import fail
from .storage import digest
from .identity_rename import pointer, rename_identity

VERSION = 'schemaxis.identity-transition/1'
MAX_STEPS = 32
BINDING = ('version', 'operation', 'scope', 'pointer', 'old', 'new', 'provider', 'route',
           'inputDigest', 'outputDigest', 'policyDigest')


def checked_transition(request, identity_pointer, new_name, expected_input_digest):
    """Recompute one pure graph-identity rename inside the request's selected scope.

    Returns the candidate input and its binding. A no-op, another operation's
    identity or an identity that is not a graph node of that scope is refused.
    """
    from .spatial_actions import Draft
    from .spatial_load import Closure
    if not isinstance(request, dict) or not isinstance(request.get('input'), dict):
        fail('INVALID_REQUEST', 'An identity transition needs the whole authored input as an object', '$.input')
    from .identity_rename import bounded, parts, scopes, resolve_target
    from .identity_policy import local_identity
    bounded(request['input'])
    if not isinstance(expected_input_digest, str) or expected_input_digest != digest(request['input']):
        fail('STALE_IDENTITY_INPUT', 'The document changed; preview against its current digest')
    target = parts(identity_pointer, '$identityPointer')
    _, _, members = scopes(request['input'])
    base, _, _, _, _, _, descriptor, _ = resolve_target(request['input'], target, members)
    if (local_identity(descriptor) or descriptor['collection'] != ['nodes']
            or descriptor['nameProperty'] != 'id' or target[:-2] != base + ('nodes',)):
        fail('UNSUPPORTED_IDENTITY_TRANSITION', 'Only the exact declared graph node identity slot carries resident data',
             '$identityPointer')
    candidate = rename_identity(request['input'], identity_pointer, new_name, expected_input_digest)
    if not candidate['identityChanges']:
        fail('IDENTITY_TRANSITION_NOOP', 'The name is unchanged; there is no identity transition to adopt',
             '$newName')
    change = candidate['identityChanges'][0]
    draft = Draft(request)
    member = draft.selected
    if member.base != change['scope'] or (draft.workflow and member.operation is None):
        fail('IDENTITY_SCOPE_MISMATCH', 'Rename an identity of the operation this request selects',
             '$identityPointer', scope=change['scope'], operation=draft.operation)
    if change['old'] not in Closure(member).by_id:
        fail('UNSUPPORTED_IDENTITY_TRANSITION', 'Only graph nodes of the selected document carry resident data',
             '$identityPointer')
    return {'version': VERSION, 'operation': draft.operation, 'scope': change['scope'],
            'pointer': change['pointer'], 'old': change['old'], 'new': change['new'],
            'provider': change['provider'], 'route': change['route'],
            'inputDigest': candidate['inputDigest'], 'outputDigest': candidate['outputDigest'],
            'policyDigest': candidate['policyDigest'], 'input': candidate['input'],
            'changedPointers': candidate['changedPointers'], 'identityChanges': candidate['identityChanges']}


def binding(transition):
    """The exact fields a later step must match; never the candidate document itself."""
    return {key: transition[key] for key in BINDING}


def proof(before, identity_pointer, new_name, *, operation=None):
    """Durable, native-free forward evidence; inverse uses this same exact proof."""
    import copy
    checked = checked_transition({'input': before, 'operation': operation}, identity_pointer, new_name, digest(before))
    return {'before': copy.deepcopy(before), 'after': checked['input'], 'binding': binding(checked)}


def verify(proof, *, reverse=False):
    """Recompute a stored forward proof, then return its exact directed authored endpoints.

    Undo restores the original expression spelling. It does not pretend that a
    textual inverse rewrite has to reproduce that spelling.
    """
    if (not isinstance(proof, dict) or set(proof) != {'before', 'after', 'binding'}
            or not isinstance(proof['binding'], dict) or set(proof['binding']) != set(BINDING)
            or type(reverse) is not bool):
        fail('INVALID_IDENTITY_TRANSITION', 'Use exact checked forward identity evidence')
    bound = proof['binding']
    checked = checked_transition({'input': proof['before'], 'operation': bound['operation']},
                                 bound['pointer'], bound['new'], bound['inputDigest'])
    if binding(checked) != bound or checked['input'] != proof['after']:
        fail('STALE_IDENTITY_TRANSITION', 'The exact identity proof no longer matches its policy and documents')
    return ((proof['after'], proof['before'], [[bound['new'], bound['old']]]) if reverse else
            (proof['before'], proof['after'], [[bound['old'], bound['new']]]))


def stored(proof):
    """Check saved evidence's structure/endpoints without admitting its old policy.

    Recoverable authored history is independent of current adaptor policy.
    Callers must still use verify before granting any identity continuity.
    """
    import re
    from .observations import at_pointer
    from .identity_rename import bounded
    if (not isinstance(proof, dict) or set(proof) != {'before', 'after', 'binding'}
            or not all(isinstance(proof[k], dict) for k in ('before', 'after', 'binding'))
            or set(proof['binding']) != set(BINDING)):
        fail('INVALID_IDENTITY_TRANSITION', 'Invalid saved identity evidence')
    for value in proof.values():
        bounded(value)
    b = proof['binding']
    if (b['version'] != VERSION or b['operation'] is not None and not isinstance(b['operation'], str)
            or any(not isinstance(b[k], str) for k in BINDING if k != 'operation')
            or any(not re.fullmatch('[0-9a-f]{64}', b[k]) for k in ('inputDigest', 'outputDigest', 'policyDigest'))
            or not b['old'] or not b['new'] or b['old'] == b['new']
            or digest(proof['before']) != b['inputDigest'] or digest(proof['after']) != b['outputDigest']
            or at_pointer(proof['before'], b['pointer']) != b['old']
            or at_pointer(proof['after'], b['pointer']) != b['new']):
        fail('INVALID_IDENTITY_TRANSITION', 'Saved identity evidence has inconsistent endpoints')
    return proof['after']


def current_policy_digest(proof):
    """Read the actual selected scope's admitted authority for recovery only.

    No continuity is granted here. Structural/endpoints checks must precede
    this lookup, and unchanged authority still requires full verification.
    """
    from .adaptors import registry
    from .identity_policy import for_route
    from .identity_rename import scopes, parts
    from .core.faults import SchemaxisError
    bound = proof['binding']
    target = parts(bound['pointer'], '$identityPointer')
    _, _, members = scopes(proof['before'])
    selected = [m for m in members if target[:len(m[0])] == m[0]]
    if not selected:
        fail('INVALID_IDENTITY_TRANSITION', 'Saved identity scope is absent')
    base, document, operation = max(selected, key=lambda m: len(m[0]))
    if pointer(base) != bound['scope'] or operation != bound['operation']:
        fail('INVALID_IDENTITY_TRANSITION', 'Saved identity scope does not match its pointer')
    try:
        provider, route = registry.resolve(document)
    except SchemaxisError as error:
        if error.fault.code == 'UNSUPPORTED_VERSION':
            return None
        raise
    policy = for_route(provider, route)
    return None if policy is None else digest(policy)


def append_verified(chain, directed):
    """Verify and compose ordered evidence, cancelling only exact inverse pairs."""
    result = []
    current = None
    for item in [*chain, directed]:
        if not isinstance(item, dict) or set(item) != {'proof', 'reverse'}:
            fail('INVALID_IDENTITY_TRANSITION', 'Use directed original forward evidence')
        before, after, _ = verify(item['proof'], reverse=item['reverse'])
        if current is not None and current != before:
            fail('STALE_IDENTITY_TRANSITION', 'Identity evidence is not an ordered exact history path')
        current = after
        if result and result[-1]['proof'] == item['proof'] and result[-1]['reverse'] != item['reverse']:
            result.pop()
        else:
            result.append(item)
    if len(result) > MAX_STEPS:
        fail('IDENTITY_LIMIT', 'At most 32 pending identity steps; Preview to align them before further Undo, Redo or rename.')
    return result


def steps_of(value, location='$.steps'):
    """Validated ordered (old, new) identity steps."""
    if not isinstance(value, (list, tuple)) or not value or len(value) > MAX_STEPS:
        fail('INVALID_IDENTITY_TRANSITION', 'Use 1-32 ordered identity steps', location)
    result = []
    for index, step in enumerate(value):
        if (not isinstance(step, (list, tuple)) or len(step) != 2 or not all(isinstance(s, str) and s for s in step)
                or step[0] == step[1]):
            fail('INVALID_IDENTITY_TRANSITION', 'Each step names a different old and new identity',
                 location + '/' + str(index))
        result.append((step[0], step[1]))
    return result


def replay(document, steps):
    """Apply exact single-identity renames, in order, to a lowered graph plan.

    Each step must name exactly one declared graph identity of the plan. The
    accepted checked rename rewrites its consumers; unsupported or colliding
    references refuse before any caller mutation.
    """
    from .adaptors import registry
    from .identity_policy import for_route, local_identity
    current = document
    for index, (old, new) in enumerate(steps_of(steps)):
        provider, route = registry.resolve(current)
        policy = for_route(provider, route) if isinstance(route, dict) else None
        if policy is None:
            fail('UNSUPPORTED_IDENTITY_TRANSITION', 'This resident plan route has no audited identity policy',
                 '$.steps/' + str(index))
        found = []
        for identity in policy['identities']:
            if local_identity(identity) or identity['collection'] != ['nodes'] or identity['nameProperty'] != 'id':
                continue
            members = current
            for part in identity['collection']:
                members = members.get(part) if isinstance(members, dict) else None
            for position, member in enumerate(members if isinstance(members, list) else []):
                if isinstance(member, dict) and member.get(identity['nameProperty']) == old:
                    found.append(identity['collection'] + [str(position), identity['nameProperty']])
        if len(found) != 1:
            fail('IDENTITY_TRANSITION_MISMATCH', 'The resident plan has no single identity with this name',
                 '$.steps/' + str(index), identity=old)
        current = rename_identity(current, pointer(found[0]), new, digest(current))['input']
    return current
