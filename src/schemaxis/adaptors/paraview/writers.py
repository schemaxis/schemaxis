# Copyright (C) 2026 David L F Gaden
"""Declared writer publication, loss contracts and semantic readback.

Native imports remain inside execution functions. Publication owns filenames and
one selected timestep; writer-controlled file series cannot escape the schedule.
"""
import copy
import hashlib
import math
from pathlib import Path
from schemaxis.errors import fail, keys
from schemaxis.bindings import validate_options
from schemaxis.pipeline import name, markers
from schemaxis.camera import staged_values

SERIES_PROPERTIES = {'WriteTimeSteps', 'WriteAllTimeSteps', 'Writetimestepsasfileseries',
                     'Writealltimestepsasfileseries', 'WriteSeriesMetaFile',
                     'WriteTimeStepsSeparately'}
MANAGED_PROPERTIES = SERIES_PROPERTIES | {'FileName', 'Filenamesuffix', 'Firsttimestep',
                                         'Lasttimestep', 'Timestepstride',
                                         # vtkIOSSWriter runs its own time loop; publication selects the step
                                         # (PV5.13.3:VTK/IO/IOSS/vtkIOSSWriter.cxx:244-257,285-342). IOSSWriter is the
                                         # only writer declaring these two settings.
                                         'TimeStepRange', 'TimeStepStride'}
# vtkSMFieldDataDomain entry texts keyed by vtkDataObject attribute type
# (PV5.13.3:Remoting/ServerManager/vtkSMFieldDataDomain.cxx:35-36).
FIELD_ASSOCIATIONS = {0: 'Point Data', 1: 'Cell Data', 2: 'Field Data',
                      4: 'Vertex Data', 5: 'Edge Data', 6: 'Row Data'}
CSV_VERIFIED_ASSOCIATIONS = ('Point Data', 'Cell Data', 'Row Data')
LOSSES = {'geometry': ['fields', 'point-identity', 'interior-cells', 'structure'],
          'pixels': ['coordinates', 'fields'], 'table': ['topology', 'coordinates', 'structure'],
          'semantic': ['structure', 'point-identity', 'connectivity-order', 'storage-type'],
          'exact': []}


def managed_property(key):
    return key in MANAGED_PROPERTIES


def writer_contract(native, extensions):
    comparison = ('geometry' if native in ('PSTLWriter','PPLYWriter','POBJWriter','HoudiniWriter') else
                  'pixels' if native in ('PNGWriter','JPEGWriter','TIFFWriter','JSONImageWriter','MetaImageWriter') else
                  'table' if native in ('CSVWriter','DataSetCSVWriter') else 'exact')
    if native in ('CGNSWriter','ExodusIIWriter','IOSSWriter','EnSightWriter','XdmfWriter','Xdmf3Writer','GenericIOWriter'):
        comparison = 'semantic'
    return {'extensions': extensions, 'comparison': comparison,
            'losses': LOSSES[comparison], 'qualification': 'requires fixture',
            'time': 'one scheduled state', 'filenames': 'managed output directory'}


def check_verifiable_selection(options, comparison, location):
    """Reject writer subsets that no declared comparison can verify.

    ChooseArraysToWrite/ChooseBlocksToWrite make the file hold less than the
    export node, so an exact, semantic or table comparison against the node
    would fail, and comparing only the subset would loosen verification.
    Marked (late-bound) values are re-checked by publish() once resolved.
    """
    if options.get('ChooseBlocksToWrite') is True:
        fail('BLOCK_SELECTION_UNVERIFIABLE',
             'ChooseBlocksToWrite drops blocks and no declared comparison accepts missing blocks', location + '.ChooseBlocksToWrite',
             comparison=comparison, recovery='extract the blocks to keep with pvExtractBlock and export that node')
    if options.get('ChooseArraysToWrite') is True and comparison in ('exact', 'semantic', 'table'):
        fail('ARRAY_SELECTION_UNVERIFIABLE',
             f'ChooseArraysToWrite omits input arrays, which the {comparison} comparison requires to be present',
             location + '.ChooseArraysToWrite', comparison=comparison,
             recovery='filter arrays with pvPassArrays and export that node')


def check_csv_association(options, location):
    """Reject at planning an authored association that verify_csv cannot verify.

    Row Data is valid only for table input, which is not known until publication.
    """
    value = options.get('FieldAssociation')
    text = FIELD_ASSOCIATIONS.get(value, value) if isinstance(value, (int, str)) and not isinstance(value, bool) else None
    if text in ('Field Data', 'Vertex Data', 'Edge Data'):
        fail('UNSUPPORTED_ASSOCIATION', 'CSV verification supports point, cell and row data', location + '.FieldAssociation',
             association=text, supported=list(CSV_VERIFIED_ASSOCIATIONS),
             recovery='export Point Data or Cell Data, or pass the field data through a table-producing filter first')


def houdini_minimum_tolerance(maximum_magnitude):
    """Half a unit in the sixth significant digit of the largest coordinate.

    vtkHoudiniPolyDataWriter streams coordinates with the default 6 significant
    digits (PV5.13.3:VTK/IO/Geometry/vtkHoudiniPolyDataWriter.cxx:383-386; the
    file never sets a precision), so each printed coordinate can differ from the
    stored one by up to this amount.
    """
    magnitude = abs(float(maximum_magnitude))
    if magnitude == 0 or not math.isfinite(magnitude): return 0.0
    return 0.5 * 10.0 ** (math.floor(math.log10(magnitude)) - 5)


