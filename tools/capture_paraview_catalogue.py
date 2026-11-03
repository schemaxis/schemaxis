# Copyright (C) 2026 David L F Gaden
"""Run with pvpython: capture installed public definitions without executing filters.

Usage: pvpython tools/capture_paraview_catalogue.py OUTPUT.json
Metadata is derived from ParaView's public server-manager API; see the bundled
ParaView-Copyright.txt. Native defaults are observations, not portable promises.
"""
import argparse
import hashlib
import json
from pathlib import Path
import sys
from paraview import servermanager as sm, simple
import paraview


def capture():
    manager = sm.ProxyManager()
    definitions = manager.GetProxyDefinitionManager()
    attributes = ('name', 'label', 'number_of_elements', 'repeat_command', 'optional',
                  'multiple_input', 'port_index', 'composite_data_supported', 'default_values',
                  'attribute_type', 'data_type', 'min', 'max', 'value', 'text', 'index',
                  'group', 'proxyname', 'proxygroup', 'property', 'function', 'mode', 'extensions', 'file_description', 'command',
                  'number_of_elements_per_command')
    def tree(element):
        return {'tag': element.GetName(), 'attributes': {
            k: element.GetAttribute(k) for k in attributes if element.GetAttribute(k) is not None},
            'children': [tree(element.GetNestedElement(i)) for i in range(element.GetNumberOfNestedElements())]}
    entries = {}
    def proxy(group, name, depth=0):
        identity = group + '/' + name
        if identity in entries: return identity
        entry = {'group': group, 'name': name, 'properties': {}}
        entries[identity] = entry
        try:
            native = manager.GetPrototypeProxy(group, name)
            if native is None: raise ValueError('prototype unavailable')
            # Wrapping a prototype can initialise its unconnected algorithm and
            # replace XML-declared ports with zero; capture the declaration first.
            if hasattr(native, 'GetNumberOfOutputPorts'):
                entry['outputPorts'] = native.GetNumberOfOutputPorts()
            wrapped = sm.Proxy(proxy=native, no_update=True)
            entry['label'] = wrapped.GetXMLLabel()
            entry['runtimeIdentity'] = wrapped.GetXMLGroup() + '/' + wrapped.GetXMLName()
            entry['native'] = paraview.make_name_valid(entry['label'])
            entry['constructorAvailable'] = bool(getattr(getattr(simple, entry['native'], None), '__paraview_create_object_tag', False))
            xml = definitions.GetCollapsedProxyDefinition(wrapped.GetXMLGroup(), wrapped.GetXMLName(), None, True)
            entry['implementationClass'] = xml.GetAttribute('class')
            entry['hints'] = tree(wrapped.GetHints()) if wrapped.GetHints() else None
            children = {xml.GetNestedElement(i).GetAttribute('name'): xml.GetNestedElement(i)
                        for i in range(xml.GetNumberOfNestedElements())}
            for key in sorted(wrapped.ListProperties()):
                prop = wrapped.GetProperty(key)
                n = prop.SMProperty
                record = {'nativeName': n.GetXMLName(), 'class': n.GetClassName(),
                          'informationOnly': bool(n.GetInformationOnly()), 'domains': []}
                entry['properties'][key] = record
                if hasattr(n, 'GetNumberOfElements'):
                    record['numberOfElements'] = n.GetNumberOfElements()
                    record['repeatCommand'] = bool(n.GetRepeatCommand())
                    if hasattr(n, 'GetNumberOfElementsPerCommand'):
                        record['elementsPerCommand'] = n.GetNumberOfElementsPerCommand()
                if n.GetXMLName() in children: record['definition'] = tree(children[n.GetXMLName()])
                try:
                    value = prop.GetData()
                    json.dumps(value, allow_nan=False)
                    record['observedDefault'] = value
                except (AttributeError, TypeError, ValueError): pass
                iterator = n.NewDomainIterator(); iterator.Begin()
                while not iterator.IsAtEnd():
                    domain = iterator.GetDomain()
                    info = {'class': domain.GetClassName()}
                    if domain.IsA('vtkSMEnumerationDomain'):
                        info['entries'] = [domain.GetEntryText(i) for i in range(domain.GetNumberOfEntries())]
                    if domain.IsA('vtkSMProxyListDomain'):
                        info['choices'] = []
                        if depth < 3:
                            for i in range(domain.GetNumberOfProxyTypes()):
                                g, nm = domain.GetProxyGroup(i), domain.GetProxyName(i)
                                child = proxy(g, nm, depth + 1)
                                info['choices'].append(child)
                        else: info['gap'] = 'nested depth limit'
                    record['domains'].append(info)
                    iterator.Next()
        except Exception as exc:
            entry['error'] = type(exc).__name__ + ': ' + str(exc)
        return identity
    roots = []
    groups = {}
    for item in sm.ProxyDefinitionIterator(definitions.NewIterator()):
        group, name = item['group'], item['key']
        groups.setdefault(group, []).append(name)
    for group in ('sources', 'filters', 'writers'):
        for name in sorted(groups.get(group, [])): roots.append(proxy(group, name))
    resources = [proxy(group, name) for group in ('lookup_tables', 'piecewise_functions', 'textures', 'transfer_2d_functions')
                 for name in sorted(groups.get(group, []))]
    return {'format': 'schemaxis.paraview-native/1', 'version': simple.GetParaViewSourceVersion(),
            'source': 'installed server-manager definitions and prototype property API',
            'scope': 'registered sources, filters and writers; no explicit plugin loading',
            'groups': {g: sorted(v) for g,v in sorted(groups.items())},
            'roots': roots, 'resources': resources, 'proxies': dict(sorted(entries.items()))}


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('output', type=Path)
    parser.add_argument('--xml-extension', type=Path, action='append', default=[])
    parser.add_argument('--plugin', type=Path, action='append', default=[])
    args = parser.parse_args()
    dependencies = []
    for path in args.xml_extension:
        xml = path.read_text()
        simple.LoadPlugin(str(path.resolve()), ns=vars(simple))
        dependencies.append({'kind':'xml', 'xml':xml, 'sha256':hashlib.sha256(xml.encode()).hexdigest()})
    for path in args.plugin:
        path = path.resolve()
        checksum = hashlib.sha256(path.read_bytes()).hexdigest()
        simple.LoadPlugin(str(path), ns=vars(simple))
        dependencies.append({'kind':'plugin', 'path':str(path), 'sha256':checksum})
    result = capture()
    result['dependencies'] = dependencies
    with args.output.open('w') as stream:
        json.dump(result, stream, indent=2, sort_keys=True, allow_nan=False)
        stream.write('\n')
