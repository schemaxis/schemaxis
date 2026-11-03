# Copyright (C) 2026 David L F Gaden
"""Compile captured native metadata into bounded, host-safe declaration packages.

This developer intake language describes bindings, never arbitrary Python. Unknown
property classes stay visible as gaps. Generated bindings are not qualifications.
"""
import copy
import hashlib
import json
import re
from schemaxis.core.declarations import validate_specifications
from .selection_query import PYTHON_EVALUATED, QUERY, UNSAFE_COMMANDS

RESOURCE_GROUPS = {'lookup_tables': ('lookup-table','rendering'),
                   'piecewise_functions': ('piecewise-function','piecewise_functions'),
                   'textures': ('texture','rendering'),
                   'transfer_2d_functions': ('transfer-function-2d',None)}


# Explicit override tables. The native capture records neither FileListDomain `optional`,
# element_types nor the bundled VTK setter limits, so each rule below is keyed by the captured
# proxy identity and property name and cites its source (PV5.13.3 = bundled ParaView 5.13.3 tree).
#
# Secondary FileListDomain properties that are NOT required natively. The primary file property
# (vtkSMCoreUtilities::GetFileNameProperty, PV5.13.3:Remoting/ServerManager/vtkSMCoreUtilities.cxx:47-92)
# stays a required constructor option; so does every other FileListDomain property unless it is
# listed here. Optional ones become ordinary non-constructor options that must be non-empty when
# supplied. sources/NetCDFCAMReader ConnectivityFileName is deliberately absent:
# vtkNetCDFCAMReader::RequestUpdateExtent and RequestData return 0 without it
# (PV5.13.3:VTK/IO/NetCDF/vtkNetCDFCAMReader.cxx:476-480,542-546).
OPTIONAL_FILE_PROPERTIES = {
    # PV5.13.3:VTK/IO/Parallel/vtkMultiBlockPLOT3DReader.cxx:1558-1579 (no q file: nothing read) and
    # :1468,1964,2341 (empty Q or function file name skipped); XML readers_ioparallel.xml:445-490.
    ('sources/P3DReader', 'FunctionFileName'), ('sources/P3DReader', 'QFileName'),
    # PV5.13.3:VTK/IO/NetCDF/vtkSLACReader.cxx:648-652 (only MeshFileName required) and :665-686
    # (mode files read only when the list is non-empty). A bounded native probe (2026-10-12, ParaView
    # 5.13.3, serial) confirmed a mesh-only read with ModeFileName omitted.
    ('sources/SLACReader', 'ModeFileName'),
    # PV5.13.3:VTK/IO/XML/vtkRTXMLPolyDataReader.cxx:29-33,64-70,166-175 (Location is a data
    # directory; unset defaults to "./"); readers_ioxml.xml:2295-2330. FileName is the primary file.
    ('sources/RTXMLPolyDataReader', 'Location'),
    # PV5.13.3:VTKExtensions/IOExodus/Resources/readers_ioexodus.xml:704-718,738-748
    # (FileListDomain optional="1").
    ('sources/ExodusIIReader', 'FilePattern'), ('sources/ExodusIIReader', 'FilePrefix'),
    ('sources/ExodusIIReader', 'XMLFileName'),
    ('sources/ExodusRestartReader', 'FilePattern'), ('sources/ExodusRestartReader', 'FilePrefix'),
    ('sources/ExodusRestartReader', 'XMLFileName'),
}

# String-vector properties whose repeated commands are (name, non-negative integer written as
# text) pairs. PV5.13.3:Remoting/Application/Resources/readers_ionetcdf.xml:795-810 (element_types
# "2 0", number_of_elements_per_command 2); vtkSIStringVectorProperty.cxx:266-300 (INT element
# read with atoi, so non-numeric text silently becomes 0).
INDEX_PAIR_PROPERTIES = {('sources/MPASReader', 'ExtraDimensionIndices')}

# Limits imposed by the bundled VTK that are narrower than (or absent from) the XML domain.
# (identity, property) -> bounds applied to each scalar element.
VTK_LIMITS = {
    # PV5.13.3:VTK/Filters/AMR/vtkImageToAMR.h:41 vtkSetClampMacro(RefinementRatio, int, 2, VTK_INT_MAX);
    # the XML IntRangeDomain (filters_filtersamr.xml:52) allows 1, which would silently run as 2.
    ('filters/ImageDataToAMR', 'RefinementRatio'): {'minimum': 2},
    # PV5.13.3:VTK/Imaging/Sources/vtkImageMandelbrotSource.cxx:237-247,362-372 (axes outside 0..3
    # fail); the XML IntRangeDomain (sources_imagingsources.xml:38-42) is unbounded.
    ('sources/ImageMandelbrotSource', 'ProjectionAxes'): {'minimum': 0, 'maximum': 3},
}


