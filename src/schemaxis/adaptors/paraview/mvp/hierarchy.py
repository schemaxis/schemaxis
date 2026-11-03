# Copyright (C) 2026 David L F Gaden
"""Static, hierarchical native browsing. These paths are help addresses, not code."""
import json
from collections import Counter
import re
from pathlib import Path

from schemaxis.core.faults import SchemaxisError, Fault
from .slice_options import SLICE_COVERAGE, SLICE_OPTIONS

NATIVE = Path(__file__).parent / 'native'


def _segment(label):
    words = re.findall(r'[A-Za-z0-9_]+', label)
    if not words:
        return 'unnamed'
    return words[0][:1].lower() + words[0][1:] + ''.join(w[:1].upper() + w[1:] for w in words[1:])


def _node(name, *, aliases=(), **details):
    children = details.get('children', [])
    counts = Counter(child['name'].casefold() for child in children)
    for child in children:
        if counts[child['name'].casefold()] > 1:
            child['aliases'] = sorted(set([*child['aliases'], child['name']]))
            child['name'] = _segment(child.get('nativeName', child.get('nativeProxy', child['name'])))
    counts = Counter(child['name'].casefold() for child in children)
    for child in children:
        if counts[child['name'].casefold()] > 1:
            identity = child.get('nativeName', child.get('nativeProxy', child['name']))
            child['name'] += '__' + identity.encode('utf-8').hex()
    return {'name': name, 'aliases': sorted(set(aliases) - {name}), **details}


def _slice(snapshot):
    def proxy_node(key, ancestors=()):
        entry = snapshot['proxies'].get(key)
        if entry is None or key in ancestors:
            return _node(_segment(key.split('/')[-1]), coverage='not expanded', children=[])
        children = []
        for python_name, prop in entry['properties'].items():
            name = _segment(prop['label'])
            aliases = [python_name, prop['nativeName'], prop['label']]
            if key == snapshot['root']:
                aliases += [option for option, mapping in SLICE_OPTIONS.items()
                            if mapping['pythonName'] == python_name]
            choices = []
            for domain in prop['domains']:
                choices += [proxy_node(child, (*ancestors, key)) for child in domain.get('proxies', [])]
            children.append(_node(name, aliases=aliases, **prop,
                adaptor=SLICE_COVERAGE.get(python_name, {'status': 'inventoried'})
                        if key == snapshot['root'] else {'status': 'inventoried'},
                children=choices))
        return _node(_segment(entry['label']), aliases=[entry['name'], entry['label']],
                     documentation=entry['documentation'], nativeProxy=key, children=children)
    root = proxy_node(snapshot['root'])
    root['version'] = snapshot['version']
    return root


def roots():
    snapshot = json.loads((NATIVE / 'slice-5.13.3.json').read_text(encoding='utf-8'))
    index = json.loads((NATIVE / 'commands-5.13.3.json').read_text(encoding='utf-8'))
    groups = []
    for group, entries in index['groups'].items():
        proxies = []
        for native, entry in entries.items():
            properties = [_node(_segment(prop['label']), aliases=[key, prop['label']],
                               **prop, adaptor={'status': 'inventoried'}, children=[])
                          for key, prop in entry['properties'].items()]
            proxies.append(_node(_segment(native), aliases=[native, entry['label']],
                                 documentation=entry['documentation'], children=properties,
                                 nativeProxy=group + '/' + native, adaptor={'status': 'inventoried'}))
        groups.append(_node(group, children=proxies))
    functions = [_node(_segment(name), aliases=[name], **entry, children=[],
                       adaptor={'status': 'inventoried'}) for name, entry in index['functions'].items()]
    return [_slice(snapshot), _node('groups', children=groups, version=index['version'], coverage=index['coverage']),
            _node('functions', children=functions, version=index['version'], coverage=index['coverage'])]


def help_at(path='', *, recursive=False):
    node = _node('', children=roots())
    canonical = []
    version = None
    if path:
        for component in path.split('.'):
            exact = [child for child in node['children'] if component.casefold() == child['name'].casefold()]
            matches = exact or [child for child in node['children']
                       if component.casefold() in {item.casefold() for item in [child['name'], *child['aliases']]}]
            if len(matches) != 1:
                raise SchemaxisError(Fault(
                    'AMBIGUOUS_HELP_PATH' if matches else 'UNKNOWN_HELP_PATH',
                    f'cannot resolve help component {component!r}', path, 'discovery',
                    observed={'available': sorted(child['name'] for child in node['children'])},
                    recovery='list the parent path and use a listed name',
                ))
            node = matches[0]
            canonical.append(node['name'])
            version = node.get('version', version)
    result = {key: value for key, value in node.items() if key != 'children'}
    def listing(parent, prefix, depth=0):
        for child in sorted(parent['children'], key=lambda item: item['name']):
            address = [*prefix, child['name']]
            row = {'path': '.'.join(address), 'label': child.get('label', child['name']),
                   'status': child.get('adaptor', {}).get('status', 'browse')}
            if recursive:
                row['depth'] = depth
            yield row
            if recursive:
                yield from listing(child, address, depth + 1)

    result.update(path='.'.join(canonical), version=version,
                  children=list(listing(node, canonical)))
    result['upstreamNotice'] = 'native/ParaView-Copyright.txt'
    return result
