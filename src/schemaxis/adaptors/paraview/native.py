# Copyright (C) 2026 David L F Gaden
"""ParaView backend. Imported only inside the selected native interpreter."""
import hashlib
import math
import struct
from pathlib import Path
from schemaxis.bindings import native_value
from schemaxis.core.faults import Fault, SchemaxisError
from schemaxis.errors import fail
from schemaxis.pipeline import digest
from .reader_choices import is_deferred, resolve_selection
from . import block_choices
from .selection_query import guard_native_value


def assign(proxy, path, value):
    target = proxy
    for part in path[:-1]:
        target = getattr(target, part)
    if path[-1] not in target.ListProperties():
        fail('UNSUPPORTED_NATIVE_PROPERTY', 'property is unavailable in this runtime',
             '.'.join(path), available=target.ListProperties())
    guard(target, path[-1], value, '.'.join(path))
    setattr(target, path[-1], value)


def guard(proxy, name, value, location):
    # Every native assignment passes here, after runtime values are resolved.
    guard_native_value(proxy.GetProperty(name).SMProperty.GetCommand(), value, location)


def property_value(proxy, path):
    for part in path:
        proxy = getattr(proxy, part)
    if hasattr(proxy, 'GetData'):
        proxy = proxy.GetData()
    return proxy


def equivalent(actual, expected):
    if isinstance(expected, (list, tuple)):
        try:
            return len(actual) == len(expected) and all(equivalent(a, b) for a, b in zip(actual, expected))
        except TypeError:
            return False
    if isinstance(expected, (int, float)):
        return isinstance(actual, (int, float)) and math.isclose(actual, expected, rel_tol=1e-10, abs_tol=1e-12)
    return actual == expected


def configure_binding(proxy, binding, value, location):
    """Assign captured bindings, checking nested identity, domains and readback."""
    from schemaxis.core.declarations import validate_value
    from schemaxis.bindings import validate_binding
    validate_value(value,binding['value'],location)
    validate_binding(binding,value,location)
    native = native_value(binding,value,location)
    from vtkmodules.vtkCommonCore import vtkOutputWindow
    window=vtkOutputWindow.GetInstance()
    errors=[]
    observer=window.AddObserver('ErrorEvent',lambda *args: errors.append(True))
    try:
        _configure_binding(proxy,binding,value,native,location)
    finally:
        window.RemoveObserver(observer)
    if errors:
        fail('NATIVE_PROPERTY_ERROR','native property assignment reported an error',location)


def _configure_binding(proxy, binding, value, native, location):
    if binding.get('initialiseElements'):
        target = proxy
        for part in binding['path'][:-1]: target = getattr(target,part)
        prop = target.GetProperty(binding['path'][-1]).SMProperty
        if prop.GetNumberOfElements()==0:
            prop.SetNumberOfElements(binding['initialiseElements'])
    if 'proxyChoices' in binding:
        choice = binding['proxyChoices'][value['type']]
        assign(proxy, binding['path'], value['type'])
        selected = property_value(proxy, binding['path'])
        identity = selected.GetXMLGroup() + '/' + selected.GetXMLName()
        if identity != choice['identity']:
            fail('NATIVE_VALUE_MISMATCH', 'native nested proxy identity differs', location,
                 requested=choice['identity'], actual=identity)
        for key, item in value.get('options', {}).items():
            configure_binding(selected, choice['options'][key], item, location + '.' + key)
        return
    try:
        assign(proxy, binding['path'], native)
    except ValueError as error:
        # A vtkSMFieldDataDomain narrows its entries to the associations the connected input
        # provides (PV5.13.3:Remoting/ServerManager/vtkSMFieldDataDomain.cxx:180-217);
        # EnumerationProperty.ConvertValue then raises ValueError for the others.
        if 'vtkSMFieldDataDomain' not in binding.get('nativeDomains', []): raise
        from schemaxis.core.faults import Fault, SchemaxisError
        raise SchemaxisError(Fault('NATIVE_DOMAIN_MISMATCH', 'the connected input does not provide this field association',
            location, 'pipeline', observed={'requested': native, 'detail': str(error)},
            recovery='choose an association the input provides, or connect a different input')) from error
    actual = retained_value(proxy, binding, native)
    if not equivalent(actual, native):
        fail('NATIVE_VALUE_MISMATCH', 'native property did not retain the requested value',
             location, requested=native, actual=str(actual))