def resource_input(identity, name, prop):
    if prop['class'] != 'vtkSMProxyProperty': return None
    groups = [item.get('attributes', {}).get('name') for item in walk(prop.get('definition', {}))
              if item.get('tag') == 'Group']
    # This native property has no group domain in the installed XML definition.
    if identity == 'filters/ColorByArray' and name == 'LookupTable': groups = ['lookup_tables']
    if identity == 'lookup_tables/PVLookupTable' and name == 'ScalarOpacityFunction': groups = ['piecewise_functions']
    if identity == 'writers/PPLYWriter' and name == 'LookupTable': groups = ['lookup_tables']
    return groups[0] if len(groups)==1 and groups[0] in RESOURCE_GROUPS else None


# Types no ParaView 5.13.3 reader, source or filter produces (only test-only VTK bridge classes).
UNPRODUCIBLE_INPUT_TYPES = {'vtkGenericDataSet'}

# The capture omits the XML attribute composite_data_required. These DataTypeDomains
# declare composite_data_required="1": the input must be a composite dataset.
# PV5.13.3:Remoting/Application/Resources/writers_ioxml.xml:781 (SerialHTGMultiBlock Input).
COMPOSITE_REQUIRED = {('writers/SerialHTGMultiBlock', 'Input')}


def output_ports(entry, writer):
    """Captured output-port count, or None when the capture could not know it.

    The capture counts ports on an unconnected prototype. A vtkSMSourceProxy only creates its
    output ports from the algorithm (CreateOutputPorts), so XML without <OutputPort> elements
    reports 0 on a prototype: "not captured", not "no ports"
    (PV5.13.3:Remoting/ServerManager/vtkSMSourceProxy.cxx:152-155,416-440). Writers are the one
    group whose 0 is genuine for all 44 declared writers, each of which calls SetNumberOfOutputPorts(0)
    (PV5.13.3:VTK/IO/Core/vtkWriter.cxx:19, VTK/IO/XML/vtkXMLWriterBase.cxx:37,
    VTK/IO/Image/vtkImageWriter.cxx:42, vtkJSONImageWriter.cxx:29, vtkXdmfWriter.cxx:187,
    vtkXdmf3Writer.cxx:161; vtkFileSeriesWriter.cxx:30 and vtkParallelSerialWriter.cxx:62 under
    VTKExtensions/IOCore).
    """
    ports = entry.get('outputPorts')
    return None if ports == 0 and not writer else ports


def command_property(prop):
    # A property is a command only when it has a command and pushes it as a call. A
    # zero-element IntVectorProperty sends no message, so it is not one
    # (PV5.13.3:Remoting/ServerManager/vtkSIVectorPropertyTemplate.txx:230-249).
    if not prop.get('definition', {}).get('attributes', {}).get('command'): return False
    return prop['class']=='vtkSMProperty'


def python_evaluated(prop):
    """Return (True, compiler or None) when ParaView evaluates the value as Python."""
    command = prop.get('definition', {}).get('attributes', {}).get('command')
    return (command in PYTHON_EVALUATED, PYTHON_EVALUATED.get(command))


def walk(tree):
    yield tree
    for child in tree.get('children', []):
        yield from walk(child)


def input_properties(entry):
    return {key: prop for key, prop in entry['properties'].items() if prop['class'] == 'vtkSMInputProperty'}


def domain_only_input(prop):
    """A named input with no command only feeds domains; it pushes nothing to the native object."""
    attrs = prop.get('definition', {}).get('attributes', {})
    return 'name' in attrs and not attrs.get('command')


def contract(prop, composite_required=False):
    tree = prop.get('definition', {})
    types = [x['attributes']['value'] for x in walk(tree)
             if x.get('tag') == 'DataType' and 'value' in x.get('attributes', {})]
    composite = next(({'0': False, '1': True}.get(x.get('attributes', {}).get('composite_data_supported'))
                      for x in walk(tree) if x.get('tag') == 'DataTypeDomain'), None)
    if composite_required: composite = 'required'
    return {'nativeTypes': types, 'composite': composite,
            'requirements': {},
            'traits': {'contiguity': 'unknown', 'indexing': 'unknown', 'iteration': 'unknown'},
            'compatibility': 'native-domain-checked',
            'cost': {'rating': 'unknown', 'basis': 'no benchmark', 'conversion': 'none inserted'}}


