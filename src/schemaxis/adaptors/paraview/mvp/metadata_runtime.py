# Copyright (C) 2026 David L F Gaden
"""Native metadata capture, submitted only by the explicit inspect-native command.

No filter is executed. Definitions and prototype properties are inspected on the
client. Unknown domain semantics and recursion limits are reported, not guessed.
"""
import json
from pathlib import Path


def capture_native_metadata(group, name, destination, max_depth=2):
    from paraview import servermanager
    from paraview.simple import GetParaViewSourceVersion

    manager = servermanager.ProxyManager()
    definitions = manager.GetProxyDefinitionManager()
    snapshots = {}
    gaps = []
    attribute_names = (
        'name', 'label', 'default_values', 'number_of_elements', 'repeat_command',
        'information_only', 'panel_visibility', 'panel_widget', 'animateable',
        'min', 'max', 'text', 'value', 'group', 'proxygroup', 'proxyname',
        'attribute_type', 'composite_data_supported', 'optional', 'type',
        'function', 'mode', 'property', 'index', 'port_index',
    )

    def tree(element):
        if element is None:
            return None
        return {'tag': element.GetName(),
                'attributes': {key: element.GetAttribute(key) for key in attribute_names
                               if element.GetAttribute(key) is not None},
                'text': element.GetCharacterData(),
                'children': [tree(element.GetNestedElement(i))
                             for i in range(element.GetNumberOfNestedElements())]}

    def documentation(value):
        if value is None:
            return {'shortHelp': None, 'longHelp': None, 'description': None}
        return {'shortHelp': value.GetShortHelp(), 'longHelp': value.GetLongHelp(),
                'description': value.GetDescription()}

    def capture(group, name, depth):
        key = group + '/' + name
        if key in snapshots:
            return key
        if depth > max_depth:
            gaps.append({'proxy': key, 'reason': 'nested proxy depth limit'})
            return key
        proxy = manager.GetPrototypeProxy(group, name)
        if proxy is None:
            gaps.append({'proxy': key, 'reason': 'prototype unavailable'})
            return key
        proxy = servermanager.Proxy(proxy=proxy, no_update=True)
        definition = definitions.GetCollapsedProxyDefinition(group, name, None, True)
        entry = {'group': group, 'name': name, 'label': proxy.GetXMLLabel(),
                 'documentation': documentation(proxy.GetDocumentation()), 'properties': {}}
        snapshots[key] = entry
        for python_name in sorted(proxy.ListProperties()):
            prop = proxy.GetProperty(python_name)
            native = prop.SMProperty
            record = {'pythonName': python_name, 'nativeName': native.GetXMLName(),
                      'label': native.GetXMLLabel(), 'propertyClass': native.GetClassName(),
                      'informationOnly': bool(native.GetInformationOnly()),
                      'documentation': documentation(native.GetDocumentation()), 'domains': []}
            for i in range(definition.GetNumberOfNestedElements()):
                element = definition.GetNestedElement(i)
                if element.GetAttribute('name') == native.GetXMLName():
                    record['definition'] = tree(element)
                    break
            iterator = native.NewDomainIterator()
            iterator.Begin()
            while not iterator.IsAtEnd():
                domain = iterator.GetDomain()
                domain_info = {'name': iterator.GetKey(), 'class': domain.GetClassName()}
                if domain.IsA('vtkSMProxyListDomain'):
                    choices = []
                    for i in range(domain.GetNumberOfProxyTypes()):
                        child_group, child_name = domain.GetProxyGroup(i), domain.GetProxyName(i)
                        choices.append(capture(child_group, child_name, depth + 1))
                    domain_info['proxies'] = choices
                    domain_info['pythonChoices'] = list(prop.Available)
                elif domain.IsA('vtkSMEnumerationDomain'):
                    domain_info['entries'] = [
                        {'label': domain.GetEntryText(i), 'value': domain.GetEntryValue(i)}
                        for i in range(domain.GetNumberOfEntries())]
                elif not domain.IsA('vtkSMBooleanDomain'):
                    domain_info['semanticStatus'] = 'retained definition; requires domain-specific interpretation'
                record['domains'].append(domain_info)
                iterator.Next()
            entry['properties'][python_name] = record
        return key

    root = capture(group, name, 0)
    result = {'format': 'schemaxis.native-metadata/0.1', 'application': 'ParaView',
              'version': GetParaViewSourceVersion(), 'root': root,
              'source': 'installed server-manager definitions and prototype property API',
              'coverage': {'properties': 'ListProperties on captured prototypes',
                           'xmlAttributes': list(attribute_names),
                           'defaults': 'raw definition default_values; not data-dependent effective defaults',
                           'nestedProxyDepth': max_depth,
                           'limitations': ['XML attributes outside the listed set are not captured',
                                           'runtime/plugin-specific domains depend on the inspected installation',
                                           'GUI-only behaviour and property interactions require review/tests']},
              'proxies': snapshots, 'gaps': gaps}
    Path(destination).write_text(json.dumps(result, indent=2, allow_nan=False) + '\n', encoding='utf-8')
    return result


def capture_command_index(destination):
    """Inventory definitions and module functions without constructing filters."""
    import inspect
    from paraview import servermanager, simple
    manager = servermanager.ProxyManager().GetProxyDefinitionManager()
    groups = {}
    for item in servermanager.ProxyDefinitionIterator(manager.NewIterator()):
        group, name = item['group'], item['key']
        xml = manager.GetCollapsedProxyDefinition(group, name, None, False)
        if xml is None:
            continue
        properties = {}
        documentation = None
        for i in range(xml.GetNumberOfNestedElements()):
            child = xml.GetNestedElement(i)
            if child.GetName() == 'Documentation':
                documentation = child.GetCharacterData()
            if child.GetName().endswith('Property') and child.GetAttribute('name'):
                native = child.GetAttribute('name')
                label = child.GetAttribute('label') or native
                doc = None
                for j in range(child.GetNumberOfNestedElements()):
                    nested = child.GetNestedElement(j)
                    if nested.GetName() == 'Documentation':
                        doc = nested.GetCharacterData()
                properties[native] = {
                    'nativeName': native, 'label': label,
                    'documentation': {'description': doc},
                    'propertyClass': child.GetName(),
                    'declaredDefault': child.GetAttribute('default_values'),
                    'informationOnly': child.GetAttribute('information_only') == '1',
                }
        groups.setdefault(group, {})[name] = {
            'label': xml.GetAttribute('label') or name,
            'documentation': {'description': documentation}, 'properties': properties,
        }
    functions = {}
    # vars avoids evaluating descriptors on arbitrary instances; nothing is called.
    for name, value in sorted(vars(simple).items()):
        if name.startswith('_') or not inspect.isfunction(value):
            continue
        try:
            signature = str(inspect.signature(value))
        except (ValueError, TypeError):
            signature = None
        functions[name] = {'signature': signature, 'documentation': {'description': value.__doc__},
                           'module': value.__module__}
    result = {'format': 'schemaxis.native-index/0.1', 'version': simple.GetParaViewSourceVersion(),
              'groups': groups, 'functions': functions,
              'coverage': {'definitions': 'registered proxy definitions, collapsed direct properties',
                           'functions': 'public Python functions present in paraview.simple',
                           'limitations': ['not an execution capability catalogue',
                                           'nested domains require inspect-native for the selected proxy',
                                           'unloaded plugins and arbitrary instance methods are not inventoried']}}
    Path(destination).write_text(json.dumps(result, indent=2, sort_keys=True) + '\n', encoding='utf-8')
