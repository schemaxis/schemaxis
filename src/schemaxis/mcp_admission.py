"""Pure, digest-pinned admission before any planner can open authored paths."""
from dataclasses import dataclass
import hashlib
import json
import re
from pathlib import Path
import math
from .observations import fail

WORKFLOW_MAX_NODES = 32768
WORKFLOW_MAX_BYTES = 1024 * 1024
WORKFLOW_MAX_DEPTH = 64


def materialise_workflow(document):
    """Pure reviewed subset: scalar metadata references, no native/artifact hooks."""
    if (type(document) is not dict or any(type(key) is not str for key in document)
            or type(document.get('version')) is not str or document['version'] != 'schemaxis.workflow/1'
            or set(document) - {'version', 'operations', 'dimensions', 'definitions', 'settings'}
            or type(document.get('operations')) is not list or not 1 <= len(document['operations']) <= 32):
        fail('MCP_POLICY_DENIED', 'only bounded file-free workflows without execution overrides are admitted')
    from .observations import at_pointer
    nodes, remaining = 0, WORKFLOW_MAX_BYTES
    def charge(size):
        nonlocal remaining
        if size > remaining:
            fail('MCP_POLICY_DENIED', 'workflow materialisation exceeds its encoded byte budget')
        remaining -= size
    def token(value):
        if type(value) is str and len(value) > remaining:
            fail('MCP_POLICY_DENIED', 'workflow materialisation exceeds its encoded byte budget')
        try:
            size = len(json.dumps(value, ensure_ascii=False, allow_nan=False,
                                  separators=(',', ':')).encode('utf-8'))
        except (TypeError, ValueError, UnicodeError):
            fail('MCP_POLICY_DENIED', 'workflow metadata must contain finite JSON values')
        charge(size)
    def resolve(value, active=(), depth=0):
        nonlocal nodes
        nodes += 1
        if nodes > WORKFLOW_MAX_NODES or depth > WORKFLOW_MAX_DEPTH:
            fail('MCP_POLICY_DENIED', 'workflow materialisation exceeds its node or output depth budget')
        if type(value) is list:
            if len(value) > WORKFLOW_MAX_NODES-nodes:
                fail('MCP_POLICY_DENIED', 'workflow materialisation exceeds its node budget')
            charge(2+max(0,len(value)-1))
            return [resolve(child, active, depth+1) for child in value]
        if type(value) is not dict:
            if type(value) not in (str, int, float, bool, type(None)):
                fail('MCP_POLICY_DENIED', 'workflow metadata must contain only JSON values')
            token(value)
            return value
        if any(type(key) is not str for key in value):
            fail('MCP_POLICY_DENIED', 'workflow metadata keys must be strings')
        markers = [key for key in value if key.startswith('$')]
        if markers:
            if (set(value) != {'$document', 'scope'} or type(value['scope']) is not str
                    or value['scope'] != 'workflow'):
                fail('MCP_POLICY_DENIED', 'only workflow metadata references are admitted before planning')
            pointer = value['$document']
            if (len(active) >= 64 or type(pointer) is not str or not pointer.startswith(('/dimensions/', '/definitions/', '/settings/'))
                    or pointer in active):
                fail('MCP_POLICY_DENIED', 'invalid or cyclic workflow metadata reference')
            # Charge reference syntax as work as well as every expanded target.
            # Sharing/memoising a target cannot evade its eventual JSON size.
            charge(3)
            for key, child in value.items():
                token(key); charge(1); token(child)
            return resolve(at_pointer(document, pointer), (*active, pointer), depth)
        if len(value) > WORKFLOW_MAX_NODES-nodes:
            fail('MCP_POLICY_DENIED', 'workflow materialisation exceeds its node budget')
        charge(2+max(0,len(value)-1))
        result = {}
        for key, child in value.items():
            token(key); charge(1)
            result[key] = resolve(child, active, depth+1)
        return result
    result = resolve(document)
    seen = set()
    for operation in result['operations']:
        if (not isinstance(operation, dict) or set(operation) != {'id', 'document'}
                or not isinstance(operation['id'], str) or not re.fullmatch('[A-Za-z][A-Za-z0-9_-]{0,63}', operation['id'])
                or operation['id'] in seen):
            fail('MCP_POLICY_DENIED', 'workflow operations need distinct bounded IDs and documents')
        seen.add(operation['id'])
    return result