def compile_catalogue(snapshot):
    proxies = snapshot['proxies']
    def options(identity, ancestors=()):
        if identity in ancestors: return {}, {'$proxy': 'recursive proxy choice'}
        entry = proxies[identity]
        result, gaps = {}, {}
        for name, prop in entry['properties'].items():
            if prop['informationOnly']: continue
            if resource_input(identity, name, prop): continue
            if prop['class'] == 'vtkSMInputProperty' and domain_only_input(prop):
                if not ancestors and 'vtkSMProxyListDomain' not in {d['class'] for d in prop['domains']}:
                    gaps[name] = 'domain-only input (no native command)'
                continue
            domains = {d['class']: d for d in prop['domains']}
            if prop['class'] == 'vtkSMInputProperty' and 'vtkSMProxyListDomain' not in domains: continue
            binding = {'path': [name], 'nativeDomains': list(domains)}
            attrs = prop.get('definition', {}).get('attributes', {})
            if command_property(prop) and identity in snapshot['roots'] + snapshot.get('resources', []):
                continue
            default = prop.get('observedDefault')
            unsafe = UNSAFE_COMMANDS.get(attrs.get('command'))
            if unsafe:
                gaps[name] = unsafe; continue
            # A commandless vector pushes nothing to the native object; in a non-resource
            # proxy it only drives GUI widgets. (Resources such as lookup tables use
            # commandless properties at proxy level, so they are excluded.)
            if (entry['group'] not in RESOURCE_GROUPS and attrs and not attrs.get('command')
                    and prop['class'].endswith('VectorProperty')):
                gaps[name] = 'no native command (GUI-only property)'; continue
            evaluated, compiler = python_evaluated(prop)
            if evaluated:
                # Authored text never reaches a Python-evaluated property. A
                # closed grammar is compiled instead, or the property is a gap.
                if compiler is None:
                    gaps[name] = 'evaluated as Python by the native application'; continue
                binding.update(value=copy.deepcopy(QUERY), compiler=compiler)
                result[name] = binding
                continue
            if 'vtkSMProxyListDomain' in domains:
                choices, variants = {}, []
                for child in domains['vtkSMProxyListDomain'].get('choices', []):
                    if child in ancestors or child == identity: continue
                    child_options, child_gaps = options(child, (*ancestors, identity))
                    label = proxies[child].get('label', proxies[child]['name'])
                    choices[label] = {'identity': proxies[child].get('runtimeIdentity', child), 'options': child_options, 'gaps': child_gaps}
                    variants.append({'type': 'object', 'properties': {
                        'type': {'type': 'enum', 'values': [label], 'required': True},
                        'options': {'type': 'object', 'properties': {k:v['value'] for k,v in child_options.items()}, 'default': {}}}})
                if not variants:
                    gaps[name] = 'no finite proxy choices'; continue
                spec = {'type': 'union', 'options': variants} if len(variants) > 1 else variants[0]
                binding['proxyChoices'] = choices
            elif prop['class'] in ('vtkSMIntVectorProperty', 'vtkSMDoubleVectorProperty',
                                   'vtkSMIdTypeVectorProperty', 'vtkSMStringVectorProperty'):
                kind = {'vtkSMIntVectorProperty': 'integer', 'vtkSMIdTypeVectorProperty': 'integer',
                        'vtkSMDoubleVectorProperty': 'number', 'vtkSMStringVectorProperty': 'string'}[prop['class']]
                scalar = {'type': kind}
                if 'vtkSMBooleanDomain' in domains: scalar = {'type': 'boolean'}
                # vtkSMFieldDataDomain derives from vtkSMEnumerationDomain, so ParaView wraps the
                # property as an EnumerationProperty and reads back the entry text ("Point Data"),
                # not an integer (PV5.13.3:Wrapping/Python/paraview/servermanager.py:113-117,980-989).
                enum = (domains.get('vtkSMEnumerationDomain') or domains.get('vtkSMFieldDataDomain') or {}).get('entries')
                if enum: scalar = {'type': 'enum', 'values': list(dict.fromkeys(enum))}
                # Static scalar ranges are portable. Component-specific/data-dependent
                # restrictions are checked by the native domain before assignment.
                if scalar['type'] in ('integer', 'number'):
                    for child in prop.get('definition', {}).get('children', []):
                        if child['tag'] not in ('IntRangeDomain', 'DoubleRangeDomain'): continue
                        for native_key, key in [('min','minimum'), ('max','maximum')]:
                            if native_key in child['attributes'] and len(child['attributes'][native_key].split()) == 1:
                                scalar[key] = (int if kind == 'integer' else float)(child['attributes'][native_key])
                limits = VTK_LIMITS.get((identity, name))
                if limits and scalar['type'] == 'integer': scalar.update(limits)
                repeat = prop.get('repeatCommand', attrs.get('repeat_command') == '1')
                count = prop.get('numberOfElements', int(attrs.get('number_of_elements', '0')))
                if not count and not repeat:
                    basis = None
                    if kind=='string' and 'vtkSMArrayListDomain' in domains and any(
                            item.get('tag')=='ArraySelectionWidget' for item in walk(prop.get('definition',{}))):
                        basis = 'single array-selection widget'
                    if basis:
                        count = 1
                        binding['initialiseElements'] = 1
                        binding['cardinalityBasis'] = basis
                array = isinstance(default, list) or repeat or count > 1
                if default is None and not count and not repeat and not enum:
                    gaps[name] = ('zero-element property with no usable native command'
                                  if prop['class'] == 'vtkSMIntVectorProperty' and attrs.get('command')
                                  else 'property cardinality unavailable')
                    continue
                spec = {'type': 'array', 'items': scalar} if array else scalar
                tuple_size=prop.get('elementsPerCommand',int(attrs.get('number_of_elements_per_command','1')))
                # Pair lists with an ArrayListDomain (pvRenameArrays, pvYoungsMaterialInterface) are
                # tuples too; only the *SelectionDomain name/status lists stay flat. Planning rejects
                # incomplete tuples (bindings.validate_binding: length % tupleSize).
                if array and repeat and tuple_size>1 and not any('SelectionDomain' in domain for domain in domains):
                    binding['tupleSize']=tuple_size
                if (identity, name) in INDEX_PAIR_PROPERTIES:
                    binding['tupleSize']=2
                    binding['tupleElementTypes']=['string','index']
                if array and not repeat and count and 'vtkSMArrayListDomain' not in domains:
                    spec.update(minItems=count, maxItems=count)
                # Native array-selector wrappers expose association/name rather than
                # the five internal SM elements.
                if 'vtkSMArrayListDomain' in domains and count == 5:
                    spec = {'type': 'array', 'items': {'type':'string'}, 'minItems':2, 'maxItems':2}
                if 'vtkSMFileListDomain' in domains:
                    if (identity, name) not in OPTIONAL_FILE_PROPERTIES:
                        binding['constructor'] = True
                        spec['required'] = True
                    if spec['type'] == 'array':
                        spec['minItems'] = 1; spec['items']['minLength'] = 1
                    else: spec['minLength'] = 1
            else:
                gaps[name] = 'unsupported property class: ' + prop['class']; continue
            binding['value'] = spec
            result[name] = binding
        return result, gaps

    declarations, inventory = {}, {}
    for identity in snapshot['roots'] + snapshot.get('resources', []):
        entry = proxies[identity]
        record = {'identity': identity, 'status': 'unsupported', 'qualification': 'not-run'}
        inventory[identity] = record
        writer = entry['group'] == 'writers'
        resource = entry['group'] in RESOURCE_GROUPS
        if entry['group']=='transfer_2d_functions' and entry['name']!='TransferFunction2D':
            record['reason']='no declared factory for this transfer function'; continue
        if writer and entry['name'] == 'XMLPVAnimationWriter':
            record['reason'] = 'animation writer needs view/representation lifecycle'; continue
        if 'error' in entry:
            record['reason'] = entry['error']; continue
        if not entry.get('constructorAvailable') and not resource:
            record['reason'] = 'no public simple constructor'; continue
        # Effectful code is intentionally outside the authored-input language.
        if (any(token in (entry['name'] + (entry.get('implementationClass') or '')).lower()
                for token in ('python', 'programmable')) or
                any(key.lower().endswith('script') or key == 'PythonPath' for key in entry['properties']) or
                any(python_evaluated(prop) == (True, None) for prop in entry['properties'].values())):
            record['reason'] = 'requires arbitrary code execution'; continue
        inputs_all = input_properties(entry)
        # Narrow on purpose: every input property (proxy-list ones included) sits on a
        # non-zero port, so nothing can connect port 0. Proven required for the two
        # interpolator bases (vtkDataSetAlgorithm, no INPUT_IS_OPTIONAL); a test pins the hit set.
        if inputs_all and all(prop.get('definition', {}).get('attributes', {}).get('port_index', '0') != '0'
                              for prop in inputs_all.values()):
            record['reason'] = 'no input property connects required port 0'; continue
        required_types = [contract(prop)['nativeTypes'] for prop in inputs_all.values()
                          if not any(d['class'] == 'vtkSMProxyListDomain' for d in prop['domains'])
                          and prop.get('definition', {}).get('attributes', {}).get('optional') != '1']
        if any(types and set(types) <= UNPRODUCIBLE_INPUT_TYPES for types in required_types):
            record['reason'] = 'requires vtkGenericDataSet input, which no reader or source in the captured %s produces' % snapshot['version']; continue
        # Source proxies always carry an outputPorts record, even when it is 0.
        if not entry.get('implementationClass') and 'outputPorts' not in entry and not resource:
            record['reason'] = 'internal base proxy without a VTK class or output ports'; continue
        name = ('pvWrite' if writer else 'pvResource' if resource else 'pv') + entry['native']
        if not re.fullmatch('[A-Za-z][A-Za-z0-9_]*', name):
            record['reason'] = 'constructor identifier is not representable'; continue
        if name in declarations:
            record['reason'] = 'ambiguous public constructor'; continue
        props, gaps = options(identity)
        inputs = {}
        for key, prop in entry['properties'].items():
            group = resource_input(identity, key, prop)
            if group:
                inputs[key] = {'native':key, 'required':False, 'multiple':False,
                               'kind':RESOURCE_GROUPS[group][0],
                               'contract':{'compatibility':'native-proxy-group','nativeGroup':group,
                                           'cost':{'rating':'unknown','basis':'no benchmark'}}}
                continue
            if prop['class'] != 'vtkSMInputProperty' or any(d['class']=='vtkSMProxyListDomain' for d in prop['domains']): continue
            if domain_only_input(prop): continue
            attrs = prop.get('definition', {}).get('attributes', {})
            optional = attrs.get('optional') == '1' or any(
                item.get('tag') == 'Optional' for item in walk(prop.get('definition', {})))
            inputs[key] = {'native': key, 'required': not optional,
                           'multiple': attrs.get('multiple_input') == '1',
                           'contract': contract(prop, (identity, key) in COMPOSITE_REQUIRED)}
        validate_specifications({k:v['value'] for k,v in props.items()}, name)
        declaration = {'id': name, 'native': entry['native'], 'nativeIdentity': entry.get('runtimeIdentity', identity),
                       'inputs': inputs, 'options': props,
                       'coverage': {'origin': 'generated', 'qualification': 'not-run', 'gaps': gaps,
                                    'defaults': 'native defaults for omitted options',
                                    'output': 'native inspection required; explicit output-port selection available',
                                    'outputPorts': output_ports(entry, writer)},
                       'execution': {'mode': 'serial', 'performance': 'unknown'}}
        commands = {key: {'native': prop['nativeName'], 'command': prop['definition']['attributes']['command']}
                    for key, prop in entry['properties'].items()
                    if command_property(prop) and not prop['informationOnly']}
        if commands: declaration['commands'] = commands
        if resource:
            kind, module = RESOURCE_GROUPS[entry['group']]
            declaration.update(role='resource', kinds=[kind], factory={
                'module':module, 'class':entry['name'], 'group':entry['group']})
            if module is None: declaration['factory']['helper']='GetTransferFunction2D'
            declaration['coverage']['output'] = 'process-local typed native resource'
        if writer:
            from .writers import writer_contract, managed_property
            extensions = [e for hint in walk(entry.get('hints') or {}) if hint.get('tag') == 'WriterFactory'
                          for e in hint.get('attributes', {}).get('extensions', '').split()]
            declaration['role'] = 'writer'
            declaration['publication'] = writer_contract(entry['name'], extensions)
            for key in list(props):
                if managed_property(key):
                    del props[key]
            declaration['coverage']['output'] = 'explicit exports with semantic readback'
        if snapshot.get('dependencies'):
            declaration['nativeDependencies'] = snapshot['dependencies']
        declarations[name] = declaration
        record.update(status='declared', operation=name, propertyGaps=gaps)
    return {'format': 'schemaxis.paraview-catalogue/1', 'version': snapshot['version'],
            'source': snapshot['source'],
            'captureSHA256': hashlib.sha256(json.dumps(snapshot, sort_keys=True, separators=(',', ':')).encode()).hexdigest(),
            'declarations': declarations, 'inventory': inventory,
            'groups': {k:len(v) for k,v in snapshot['groups'].items()}}