def check_precision_contract(native, comparison, tolerance, location):
    """Planning-time constraints for writers whose files cannot round-trip exactly."""
    if native == 'HoudiniWriter':
        if comparison != 'geometry':
            fail('INVALID_VERIFICATION', 'Houdini verification requires the geometry loss contract', location + '.comparison')
        if tolerance == 0:
            fail('INVALID_TOLERANCE',
                 'Houdini ASCII stores coordinates with 6 significant digits, so a zero tolerance cannot be met by general data',
                 location + '.tolerance', recovery='set a tolerance of at least half a unit in the sixth significant digit of the '
                 'largest coordinate (about 5e-6 times that coordinate); publication rejects a tolerance below that bound')
    if native == 'JPEGWriter':
        if comparison != 'pixels':
            fail('INVALID_VERIFICATION', 'JPEG verification requires the pixels loss contract', location + '.comparison')
        if tolerance == 0:
            fail('INVALID_TOLERANCE', 'JPEG is lossy (quality 95), so a zero pixel tolerance cannot be met',
                 location + '.tolerance', recovery='set a tolerance in pixel-value units, or export PNG for lossless pixels')


def validate_exports(master, values, location):
    if not isinstance(values, list): fail('INVALID_PUBLICATION', 'exports must be a list', location)
    result, names = [], set()
    for index, value in enumerate(values):
        item_location = f'{location}[{index}]'
        keys(value, ('id','node','writer','options','extension','comparison','acceptLosses','tolerance','readback','resources'), item_location)
        identity = name(value.get('id'), item_location+'.id')
        if identity in names: fail('DUPLICATE_WRITER','export identifiers must be unique',item_location+'.id')
        names.add(identity)
        node = name(value.get('node'), item_location+'.node')
        writer = value.get('writer')
        declaration = master.declarations.get(writer) if isinstance(writer, str) else None
        if not declaration or declaration.get('role') != 'writer':
            fail('UNKNOWN_WRITER','select a declared writer operation', item_location+'.writer')
        contract = declaration['publication']
        resources=copy.deepcopy(value.get('resources',{}))
        ports={k:s for k,s in declaration['inputs'].items() if s.get('kind','data')!='data'}
        keys(resources, ports, item_location+'.resources')
        for port, target in resources.items():
            name(target,item_location+'.resources.'+port)
            if target not in master.nodes: fail('UNKNOWN_REFERENCE','writer resource node does not exist',item_location,node=target)
            available=master.declarations[master.nodes[target]['filter']].get('kinds',['data'])
            if ports[port]['kind'] not in available:
                fail('TYPE_MISMATCH','writer resource has the wrong kind',item_location,port=port,expected=ports[port]['kind'])
        extension = value.get('extension', next(iter(contract['extensions']), None))
        if not isinstance(extension, str) or extension not in contract['extensions']:
            fail('INVALID_FORMAT','extension is not declared by the writer',item_location+'.extension',available=contract['extensions'])
        comparison = value.get('comparison', contract['comparison'])
        if comparison not in LOSSES: fail('INVALID_VERIFICATION','unknown export comparison',item_location+'.comparison')
        if declaration['native']=='JSONImageWriter' and comparison!='pixels':
            fail('INVALID_VERIFICATION','JSON image verification requires the pixels loss contract',item_location+'.comparison')
        losses = value.get('acceptLosses', [])
        if not isinstance(losses,list) or any(not isinstance(v,str) for v in losses):
            fail('INVALID_LOSS_CONTRACT','acceptLosses must be a list of loss categories',item_location+'.acceptLosses')
        if not set(LOSSES[comparison]) <= set(losses):
            fail('LOSS_NOT_ACCEPTED','the selected comparison requires explicit accepted losses',item_location+'.acceptLosses',
                 required=LOSSES[comparison])
        tolerance = value.get('tolerance',0.0)
        if type(tolerance) not in (int,float) or not math.isfinite(tolerance) or tolerance < 0:
            fail('INVALID_TOLERANCE','tolerance must be finite and nonnegative',item_location+'.tolerance')
        if comparison == 'exact' and tolerance:
            fail('INVALID_TOLERANCE','exact comparison does not discard numerical precision',item_location+'.tolerance')
        options = staged_values({k:v['value'] for k,v in declaration['options'].items()},
                                value.get('options',{}),item_location+'.options')
        if not list(markers(options)): options = validate_options(declaration,options,item_location+'.options')
        check_verifiable_selection(options, comparison, item_location+'.options')
        check_precision_contract(declaration['native'], comparison, tolerance, item_location)
        if comparison == 'table': check_csv_association(options, item_location+'.options')
        readback = value.get('readback')
        if readback is not None:
            if comparison=='table' or declaration['native'] in ('JSONImageWriter','HoudiniWriter'):
                fail('INVALID_READER','this format uses its declared direct readback verifier',item_location)
            keys(readback, ('operation','options'),item_location+'.readback')
            operation=readback.get('operation')
            d=master.declarations.get(operation) if isinstance(operation,str) else None
            if not d or d.get('role')=='writer' or d['inputs']:
                fail('INVALID_READER','readback requires a declared source reader',item_location)
            filenames=[k for k,v in d['options'].items() if v.get('constructor') and 'vtkSMFileListDomain' in v.get('nativeDomains',[])]
            if len(filenames)!=1: fail('INVALID_READER','readback needs exactly one declared file argument',item_location)
            key=filenames[0]
            opts=copy.deepcopy(readback.get('options',{}))
            managed=sorted(k for k,v in d['options'].items() if 'vtkSMFileListDomain' in v.get('nativeDomains',[]) and k in opts)
            if managed:
                fail('MANAGED_FILENAME','readback file names are managed; no file-list option may be authored',
                     item_location+'.readback.options',options=managed)
            opts[key]=['output'] if d['options'][key]['value']['type']=='array' else 'output'
            validate_options(d,opts,item_location+'.readback')
        result.append({'id':identity,'node':node,'writer':writer,'options':options,'extension':extension,
                       'comparison':comparison,'acceptLosses':losses,'tolerance':tolerance,'readback':readback,
                       'resources':resources})
    return result


def checked_update(backend, proxy, time, location):
    from vtkmodules.vtkCommonCore import vtkOutputWindow
    errors=[]
    window=vtkOutputWindow.GetInstance()
    observer=window.AddObserver('ErrorEvent',lambda *args: errors.append(True))
    try: backend.pv.UpdatePipeline(time=time,proxy=proxy)
    finally: window.RemoveObserver(observer)
    if errors: fail('NATIVE_PIPELINE_ERROR','native writer/reader reported an error; inspect retained stderr',location)