def retained_value(proxy, binding, native):
    actual = property_value(proxy, binding['path'])
    if not equivalent(actual, native) and integer_binding(binding):
        # Integer properties with a data-dependent enumeration domain (for example
        # vtkSMNumberOfComponentsDomain) read back as entry text such as 'Y' once the
        # upstream array exists (native probe, ParaView 5.13.3); compare the stored integers.
        actual = raw_elements(proxy, binding['path'])
        if not isinstance(native, (list, tuple)) and len(actual) == 1: actual = actual[0]
    return actual


def integer_binding(binding):
    spec = binding.get('value', {})
    return spec.get('type') == 'integer' or (spec.get('type') == 'array' and spec.get('items', {}).get('type') == 'integer')


def raw_elements(proxy, path):
    for part in path[:-1]:
        proxy = getattr(proxy, part)
    prop = proxy.GetProperty(path[-1]).SMProperty
    return [prop.GetElement(i) for i in range(prop.GetNumberOfElements())]


class ParaViewBackend:
    def __init__(self):
        from paraview import simple, servermanager
        self.pv, self.sm = simple, servermanager
        self.records = {}
        self.loaded_dependencies = set()

    def load_dependencies(self, node, declaration):
        for dependency in declaration.get('nativeDependencies', []):
            checksum = dependency['sha256']
            if checksum in self.loaded_dependencies: continue
            if dependency['kind'] == 'xml':
                payload = dependency['xml'].encode()
            elif dependency['kind'] == 'plugin':
                path = Path(dependency['path'])
                if not path.is_file():
                    fail('RESOURCE_NOT_FOUND', 'declared native plugin is unavailable', str(path))
                payload = path.read_bytes()
            else:
                fail('INVALID_EXTENSION', 'unknown native dependency kind', node)
            if hashlib.sha256(payload).hexdigest() != checksum:
                fail('DEPENDENCY_MISMATCH', 'native dependency checksum changed', node)
            if dependency['kind'] == 'xml':
                import tempfile
                with tempfile.NamedTemporaryFile(suffix='.xml') as stream:
                    stream.write(payload); stream.flush()
                    self.pv.LoadPlugin(stream.name, ns=vars(self.pv))
            else:
                self.pv.LoadPlugin(dependency['path'], ns=vars(self.pv))
            self.loaded_dependencies.add(checksum)

    def create(self, node, declaration, inputs, constructor):
        self.load_dependencies(node, declaration)
        kwargs = {declaration['inputs'][p]['native']: value for p, value in inputs.items()}
        kwargs.update({declaration['options'][k]['path'][0]: v for k, v in constructor.items()})
        if declaration['id'] == 'foam':
            kwargs = {'CaseType': kwargs['CaseType'], **{k: v for k, v in kwargs.items() if k != 'CaseType'}}
        if declaration.get('role') == 'resource':
            factory = declaration['factory']
            if factory.get('helper'):
                proxy = getattr(self.pv, factory['helper'])(node, **kwargs)
                registration = self.sm.ProxyManager().GetProxyName(factory['group'], proxy.SMProxy)
            else:
                proxy = getattr(getattr(self.sm, factory['module']), factory['class'])(**kwargs)
                registration = node
                self.sm.ProxyManager().RegisterProxy(factory['group'], registration, proxy.SMProxy)
        else:
            proxy = getattr(self.pv, declaration['native'])(registrationName=node, **kwargs)
        # Register immediately, including when later fixed-property setup fails.
        self.records[id(proxy)] = {'node': node, 'declaration': declaration, 'inputs': inputs,
                                   'options': dict(constructor)}
        if declaration.get('role') == 'resource': self.records[id(proxy)]['registration'] = registration
        try:
            vtk_class = proxy.SMProxy.GetVTKClassName() or ''
            if 'python' in vtk_class.lower():
                fail('UNSAFE_NATIVE_PROXY', 'ParaView runs authored Python in this object; Schemaxis never creates it',
                     node, vtkClass=vtk_class)
            for key, value in kwargs.items():
                if key in proxy.ListProperties():
                    guard(proxy, key, value, node + '.' + key)
            if declaration.get('nativeIdentity'):
                actual = proxy.GetXMLGroup() + '/' + proxy.GetXMLName()
                if actual != declaration['nativeIdentity']:
                    fail('NATIVE_IDENTITY_MISMATCH', 'constructor resolved to a different native definition',
                         node, requested=declaration['nativeIdentity'], actual=actual)
            for path, value in declaration.get('fixed', {}).items():
                assign(proxy, path.split('.'), value)
        except Exception:
            self.delete(proxy)
            raise
        return proxy

    def output_port(self, proxy, port):
        count = proxy.GetNumberOfOutputPorts()
        if type(port) is not int or not 0 <= port < count:
            fail('INVALID_OUTPUT_PORT', 'selected output port does not exist',
                 self.records[id(proxy)]['node'], port=port, available=count)
        return self.pv.OutputPort(proxy, port)

    def configure(self, proxy, declaration, changes):
        record = self.records[id(proxy)]
        for key, value in changes.items():
            binding = declaration['options'][key]
            if binding.get('readerSelection') and is_deferred(value):
                proxy.UpdatePipelineInformation()
                value = resolve_selection(value, list(getattr(proxy, binding['path'][0]).Available), record['node'] + '.' + key)
            if binding.get('blockSelection') and block_choices.is_deferred(value):
                source = getattr(proxy, declaration['inputs']['input']['native'])
                source.UpdatePipeline()
                value = block_choices.resolve_blocks(value, block_choices.leaves(source.GetDataInformation().GetHierarchy()),
                                                     record['node'] + '.' + key)
            if key == 'normal' and sum(v * v for v in value) == 0:
                fail('INVALID_NORMAL', 'normal cannot be zero', record['node'])
            if key in ('field', 'vectors') and value[0] not in ('POINTS', 'CELLS'):
                fail('INVALID_ASSOCIATION', 'field association must be POINTS or CELLS', record['node'])
            if not binding.get('constructor'):
                configure_binding(proxy, binding, value, record['node'] + '.' + key)
            if 'proxyChoices' in binding:
                record['options'][key] = value
                continue
            expected = native_value(binding, value, record['node'] + '.' + key)
            actual = retained_value(proxy, binding, expected)
            if not equivalent(actual, expected):
                fail('NATIVE_VALUE_MISMATCH', 'native property did not retain the effective requested value',
                     record['node'] + '.' + key, requested=expected, actual=str(actual))
            record['options'][key] = value

    def command(self, proxy, name):
        record = self.records[id(proxy)]
        declaration = record['declaration'].get('commands', {}).get(name)
        if declaration is None:
            fail('INVALID_COMMAND', 'command is not declared for this operation', record['node'])
        from vtkmodules.vtkCommonCore import vtkOutputWindow
        errors=[]
        window=vtkOutputWindow.GetInstance()
        observer=window.AddObserver('ErrorEvent', lambda *args: errors.append(True))
        try:
            proxy.InvokeCommand(declaration['native'])
        finally:
            window.RemoveObserver(observer)
        if errors:
            fail('NATIVE_COMMAND_FAILED', 'native command reported an error', record['node'], command=name)

    def update(self, proxy, time):
        record = self.records[id(proxy)]
        record.pop('fetched', None)
        record['inputContracts'] = {}
        # Upstream objects have now updated. Input domains are meaningful here,
        # whereas bounds/range domains may merely describe GUI slider suggestions.
        for port in record['inputs']:
            spec = record['declaration']['inputs'][port]
            if spec.get('kind', 'data') != 'data':
                record['inputContracts'][port] = {'kind':spec['kind'], 'compatibility':'supported',
                                                  'performance':{'rating':'unknown'}}
                continue
            from schemaxis.data_contracts import assess
            from .traits import paraview_traits
            sources = record['inputs'][port]
            sources = sources if isinstance(sources, list) else [sources]
            assessments = []
            for source in sources:
                data_class = source.GetDataInformation().GetDataClassName()
                traits = paraview_traits(data_class)
                contract = spec.get('contract', {})
                assessment = assess(contract.get('requirements', {}), traits, contract.get('cost'))
                if assessment['compatibility'] == 'unsupported':
                    raise SchemaxisError(Fault(
                        'INPUT_TRAIT_MISMATCH', 'input lacks required data capabilities',
                        record['node'] + '.' + port, 'pipeline', observed={
                            'assessment': assessment, 'dataClass': data_class},
                        recovery=contract.get('recovery')))
                assessments.append({'traits': traits, **assessment})
            record['inputContracts'][port] = assessments
            prop = proxy.GetProperty(spec['native']).SMProperty
            for domain_class in ('vtkSMDataTypeDomain', 'vtkSMInputArrayDomain'):
                domain = prop.FindDomain(domain_class)
                if domain is not None and not domain.IsInDomain(prop):
                    fail('INPUT_DOMAIN_MISMATCH', 'input violates native data or array requirements',
                         record['node'] + '.' + port, contract=spec.get('contract'))
        if record['declaration']['id'] == 'foam':
            proxy.UpdatePipelineInformation()
            available = list(proxy.TimestepValues)
            if not any(abs(t - time) <= 1e-10 for t in available):
                fail('TIME_UNAVAILABLE', 'requested time is not available', record['node'],
                     time=time, available=available)
        for key in ('field', 'vectors'):
            if key in record['options']:
                association, field_name = record['options'][key]
                source = record['inputs']['input']
                arrays = source.PointData if association == 'POINTS' else source.CellData
                if field_name not in arrays.keys():
                    fail('MISSING_FIELD', 'requested field is absent', record['node'] + '.' + key,
                         field=field_name, association=association, available=list(arrays.keys()))
        from vtkmodules.vtkCommonCore import vtkOutputWindow
        errors = []
        window = vtkOutputWindow.GetInstance()
        observer = window.AddObserver('ErrorEvent', lambda *args: errors.append(True))
        try:
            if record['declaration'].get('role') == 'resource':
                proxy.UpdateVTKObjects()
            else:
                self.pv.UpdatePipeline(time=time, proxy=proxy)
        finally:
            window.RemoveObserver(observer)
        if errors:
            fail('NATIVE_PIPELINE_ERROR', 'native algorithm emitted an error; inspect retained stderr', record['node'])
        record['time'] = time
        if record['declaration']['native'] == 'Calculator':
            association = property_value(proxy, ['AttributeType'])
            result_name = property_value(proxy, ['ResultArrayName'])
            arrays = proxy.PointData if association == 'Point Data' else proxy.CellData
            if result_name not in arrays.keys():
                fail('CALCULATION_FAILED', 'calculator did not produce its declared result', record['node'])

    def fetch(self, proxy):
        # The serial builtin session owns the actual output locally. Generic Fetch
        # uses reduction filters which cannot preserve every composite data type.
        from vtkmodules.vtkParallelCore import vtkMultiProcessController
        controller = vtkMultiProcessController.GetGlobalController()
        serial = controller is None or controller.GetNumberOfProcesses() == 1
        if serial and not self.sm.ActiveConnection.IsRemote():
            algorithm = proxy.GetClientSideObject()
            if algorithm is not None and hasattr(algorithm, 'GetOutputDataObject'):
                data = algorithm.GetOutputDataObject(proxy.Port)
                if data is not None:
                    return data
        if not serial:
            info = proxy.GetDataInformation()
            if info.GetNumberOfPoints() > 4096 or info.GetNumberOfCells() > 4096 or info.GetMemorySize() > 1024:
                fail('UNBOUNDED_MPI_GATHER', 'only small reduced results may be fetched; publish native distributed geometry instead', points=info.GetNumberOfPoints(), cells=info.GetNumberOfCells(), memoryKiB=info.GetMemorySize(), node=self.records.get(id(proxy), {}).get('node'))
        return self.sm.Fetch(proxy, idx=proxy.Port)

    def observe(self, proxy):
        record = self.records[id(proxy)]
        if record['declaration'].get('role') == 'resource':
            return {'kind':record['declaration']['kinds'][0],
                    'nativeIdentity':record['declaration']['nativeIdentity'],
                    'inputContracts':record.get('inputContracts', {})}
        info = proxy.GetDataInformation()
        bounds = list(info.GetBounds())
        result = {'points': info.GetNumberOfPoints(), 'cells': info.GetNumberOfCells(),
                  'bounds': bounds, 'fields': {}}
        result['dataType'] = info.GetDataClassName()
        from .traits import paraview_traits
        result['traits'] = paraview_traits(result['dataType'])
        result['inputContracts'] = self.records[id(proxy)].get('inputContracts', {})
        if result['dataType'] == 'vtkTable':
            result['rows'] = info.GetNumberOfRows()
            result['bounds'] = bounds = None
        if bounds is not None and not all(math.isfinite(v) for v in bounds):
            fail('INVALID_DATA', 'nonfinite dataset bounds')
        associations = [('ROWS', self.sm.FieldDataInformation(proxy.SMProxy, proxy.Port, 'RowData'))] if result['dataType'] == 'vtkTable' else [('POINTS', proxy.PointData), ('CELLS', proxy.CellData)]
        for association, arrays in associations:
            result['fields'][association] = {
                key: {'components': arrays[key].GetNumberOfComponents(),
                      'range': list(arrays[key].GetRange()) if arrays[key].GetDataType() != 13 else None}
                for key in arrays.keys()}
        # Invalid empty-data ranges must not leak NaN into JSON observations.
        for arrays in result['fields'].values():
            for field in arrays.values():
                if field['range'] is not None and not all(math.isfinite(v) for v in field['range']):
                    field['range'] = None
        return result

    def delete(self, proxy):
        record = self.records.get(id(proxy), {})
        declaration = record.get('declaration', {})
        if declaration.get('role') == 'resource':
            self.sm.ProxyManager().UnRegisterProxy(declaration['factory']['group'], record['registration'], proxy.SMProxy)
        else:
            self.pv.Delete(proxy)
        self.records.pop(id(proxy), None)

    def sample(self, proxy, association, field, index, component, block):
        record = self.records[id(proxy)]
        if 'fetched' not in record:
            record['fetched'] = self.fetch(proxy)
        data = record['fetched']
        for i in block:
            if not data.IsA('vtkMultiBlockDataSet') or i >= data.GetNumberOfBlocks() or data.GetBlock(i) is None:
                fail('INVALID_SELECTION', 'sample block does not exist', record['node'], block=block)
            data = data.GetBlock(i)
        if association == 'ROWS' and not data.IsA('vtkTable'):
            fail('INVALID_ASSOCIATION', 'ROWS requires a table', record['node'])
        if association != 'ROWS' and not hasattr(data, 'GetPointData'):
            fail('INVALID_SELECTION', 'select an explicit leaf block before sampling', record['node'])
        arrays = data.GetRowData() if association == 'ROWS' else data.GetPointData() if association == 'POINTS' else data.GetCellData()
        array = arrays.GetArray(field)
        if array is None:
            fail('MISSING_FIELD', 'sample field is unavailable', record['node'], field=field)
        if type(index) is not int or index < 0 or index >= array.GetNumberOfTuples():
            fail('INVALID_SELECTION', 'sample tuple index is out of range', record['node'], index=index)
        if component is not None and component >= array.GetNumberOfComponents():
            fail('INVALID_COMPONENT', 'sample component is out of range', record['node'])
        values = list(array.GetTuple(index))
        if not all(math.isfinite(v) for v in values):
            fail('NONFINITE_DATA', 'sample contains nonfinite values', record['node'])
        return values[component] if component is not None else (values[0] if len(values) == 1 else values)


