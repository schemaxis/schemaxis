#!/usr/bin/env python3
# Copyright (C) 2026 David L F Gaden
"""Run with the matching pvpython to refresh public native selection documentation.

This captures metadata only, never executes a filter. Review changed wording and
supply curated selection/limitation text for new proxies whose native docs are
empty. Existing fallback text is retained explicitly as curated, not native help.
Derived public documentation uses the bundled ParaView-Copyright.txt licence.
"""
import argparse
import json
from importlib.resources import files
from pathlib import Path

CORRECTED = 'curated correction of installed native documentation'


def documentation(proxy):
    doc = proxy.GetDocumentation() if proxy else None
    return {'short': doc.GetShortHelp() if doc else None,
            'long': doc.GetLongHelp() if doc else None,
            'description': doc.GetDescription() if doc else None}


def corrected_record(identity, old, record, text):
    """Fields of a curated correction to keep when ParaView's documentation is captured again.

    ``old['captured']`` holds the upstream text each corrected field was written against
    ('selection' and/or 'description'). A corrected field keeps its Schemaxis text only while
    the newly captured upstream text is unchanged; otherwise the capture stops so the correction
    is reviewed. Fields that were never corrected come from the new capture.
    """
    captured = old['captured']
    fresh = {'selection': text, 'description': record['description']}
    for field, upstream in captured.items():
        if fresh[field] != upstream:
            raise ValueError('Upstream %s text changed; review the Schemaxis correction for %s' % (field, identity))
    result = {'basis': CORRECTED, 'captured': captured}
    for field in ('selection', 'description'):
        if field in captured:
            result[field] = old[field]
        elif field == 'selection':
            result[field] = text
    return result


def main():
    from paraview import servermanager, simple, make_name_valid
    from schemaxis.adaptors.paraview.filters import catalogue
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('output', type=Path)
    parser.add_argument('--properties', action='store_true',
                        help='Also capture public property documentation on prototype proxies; no filter execution')
    args = parser.parse_args()
    if args.output.exists():
        parser.error('choose a new output file, then review before replacing native-context.json')
    previous = json.loads(files('schemaxis.adaptors.paraview').joinpath('native-context.json').read_text())['operations']
    manager = servermanager.ProxyManager()
    records = {}
    for declaration in catalogue().values():
        identity = declaration.get('nativeIdentity')
        if not identity:
            continue
        proxy = manager.GetPrototypeProxy(*identity.split('/', 1))
        record = documentation(proxy)
        if args.properties and proxy:
            iterator = proxy.NewPropertyIterator()
            iterator.Begin()
            properties = {}
            while not iterator.IsAtEnd():
                prop = iterator.GetProperty()
                properties[iterator.GetKey()] = {**documentation(prop), 'label': prop.GetXMLLabel(),
                    'pythonName': make_name_valid(prop.GetXMLLabel())}
                iterator.Next()
            record['properties'] = properties
        text = record['short'] or record['long'] or record['description']
        old = previous.get(identity)
        if old and old['basis'] == CORRECTED:
            record.update(corrected_record(identity, old, record, text))
        elif text:
            record.update(selection=text, basis='installed native documentation')
        else:
            old = previous.get(identity)
            if not old or old['basis'] != 'curated scope and limitation':
                raise ValueError('Write reviewed selection/limitation guidance for ' + identity)
            record.update(selection=old['selection'], basis=old['basis'])
        records[identity] = record
    result = {'source': simple.GetParaViewSourceVersion() + ' public server-manager GetDocumentation API; see ParaView-Copyright.txt',
              'qualification': 'Documentation and binding coverage only; not native acceptance.', 'operations': records}
    args.output.write_text(json.dumps(result, indent=2)+'\n')


if __name__ == '__main__':
    main()
