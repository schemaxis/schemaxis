"""The existing Schemaxis fault envelope at schemaxis boundaries."""
from schemaxis.core.faults import SchemaxisError, Fault


def fail(code, message, location='$', **observed):
    raise SchemaxisError(Fault(code, message, location, 'pipeline', observed=observed))


def keys(value, allowed, location):
    if not isinstance(value, dict):
        fail('INVALID_DOCUMENT', 'expected an object', location)
    extra = set(value) - set(allowed)
    if extra:
        fail('UNKNOWN_ARGUMENT', 'unsupported keys', location, keys=sorted(extra))