from .data import snapshot


def geometry(backend, proxy, path, allow_empty=False):
    from vtkmodules.vtkParallelCore import vtkMultiProcessController
    controller = vtkMultiProcessController.GetGlobalController()
    if controller and controller.GetNumberOfProcesses() > 1:
        from .parallel_native import geometry as distributed_geometry
        return distributed_geometry(backend, proxy, path, allow_empty)
    live = backend.fetch(proxy)
    formats = {'vtkPolyData': ('vtp', 'XMLPolyDataReader'),
               'vtkUnstructuredGrid': ('vtu', 'XMLUnstructuredGridReader'),
               'vtkImageData': ('vti', 'XMLImageDataReader'),
               'vtkStructuredGrid': ('vts', 'XMLStructuredGridReader'),
               'vtkRectilinearGrid': ('vtr', 'XMLRectilinearGridReader'),
               'vtkMultiBlockDataSet': ('vtm', 'XMLMultiBlockDataReader'),
               'vtkTable': ('vtt', 'XMLTableReader'),
               'vtkPartitionedDataSet': ('vtpd', None),
               'vtkPartitionedDataSetCollection': ('vtpc', None),
               'vtkHyperTreeGrid': ('htg', None),
               'vtkHierarchicalBoxDataSet': ('vthb', None),
               'vtkOverlappingAMR': ('vthb', None)}
    if live.GetClassName() not in formats:
        fail('UNSUPPORTED_OUTPUT', 'no verified writer for this data type', str(path), dataType=live.GetClassName())
    size = (live.GetNumberOfRows() if live.IsA('vtkTable') else
            live.GetNumberOfCells() if live.IsA('vtkHyperTreeGrid') else live.GetNumberOfPoints())
    if not allow_empty and size == 0:
        fail('EMPTY_GEOMETRY', 'requested output contains no points or rows', str(path))
    extension, reader = formats[live.GetClassName()]
    path = Path(str(path) + '.' + extension)
    before = snapshot(live)
    from .writers import checked_update, preserve_field_data
    writer = backend.pv.CreateWriter(str(path), proxy)
    if writer is None:
        fail('UNAVAILABLE_WRITER', 'no registered writer for the output', str(path))
    try:
        preserve_field_data(writer, {})
        checked_update(backend, writer, backend.records.get(id(proxy), {}).get('time', 0), str(path))
    finally:
        backend.pv.Delete(writer)
    reopened = (getattr(backend.pv, reader)(FileName=[str(path)]) if reader else backend.pv.OpenDataFile(str(path)))
    if reopened is None:
        fail('UNAVAILABLE_READER', 'no registered reader can verify this output', str(path))
    try:
        if live.IsA('vtkUniformGridAMR') and 'DefaultNumberOfLevels' in reopened.ListProperties():
            reopened.DefaultNumberOfLevels = live.GetNumberOfLevels()
        backend.pv.UpdatePipeline(proxy=reopened)
        after = snapshot(backend.fetch(reopened))
    finally:
        backend.pv.Delete(reopened)
    if before != after:
        fail('VERIFICATION_FAILED', 'reopened data differs from live output', str(path),
             live=before, reopened=after)
    files = [path]
    if extension in ('vtm', 'vtpd', 'vtpc', 'vthb'):
        files.extend(p for p in sorted(path.with_suffix('').rglob('*')) if p.is_file())
    return {'file': str(path), 'sha256': hashlib.sha256(path.read_bytes()).hexdigest(),
            'files': [{'file': str(p), 'sha256': hashlib.sha256(p.read_bytes()).hexdigest()} for p in files],
            'verified': True, 'data': before, 'dataDigest': digest(before),
            'spatial': {'state': 'known', 'frame': 'native-world', 'units': 'unknown',
                        'bounds': list(proxy.GetDataInformation().GetBounds()),
                        'boundsOrder': ['xmin','xmax','ymin','ymax','zmin','zmax'], 'axisOrder': ['x','y','z'], 'coordinateRepresentation': 'world coordinates stored in dataset'}}