def preserve_field_data(writer, options):
    """The receipt carries time; do not inject a new TimeValue data array."""
    if 'WriteTimeValue' in options:
        return
    if 'WriteTimeValue' in writer.ListProperties():
        writer.WriteTimeValue = 0
    else:
        algorithm = writer.GetClientSideObject()
        if algorithm is not None and algorithm.IsA('vtkFileSeriesWriter'):
            algorithm = algorithm.GetWriter()
        if algorithm is not None and hasattr(algorithm, 'SetWriteTimeValue'):
            algorithm.SetWriteTimeValue(False)


def surface_triangles(data):
    """Canonical surface triangles preserve geometry across point-ID changes."""
    from vtkmodules.vtkFiltersGeometry import vtkGeometryFilter, vtkCompositeDataGeometryFilter
    from vtkmodules.vtkFiltersCore import vtkTriangleFilter
    surface=vtkCompositeDataGeometryFilter() if data.IsA('vtkCompositeDataSet') else vtkGeometryFilter()
    surface.SetInputDataObject(data); surface.Update()
    triangulate=vtkTriangleFilter();triangulate.SetInputConnection(surface.GetOutputPort());triangulate.Update()
    mesh=triangulate.GetOutput()
    if not mesh.GetNumberOfCells(): fail('EMPTY_GEOMETRY','surface comparison requires nonempty geometry')
    records=[]
    for index in range(mesh.GetNumberOfCells()):
        cell=mesh.GetCell(index)
        records.append(sorted(tuple(mesh.GetPoint(cell.GetPointId(i))) for i in range(cell.GetNumberOfPoints())))
    return sorted(records)


def numbers_equal(left, right, tolerance):
    if isinstance(left,(list,tuple)) and isinstance(right,(list,tuple)):
        return len(left)==len(right) and all(numbers_equal(a,b,tolerance) for a,b in zip(left,right))
    return (type(left) in (int,float) and type(right) in (int,float) and
            math.isfinite(left) and math.isfinite(right) and abs(left-right)<=tolerance)


def compare_data(before, after, comparison, tolerance):
    from .data import snapshot
    if comparison=='exact':
        left,right=snapshot(before),snapshot(after)
        if left!=right: fail('VERIFICATION_FAILED','writer readback differs from its input',live=left,reopened=right)
        return {'comparison':'exact','data':left}
    if comparison=='semantic':
        return compare_semantic(before,after,tolerance)
    if comparison=='geometry':
        left,right=surface_triangles(before),surface_triangles(after)
        if not numbers_equal(left,right,tolerance):
            fail('VERIFICATION_FAILED','surface geometry changed beyond the accepted tolerance',
                 inputCells=len(left),outputCells=len(right),tolerance=tolerance)
        return {'comparison':'geometry','surfaceCells':len(left),'tolerance':tolerance}
    if comparison=='pixels':
        if not before.IsA('vtkImageData') or not after.IsA('vtkImageData'):
            fail('INVALID_DATA_TYPE','pixel comparison requires image data')
        a,b=before.GetPointData().GetScalars(),after.GetPointData().GetScalars()
        if (not a or not b or before.GetDimensions()!=after.GetDimensions()
                or a.GetNumberOfComponents()!=b.GetNumberOfComponents()
                or a.GetNumberOfTuples()!=b.GetNumberOfTuples()):
            fail('VERIFICATION_FAILED','image dimensions or components changed')
        maximum=0.0
        for i in range(a.GetNumberOfTuples()):
            x,y=a.GetTuple(i),b.GetTuple(i)
            if not numbers_equal(x,y,tolerance):fail('VERIFICATION_FAILED','pixel values changed beyond tolerance',tuple=i,tolerance=tolerance)
            maximum=max(maximum,max(abs(u-v) for u,v in zip(x,y)))
        return {'comparison':'pixels','dimensions':list(before.GetDimensions()),'maximumError':maximum}
    fail('INVALID_VERIFICATION','comparison needs a format-specific verifier')


