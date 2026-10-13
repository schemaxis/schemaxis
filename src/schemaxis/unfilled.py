"""Durable authoring markers are drafts, never executable runtime values."""
from .errors import fail


def find_unfilled(document):
    """Return every marker with its exact RFC 6901 pointer, in document order."""
    found = []
    pending = [(document, '', frozenset())]
    while pending:
        value, pointer, ancestors = pending.pop()
        if not isinstance(value, (dict, list)):
            continue
        if id(value) in ancestors or len(ancestors) > 64:
            fail('INVALID_DOCUMENT', 'JSON must be acyclic and no deeper than 64 levels', pointer or '$')
        ancestors = ancestors | {id(value)}
        if isinstance(value, dict):
            if '$fill' in value:
                field = value['$fill']
                found.append({'pointer': pointer, 'field': field,
                              'label': value.get('label', str(field)), 'type': value.get('type', 'json')})
            for key, child in reversed(list(value.items())):
                if not isinstance(key, str):
                    fail('INVALID_DOCUMENT', 'JSON object keys must be strings', pointer or '$')
                path = pointer + '/' + key.replace('~', '~0').replace('/', '~1')
                pending.append((child, path, ancestors))
        else:
            for index in range(len(value) - 1, -1, -1):
                pending.append((value[index], pointer + '/' + str(index), ancestors))
    return found


def reject_unfilled(document, *, allowed=()):
    """Reject markers except those exactly at already-validated parameter targets."""
    allowed = set(allowed)
    values = [item for item in find_unfilled(document) if item['pointer'] not in allowed]
    if values:
        fail('UNFILLED_VALUES', f"{len(values)} values still need to be filled", values[0]['pointer'] or '$',
             values=values, pointers=[item['pointer'] for item in values],
             recovery='Fill these values, or expose them as template parameters before exporting.')
