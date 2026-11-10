"""Curated discovery for HDF5 scientific data files (host only; never imports h5py)."""
import json
from importlib.resources import files

EXAMPLES = 'examples/schemaxis/'


def catalogue():
    return {
        'application': {
            'label': 'HDF5',
            'purpose': 'Create, inspect, extract, edit and exchange HDF5 scientific data files: typed hierarchical datasets with '
                       'units, dimension scales, compression, links, virtual datasets, mesh/field time series and SWMR acquisition, '
                       'each checked against independent expectations and an HDF Group h5dump reading.',
            'keywords': ['HDF5', 'h5py', 'hierarchical data format', '.h5', 'scientific data file', 'NetCDF-4 storage layer']},
        'searchCases': json.loads(files(__package__).joinpath('search-cases.json').read_text()),
        'groups': {
            'files': {'label': 'Write HDF5 files', 'purpose': 'Build new typed files and mesh/series outputs.', 'domain': 'scientific-data'},
            'adoption': {'label': 'Use existing HDF5 files', 'purpose': 'Inspect, audit, extract, edit and compare files you received.', 'domain': 'scientific-data'}},
        'requirements': ['parallelWrite additionally needs h5py 3.16.0 built against parallel HDF5 2.0.0 with mpi4py, and Open MPI 4.1 mpiexec.',
                         'Isolated Python with exactly h5py 3.16.0 (bundled HDF5 2.0.0) and NumPy 2.5.4 on POSIX; the host never imports them.',
                         'HDF Group h5dump 2.2.0 as the independent consumer for every verification.',
                         'Inputs, sources and dependent files are captured as immutable local bytes; originals are never modified.'],
        'references': ['docs/hdf5.md', 'src/schemaxis/adaptors/hdf5/readiness.json'],
        'operations': {
            'createFile': {
                'purpose': 'Build a new HDF5 file from declared groups, typed datasets, attributes, units, dimension scales, chunked '
                           'compression, fill values, resizable axes, links, committed datatypes, virtual datasets and external raw '
                           'storage, with values from literals, documented generators, captured CSV/NPY/raw inputs or in-file copies.',
                'groups': ['files'],
                'keywords': ['create HDF5', 'write h5', 'new dataset', 'group hierarchy', 'chunking', 'gzip', 'deflate', 'lzf', 'szip',
                             'shuffle', 'fletcher32', 'scale-offset', 'fill value', 'maxshape', 'unlimited dimension', 'resizable dataset',
                             'compound dtype', 'record array', 'enum dtype', 'variable-length string', 'vlen', 'object reference',
                             'region reference', 'complex number', 'big-endian', 'committed datatype', 'named type', 'attribute', 'units',
                             'dimension scale', 'coordinate variable', 'soft link', 'hard link', 'external link', 'virtual dataset', 'VDS',
                             'external storage', 'raw binary', 'user block', 'libver', 'file driver', 'family driver', 'split driver',
                             'core driver', 'paged aggregation', 'CSV to HDF5', 'npy to HDF5', 'alignment', 'metadata block size',
                             'large attribute', 'attribute order', 'track order', 'dense attribute storage', 'null dataspace', 'empty dataset',
                             'h5py.Empty',
                             'Unicode names', 'names with spaces'],
                'related': ['editFile', 'inspectFile', 'extractData', 'writeMeshFields'],
                'semantics': ['Every object is addressed by its absolute HDF5 path (Unicode names such as /Experiment 1/Temperature (°C) are ordinary); parent groups are created implicitly.',
                              'Values are flattened in row-major (C) order; floats are rounded once to the declared precision and out-of-range integers are refused.',
                              'Publication requires host expectations to agree with a fresh h5py readback and the HDF Group h5dump XML reading.'],
                'examples': [{'reference': EXAMPLES + 'hdf5-sensor-run.json', 'purpose': 'A calibrated sensor run using most HDF5 type and storage families.'},
                             {'reference': EXAMPLES + 'hdf5-large-attributes.json', 'purpose': 'Attributes larger than 64 KiB kept in creation order on the root, a group and a dataset.'},
                             {'reference': EXAMPLES + 'hdf5-human-names.json', 'purpose': 'Human-readable Unicode, spaced and punctuated object and field names with links, references and a quoted CSV header.'},
                             {'reference': EXAMPLES + 'hdf5-campaign.json', 'purpose': 'Stitch run files with a virtual dataset, reference raw instrument bytes and import CSV/NPY.'}]},
            'editFile': {
                'purpose': 'Apply ordered typed edits to a captured copy of an existing HDF5 file - create, delete, move, copy, link, set '
                           'or delete attributes, write selections, resize, append, make/attach/detach dimension scales and change '
                           'storage layout - optionally repacking into a fresh file to reclaim space.',
                'groups': ['adoption'],
                'keywords': ['edit HDF5', 'modify h5', 'update attribute', 'rename dataset', 'move group', 'delete dataset', 'copy dataset',
                             'append rows', 'resize dataset', 'write hyperslab', 'attach scale', 'repack', 'h5repack', 'reclaim space',
                             'change compression', 'relayout', 'fix units', 'copy chunks', 'direct chunk write', 'without recompression',
                             'edit compound field', 'update one column of a record', 'record member'],
                'related': ['inspectFile', 'createFile', 'compareFiles'],
                'semantics': ['The source is captured and never modified; the edited copy is published under a new name.',
                              'Each edit is checked against the simulated state from the independent reading of the source before native work.',
                              'Copies re-attach dimension scales: scales inside the copied tree map to their copies, others stay shared.',
                              'copyChunks writes stored chunks unchanged; fresh chunk listings must show the source bytes in the target.',
                              'write with fields changes only those compound members; the other members of each record keep their stored values.'],
                'examples': [{'reference': EXAMPLES + 'hdf5-edit.json', 'purpose': 'Annotate a vendor export: calibration attribute, corrected pixels, derived series and reorganised links.'},
                             {'reference': EXAMPLES + 'hdf5-copy-chunks.json', 'purpose': 'Mirror compressed counts into an archive dataset by copying stored chunks unchanged.'},
                             {'reference': EXAMPLES + 'hdf5-edit-fields.json', 'purpose': 'Correct individual compound members and add a null placeholder dataset.'}]},
            'inspectFile': {
                'purpose': 'Inventory an existing HDF5 file - groups, datasets, types, shapes, layouts, filters, fill values, attributes, '
                           'links, hard-link aliases, dimension scales, virtual and external storage - and decide typed expectations '
                           'such as units, shapes, ranges, finiteness and compression as met or unmet.',
                'groups': ['adoption'],
                'keywords': ['inspect HDF5', 'h5ls', 'h5dump', 'list datasets', 'file inventory', 'audit', 'check units', 'validate file',
                             'value range', 'missing values', 'NaN check', 'data quality', 'what is in this h5 file'],
                'related': ['extractData', 'compareFiles', 'editFile'],
                'semantics': ['Read-only: the captured copy is read by h5py and h5dump, which must agree before anything is reported.',
                              'Expectations are decided by the host from observed values, never by the native process.'],
                'examples': [{'reference': EXAMPLES + 'hdf5-inspect.json', 'purpose': 'Audit a vendor export against shape, unit, range and link expectations.'}]},
            'extractData': {
                'purpose': 'Read slices, strided block hyperslabs, point lists, compound fields or the rows meeting typed conditions of '
                           'datasets in an existing HDF5 file into CSV tables (with dimension-scale coordinates and units in the header), NPY '
                           'arrays or JSON for downstream tools.',
                'groups': ['adoption'],
                'keywords': ['extract dataset', 'HDF5 to CSV', 'h5 to csv', 'export array', 'npy export', 'hyperslab', 'slice', 'subset',
                             'point selection', 'compound field', 'coordinates', 'read selection', 'table handoff', 'chunk cache',
                             'memory-bounded', 'streaming export', 'larger than memory', 'parallel read', 'MPI read',
                             'filter rows', 'where', 'boolean mask', 'predicate', 'rows where', 'select by condition', 'threshold',
                             'chunk index', 'direct chunk read', 'byte offsets', 'kerchunk', 'virtualizarr', 'zarr references',
                             'sieve buffer', 'data sieving', 'contiguous partial read'],
                'related': ['inspectFile', 'createFile'],
                'semantics': ['Selections are checked against the dataset shape; expected values are selected on the host from the independent h5dump reading.',
                              'access.memoryBytes streams each extract in bounded axis-0 blocks; parallel reads blocks on MPI ranks (local workstation qualification).',
                              'CSV rows follow axis 0; remaining axes are flattened in C order into columns.',
                              'where keeps axis-0 rows meeting typed conditions; h5py and the independent reading must choose the same rows.',
                              'A chunk index is checked by decoding every listed chunk from the file bytes on the host (gzip, shuffle, Fletcher-32).'],
                'examples': [{'reference': EXAMPLES + 'hdf5-extract.json', 'purpose': 'Extract frame pixels, a time profile, a log table and the time axis.'},
                             {'reference': EXAMPLES + 'hdf5-filter-rows.json', 'purpose': 'Keep rows where a state flag, a threshold or a compound field condition holds.'},
                             {'reference': EXAMPLES + 'hdf5-chunk-index.json', 'purpose': 'Index the stored compressed chunks of a dataset for in-place references.'},
                             {'reference': EXAMPLES + 'hdf5-sieve-columns.json', 'purpose': 'Read strided columns of a contiguous grid with a larger data sieve buffer.'}]},
            'writeMeshFields': {
                'purpose': 'Write unstructured mesh points, cell connectivity and per-time-step point or cell fields to HDF5 with an XDMF 3 '
                           'temporal description that visualisation tools such as ParaView can open.',
                'groups': ['files'],
                'keywords': ['XDMF', 'mesh', 'unstructured grid', 'tetrahedra', 'hexahedra', 'field data', 'time series', 'transient results',
                             'ParaView', 'point data', 'cell data', 'heavy data', 'simulation output'],
                'related': ['createFile', 'appendSeries'],
                'semantics': ['Connectivity is zero-based point indices; degenerate cells and out-of-range indices are refused.',
                              'The report includes an independent signed-volume/area total per block as an orientation check.'],
                'examples': [{'reference': EXAMPLES + 'hdf5-mesh-fields.json', 'purpose': 'A cooling block with temperature and heat flux over three times.'}]},
            'appendSeries': {
                'purpose': 'Append batches of sample rows to an unlimited chunked dataset in single-writer/multiple-reader (SWMR) mode while '
                           'concurrent reader processes observe each flushed batch, for live acquisition and monitoring.',
                'groups': ['files'],
                'keywords': ['SWMR', 'single writer multiple reader', 'live acquisition', 'streaming append', 'data logger', 'monitor',
                             'concurrent read', 'flush', 'growing dataset', 'time series append'],
                'related': ['editFile', 'createFile'],
                'semantics': ['Files are written with libver latest (HDF5 1.10+ readers); structure cannot change after SWMR starts.',
                              'Every reader observation must equal the independently computed flushed prefix.'],
                'examples': [{'reference': EXAMPLES + 'hdf5-swmr-monitor.json', 'purpose': 'Three batches of a three-channel probe observed by two readers.'}]},
            'parallelWrite': {
                'purpose': 'Write integer or float datasets from several MPI ranks at once through parallel HDF5 (the mpio driver), each rank '
                           'writing its block of axis-0 rows with collective or independent I/O, then reduce the file in parallel and verify it serially.',
                'groups': ['files'],
                'keywords': ['MPI', 'MPI-IO', 'parallel HDF5', 'mpio', 'mpi4py', 'collective I/O', 'independent I/O', 'domain decomposition',
                             'parallel write', 'ranks', 'multi-process write'],
                'related': ['createFile', 'appendSeries'],
                'semantics': ['Needs a separately built parallel h5py (HDF5_MPI=ON) and mpiexec from configuration; the serial wheel cannot do MPI-IO. '
                              'Qualified on one local workstation only (Open MPI 4.1.7, 2-3 ranks, launched on localhost), not on a cluster.',
                              'Rank r writes rows [r*n/R, (r+1)*n/R); every rank receipt, the serial readback, h5dump and a parallel reduction must agree.'],
                'examples': [{'reference': EXAMPLES + 'hdf5-parallel-write.json', 'purpose': 'Two ranks write a compressed temperature field and cell ids collectively.'}]},
            'compareFiles': {
                'purpose': 'Compare two HDF5 files object by object - presence, kinds, types, shapes, attributes, optional storage and numeric '
                           'values within absolute and relative tolerances - as a regression check (h5diff semantics).',
                'groups': ['adoption'],
                'keywords': ['compare HDF5', 'h5diff', 'diff', 'regression test', 'tolerance', 'numerical difference', 'same results'],
                'related': ['inspectFile', 'editFile'],
                'semantics': ['A value differs when |a-b| > absolute + relative*|reference|; NaN equals NaN.',
                              'The native comparison must agree with an independent host comparison of the h5dump readings.'],
                'examples': [{'reference': EXAMPLES + 'hdf5-compare.json', 'purpose': 'Compare two run files with an absolute tolerance.'}]},
        },
    }
