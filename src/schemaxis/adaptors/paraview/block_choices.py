# Copyright (C) 2026 David L. F. Gaden
"""Deferred block selection for ExtractBlock; host validation and native resolution.

A selection is a list of entries. An entry is a native selector path, a
``{"pattern": ...}`` regular expression matched against block names, or an
``{"exclude": ...}`` regular expression that removes matching blocks. A list
with no selector or pattern starts from every block.
"""
import re
from schemaxis.errors import fail

PATTERN = {'type': 'object', 'properties': {'pattern': {'type': 'string', 'minLength': 1, 'maxLength': 256, 'required': True}}}
EXCLUDE = {'type': 'object', 'properties': {'exclude': {'type': 'string', 'minLength': 1, 'maxLength': 256, 'required': True}}}


def selection(path):
    entry = {'type': 'union', 'options': [{'type': 'string', 'minLength': 1}, PATTERN, EXCLUDE]}
    spec = {'type': 'array', 'items': entry, 'minItems': 1, 'required': True}
    return {'value': spec, 'path': [path], 'blockSelection': True, 'compiler': 'paraview-block-selection'}


def is_deferred(value):
    """True when the input's block names are needed to resolve ``value``."""
    return any(isinstance(entry, dict) for entry in value)


def compile_entry(entry, location):
    try: return re.compile(entry.get('pattern', entry.get('exclude')))
    except re.error as error: fail('INVALID_PATTERN', str(error), location)


def selector(entry):
    """A bare block name selects the node of that name at any depth."""
    return '//' + entry if isinstance(entry, str) and '/' not in entry else entry


def resolve_blocks(value, blocks, location):
    """``blocks`` are ``{'selector', 'label'}`` records for the selectable leaves."""
    value = [selector(entry) for entry in value]
    if not is_deferred(value): return value
    labels = {block['selector']: block['label'] for block in blocks}
    includes = any(not isinstance(entry, dict) or 'pattern' in entry for entry in value)
    result = [] if includes else [block['selector'] for block in blocks]
    for index, entry in enumerate(value):
        if not isinstance(entry, dict):
            if entry not in result: result.append(entry)
            continue
        pattern = compile_entry(entry, '%s[%d]' % (location, index))
        if 'exclude' in entry:
            result = [selector for selector in result
                      if not pattern.search(labels.get(selector, selector.rsplit('/', 1)[-1]))]
            continue
        matched = [block['selector'] for block in blocks if pattern.search(block['label'])]
        if not matched:
            fail('EMPTY_SELECTION', 'Block selection entry matched no block names', '%s[%d]' % (location, index),
                 pattern=entry['pattern'], available=[block['label'] for block in blocks])
        result.extend(selector for selector in matched if selector not in result)
    if not result:
        fail('EMPTY_SELECTION', 'Block selection left no blocks to extract', location,
             available=[block['label'] for block in blocks])
    return result


def leaves(assembly):
    """Selectable leaf blocks of a vtkDataAssembly, as ``{'selector', 'label'}``."""
    import xml.etree.ElementTree as ET
    from vtkmodules.vtkCommonCore import vtkIndent
    if assembly is None: return []
    root = ET.fromstring(assembly.SerializeToXML(vtkIndent()))
    result = []

    def visit(element):
        children = [child for child in element if child.tag != 'dataset']
        if not children and element is not root:
            result.append({'selector': assembly.GetNodePath(int(element.attrib['id'])),
                           'label': element.get('label', element.tag)})
        for child in children: visit(child)
    visit(root)
    return result


def validate_selection(value, location):
    for index, entry in enumerate(value):
        if isinstance(entry, dict): compile_entry(entry, '%s[%d]' % (location, index))
    return [selector(entry) for entry in value]


from schemaxis.bindings import register_compiler
register_compiler('paraview-block-selection', validate_selection)