@dataclass(frozen=True)
class InputAdmission:
    routes: tuple
    contract_digests: tuple


@dataclass(frozen=True)
class InputSlot:
    pointer: str
    suffixes: tuple
    max_bytes: int


def _validate(value, schema, pointer='$'):
    """The deliberately small reviewed-schema vocabulary; unknown keywords refuse."""
    known = {'$schema', 'type', 'properties', 'required', 'additionalProperties',
             'const', 'enum', 'items', 'minItems', 'maxItems', 'minLength', 'maxLength', 'default',
             'minimum', 'maximum', 'exclusiveMinimum', 'exclusiveMaximum', 'minProperties', 'maxProperties'}
    if set(schema) - known:
        fail('MCP_POLICY_DENIED', 'admission schema uses an unqualified keyword')
    kind = schema.get('type')
    types = {'object': dict, 'array': list, 'string': str, 'integer': int, 'boolean': bool}
    valid_type = (type(value) in (int, float) if kind == 'number'
                  else kind in types and type(value) is types[kind])
    if kind is not None and not valid_type:
        fail('MCP_POLICY_DENIED', 'input does not match the reviewed declared contract', pointer)
    if 'const' in schema and (type(value) is not type(schema['const']) or value != schema['const']):
        fail('MCP_POLICY_DENIED', 'input differs from reviewed route identity', pointer)
    if 'enum' in schema and not any(type(value) is type(item) and value == item for item in schema['enum']):
        fail('MCP_POLICY_DENIED', 'input differs from the reviewed enumeration', pointer)
    if kind in ('integer', 'number'):
        if type(value) is float and not math.isfinite(value):
            fail('MCP_POLICY_DENIED', 'numeric input must be finite', pointer)
        for keyword, accepted in (('minimum', lambda x: value >= x), ('maximum', lambda x: value <= x),
                                  ('exclusiveMinimum', lambda x: value > x), ('exclusiveMaximum', lambda x: value < x)):
            if keyword in schema and not accepted(schema[keyword]):
                fail('MCP_POLICY_DENIED', 'numeric input exceeds the reviewed bound', pointer)
    if kind == 'object':
        if not schema.get('minProperties', 0) <= len(value) <= schema.get('maxProperties', float('inf')):
            fail('MCP_POLICY_DENIED', 'object exceeds the reviewed bound', pointer)
        fields = schema.get('properties', {})
        if set(schema.get('required', [])) - set(value) or set(value) - set(fields):
            fail('MCP_POLICY_DENIED', 'unknown or missing fields in reviewed input', pointer)
        if schema.get('additionalProperties') is not False:
            fail('MCP_POLICY_DENIED', 'reviewed input must have closed properties', pointer)
        for key, child in value.items():
            _validate(child, fields[key], pointer + '/' + key)
    elif kind in ('array', 'string'):
        minimum, maximum = ('minItems', 'maxItems') if kind == 'array' else ('minLength', 'maxLength')
        if not schema.get(minimum, 0) <= len(value) <= schema.get(maximum, float('inf')):
            fail('MCP_POLICY_DENIED', 'input exceeds the reviewed contract bound', pointer)
        if kind == 'array':
            for index, child in enumerate(value):
                _validate(child, schema['items'], pointer + '/' + str(index))