def publish(backend, proxy, declaration, settings, directory, time, declarations, resources=None):
    from .native import configure_binding
    directory=Path(directory);directory.mkdir(exist_ok=False)
    path=directory/('data.'+settings['extension'])
    before=backend.fetch(proxy)
    writer=reader=None
    options=validate_options(declaration,settings['options'],settings['id'])
    check_verifiable_selection(options,settings['comparison'],settings['id']+'.options')
    check_input_contract(declaration['native'],before,options,settings,settings['id'])
    try:
        backend.load_dependencies(settings['id'], declaration)
        resource_handles=resources or {}
        writer=getattr(backend.pv,declaration['native'])(Input=proxy,FileName=str(path), **{
            declaration['inputs'][key]['native']:handle for key,handle in resource_handles.items()})
        for key,handle in resource_handles.items():
            actual_resource=writer.GetProperty(declaration['inputs'][key]['native']).GetData()
            if actual_resource is None or actual_resource.GetGlobalIDAsString()!=handle.GetGlobalIDAsString():
                fail('NATIVE_VALUE_MISMATCH','writer did not retain its requested resource',settings['id'],port=key)
        actual=writer.GetXMLGroup()+'/'+writer.GetXMLName()
        if actual!=declaration['nativeIdentity']:
            fail('NATIVE_IDENTITY_MISMATCH','writer identity differs',settings['id'],actual=actual)
        prop=writer.GetProperty('Input').SMProperty
        domain=prop.FindDomain('vtkSMDataTypeDomain')
        if domain is not None and not domain.IsInDomain(prop):
            fail('INPUT_DOMAIN_MISMATCH','writer cannot accept this data type',settings['id'])
        for key in SERIES_PROPERTIES:
            if key in writer.ListProperties(): setattr(writer,key,0)
        preserve_field_data(writer, options)
        for key,value in options.items(): configure_binding(writer,declaration['options'][key],value,settings['id']+'.'+key)
        if declaration['native']=='IOSSWriter':
            steps=input_time_steps(proxy)
            check_ioss_global_ids(before,steps,settings['id'],offset=bool(options.get('OffsetGlobalIds')))
            apply_ioss_single_step(writer,steps,time,settings['id'])
        checked_update(backend,writer,time,settings['id'])
        if not path.is_file() and declaration['native']=='EnSightWriter':
            path = directory / 'data.0.case'
        if not path.is_file(): fail('MISSING_ARTIFACT','writer did not produce its declared output',str(path))
        if settings['comparison']=='table':
            verification=verify_csv(before,path,effective_csv_settings(writer),settings['tolerance'])
        elif declaration['native']=='JSONImageWriter':
            verification=verify_json_image(before,path,settings['tolerance'],options)
        elif declaration['native']=='HoudiniWriter':
            verification=compare_data(before,read_houdini(path),settings['comparison'],settings['tolerance'])
        else:
            readback=settings['readback']
            if readback:
                d=declarations[readback['operation']]
                key=next(k for k,v in d['options'].items() if v.get('constructor') and 'vtkSMFileListDomain' in v.get('nativeDomains',[]))
                opts=copy.deepcopy(readback.get('options',{}))
                opts[key]=[str(path)] if d['options'][key]['value']['type']=='array' else str(path)
                opts=validate_options(d,opts,settings['id']+'.readback')
                reader=backend.create(settings['id']+'Readback',d,{}, {k:v for k,v in opts.items() if d['options'][k].get('constructor')})
                backend.configure(reader,d,opts);backend.update(reader,time)
            else:
                # PDAL also registers .ply but deliberately reads only points.
                # Select the mesh reader when verifying a polygon writer.
                reader=(backend.pv.PLYReader(FileNames=[str(path)])
                        if declaration['native']=='PPLYWriter' else backend.pv.OpenDataFile(str(path)))
                if reader is None:fail('UNAVAILABLE_READER','configure a readback reader for this format',str(path))
                if before.IsA('vtkUniformGridAMR') and 'DefaultNumberOfLevels' in reader.ListProperties():
                    reader.DefaultNumberOfLevels=before.GetNumberOfLevels()
                checked_update(backend,reader,time,settings['id']+'.readback')
            verification=compare_data(before,backend.fetch(reader),settings['comparison'],settings['tolerance'])
        files=[p for p in sorted(directory.rglob('*')) if p.is_file()]
        if any(not p.resolve().is_relative_to(directory.resolve()) for p in files):
            fail('INVALID_ARTIFACT','writer produced a file outside its output directory',str(directory))
        return {'file':str(path),'sha256':hashlib.sha256(path.read_bytes()).hexdigest(),'verified':True,
                'files':[{'file':str(p),'sha256':hashlib.sha256(p.read_bytes()).hexdigest()} for p in files],
                'writer':settings['writer'],'effectiveOptions':options,'comparison':settings['comparison'],
                'acceptedLosses':settings['acceptLosses'],'tolerance':settings['tolerance'],
                'readback':settings['readback'],'verification':verification,
                'resources':settings.get('resources',{}),
                'resourceProxyIds':{key:str(handle.GetGlobalIDAsString()) for key,handle in resource_handles.items()}}
    finally:
        if reader is not None:
            if id(reader) in backend.records: backend.delete(reader)
            else: backend.pv.Delete(reader)
        if writer is not None: backend.pv.Delete(writer)


def check_input_contract(native, before, options, settings, location):
    """Faults that can be decided from the input before the writer runs."""
    if native == 'JPEGWriter':
        scalars = before.GetPointData().GetScalars() if before.IsA('vtkImageData') else None
        if scalars is None or scalars.GetDataType() != 3:  # VTK_UNSIGNED_CHAR
            fail('UNSUPPORTED_DATA_TYPE',
                 'vtkJPEGWriter writes only unsigned char scalars and otherwise produces no file',
                 location, scalarType=None if scalars is None else scalars.GetDataTypeAsString(),
                 recovery='convert the active scalars to unsigned char upstream, for example with a calculator '
                          'and pvImageShiftScale, or export PNG')
    elif native == 'JSONImageWriter':
        check_json_image_options(before, options, location)
    elif native == 'HoudiniWriter':
        # Other input types are left to the native input-domain check, which faults structurally.
        if before.IsA('vtkPolyData') and before.GetNumberOfPoints():
            bounds = before.GetBounds()
            required = houdini_minimum_tolerance(max(abs(v) for v in bounds))
            if settings['tolerance'] < required:
                fail('TOLERANCE_BELOW_WRITER_PRECISION',
                     'Houdini ASCII prints 6 significant digits; the tolerance is below the rounding error of the input coordinates',
                     location + '.tolerance', tolerance=settings['tolerance'], minimum=required,
                     recovery='raise the tolerance to at least the reported minimum')
    elif settings['comparison'] == 'table':
        reject_composite_csv(before, location)


def reject_composite_csv(data, location='$'):
    if data.IsA('vtkCompositeDataSet'):
        fail('UNSUPPORTED_DATA_TYPE',
             'CSV verification needs a dataset or table; ParaView flattens composite input and the merged columns are not verified',
             location, recovery='merge composite input with pvMergeBlocks and export that node')


def effective_csv_settings(writer):
    """Read the settings ParaView actually holds, after any initialization helper ran."""
    def element(key):
        prop = writer.GetProperty(key)
        return None if prop is None else prop.SMProperty.GetElement(0)
    result = {}
    code = element('FieldAssociation')
    if code is not None:
        if code not in FIELD_ASSOCIATIONS:
            fail('INVALID_ASSOCIATION', 'writer holds an unknown FieldAssociation code', 'FieldAssociation', nativeCode=code)
        result['FieldAssociation'] = FIELD_ASSOCIATIONS[code]
    for key in ('FieldDelimiter', 'StringDelimiter'):
        value = element(key)
        if value is not None: result[key] = value
    flag = element('UseStringDelimiter')
    if flag is not None: result['UseStringDelimiter'] = bool(flag)
    return result