def measurement(backend, proxy, path, association='POINTS'):
    """Durable field table with an explicit association; no unit inference."""
    import csv
    from vtkmodules.vtkParallelCore import vtkMultiProcessController
    controller = vtkMultiProcessController.GetGlobalController()
    if controller and controller.GetNumberOfProcesses() > 1:
        from .parallel_native import measurement as reduced_measurement
        return reduced_measurement(backend, proxy, path, association)
    data = backend.fetch(proxy)
    if association == 'ROWS' and not data.IsA('vtkTable'):
        fail('INVALID_ASSOCIATION', 'ROWS requires a table', str(path))
    if association != 'ROWS' and not hasattr(data, 'GetPointData'):
        fail('INVALID_ASSOCIATION', 'spatial measurements require a dataset', str(path))
    arrays = data.GetRowData() if association == 'ROWS' else data.GetPointData() if association == 'POINTS' else data.GetCellData()
    size = data.GetNumberOfRows() if association == 'ROWS' else data.GetNumberOfPoints() if association == 'POINTS' else data.GetNumberOfCells()
    fields = [arrays.GetArray(i) for i in range(arrays.GetNumberOfArrays()) if arrays.GetArray(i) is not None]
    if not fields or size == 0:
        fail('EMPTY_MEASUREMENT', 'no tuples available for the requested association', str(path))
    headers = ['index'] + [f'{a.GetName()}[{c}]' for a in fields for c in range(a.GetNumberOfComponents())]
    rows = [[i] + [a.GetComponent(i, c) for a in fields for c in range(a.GetNumberOfComponents())]
            for i in range(size)]
    if any(not math.isfinite(v) for row in rows for v in row):
        fail('NONFINITE_DATA', 'measurement contains nonfinite values', str(path))
    path = Path(str(path) + '.csv')
    with path.open('w', newline='') as stream:
        writer = csv.writer(stream)
        writer.writerow(headers)
        writer.writerows(rows)
    with path.open(newline='') as stream:
        reader = csv.reader(stream)
        restored_header = next(reader)
        restored = [[float(v) for v in row] for row in reader]
    if restored_header != headers or restored != rows:
        fail('VERIFICATION_FAILED', 'measurement round trip differs', str(path))
    return {'file': str(path), 'sha256': hashlib.sha256(path.read_bytes()).hexdigest(),
            'verified': True, 'association': association, 'rows': size,
            'columns': headers, 'units': 'not inferred', 'values': rows if size <= 10 else None}
