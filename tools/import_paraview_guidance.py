#!/usr/bin/env python3
"""Import public property documentation as reference guidance, never as reviewed prose.

Run capture_paraview_context.py --properties in pvpython first. This host-only
import matches native identity and Python property names, preserving all existing
explanations. XML names are not interchangeable with Python property names.
"""
import argparse
import json
import re
from pathlib import Path
from schemaxis.adaptors import registry
from schemaxis.studio_guidance import load, escape, validate_record

ROOT = Path(__file__).resolve().parents[1]


def project(context, guide, declarations):
    result = json.loads(json.dumps(guide))
    by_native = {value['native']: value.get('nativeIdentity') for value in declarations.values() if value.get('nativeIdentity')}
    changes = []
    records = result['routes']['schemaxis/1']['fields']
    for name, declaration in declarations.items():
        identity = declaration.get('nativeIdentity') or by_native.get(declaration['native'])
        native = context['operations'].get(identity, {})
        properties = {}
        for xml_name, prop in native.get('properties', {}).items():
            py_name = prop.get('pythonName')
            if py_name:
                properties.setdefault(py_name, []).append((xml_name, prop))
        for key, binding in declaration['options'].items():
            address = '/$defs/options-' + escape(name) + '/properties/' + escape(key)
            if address not in records or records[address].get('explanation'):
                continue
            path = binding.get('path', [])
            candidates = properties.get(path[0], []) if len(path) == 1 else []
            if len(candidates) != 1:
                continue
            xml_name, prop = candidates[0]
            text = (prop.get('description') or prop.get('long') or prop.get('short') or '').strip()
            if not text:
                continue
            record = {**records[address], 'status': 'reference', 'explanation': text,
                'sources': ['src/schemaxis/adaptors/paraview/native-context.json#/operations/'
                            + escape(identity) + '/properties/' + escape(xml_name)]}
            if prop.get('label'):
                record['label'] = prop['label']
            validate_record(record)
            records[address] = record
            changes.append(address)
    return result, changes


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('capture', type=Path)
    parser.add_argument('--apply', action='store_true')
    args = parser.parse_args()
    context = json.loads(args.capture.read_text())
    previous_path = ROOT / 'src/schemaxis/adaptors/paraview/native-context.json'
    previous = json.loads(previous_path.read_text())
    # A capture must describe the same public operation inventory; updates to
    # native versions go through the adaptor's separate qualification workflow.
    captured_version = re.search(r'\b\d+\.\d+\.\d+\b', context['source'])
    previous_version = re.search(r'\b\d+\.\d+\.\d+\b', previous['source'])
    if (set(context['operations']) != set(previous['operations']) or not captured_version or not previous_version
            or captured_version[0] != previous_version[0]):
        raise ValueError('Native version or operation inventory differs; review the capture before import')
    result, changes = project(context, load('paraview'), registry.declarations('paraview'))
    print(f'{len(changes)} pending fields have unambiguous public property documentation')
    if args.apply:
        for key, value in context['operations'].items():
            previous['operations'][key]['properties'] = value.get('properties', {})
        previous_path.write_text(json.dumps(previous, indent=2) + '\n')
        (previous_path.parent / 'guidance.json').write_text(json.dumps(result, ensure_ascii=False, indent=2) + '\n')


if __name__ == '__main__':
    main()