def verify_csv(data, path, effective, tolerance):
    """Verify a CSV/TSV table against its input.

    `effective` holds the FieldAssociation (text), FieldDelimiter, StringDelimiter and
    UseStringDelimiter read back from the writer proxy by publish(). They are required:
    ParaView chooses the association and the .tsv delimiter itself, so no host default
    is assumed.
    """
    import csv
    reject_composite_csv(data)
    if not (data.IsA('vtkTable') or data.IsA('vtkDataSet')):
        fail('UNSUPPORTED_DATA_TYPE', 'CSV verification needs a dataset or table')
    missing=[k for k in ('FieldAssociation','FieldDelimiter','StringDelimiter','UseStringDelimiter') if k not in (effective or {})]
    if missing: fail('MISSING_EFFECTIVE_SETTINGS','CSV verification needs the settings read back from the writer',
                     'effective',missing=missing)
    association = effective['FieldAssociation']
    if association not in FIELD_ASSOCIATIONS.values():
        fail('INVALID_ASSOCIATION', 'FieldAssociation must be one of the ParaView field data domain entries',
             'FieldAssociation', association=association, supported=sorted(FIELD_ASSOCIATIONS.values()))
    if data.IsA('vtkTable'): arrays = data.GetRowData()  # tables are written directly (vtkCSVWriter.cxx:634)
    elif association == 'Cell Data': arrays = data.GetCellData()
    elif association == 'Point Data': arrays = data.GetPointData()
    else:
        fail('UNSUPPORTED_ASSOCIATION', 'CSV verification supports point, cell and row data',
             association=association, supported=list(CSV_VERIFIED_ASSOCIATIONS),
             recovery='export Point Data or Cell Data, or pass the field data through a table-producing filter first')
    # ParaView sets a tab for .tsv (vtkSMCSVProxiesInitializationHelper.cxx:25-29); the read-back value already reflects it.
    delimiter = effective['FieldDelimiter']
    if not isinstance(delimiter, str) or len(delimiter) != 1:
        fail('UNSUPPORTED_DELIMITER', 'CSV verification needs a one-character FieldDelimiter',
             'FieldDelimiter', delimiter=delimiter, recovery='use a single-character FieldDelimiter')
    use_quotes = effective['UseStringDelimiter']
    quote = effective['StringDelimiter']
    if use_quotes and isinstance(quote, str) and len(quote) == 1:
        dialect = {'quotechar': quote}
    elif use_quotes and quote:
        fail('UNSUPPORTED_DELIMITER', 'CSV verification needs a one-character StringDelimiter',
             'StringDelimiter', delimiter=quote, recovery='use a single-character StringDelimiter or disable UseStringDelimiter')
    else:
        dialect = {'quoting': csv.QUOTE_NONE}
    try:
        with Path(path).open(newline='') as stream:
            rows = list(csv.reader(stream, delimiter=delimiter, **dialect))
    except csv.Error as error:
        fail('UNSUPPORTED_DELIMITER', 'CSV delimiters cannot be parsed by the verifier', 'FieldDelimiter', reason=str(error))
    if not rows: fail('VERIFICATION_FAILED','CSV output has no header')
    headers,values=rows[0],rows[1:]
    expected_rows=arrays.GetNumberOfTuples()
    if len(values)!=expected_rows:fail('VERIFICATION_FAILED','CSV row count differs',expected=expected_rows,actual=len(values))
    verified=[]
    for index in range(arrays.GetNumberOfArrays()):
        array=arrays.GetAbstractArray(index);name=array.GetName()
        for component in range(array.GetNumberOfComponents()):
            candidates=[name] if array.GetNumberOfComponents()==1 else [name+':'+str(component),name+'_'+str(component)]
            header=next((h for h in candidates if h in headers),None)
            if header is None:fail('VERIFICATION_FAILED','CSV omitted an input column',column=name,component=component)
            col=headers.index(header)
            for row,values_row in enumerate(values):
                expected=array.GetValue(row*array.GetNumberOfComponents()+component) if array.GetDataType()==13 else array.GetComponent(row,component)
                actual=values_row[col]
                if isinstance(expected,str): equal=actual==expected
                else:
                    try: equal=numbers_equal(expected,float(actual),tolerance)
                    except ValueError: equal=False
                if not equal:fail('VERIFICATION_FAILED','CSV cell differs from input',row=row,column=header)
            verified.append(header)
    if not verified:fail('VERIFICATION_FAILED','no input columns were verified')
    return {'comparison':'table','rows':expected_rows,'verifiedColumns':verified,'additionalColumns':[h for h in headers if h not in verified],
            'association':association,'delimiter':delimiter}


def leaves(data):
    if data.IsA('vtkCompositeDataSet'):
        iterator=data.NewIterator();iterator.InitTraversal()
        while not iterator.IsDoneWithTraversal():
            value=iterator.GetCurrentDataObject()
            if value is not None:
                yield from leaves(value)
            iterator.GoToNextItem()
    else: yield data