class FileAdmission:
    def __init__(self, policies=None):
        self.root = Path(__file__).parent
        self.policies = (json.loads((self.root/'mcp_admission.json').read_text())
                         if policies is None else policies)

    @staticmethod
    def _matches(document, pattern):
        """Expand declared pointer patterns, never recursive field-name guesses."""
        def walk(value, parts, pointer):
            if not parts:
                yield pointer, value
                return
            token, *rest = parts
            if token == '*':
                if type(value) is list:
                    for index, child in enumerate(value):
                        yield from walk(child, rest, pointer+'/'+str(index))
                elif type(value) is dict:
                    for key, child in value.items():
                        yield from walk(child, rest, pointer+'/'+key.replace('~', '~0').replace('/', '~1'))
            elif type(value) is dict and token in value:
                yield from walk(value[token], rest, pointer+'/'+token.replace('~', '~0').replace('/', '~1'))
            elif type(value) is list and re.fullmatch(r'0|[1-9][0-9]*', token) and int(token) < len(value):
                yield from walk(value[int(token)], rest, pointer+'/'+token)
        if type(pattern) is not str or not pattern.startswith('/'):
            fail('MCP_POLICY_DENIED', 'invalid installed file-slot pattern')
        return tuple(walk(document, [p.replace('~1', '/').replace('~0', '~') for p in pattern[1:].split('/')], ''))

    def _slots(self, document, policy):
        if policy.get('catalogueGenerated') is not True:
            return policy.get('inputSlots', {})
        for pattern in policy.get('forbiddenPointers', ()):
            if self._matches(document, pattern):
                fail('MCP_POLICY_DENIED', 'authored variant has no closed file-access contract', pattern)
        allowed = set(policy['operations'])
        for selector in policy['operationSelectors']:
            for pointer, value in self._matches(document, selector):
                if type(value) is not str or value not in allowed:
                    fail('MCP_POLICY_DENIED', 'operation has no qualified file-access contract', pointer)
                contexts = policy.get('operationContexts', {}).get(value)
                if contexts is not None and selector not in contexts:
                    fail('MCP_POLICY_DENIED', 'operation is unqualified in this authored context', pointer)
        slots = {}
        for declaration in policy['fileSlots']:
            for pointer, value in self._matches(document, declaration['pointer']):
                applicable = True
                source, actual = declaration['pointer'].split('/'), pointer.split('/')
                for selector, expected in declaration.get('when', {}).items():
                    # Conditions inherit this candidate's wildcard coordinates;
                    # another node's discriminator cannot authorise this slot.
                    condition = selector.split('/')
                    for index, token in enumerate(condition):
                        if token == '*':
                            if (index >= len(source) or index >= len(actual) or source[index] != '*'
                                    or selector.split('/')[:index] != source[:index]):
                                fail('MCP_POLICY_DENIED', 'input-slot condition has an unbound wildcard')
                            condition[index] = actual[index]
                    matches = self._matches(document, '/'.join(condition))
                    if (len(matches) != 1 or type(matches[0][1]) is not type(expected)
                            or matches[0][1] != expected):
                        applicable = False
                        break
                if not applicable:
                    continue
                if declaration.get('stringOnly') and type(value) is not str:
                    continue
                if pointer in slots:
                    fail('MCP_POLICY_DENIED', 'installed file-slot contracts overlap', pointer)
                slots[pointer] = declaration
        if len(slots) > 256:
            fail('MCP_POLICY_DENIED', 'input slot count exceeds the closure bound')
        return slots

    def _inputs(self, document, policy, context, *, bound):
        """Only trusted immutable captures in exact reviewed slots; no input I/O.

        CapturePolicy owns filesystem identity, leases and task ownership. This
        layer checks the complete structural closure before any binding/planner
        hook, and repeats the same check on stored bound documents. A suffix is
        a declared slot constraint, never a claim about the file's actual bytes.
        """
        if context is None:
            fail('MCP_POLICY_DENIED', 'staged input admission requires trusted InputBindings')
        from .execution_inputs import InputBindings, validate_bindings
        if type(context) is not InputBindings:
            fail('MCP_POLICY_DENIED', 'staged input admission requires trusted InputBindings')
        try:
            validate_bindings(context)
        except Exception as error:
            fail('MCP_POLICY_DENIED', 'invalid trusted input binding structure', reason=type(error).__name__)
        captures = {item.identity: item for item in context.captures}
        supplied = dict(context.slots)
        declared = self._slots(document, policy)
        if set(supplied) != set(declared) or set(captures) != set(supplied.values()):
            fail('MCP_POLICY_DENIED', 'staged input closure differs from the reviewed slots')
        from .observations import at_pointer
        for pointer, slot in declared.items():
            capture = captures[supplied[pointer]]
            leaf = at_pointer(document, pointer)
            if type(leaf) is not str or leaf != (str(capture.path) if bound else capture.identity):
                fail('MCP_POLICY_DENIED', 'input slot must match its exact trusted capture', pointer)
            if capture.path.suffix.lower() not in slot['suffixes'] or capture.bytes > slot['maxBytes']:
                fail('MCP_POLICY_DENIED', 'capture exceeds the reviewed slot type or size bound', pointer)

    def _policy(self, document):
        if not isinstance(document, dict):
            fail('MCP_POLICY_DENIED', 'only a reviewed declared document is admitted')
        version = document.get('version')
        policy = self.policies.get(version) if isinstance(version, str) else None
        if policy is None:
            fail('MCP_POLICY_DENIED', 'route has no qualified file-access contract', version=version)
        declared = {key: value for key, value in policy.items() if key != 'contractDigest'}
        fingerprint = 'sha256:' + hashlib.sha256(json.dumps(declared, sort_keys=True,
            separators=(',', ':'), ensure_ascii=False, allow_nan=False).encode()).hexdigest()
        if fingerprint != policy.get('contractDigest'):
            fail('MCP_POLICY_DENIED', 'admission declaration changed without a reviewed contract digest')
        from .adaptors import registry
        if policy['classification'] != 'workflow' and registry.routes().get(version) != (policy['provider'], policy['route']):
            fail('MCP_POLICY_DENIED', 'registered route changed; file admission requires review', route=version)
        for member, expected in policy['files'].items():
            path = self.root/member
            if path.is_symlink() or not path.resolve().is_relative_to(self.root.resolve()):
                fail('MCP_POLICY_DENIED', 'reviewed route source is not a confined regular file')
            try:
                actual = hashlib.sha256(path.read_bytes()).hexdigest()
            except OSError:
                fail('MCP_POLICY_DENIED', 'reviewed route source is unavailable')
            if actual != expected:
                fail('MCP_POLICY_DENIED', 'route contract changed; file admission requires review', route=version)
        if policy['classification'] != 'workflow':
            if policy.get('catalogueGenerated') is True:
                from .admission_schema import validate
                validate(document, policy['schema'])
                self._slots(document, policy)
            else:
                _validate(document, policy['schema'])
        return policy

    def input_slots(self, document):
        """Reviewed creation metadata for opaque uploads, before capture I/O.

        This does not authorise a path, validate bytes or replace final admission.
        The same qualified route/schema/source declarations are used by check().
        """
        policy = self._policy(document)
        if policy['classification'] == 'workflow':
            prepared = materialise_workflow(document)
            return tuple(InputSlot('/operations/'+str(index)+'/document'+slot.pointer,
                slot.suffixes, slot.max_bytes)
                for index, operation in enumerate(prepared['operations'])
                for slot in self.input_slots(operation['document']))
        if policy['classification'] != 'captured-inputs':
            self.check(document)
            return ()
        from .execution_inputs import validate_identity
        from .observations import at_pointer
        slots = []
        for pointer, slot in self._slots(document, policy).items():
            try:
                validate_identity(at_pointer(document, pointer))
            except Exception as error:
                fail('MCP_POLICY_DENIED', 'input slots require opaque capture identities', pointer,
                     reason=type(error).__name__)
            slots.append(InputSlot(pointer, tuple(slot['suffixes']), slot['maxBytes']))
        return tuple(slots)

    def check(self, document, context=None, *, bound=False):
        if type(bound) is not bool:
            fail('MCP_POLICY_DENIED', 'binding mode must be a trusted boolean')
        policy = self._policy(document)
        version = document['version']
        if policy['classification'] == 'workflow':
            prepared = materialise_workflow(document)
            if context is not None:
                # Bindings refer to literal authored positions. Expansion may
                # not manufacture a path slot through a metadata reference.
                for index, operation in enumerate(prepared['operations']):
                    if operation['document'] != document['operations'][index]['document']:
                        fail('MCP_POLICY_DENIED', 'captured workflow documents must be literal')
                from .execution_inputs import InputBindings, validate_bindings
                if type(context) is not InputBindings:
                    fail('MCP_POLICY_DENIED', 'workflow inputs require trusted InputBindings')
                validate_bindings(context)
                admissions, used = [], set()
                for index, operation in enumerate(prepared['operations']):
                    prefix = '/operations/'+str(index)+'/document'
                    slots = tuple((pointer[len(prefix):], identity) for pointer, identity in context.slots
                                  if pointer.startswith(prefix+'/'))
                    identities = {identity for _, identity in slots}
                    captures = tuple(c for c in context.captures if c.identity in identities)
                    used.update(prefix+p for p, _ in slots)
                    child = InputBindings(context.namespace, captures, slots) if slots else None
                    admissions.append(self.check(operation['document'], child, bound=bound and child is not None))
                if used != {p for p, _ in context.slots} or {i for _, i in context.slots} != {c.identity for c in context.captures}:
                    fail('MCP_POLICY_DENIED', 'workflow captures differ from the declared closure')
            else:
                if bound:
                    fail('MCP_POLICY_DENIED', 'bound workflow requires its captured-input context')
                admissions = [self.check(operation['document']) for operation in prepared['operations']]
            return InputAdmission((version, *(r for item in admissions for r in item.routes)),
                (policy['contractDigest'], *(d for item in admissions for d in item.contract_digests)))
        if policy['classification'] == 'captured-inputs':
            if self._slots(document, policy):
                self._inputs(document, policy, context, bound=bound)
            elif context is not None or bound:
                fail('MCP_POLICY_DENIED', 'document has no declared captured-input slots')
        elif policy['classification'] != 'file-free' or context is not None or bound:
            fail('MCP_POLICY_DENIED', 'file-free input does not accept a staged binding context')
        return InputAdmission((version,), (policy['contractDigest'],))

    def captured_content_policy(self, document, context):
        """Trusted executor header; authored arguments cannot supply this scope."""
        admitted = self.check(document, context, bound=True)
        return {'protocol': 'schemaxis.captured-content-policy/1',
                'contracts': list(admitted.contract_digests)}

    def validate_captured_content(self, document, context):
        """Worker-only byte guards AFTER immutable capture/mount verification.

        Pure check()/input_slots() never call this method. The contained worker
        owns its ordering: prove every exact read-only mount and digest first,
        call this method, and only then enter the planner/native parser.
        """
        from .adaptors import registry
        from .execution_inputs import InputBindings
        if type(context) is not InputBindings:
            fail('MCP_POLICY_DENIED', 'content guards require trusted immutable input bindings')
        self.check(document, context, bound=True)
        captures = {item.identity: item for item in context.captures}
        supplied = dict(context.slots)
        def visit(child, prefix=''):
            policy = self._policy(child)
            if policy['classification'] == 'workflow':
                prepared = materialise_workflow(child)
                for index, operation in enumerate(prepared['operations']):
                    visit(operation['document'], prefix+'/operations/'+str(index)+'/document')
                return
            for pointer, slot in self._slots(child, policy).items():
                mode = slot.get('contentPolicy')
                if mode == 'native':
                    # The reviewed adaptor owns its existing format parser and
                    # byte validation; this is explicit metadata, not a default.
                    continue
                hook = slot.get('contentHook')
                options = slot.get('contentOptions')
                package = registry.adaptor_package(policy['provider'])
                if (mode != 'hook' or type(hook) is not str or ':' not in hook
                        or not hook.split(':', 1)[0].startswith(package+'.')
                        or type(options) is not dict):
                    fail('MCP_POLICY_DENIED', 'captured slot lacks a confined content-validation contract', prefix+pointer)
                capture = captures[supplied[prefix+pointer]]
                registry.binding(hook)(capture.path, **options)
        visit(document)

    def coverage(self):
        """Installed generated profile scope, without importing planner hooks."""
        from .adaptors import registry
        routes, missing = [], []
        for provider, manifest in sorted(registry.ADAPTORS.items()):
            for version in manifest['routes']:
                policy = self.policies.get(version)
                if policy is None:
                    missing.append({'provider': provider, 'version': version,
                                    'reason': ('Installed plugin implementation-package pins are not qualified.'
                                        if manifest.get('source') != 'builtin' else
                                        'No generated closed file-access admission contract.')})
                    continue
                routes.append({'version': version, 'provider': provider,
                    'operations': list(policy.get('operations', ())),
                    'contractDigest': policy['contractDigest'],
                    'classification': policy['classification'],
                    'scope': policy.get('scope', ''),
                    'limitations': list(policy.get('limitations', ())),
                    'operationContexts': policy.get('operationContexts', {}),
                    'unqualifiedOperations': list(policy.get('unqualifiedOperations', ()))})
        return {'protocol': 'schemaxis.mcp-admission-coverage/1', 'routes': routes, 'missing': missing}

    def operations(self, document):
        """Pure validated selection identities for qualification/evidence tools.

        This reports authored selections, never certifies execution or replaces
        captured-input admission. No application-specific routing is repeated.
        """
        policy = self._policy(document)
        if policy['classification'] == 'workflow':
            prepared = materialise_workflow(document)
            return tuple(sorted({item for operation in prepared['operations']
                                 for item in self.operations(operation['document'])}))
        if policy.get('catalogueGenerated') is not True:
            fail('MCP_POLICY_DENIED', 'operation identity requires generated catalogue metadata')
        self.input_slots(document)
        return tuple(sorted({(policy['provider'], value)
            for selector in policy['operationSelectors']
            for _, value in self._matches(document, selector)}))