def compare_semantic(before, after, tolerance):
    """Compare mesh geometry and every input field, allowing storage regrouping.

    Point IDs, cell connectivity ordering, duplicate block-boundary points and
    container structure are explicitly excluded by the semantic loss contract.
    """
    old,new=list(leaves(before)),list(leaves(after))
    from .data import array_record
    def global_fields(data):
        fields=data.GetFieldData()
        return [(fields.GetArrayName(i), array_record(fields.GetAbstractArray(i)))
                for i in range(fields.GetNumberOfArrays())]
    # Container regrouping must not silently discard original global metadata.
    expected=global_fields(before)+[record for d in old for record in global_fields(d)]
    actual=global_fields(after)+[record for d in new for record in global_fields(d)]
    if any(record not in actual for record in expected):
        fail('VERIFICATION_FAILED','semantic readback omitted or changed input field data')
    if any(not d.IsA('vtkDataSet') for d in old+new):
        fail('INVALID_DATA_TYPE','semantic mesh comparison needs dataset leaves')
    def field_names(datasets,association):
        names=set()
        for data in datasets:
            arrays=data.GetPointData() if association=='point' else data.GetCellData()
            names.update(arrays.GetArrayName(i) for i in range(arrays.GetNumberOfArrays()))
        return names
    def records(datasets, association, fields):
        records=[]
        for data in datasets:
            arrays=data.GetPointData() if association=='point' else data.GetCellData()
            count=data.GetNumberOfPoints() if association=='point' else data.GetNumberOfCells()
            if count==0:continue
            for field in fields:
                if arrays.GetAbstractArray(field) is None:
                    fail('VERIFICATION_FAILED','semantic readback lacks an input field',field=field)
            for index in range(count):
                if association=='point': geometry=(tuple(data.GetPoint(index)),)
                else:
                    cell=data.GetCell(index)
                    geometry=(cell.GetCellType(),tuple(sorted(tuple(data.GetPoint(cell.GetPointId(i))) for i in range(cell.GetNumberOfPoints()))))
                values=[]
                for field in sorted(fields):
                    a=arrays.GetAbstractArray(field)
                    if a.GetDataType()==13:
                        values.append(tuple(a.GetValue(index*a.GetNumberOfComponents()+c) for c in range(a.GetNumberOfComponents())))
                    elif a.GetDataTypeAsString() in ('float','double'):
                        values.append(tuple(a.GetTuple(index)))
                    else:
                        # Do not round 64-bit identifiers through GetTuple's doubles.
                        row=[]
                        for c in range(a.GetNumberOfComponents()):
                            offset=index*a.GetNumberOfComponents()+c
                            variant=a.GetVariantValue(offset)
                            row.append(variant.ToUnsignedLongLong() if a.GetDataTypeMin()>=0
                                       else variant.ToLongLong())
                        values.append(tuple(row))
                records.append((geometry,tuple(values)))
        # Block boundaries can duplicate points, but duplicate cells remain material.
        return sorted(set(records) if association=='point' else records)
    def equal(a,b):
        if isinstance(a,(tuple,list)) and isinstance(b,(tuple,list)):
            return len(a)==len(b) and all(equal(x,y) for x,y in zip(a,b))
        if isinstance(a,str) or isinstance(b,str):return a==b
        return numbers_equal(a,b,tolerance)
    counts={}
    for association in ('point','cell'):
        names=field_names(old,association)
        a,b=records(old,association,names),records(new,association,names)
        if not equal(a,b):
            fail('VERIFICATION_FAILED','semantic mesh or field values changed',association=association,
                 inputRecords=len(a),outputRecords=len(b),fields=sorted(names),tolerance=tolerance)
        counts[association]={'records':len(a),'fields':sorted(names)}
    return {'comparison':'semantic','associations':counts,'tolerance':tolerance}


def check_json_image_options(data, options, location='$'):
    """vtkJSONImageWriter does not bound-check Slice (VTK/IO/Image/vtkJSONImageWriter.cxx:108-113)."""
    slice_index = options.get('Slice', -1)
    if data.IsA('vtkImageData') and type(slice_index) is int and slice_index >= 0:
        depth = data.GetDimensions()[2]
        if slice_index >= depth:
            fail('INVALID_SLICE', 'Slice is outside the image; the writer would read past its arrays',
                 location + '.Slice', slice=slice_index, depth=depth,
                 recovery=f'choose a Slice from 0 to {depth - 1}, or -1 for the whole image')


def json_image_arrays(data, options):
    """The point arrays vtkJSONImageWriter emits (VTK/IO/Image/vtkJSONImageWriter.cxx:90-104):
    one-component arrays other than vtkValidPointMask, restricted by a non-empty ArrayName."""
    wanted = options.get('ArrayName') or ''
    arrays, selected = data.GetPointData(), []
    for index in range(arrays.GetNumberOfArrays()):
        array = arrays.GetArray(index)
        if array is None or array.GetNumberOfComponents() != 1 or array.GetName() == 'vtkValidPointMask': continue
        if wanted and array.GetName() != wanted: continue
        selected.append(array)
    return selected


def verify_json_image(data,path,tolerance,options=None):
    """Verify exactly what vtkJSONImageWriter writes for the effective ArrayName and Slice.

    Header dimensions stay full-size; with Slice k >= 0 each array holds only the
    dims[0]*dims[1] values from k*dims[0]*dims[1]; points whose vtkValidPointMask
    (a vtkCharArray, found by name) is 0 are written as null (lines 71-72, 125-132).
    """
    import json
    options = options or {}
    try: document=json.loads(Path(path).read_text())
    except ValueError as error: fail('INVALID_ARTIFACT','JSON image is not valid JSON',str(path),reason=str(error))
    if not data.IsA('vtkImageData') or document.get('dimensions')!=list(data.GetDimensions()):
        fail('VERIFICATION_FAILED','JSON image dimensions differ')
    check_json_image_options(data,options)
    for key,value in [('origin',data.GetOrigin()),('spacing',data.GetSpacing())]:
        if not numbers_equal(document.get(key),list(value),tolerance):
            fail('VERIFICATION_FAILED','JSON image coordinates differ',property=key)
    dimensions=data.GetDimensions()
    slice_index=options.get('Slice',-1)
    sliced=type(slice_index) is int and slice_index>=0
    size=dimensions[0]*dimensions[1]
    start,stop=(slice_index*size,(slice_index+1)*size) if sliced else (0,data.GetNumberOfPoints())
    mask=data.GetPointData().GetArray('vtkValidPointMask')
    if mask is not None and mask.GetDataType()!=2: mask=None  # only a vtkCharArray masks (VTK_CHAR == 2)
    verified,masked=[],0
    selected=json_image_arrays(data,options)
    present=[data.GetPointData().GetArray(i) for i in range(data.GetPointData().GetNumberOfArrays())]
    omitted=[a.GetName() for a in present if a is not None and a.GetName() not in {x.GetName() for x in selected}]
    for array in selected:
        expected=[None if mask is not None and mask.GetComponent(i,0)==0 else array.GetComponent(i,0) for i in range(start,stop)]
        actual=document.get(array.GetName())
        if (not isinstance(actual,list) or len(actual)!=len(expected)
                or any((e is None)!=(a is None) or (e is not None and not numbers_equal(a,e,tolerance))
                       for a,e in zip(actual,expected))):
            fail('VERIFICATION_FAILED','JSON image samples differ',field=array.GetName(),slice=slice_index if sliced else None)
        masked+=sum(1 for e in expected if e is None)
        verified.append(array.GetName())
    if not verified:
        fail('VERIFICATION_FAILED','JSON image has no verified numeric arrays; the writer emits only one-component '
             'arrays other than vtkValidPointMask',arrayName=options.get('ArrayName') or None)
    return {'comparison':'pixels','format':'vtk-json-image','dimensions':list(dimensions),'fields':verified,'tolerance':tolerance,
            'arrayName':options.get('ArrayName') or None,'slice':slice_index if sliced else None,'maskedPoints':masked,
            'omittedFields':omitted,'omittedSlices':(dimensions[2]-1) if sliced else 0}


def ioss_single_step_range(timesteps, time, location='$'):
    """TimeStepRange/TimeStepStride selecting exactly the scheduled input step.

    vtkIOSSWriter iterates every input time step itself and ignores the scheduled
    time (PV5.13.3:VTK/IO/IOSS/vtkIOSSWriter.cxx:285-342). A range with
    first >= last (or stride < 1) means all steps (244-246), otherwise steps
    first..min(last+1, n) by stride are written (250-257); [k, k+1] with stride 2
    therefore keeps only step k. A native pvbatch 5.13.3 probe (evidence/.../defects/probes)
    confirmed this for k = 0, 2 and 9, and that a default export writes every step.
    Returns None when the input has fewer than two steps, where nothing can escape.
    """
    steps = list(timesteps) if isinstance(timesteps, (list, tuple)) else ([] if timesteps is None else [timesteps])
    if len(steps) < 2: return None
    matches = [i for i, value in enumerate(steps) if math.isclose(value, time, rel_tol=1e-12, abs_tol=1e-12)]
    if not matches:
        fail('TIME_NOT_IN_INPUT', 'the scheduled time is not one of the input time steps', location,
             time=time, steps=steps, recovery='schedule one of the input time values')
    index = matches[0]
    return {'TimeStepRange': [index, index + 1], 'TimeStepStride': 2}


def input_time_steps(proxy):
    """Time steps the exported node advertises.

    Only readers and sources expose TimestepValues; a filter proxy has no such property
    (native pvbatch 5.13.3 probe: Tetrahedralize(TimeSource) raised AttributeError), so read
    TIME_STEPS from the node's pipeline output information in the serial builtin session.
    """
    if 'TimestepValues' in proxy.ListProperties():
        values = proxy.TimestepValues
        return list(values) if isinstance(values, (list, tuple)) or hasattr(values, '__len__') else (
            [] if values is None else [values])
    algorithm = proxy.GetClientSideObject()
    if algorithm is None: return []
    from vtkmodules.vtkCommonExecutionModel import vtkStreamingDemandDrivenPipeline as pipeline
    proxy.UpdatePipelineInformation()
    information = algorithm.GetOutputInformation(0)
    return list(information.Get(pipeline.TIME_STEPS())) if information.Has(pipeline.TIME_STEPS()) else []


def check_ioss_global_ids(data, timesteps, location, offset=False):
    """Refuse time-dependent IOSS input whose point global ids the writer would abort on.

    Native pvbatch 5.13.3 probes (2026-10-12): for time-dependent input, vtkIOSSWriter aborts the
    whole process ("node mapping routines detected non-positive global id 0") when the point
    global ids start at 0, with or without the managed time range, unless OffsetGlobalIds is on;
    with OffsetGlobalIds the managed range wrote exactly the scheduled step. Static input is
    written either way. Exodus ids start at 1.
    """
    steps = list(timesteps) if isinstance(timesteps, (list, tuple)) else ([] if timesteps is None else [timesteps])
    if len(steps) < 2: return
    leaves = []
    if data.IsA('vtkCompositeDataSet'):
        iterator = data.NewIterator(); iterator.InitTraversal()
        while not iterator.IsDoneWithTraversal():
            leaves.append(iterator.GetCurrentDataObject()); iterator.GoToNextItem()
    else:
        leaves = [data]
    for leaf in leaves:
        if not leaf.IsA('vtkDataSet') or not leaf.GetNumberOfPoints(): continue
        ids = leaf.GetPointData().GetGlobalIds()
        missing = ids is None or ids.GetNumberOfTuples() == 0
        if missing or (ids.GetRange(0)[0] < 1 and not offset):
            fail('UNSUPPORTED_INPUT', 'the IOSS writer aborts on time-dependent input without positive point global ids',
                 location, timeSteps=len(steps), globalIds=None if missing else list(ids.GetRange(0)),
                 offsetGlobalIds=offset,
                 recovery='add point global ids upstream (pvGlobalPointAndCellIds) and set OffsetGlobalIds true, '
                          'or export with pvWriteExodusIIWriter')


def apply_ioss_single_step(writer, timesteps, time, location):
    """Set the managed range on an IOSS writer proxy (both settings are Schemaxis-managed)."""
    managed = ioss_single_step_range(timesteps, time, location)
    if managed is None: return None
    for key, value in managed.items(): setattr(writer, key, value)
    return managed


_HOUDINI_NUMBER = r'[-+]?(?:\d+\.?\d*(?:[eE][-+]?\d+)?|\.\d+(?:[eE][-+]?\d+)?)'


def read_houdini(path):
    """Read the ASCII PGEOMETRY V2 produced by vtkHoudiniPolyDataWriter.

    The grammar is that of PV5.13.3:VTK/IO/Geometry/vtkHoudiniPolyDataWriter.cxx:326-554:
    four header lines (326-333); an optional PointAttrib block of "<name> <n> <float|int>
    <defaults>" lines (374-378); one "x y z 1" line per point, followed by " (<values>)"
    when the input has point arrays (383-392); an optional PrimitiveAttrib block (414-418);
    vertices as "Run n Part" plus "<k> <ids>" lines, or one "Part <k> <ids>" line (420-453);
    lines "Run n Poly" plus "<k> : <ids>" (455-481); polygons "Run n Poly" plus "<k> < <ids>"
    (483-509); each triangle strip as triangles "3 < a b c", under "Run m Poly" for m > 1
    or a single "Poly 3 < a b c" line (511-551), so NPrims counts emitted primitives (309-323);
    and the "beginExtra"/"endExtra" trailer. Every record may end in " [<cell values>]".
    Attribute values are not read; only geometry is verified. Anything else is a fault.
    """
    import re
    from vtkmodules.vtkCommonCore import vtkPoints
    from vtkmodules.vtkCommonDataModel import vtkCellArray, vtkPolyData
    lines=Path(path).read_text().splitlines()
    def malformed(message,position,**detail):
        fail('UNSUPPORTED_FORMAT',message,str(path),line=position+1,**detail)
    if not lines or lines[0]!='PGEOMETRY V2':fail('UNSUPPORTED_FORMAT','expected VTK ASCII PGEOMETRY V2',str(path))
    if len(lines)<4:fail('INVALID_ARTIFACT','PGEOMETRY header is truncated',str(path))
    header=re.fullmatch(r'NPoints (\d+) NPrims (-?\d+)',lines[1])
    if not header:fail('INVALID_ARTIFACT','PGEOMETRY header is malformed',str(path),line=2)
    points_count,cells_count=map(int,header.groups())
    if lines[2]!='NPointGroups 0 NPrimGroups 0':malformed('PGEOMETRY groups are not supported',2)
    counts=re.fullmatch(r'NPointAttrib (\d+) NVertexAttrib 0 NPrimAttrib (\d+) NAttrib 0',lines[3])
    if not counts:malformed('PGEOMETRY attribute header is not the VTK form',3)
    point_attributes,cell_attributes=map(int,counts.groups())
    position=4
    attribute_header=re.compile(r'\S+ \d+ (?:float|int)(?: \S+)+')
    def attribute_block(marker,declared):
        nonlocal position
        if not declared:return
        if position>=len(lines) or lines[position]!=marker:malformed(f'expected {marker}',position)
        position+=1
        found=0
        while position<len(lines) and attribute_header.fullmatch(lines[position]):
            position+=1;found+=1
        if found>declared:malformed(f'{marker} lists more arrays than declared',position)
    attribute_block('PointAttrib',point_attributes)
    points=vtkPoints();points.SetDataTypeToDouble()
    number=_HOUDINI_NUMBER
    point_line=re.compile(rf'({number}) ({number}) ({number}) 1'+(r' \(.*\)' if point_attributes else ''))
    for _ in range(points_count):
        match=point_line.fullmatch(lines[position]) if position<len(lines) else None
        if not match:malformed('PGEOMETRY point is malformed',min(position,len(lines)-1))
        values=list(map(float,match.groups()))
        if not all(math.isfinite(x) for x in values):malformed('PGEOMETRY point is not finite',position)
        points.InsertNextPoint(*values);position+=1
    if cell_attributes and cells_count>0:
        attribute_block('PrimitiveAttrib',cell_attributes)
    verts,segments,polys=vtkCellArray(),vtkCellArray(),vtkCellArray()
    tail=len(lines)-2
    if len(lines)<position+2 or lines[tail:]!=['beginExtra','endExtra']:
        fail('INVALID_ARTIFACT','PGEOMETRY trailer beginExtra/endExtra is missing',str(path))
    parsed=0
    def record(text,kind,at):
        """kind 'part' => 'k ids', 'line' => 'k : ids', 'poly' => 'k < ids'."""
        nonlocal parsed
        text=re.sub(r' \[.*\]$','',text) if cell_attributes else text
        pattern={'part':r'(\d+)((?: \d+)+)','line':r'(\d+) :((?: \d+)+)','poly':r'(\d+) <((?: \d+)+)'}[kind]
        match=re.fullmatch(pattern,text)
        if not match:malformed(f'PGEOMETRY {kind} record is malformed',at,record=text[:80])
        count=int(match.group(1));ids=list(map(int,match.group(2).split()))
        if len(ids)!=count or any(i>=points_count for i in ids):malformed('PGEOMETRY connectivity is malformed',at)
        array={'part':verts,'line':segments,'poly':polys}[kind]
        array.InsertNextCell(count)
        for i in ids:array.InsertCellPoint(i)
        parsed+=1
    while position<tail:
        text=lines[position]
        run=re.fullmatch(r'Run (\d+) (Part|Poly)',text)
        if run:
            number_of_records,block=int(run.group(1)),run.group(2)
            if position+1+number_of_records>tail:malformed('PGEOMETRY run is truncated',position)
            for offset in range(number_of_records):
                body=lines[position+1+offset]
                kind='part' if block=='Part' else 'line' if re.match(r'\d+ :',body) else 'poly'
                record(body,kind,position+1+offset)
            position+=1+number_of_records
        elif text.startswith('Part '):
            record(text[5:],'part',position);position+=1
        elif text.startswith('Poly '):
            record(text[5:],'poly',position);position+=1  # single-triangle strip
        else:malformed('PGEOMETRY primitive record is not part of the VTK writer grammar',position,record=text[:80])
    if parsed!=cells_count:malformed('PGEOMETRY NPrims differs from its emitted primitives',1,declared=cells_count,parsed=parsed)
    mesh=vtkPolyData();mesh.SetPoints(points);mesh.SetPolys(polys);mesh.SetVerts(verts);mesh.SetLines(segments)
    return mesh
