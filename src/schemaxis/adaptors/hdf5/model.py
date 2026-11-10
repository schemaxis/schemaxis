"""Typed HDF5 records and host-only semantic planning; never imports h5py or NumPy.

The document is flat and path-addressed: every group, dataset, committed datatype, link,
attribute, edit and extraction names its absolute HDF5 path. Records are closed objects with
an explicit discriminator (``class``, ``source``, ``kind``, ``action``) so that Studio forms
expose nested choices and the planner can locate every cross-field fault precisely.
"""
import math
import re
import unicodedata
from pathlib import PurePosixPath

from schemaxis.core.declarations import validate_arguments
from schemaxis.errors import fail, keys

VERSION = 'schemaxis.hdf5/1'
OPERATIONS = ('createFile', 'editFile', 'inspectFile', 'extractData', 'writeMeshFields', 'appendSeries', 'compareFiles', 'parallelWrite')
LIBVER = ('earliest', 'v108', 'v110', 'v112', 'v114', 'v200', 'latest')
MAX_OBJECTS = 256
MAX_ATTRIBUTES = 64
MAX_EDITS = 128
MAX_EXTRACTS = 32
MAX_RANK = 8
MAX_DIM = 2 ** 31
MAX_ELEMENTS = 4 * 1024 * 1024
MAX_TOTAL_ELEMENTS = 16 * 1024 * 1024
MAX_INLINE = 65536
MAX_INPUT_BYTES = 64 * 1024 * 1024
MAX_SOURCE_BYTES = 512 * 1024 * 1024
MAX_STRING = 65535
NAME = re.compile(r'[A-Za-z0-9_][A-Za-z0-9_.+\-]{0,63}')
IDENT = re.compile(r'[a-z][a-zA-Z0-9_]{0,39}')
HEX = re.compile(r'[0-9a-f]{64}')
FILE_NAME = re.compile(r'[A-Za-z0-9_][A-Za-z0-9_.\-]{0,63}\.(h5|hdf5|he5|nc|bin|raw|dat)')
RESERVED_ATTRIBUTES = ('CLASS', 'NAME', 'REFERENCE_LIST', 'DIMENSION_LIST', 'DIMENSION_LABELS', '_Netcdf4Dimid', '_Netcdf4Coordinates')

STR = {'type': 'string', 'minLength': 1, 'maxLength': 1024}
PATH = {'type': 'string', 'minLength': 1, 'maxLength': 1024}
ABSOLUTE = {'type': 'string', 'minLength': 1, 'maxLength': 4096}
SHA = {'type': 'string', 'minLength': 64, 'maxLength': 64}
INT = {'type': 'integer', 'minimum': 0, 'maximum': MAX_DIM}
INDEX = {'type': 'integer', 'minimum': -MAX_DIM, 'maximum': MAX_DIM}
INTS = {'type': 'array', 'items': INT, 'maxItems': MAX_RANK}
SCALAR = {'type': 'union', 'options': [{'type': 'number'}, {'type': 'string', 'maxLength': MAX_STRING}, {'type': 'boolean'}]}
ELEMENT = {'type': 'union', 'options': [*SCALAR['options'], {'type': 'array', 'maxItems': MAX_INLINE, 'items': {'type': 'union', 'options': [
    *SCALAR['options'], {'type': 'array', 'maxItems': MAX_INLINE, 'items': SCALAR}]}}]}
VALUES = {'type': 'array', 'items': ELEMENT, 'maxItems': MAX_INLINE}
VALUE = {'type': 'union', 'options': [*SCALAR['options'], VALUES]}

MEMBER = {'type': 'object', 'properties': {'name': {**STR, 'maxLength': 64, 'required': True},
                                           'value': {'type': 'integer', 'minimum': -2 ** 63, 'maximum': 2 ** 64 - 1, 'required': True}}}
SCALAR_TYPE = {'type': 'object', 'properties': {
    'class': {'type': 'enum', 'values': ['float', 'int', 'uint', 'complex', 'bool', 'string', 'enum'], 'required': True},
    'bits': {'type': 'enum', 'values': [8, 16, 32, 64, 128]},
    'order': {'type': 'enum', 'values': ['little', 'big'], 'default': 'little'},
    'length': {'type': 'integer', 'minimum': 1, 'maximum': MAX_STRING},
    'encoding': {'type': 'enum', 'values': ['utf-8', 'ascii'], 'default': 'utf-8'},
    'signed': {'type': 'boolean', 'default': False},
    'members': {'type': 'array', 'items': MEMBER, 'minItems': 1, 'maxItems': 256},
    'dims': {'type': 'array', 'items': {'type': 'integer', 'minimum': 1, 'maximum': 4096}, 'minItems': 1, 'maxItems': 4}}}
FIELD = {'type': 'object', 'properties': {'name': {**STR, 'maxLength': 64, 'required': True}, 'type': {**SCALAR_TYPE, 'required': True},
                                          'units': {**STR, 'maxLength': 64}}}
TYPE = {'type': 'object', 'properties': {
    **{k: v for k, v in SCALAR_TYPE['properties'].items() if k != 'class'},
    'class': {'type': 'enum', 'values': ['float', 'int', 'uint', 'complex', 'bool', 'string', 'enum', 'compound', 'vlen',
                                         'reference', 'opaque', 'named'], 'required': True},
    'fields': {'type': 'array', 'items': FIELD, 'minItems': 1, 'maxItems': 64},
    'base': SCALAR_TYPE,
    'reference': {'type': 'enum', 'values': ['object', 'region'], 'default': 'object'},
    'size': {'type': 'integer', 'minimum': 1, 'maximum': 4096},
    'path': PATH}}
SELECTION_SLICE = {'type': 'object', 'properties': {'start': INDEX, 'stop': INDEX, 'step': {'type': 'integer', 'minimum': 1, 'maximum': MAX_DIM}}}
SELECTION = {'type': 'object', 'properties': {
    'kind': {'type': 'enum', 'values': ['all', 'slices', 'hyperslab', 'points'], 'required': True},
    'slices': {'type': 'array', 'items': SELECTION_SLICE, 'minItems': 1, 'maxItems': MAX_RANK},
    'start': INTS, 'count': INTS, 'stride': INTS, 'block': INTS,
    'points': {'type': 'array', 'items': INTS, 'minItems': 1, 'maxItems': 65536}}}
TARGET = {'type': 'object', 'properties': {'path': {**PATH, 'required': True}, 'selection': SELECTION}}
DATA = {'type': 'object', 'properties': {
    'source': {'type': 'enum', 'values': ['values', 'fill', 'range', 'linspace', 'input', 'references', 'copy'], 'required': True},
    'values': VALUES,
    'start': {'type': 'number'}, 'step': {'type': 'number'}, 'stop': {'type': 'number'},
    'input': {'type': 'string', 'minLength': 1, 'maxLength': 40},
    'column': {**STR, 'maxLength': 64},
    'columns': {'type': 'array', 'items': {**STR, 'maxLength': 64}, 'minItems': 1, 'maxItems': 64},
    'targets': {'type': 'array', 'items': TARGET, 'minItems': 1, 'maxItems': 4096},
    'dataset': PATH}}
EXTERNAL = {'type': 'object', 'properties': {'file': {**STR, 'maxLength': 64, 'required': True},
    'offset': {'type': 'integer', 'minimum': 0, 'maximum': 2 ** 40, 'default': 0},
    'size': {'type': 'integer', 'minimum': 1, 'maximum': 2 ** 40, 'required': True}}}
STORAGE = {'type': 'object', 'properties': {
    'layout': {'type': 'enum', 'values': ['contiguous', 'chunked', 'compact', 'external', 'virtual']},
    'chunks': {'type': 'union', 'options': [{'type': 'enum', 'values': ['auto']}, {'type': 'array', 'items': {'type': 'integer', 'minimum': 1, 'maximum': MAX_DIM}, 'minItems': 1, 'maxItems': MAX_RANK}]},
    'compression': {'type': 'enum', 'values': ['none', 'gzip', 'lzf', 'szip'], 'default': 'none'},
    'level': {'type': 'integer', 'minimum': 0, 'maximum': 9},
    'szipMethod': {'type': 'enum', 'values': ['nn', 'ec']},
    'szipPixels': {'type': 'integer', 'minimum': 2, 'maximum': 32},
    'shuffle': {'type': 'boolean', 'default': False},
    'fletcher32': {'type': 'boolean', 'default': False},
    'scaleOffset': {'type': 'integer', 'minimum': 0, 'maximum': 32},
    'nbit': {'type': 'boolean', 'default': False},
    'fillValue': SCALAR,
    'fillTime': {'type': 'enum', 'values': ['ifSet', 'alloc', 'never']},
    'allocTime': {'type': 'enum', 'values': ['early', 'incremental', 'late']},
    'external': {'type': 'array', 'items': EXTERNAL, 'minItems': 1, 'maxItems': 16},
    'trackTimes': {'type': 'boolean', 'default': False}}}
VSOURCE = {'type': 'object', 'properties': {'file': {'type': 'string', 'minLength': 1, 'maxLength': 40, 'default': '.'},
    'dataset': {**PATH, 'required': True}, 'select': SELECTION, 'at': SELECTION}}
VIRTUAL = {'type': 'object', 'properties': {'sources': {'type': 'array', 'items': VSOURCE, 'minItems': 1, 'maxItems': 256, 'required': True},
                                            'fill': SCALAR}}
GENERATED = {'type': 'object', 'properties': {'source': {'type': 'enum', 'values': ['range', 'linspace'], 'required': True},
    'start': {'type': 'number'}, 'step': {'type': 'number'}, 'stop': {'type': 'number'}}}
ATTRIBUTE = {'type': 'object', 'properties': {'name': {**STR, 'maxLength': 255, 'required': True}, 'type': TYPE,
    'value': VALUE, 'data': GENERATED, 'shape': INTS, 'empty': {'type': 'boolean', 'default': False}}}
DIMENSION = {'type': 'object', 'properties': {'axis': {'type': 'integer', 'minimum': 0, 'maximum': MAX_RANK - 1, 'required': True},
    'label': {'type': 'string', 'minLength': 0, 'maxLength': 255},
    'scales': {'type': 'array', 'items': PATH, 'maxItems': 8, 'default': []}}}
OBJECT = {'type': 'object', 'properties': {
    'path': {**PATH, 'required': True},
    'kind': {'type': 'enum', 'values': ['dataset', 'group', 'datatype'], 'default': 'dataset'},
    'type': TYPE, 'shape': INTS,
    'maxshape': {'type': 'array', 'items': {'type': 'union', 'options': [INT, {'type': 'enum', 'values': ['unlimited']}]}, 'maxItems': MAX_RANK},
    'data': DATA, 'storage': STORAGE, 'virtual': VIRTUAL,
    'attributes': {'type': 'array', 'items': ATTRIBUTE, 'maxItems': MAX_ATTRIBUTES, 'default': []},
    'units': {'type': 'string', 'minLength': 1, 'maxLength': 64},
    'scale': {'type': 'string', 'minLength': 0, 'maxLength': 255},
    'dimensions': {'type': 'array', 'items': DIMENSION, 'maxItems': MAX_RANK, 'default': []},
    'trackOrder': {'type': 'boolean'}, 'empty': {'type': 'boolean'}}}
LINK = {'type': 'object', 'properties': {'path': {**PATH, 'required': True},
    'kind': {'type': 'enum', 'values': ['soft', 'hard', 'external'], 'required': True},
    'target': {**PATH, 'required': True}, 'file': {'type': 'string', 'minLength': 1, 'maxLength': 64}}}
INPUT = {'type': 'object', 'properties': {'id': {'type': 'string', 'minLength': 1, 'maxLength': 40, 'required': True},
    'path': {**ABSOLUTE, 'required': True}, 'format': {'type': 'enum', 'values': ['csv', 'npy', 'raw'], 'required': True},
    'sha256': SHA, 'type': SCALAR_TYPE, 'shape': INTS, 'offset': {'type': 'integer', 'minimum': 0, 'maximum': MAX_INPUT_BYTES, 'default': 0},
    'delimiter': {'type': 'enum', 'values': [',', ';', 'tab'], 'default': ','}}}
DEPENDENCY = {'type': 'object', 'properties': {'id': {'type': 'string', 'minLength': 1, 'maxLength': 40, 'required': True},
    'path': {**ABSOLUTE, 'required': True}, 'sha256': SHA,
    'role': {'type': 'enum', 'values': ['virtualSource', 'externalLink', 'rawStorage', 'copySource', 'reference'], 'required': True},
    'name': {'type': 'string', 'minLength': 1, 'maxLength': 64}}}
FILE = {'type': 'object', 'properties': {'name': {'type': 'string', 'minLength': 1, 'maxLength': 64, 'default': 'data.h5'},
    'libver': {'type': 'enum', 'values': list(LIBVER), 'default': 'earliest'},
    'libverHigh': {'type': 'enum', 'values': list(LIBVER), 'default': 'latest'},
    'userblock': {'type': 'integer', 'minimum': 0, 'maximum': 2 ** 20, 'default': 0},
    'trackOrder': {'type': 'boolean', 'default': False},
    'driver': {'type': 'enum', 'values': ['sec2', 'stdio', 'core', 'family', 'split'], 'default': 'sec2'},
    'memberBytes': {'type': 'integer', 'minimum': 4096, 'maximum': 2 ** 31},
    'spaceStrategy': {'type': 'enum', 'values': ['default', 'fsm', 'page', 'aggregate', 'none'], 'default': 'default'},
    'pageBytes': {'type': 'integer', 'minimum': 512, 'maximum': 2 ** 24},
    'attributes': {'type': 'array', 'items': ATTRIBUTE, 'maxItems': MAX_ATTRIBUTES, 'default': []}}}
WHERE_OPS = ('eq', 'ne', 'lt', 'le', 'gt', 'ge', 'between', 'in', 'finite', 'nan')
CONDITION = {'type': 'object', 'properties': {
    'dataset': PATH, 'field': {**STR, 'maxLength': 64},
    'op': {'type': 'enum', 'values': list(WHERE_OPS), 'required': True},
    'value': SCALAR, 'upper': {'type': 'number'},
    'values': {'type': 'array', 'items': SCALAR, 'minItems': 1, 'maxItems': 256}}}
EXTRACT = {'type': 'object', 'properties': {'id': {'type': 'string', 'minLength': 1, 'maxLength': 40, 'required': True},
    'dataset': {**PATH, 'required': True}, 'selection': SELECTION,
    'fields': {'type': 'array', 'items': {**STR, 'maxLength': 64}, 'minItems': 1, 'maxItems': 64},
    'format': {'type': 'enum', 'values': ['csv', 'npy', 'json', 'chunks'], 'default': 'csv'},
    'coordinates': {'type': 'boolean', 'default': True},
    'header': {'type': 'enum', 'values': ['units', 'names'], 'default': 'units'},
    'columns': {'type': 'array', 'items': {**STR, 'maxLength': 64}, 'minItems': 1, 'maxItems': 4096},
    'where': {'type': 'array', 'items': CONDITION, 'minItems': 1, 'maxItems': 8}}}
EXPECT = {'type': 'object', 'properties': {'id': {'type': 'string', 'minLength': 1, 'maxLength': 40, 'required': True},
    'path': {**PATH, 'required': True},
    'present': {'type': 'boolean', 'default': True},
    'kind': {'type': 'enum', 'values': ['group', 'dataset', 'datatype', 'softLink', 'externalLink']},
    'class': {'type': 'enum', 'values': TYPE['properties']['class']['values'][:-1]},
    'bits': {'type': 'enum', 'values': [8, 16, 32, 64, 128]},
    'shape': INTS, 'units': {'type': 'string', 'minLength': 1, 'maxLength': 64},
    'attribute': {'type': 'string', 'minLength': 1, 'maxLength': 255}, 'value': VALUE,
    'minimum': {'type': 'number'}, 'maximum': {'type': 'number'}, 'finite': {'type': 'boolean'},
    'compression': {'type': 'enum', 'values': ['none', 'gzip', 'lzf', 'szip']},
    'minCompressionRatio': {'type': 'number', 'minimum': 0, 'exclusiveMinimum': True, 'maximum': 1000000},
    'maxAllocatedBytes': {'type': 'integer', 'minimum': 0, 'maximum': 2 ** 50}}}
EDIT = {'type': 'object', 'properties': {
    'action': {'type': 'enum', 'values': ['create', 'delete', 'move', 'copy', 'link', 'setAttribute', 'deleteAttribute', 'renameAttribute', 'write',
                                          'resize', 'append', 'makeScale', 'attachScale', 'detachScale', 'relayout', 'copyChunks'], 'required': True},
    'path': PATH, 'to': PATH, 'object': OBJECT, 'link': LINK, 'attribute': ATTRIBUTE, 'name': {'type': 'string', 'minLength': 1, 'maxLength': 255},
    'newName': {'type': 'string', 'minLength': 1, 'maxLength': 255},
    'selection': SELECTION, 'data': DATA, 'shape': INTS, 'axis': {'type': 'integer', 'minimum': 0, 'maximum': MAX_RANK - 1},
    'scale': PATH, 'storage': STORAGE, 'from': {'type': 'string', 'minLength': 1, 'maxLength': 40},
    'shallow': {'type': 'boolean', 'default': False}, 'withoutAttributes': {'type': 'boolean', 'default': False},
    'expandSoft': {'type': 'boolean', 'default': False}, 'expandExternal': {'type': 'boolean', 'default': False},
    'expandReferences': {'type': 'boolean', 'default': False},
    'fields': {'type': 'array', 'items': {**STR, 'maxLength': 64}, 'minItems': 1, 'maxItems': 64}}}
POINTS_CELLS = ['vertex', 'line', 'triangle', 'quadrilateral', 'tetrahedron', 'pyramid', 'wedge', 'hexahedron']
CELLS = {'type': 'object', 'properties': {'type': {'type': 'enum', 'values': POINTS_CELLS, 'required': True},
    'connectivity': {**DATA, 'required': True}, 'name': {'type': 'string', 'minLength': 1, 'maxLength': 64},
    'count': {'type': 'integer', 'minimum': 1, 'maximum': MAX_ELEMENTS}}}
MESH = {'type': 'object', 'properties': {'points': {**DATA, 'required': True}, 'dimension': {'type': 'enum', 'values': [2, 3], 'default': 3},
    'pointCount': {'type': 'integer', 'minimum': 1, 'maximum': MAX_ELEMENTS},
    'cells': {'type': 'array', 'items': CELLS, 'minItems': 1, 'maxItems': 8, 'required': True},
    'units': {'type': 'string', 'minLength': 1, 'maxLength': 64, 'default': 'm'}}}
MESH_FIELD = {'type': 'object', 'properties': {'name': {**STR, 'maxLength': 64, 'required': True},
    'association': {'type': 'enum', 'values': ['point', 'cell'], 'required': True},
    'components': {'type': 'enum', 'values': [1, 3, 6, 9], 'default': 1},
    'units': {'type': 'string', 'minLength': 1, 'maxLength': 64, 'required': True},
    'type': SCALAR_TYPE,
    'steps': {'type': 'array', 'items': DATA, 'minItems': 1, 'maxItems': 256, 'required': True}}}
SERIES = {'type': 'object', 'properties': {'dataset': {**PATH, 'required': True}, 'type': SCALAR_TYPE,
    'width': {'type': 'integer', 'minimum': 1, 'maximum': 4096, 'default': 1},
    'units': {'type': 'string', 'minLength': 1, 'maxLength': 64}, 'chunkRows': {'type': 'integer', 'minimum': 1, 'maximum': 1048576, 'default': 64},
    'compression': {'type': 'enum', 'values': ['none', 'gzip', 'lzf'], 'default': 'none'}}}
COMPARE = {'type': 'object', 'properties': {'absolute': {'type': 'number', 'minimum': 0, 'default': 0},
    'relative': {'type': 'number', 'minimum': 0, 'default': 0},
    'paths': {'type': 'array', 'items': PATH, 'maxItems': 256},
    'attributes': {'type': 'boolean', 'default': True}, 'storage': {'type': 'boolean', 'default': False}}}

ACCESS = {'type': 'object', 'properties': {
    'chunkCache': {'type': 'object', 'properties': {'bytes': {'type': 'integer', 'minimum': 0, 'maximum': 2 ** 30, 'required': True},
                                                    'slots': {'type': 'integer', 'minimum': 1, 'maximum': 16777213, 'default': 12421},
                                                    'preemption': {'type': 'number', 'minimum': 0, 'maximum': 1, 'default': 0.75}}},
    'pageBufferBytes': {'type': 'integer', 'minimum': 512, 'maximum': 2 ** 30},
    'metaBlockBytes': {'type': 'integer', 'minimum': 512, 'maximum': 2 ** 24},
    'alignment': {'type': 'object', 'properties': {'threshold': {'type': 'integer', 'minimum': 0, 'maximum': 2 ** 31, 'default': 1},
                                                   'interval': {'type': 'integer', 'minimum': 1, 'maximum': 2 ** 24, 'required': True}}},
    'memoryBytes': {'type': 'integer', 'minimum': 4096, 'maximum': 2 ** 30},
    'sieveBufferBytes': {'type': 'integer', 'minimum': 512, 'maximum': 2 ** 28}}}
PARALLEL_READ = {'type': 'object', 'properties': {'ranks': {'type': 'integer', 'minimum': 2, 'maximum': 4, 'default': 2},
                                                  'io': {'type': 'enum', 'values': ['collective', 'independent'], 'default': 'collective'}}}
SOURCE = {'source': {**ABSOLUTE, 'required': True}, 'sha256': SHA}
COMMON = {'inputs': {'type': 'array', 'items': INPUT, 'maxItems': 32, 'default': []},
          'dependencies': {'type': 'array', 'items': DEPENDENCY, 'maxItems': 64, 'default': []}}
EXTRACTS = {'type': 'array', 'items': EXTRACT, 'maxItems': MAX_EXTRACTS, 'default': []}
OPTIONS = {
    'createFile': {'file': FILE, **COMMON, 'objects': {'type': 'array', 'items': OBJECT, 'minItems': 1, 'maxItems': MAX_OBJECTS, 'required': True},
                   'links': {'type': 'array', 'items': LINK, 'maxItems': MAX_OBJECTS, 'default': []}, 'extracts': EXTRACTS},
    'editFile': {**SOURCE, 'file': FILE, **COMMON, 'edits': {'type': 'array', 'items': EDIT, 'minItems': 1, 'maxItems': MAX_EDITS, 'required': True},
                 'repack': {'type': 'boolean', 'default': False}, 'extracts': EXTRACTS},
    'inspectFile': {**SOURCE, 'dependencies': COMMON['dependencies'],
                    'expectations': {'type': 'array', 'items': EXPECT, 'maxItems': 256, 'default': []},
                    'preview': {'type': 'integer', 'minimum': 0, 'maximum': 256, 'default': 8}},
    'extractData': {**SOURCE, 'dependencies': COMMON['dependencies'],
                    'extracts': {**{k: v for k, v in EXTRACTS.items() if k != 'default'}, 'minItems': 1, 'required': True}},
    'writeMeshFields': {'file': FILE, **COMMON, 'mesh': {**MESH, 'required': True},
                        'fields': {'type': 'array', 'items': MESH_FIELD, 'maxItems': 32, 'default': []},
                        'times': {'type': 'array', 'items': {'type': 'number'}, 'minItems': 1, 'maxItems': 256, 'required': True},
                        'timeUnits': {'type': 'string', 'minLength': 1, 'maxLength': 32, 'default': 's'},
                        'storage': STORAGE},
    'appendSeries': {'file': FILE, **COMMON, 'series': {**SERIES, 'required': True},
                     'batches': {'type': 'array', 'items': DATA, 'minItems': 1, 'maxItems': 64, 'required': True},
                     'swmr': {'type': 'boolean', 'default': True},
                     'readers': {'type': 'integer', 'minimum': 0, 'maximum': 2, 'default': 1}},
    'parallelWrite': {'file': FILE, 'objects': {'type': 'array', 'items': OBJECT, 'minItems': 1, 'maxItems': 32, 'required': True},
                      'ranks': {'type': 'integer', 'minimum': 2, 'maximum': 4, 'default': 2},
                      'io': {'type': 'enum', 'values': ['collective', 'independent'], 'default': 'collective'},
                      'reduce': {'type': 'boolean', 'default': True}},
    'compareFiles': {**SOURCE, 'reference': {**ABSOLUTE, 'required': True}, 'referenceSha256': SHA,
                     'dependencies': COMMON['dependencies'], 'tolerance': COMPARE},
}
NATIVE = {
    'createFile': 'h5py.File(w, libver, userblock_size, track_order, driver) / create_group / create_dataset(dtype, shape, maxshape, chunks, compression, shuffle, fletcher32, scaleoffset, fillvalue, external) / VirtualLayout / attrs.create / dims / SoftLink / ExternalLink',
    'editFile': 'h5py.File(r+) on a captured copy: create/__delitem__/move/copy/attrs/__setitem__ selection writes/resize/dims.attach_scale/make_scale; optional full copy repack',
    'inspectFile': 'h5py.File(r) visititems_links / Dataset.dtype, shape, maxshape, chunks, filters, fillvalue, external, virtual_sources / attrs / dims / h5r dereference',
    'extractData': 'Dataset[selection] (slices, MultiBlockSlice hyperslabs, point lists, field names) with dimension-scale coordinates',
    'writeMeshFields': 'h5py create_dataset for points, connectivity and per-step fields + XDMF 3 XML describing the HDF5 heavy data',
    'appendSeries': 'h5py.File(libver=latest).swmr_mode / Dataset.resize / flush; concurrent reader File(swmr=True) / refresh',
    'parallelWrite': 'mpiexec -n RANKS python: h5py.File(w, driver=mpio, comm=MPI.COMM_WORLD) / collective create_dataset / per-rank axis-0 partition writes (collective or independent) / MPI allreduce read',
    'compareFiles': 'h5py.File(r) pairwise structure, attribute and value comparison with absolute/relative tolerance (h5diff semantics)',
}
KINDS = {'createFile': ['file', 'text', 'table'], 'editFile': ['file', 'text', 'table'], 'inspectFile': ['text'], 'extractData': ['table', 'file', 'text'],
         'writeMeshFields': ['file', 'text'], 'appendSeries': ['file', 'text', 'table'], 'compareFiles': ['text'], 'parallelWrite': ['file', 'text']}
for _name in OPTIONS:
    OPTIONS[_name]['access'] = ACCESS
OPTIONS['extractData']['parallel'] = PARALLEL_READ
DECLARATIONS = {name: {'native': NATIVE[name], 'kinds': KINDS[name], 'inputs': {},
                       'options': {k: {'value': v} for k, v in OPTIONS[name].items()}} for name in OPERATIONS}
ROOT_KEYS = ('version', 'operation', *sorted(set().union(*OPTIONS.values())))


# ------------------------------------------------------------------ paths and names
def object_path(value, at, root=False):
    if not isinstance(value, str) or not value.startswith('/') or value.endswith('/') and value != '/' or '//' in value:
        fail('INVALID_HDF5_PATH', 'use an absolute HDF5 path such as /run/raw/counts (no trailing or doubled /)', at, value=str(value)[:120])
    if value == '/':
        if not root:
            fail('INVALID_HDF5_PATH', 'the root group cannot be created, moved or deleted', at)
        return value
    parts = value[1:].split('/')
    if len(parts) > 16:
        fail('INVALID_HDF5_PATH', 'nest at most 16 levels', at)
    for part in parts:
        segment_name(part, at)
    return value


def segment_name(part, at):
    """One HDF5 link name: Unicode text without / NUL or other control characters, not . or .., at most 255 UTF-8 bytes."""
    if part in ('.', '..'):
        fail('INVALID_HDF5_PATH', 'path segments . and .. are relative references, not names', at, segment=part)
    bad = [c for c in part if unicodedata.category(c) in ('Cc', 'Cs')]
    if bad:
        fail('INVALID_HDF5_PATH', 'path segments are Unicode text without control characters', at, segment=part[:64], character='U+%04X' % ord(bad[0]))
    if len(part.encode('utf-8')) > 255:
        fail('INVALID_HDF5_PATH', 'each path segment is at most 255 UTF-8 bytes', at, segment=part[:64])
    return part


def parent(path):
    return str(PurePosixPath(path).parent)


def ancestors(path):
    result, current = [], parent(path)
    while current != '/':
        result.append(current)
        current = parent(current)
    return result


def identifier(value, at, code='INVALID_HDF5_IDENTIFIER'):
    if not IDENT.fullmatch(value):
        fail(code, 'use a lower-case-initial ASCII identifier of up to 40 letters, digits or underscores', at, value=value[:64])


# ------------------------------------------------------------------ types
INT_BITS = (8, 16, 32, 64)
FLOAT_BITS = (16, 32, 64)


def scalar_type(t, at, *, field=False):
    cls = t['class']
    if cls in ('int', 'uint'):
        bits = t.get('bits', 64 if cls == 'int' else 64)
        if bits not in INT_BITS:
            fail('INVALID_HDF5_TYPE', 'integer types have 8, 16, 32 or 64 bits', at + '.bits')
        result = {'class': cls, 'bits': bits, 'order': t['order']}
    elif cls == 'float':
        bits = t.get('bits', 64)
        if bits not in FLOAT_BITS:
            fail('INVALID_HDF5_TYPE', 'floating-point types have 16, 32 or 64 bits', at + '.bits')
        result = {'class': cls, 'bits': bits, 'order': t['order']}
    elif cls == 'complex':
        bits = t.get('bits', 128)
        if bits not in (64, 128):
            fail('INVALID_HDF5_TYPE', 'complex types have 64 (two float32) or 128 (two float64) bits', at + '.bits')
        result = {'class': cls, 'bits': bits, 'order': t['order']}
    elif cls == 'bool':
        result = {'class': 'bool'}
    elif cls == 'string':
        result = {'class': 'string', 'encoding': t['encoding'], **({'length': t['length']} if 'length' in t else {})}
    elif cls == 'enum':
        bits = t.get('bits', 8)
        if bits not in INT_BITS:
            fail('INVALID_HDF5_TYPE', 'enum base integers have 8, 16, 32 or 64 bits', at + '.bits')
        members = t.get('members')
        if not members:
            fail('INVALID_HDF5_TYPE', 'an enum type declares its named members', at + '.members')
        names, codes = set(), set()
        low, high = (-(2 ** (bits - 1)), 2 ** (bits - 1) - 1) if t['signed'] else (0, 2 ** bits - 1)
        for i, member in enumerate(members):
            if not re.fullmatch(r'[A-Za-z_][A-Za-z0-9_]{0,63}', member['name']) or member['name'] in names:
                fail('INVALID_HDF5_TYPE', 'enum member names are unique identifiers', f'{at}.members[{i}].name')
            if member['value'] in codes or not low <= member['value'] <= high:
                fail('INVALID_HDF5_TYPE', 'enum codes are unique and fit the base integer', f'{at}.members[{i}].value', low=low, high=high)
            names.add(member['name']); codes.add(member['value'])
        result = {'class': 'enum', 'bits': bits, 'signed': t['signed'], 'order': t['order'], 'members': [dict(m) for m in members]}
    else:
        fail('INVALID_HDF5_TYPE', 'this position accepts a numeric, bool, string or enum type', at + '.class')
    if 'dims' in t:
        if not field:
            fail('INVALID_HDF5_TYPE', 'dims is allowed only on compound fields and array bases', at + '.dims')
        result['dims'] = list(t['dims'])
    explicit = {'bits', 'length', 'members', 'dims', 'fields', 'base', 'size', 'path'}
    applicable = {'int': {'bits'}, 'uint': {'bits'}, 'float': {'bits'}, 'complex': {'bits'}, 'bool': set(), 'string': {'length'},
                  'enum': {'bits', 'members'}}[cls] | {'dims'}
    for key in sorted((set(t) & explicit) - applicable):
        fail('INVALID_HDF5_TYPE', key + ' does not apply to class ' + cls, at + '.' + key)
    return result


def data_type(t, at, named=None):
    cls = t['class']
    if cls == 'compound':
        fields = t.get('fields')
        if not fields:
            fail('INVALID_HDF5_TYPE', 'a compound type declares fields', at + '.fields')
        names = set()
        out = []
        for i, f in enumerate(fields):
            if f['name'] in names or f['name'].strip() != f['name'] or any(unicodedata.category(c) in ('Cc', 'Cs') for c in f['name']):
                fail('INVALID_HDF5_TYPE', 'compound field names are unique nonblank text without control characters or surrounding spaces',
                     f'{at}.fields[{i}].name')
            names.add(f['name'])
            out.append({'name': f['name'], 'type': scalar_type(f['type'], f'{at}.fields[{i}].type', field=True),
                        **({'units': f['units']} if 'units' in f else {})})
        return {'class': 'compound', 'fields': out}
    if cls == 'vlen':
        if 'base' not in t:
            fail('INVALID_HDF5_TYPE', 'vlen types declare a base element type', at + '.base')
        base = scalar_type(t['base'], at + '.base')
        if base['class'] == 'string':
            fail('INVALID_HDF5_TYPE', 'vlen sequences hold numeric, bool or enum elements; use class string for text', at + '.base')
        return {'class': 'vlen', 'base': base}
    if cls == 'reference':
        return {'class': 'reference', 'reference': t['reference']}
    if cls == 'opaque':
        if 'size' not in t:
            fail('INVALID_HDF5_TYPE', 'an opaque type declares its element size in bytes', at + '.size')
        return {'class': 'opaque', 'size': t['size']}
    if cls == 'named':
        path = object_path(t.get('path', ''), at + '.path')
        if named is None or path not in named:
            fail('INVALID_HDF5_TYPE', 'a named type refers to a committed datatype object declared earlier', at + '.path', value=path)
        return {'class': 'named', 'path': path, 'resolved': named[path]}
    return scalar_type(t, at)


def resolved(t):
    return t['resolved'] if t['class'] == 'named' else t


def default_type(value):
    if isinstance(value, list):
        if not value:
            return {'class': 'float', 'bits': 64, 'order': 'little'}
        return default_type(value[0])
    if isinstance(value, bool):
        return {'class': 'bool'}
    if isinstance(value, int):
        return {'class': 'int', 'bits': 64, 'order': 'little'}
    if isinstance(value, float):
        return {'class': 'float', 'bits': 64, 'order': 'little'}
    return {'class': 'string', 'encoding': 'utf-8'}


# ------------------------------------------------------------------ element values
def element_count(shape):
    n = 1
    for d in shape:
        n *= d
    return n


def int_range(t):
    bits = t['bits']
    if t['class'] == 'int' or (t['class'] == 'enum' and t['signed']):
        return -(2 ** (bits - 1)), 2 ** (bits - 1) - 1
    return 0, 2 ** bits - 1


def check_element(value, t, at, references=None):
    """Validate one authored element against a resolved type; return its canonical host value."""
    t = resolved(t)
    cls = t['class']
    if 'dims' in t:
        inner = {k: v for k, v in t.items() if k != 'dims'}
        flat = flatten_nested(value, t['dims'], at)
        return [check_element(v, inner, at) for v in flat]
    if cls in ('int', 'uint'):
        if isinstance(value, bool) or not isinstance(value, (int, float)) or isinstance(value, float) and (not value.is_integer() or not math.isfinite(value)):
            fail('INVALID_HDF5_VALUE', 'integer types need integer values', at, value=repr(value)[:40])
        value = int(value)
        low, high = int_range(t)
        if not low <= value <= high:
            fail('INVALID_HDF5_VALUE', 'value does not fit the declared integer type', at, low=low, high=high, value=value)
        return value
    if cls == 'float':
        if isinstance(value, bool) or not isinstance(value, (int, float)):
            if value in ('nan', 'inf', '-inf'):
                return value
            fail('INVALID_HDF5_VALUE', 'floating-point values are numbers or the text nan, inf, -inf', at)
        from .expect import round_float
        rounded = round_float(float(value), t['bits'])
        if not math.isfinite(rounded) and math.isfinite(float(value)):
            fail('INVALID_HDF5_VALUE', 'value overflows the declared float precision', at, bits=t['bits'], value=value)
        return rounded if math.isfinite(rounded) else repr(rounded)
    if cls == 'complex':
        if not isinstance(value, list) or len(value) != 2 or not all(isinstance(v, (int, float)) and not isinstance(v, bool) or v in ('nan', 'inf', '-inf') for v in value):
            fail('INVALID_HDF5_VALUE', 'complex values are [real, imaginary] number pairs', at)
        from .expect import round_float
        pair = [round_float(float(v), t['bits'] // 2) for v in value]
        return [v if math.isfinite(v) else repr(v) for v in pair]
    if cls == 'bool':
        if not isinstance(value, bool):
            fail('INVALID_HDF5_VALUE', 'bool types need true or false', at)
        return value
    if cls == 'string':
        if not isinstance(value, str):
            fail('INVALID_HDF5_VALUE', 'string types need text values', at)
        if '\x00' in value:
            fail('INVALID_HDF5_VALUE', 'HDF5 strings cannot contain NUL characters', at)
        if t['encoding'] == 'ascii' and not value.isascii():
            fail('INVALID_HDF5_VALUE', 'ascii strings accept only ASCII characters; choose encoding utf-8', at)
        if 'length' in t and len(value.encode('utf-8')) > t['length']:
            fail('INVALID_HDF5_VALUE', 'text exceeds the fixed string length in encoded bytes', at, length=t['length'], bytes=len(value.encode('utf-8')))
        if 'length' in t and value.endswith('\x00'):
            fail('INVALID_HDF5_VALUE', 'fixed strings are NUL padded; trailing NUL is ambiguous', at)
        return value
    if cls == 'enum':
        names = {m['name']: m['value'] for m in t['members']}
        if isinstance(value, str) and value in names:
            return names[value]
        if isinstance(value, int) and not isinstance(value, bool) and value in names.values():
            return value
        fail('INVALID_HDF5_VALUE', 'enum values are declared member names or codes', at, members=sorted(names))
    if cls == 'compound':
        if not isinstance(value, list) or len(value) != len(t['fields']):
            fail('INVALID_HDF5_VALUE', 'compound records are arrays with one value per declared field, in field order', at, fields=[f['name'] for f in t['fields']])
        return [check_element(v, f['type'], f'{at}[{i}]') for i, (v, f) in enumerate(zip(value, t['fields']))]
    if cls == 'vlen':
        if not isinstance(value, list) or len(value) > MAX_INLINE:
            fail('INVALID_HDF5_VALUE', 'vlen elements are arrays of base values', at)
        return [check_element(v, t['base'], f'{at}[{i}]') for i, v in enumerate(value)]
    if cls == 'opaque':
        if not isinstance(value, str) or not re.fullmatch(r'([0-9a-f]{2})*', value) or len(value) != 2 * t['size']:
            fail('INVALID_HDF5_VALUE', 'opaque elements are lower-case hexadecimal of exactly size bytes', at, size=t['size'])
        return value
    fail('INVALID_HDF5_VALUE', 'references are supplied with data.source references', at)


def flatten_nested(value, dims, at):
    if not dims:
        return [value]
    if not isinstance(value, list) or len(value) != dims[0]:
        fail('INVALID_HDF5_VALUE', 'array-valued element must be a nested list with dims ' + str(dims), at)
    out = []
    for i, v in enumerate(value):
        out.extend(flatten_nested(v, dims[1:], f'{at}[{i}]'))
    return out


# ------------------------------------------------------------------ selections
def selection(s, shape, at, *, writable=False):
    """Normalise a selection against a known shape; return (normal form, selected shape, count)."""
    rank = len(shape)
    if s is None or s['kind'] == 'all':
        for key in ('slices', 'start', 'count', 'stride', 'block', 'points'):
            if s and key in s:
                fail('INVALID_HDF5_SELECTION', key + ' does not apply to kind all', at + '.' + key)
        return {'kind': 'all'}, list(shape), element_count(shape)
    kind = s['kind']
    for key in {'slices', 'start', 'count', 'stride', 'block', 'points'} - {'slices': {'slices'}, 'hyperslab': {'start', 'count', 'stride', 'block'}, 'points': {'points'}}[kind]:
        if key in s:
            fail('INVALID_HDF5_SELECTION', key + ' does not apply to kind ' + kind, at + '.' + key)
    if rank == 0:
        fail('INVALID_HDF5_SELECTION', 'scalar datasets support only kind all', at + '.kind')
    if kind == 'slices':
        items = s.get('slices') or []
        if len(items) > rank:
            fail('INVALID_HDF5_SELECTION', 'give at most one slice per axis', at + '.slices', rank=rank)
        normal, out = [], []
        for axis in range(rank):
            item = items[axis] if axis < len(items) else {}
            n = shape[axis]
            step = item.get('step', 1)
            start = item.get('start', 0)
            stop = item.get('stop', n)
            start = start + n if start < 0 else start
            stop = stop + n if stop < 0 else stop
            if not 0 <= start <= n or not 0 <= stop <= n or stop < start:
                fail('INVALID_HDF5_SELECTION', 'slice bounds lie outside the axis or stop precedes start', f'{at}.slices[{axis}]', axis=axis, size=n)
            count = (stop - start + step - 1) // step
            normal.append([start, stop, step]); out.append(count)
        return {'kind': 'slices', 'slices': normal}, out, element_count(out)
    if kind == 'hyperslab':
        start, count = s.get('start'), s.get('count')
        if start is None or count is None or len(start) != rank or len(count) != rank:
            fail('INVALID_HDF5_SELECTION', 'a hyperslab declares start and count for every axis', at, rank=rank)
        stride = s.get('stride', [1] * rank)
        block = s.get('block', [1] * rank)
        if len(stride) != rank or len(block) != rank or 0 in stride or 0 in block:
            fail('INVALID_HDF5_SELECTION', 'stride and block have one positive entry per axis', at)
        out = []
        for axis in range(rank):
            if count[axis] and start[axis] + (count[axis] - 1) * stride[axis] + block[axis] > shape[axis]:
                fail('INVALID_HDF5_SELECTION', 'hyperslab exceeds the axis extent', f'{at}.count[{axis}]', axis=axis, size=shape[axis])
            if block[axis] > stride[axis] and count[axis] > 1:
                fail('INVALID_HDF5_SELECTION', 'blocks overlap when block exceeds stride', f'{at}.block[{axis}]')
            out.append(count[axis] * block[axis])
        return {'kind': 'hyperslab', 'start': list(start), 'count': list(count), 'stride': list(stride), 'block': list(block)}, out, element_count(out)
    points = s.get('points')
    if not points:
        fail('INVALID_HDF5_SELECTION', 'a point selection lists coordinates', at + '.points')
    seen = set()
    for i, p in enumerate(points):
        if len(p) != rank or any(not 0 <= c < n for c, n in zip(p, shape)):
            fail('INVALID_HDF5_SELECTION', 'each point has one in-range coordinate per axis', f'{at}.points[{i}]', shape=list(shape))
        if writable and tuple(p) in seen:
            fail('INVALID_HDF5_SELECTION', 'a written point selection cannot repeat a coordinate', f'{at}.points[{i}]')
        seen.add(tuple(p))
    return {'kind': 'points', 'points': [list(p) for p in points]}, [len(points)], len(points)


def selection_unknown_shape(s, at):
    """Validate a selection whose dataset shape is not yet known (adopted files); bounds are checked natively."""
    if s is None:
        return {'kind': 'all'}
    big = [MAX_DIM] * MAX_RANK
    if s['kind'] == 'all':
        return selection(s, [], at)[0]
    rank = len(s.get('start') or s.get('slices') or (s.get('points') or [[0]])[0])
    if s['kind'] == 'slices':
        for i, item in enumerate(s.get('slices') or []):
            if item.get('start', 0) < 0 or item.get('stop', 1) < 0:
                fail('INVALID_HDF5_SELECTION', 'adopted-file slices use non-negative bounds; negative indices need a known shape', f'{at}.slices[{i}]')
        rank = len(s.get('slices') or [])
        normal = selection(s, big[:max(rank, 1)], at)[0]
        explicit = s.get('slices') or []
        normal['slices'] = [[item.get('start', 0), item.get('stop'), item.get('step', 1)] for item in explicit]
        return normal
    return selection(s, big[:max(rank, 1)], at)[0]


# ------------------------------------------------------------------ files and inputs
def absolute_file(value, at, code):
    if '\x00' in value or not value.startswith('/') or '..' in PurePosixPath(value).parts:
        fail(code, 'select an absolute local file path without parent references', at)
    return value


def plan_inputs(p, at='$'):
    seen = {}
    for i, item in enumerate(p.get('inputs', [])):
        where = f'{at}.inputs[{i}]'
        identifier(item['id'], where + '.id')
        if item['id'] in seen:
            fail('DUPLICATE_HDF5_INPUT', 'input ids are unique', where + '.id')
        absolute_file(item['path'], where + '.path', 'INVALID_HDF5_INPUT')
        if 'sha256' in item and not HEX.fullmatch(item['sha256']):
            fail('INVALID_SHA256', 'use 64 lower-case hexadecimal digits', where + '.sha256')
        if item['format'] == 'raw':
            if 'type' not in item or 'shape' not in item:
                fail('INVALID_HDF5_INPUT', 'raw binary inputs declare their element type and shape', where)
            t = scalar_type(item['type'], where + '.type')
            if t['class'] not in ('int', 'uint', 'float'):
                fail('INVALID_HDF5_INPUT', 'raw binary inputs hold fixed-size integer or float elements', where + '.type')
        else:
            for key in ('type', 'shape'):
                if key in item:
                    fail('INVALID_HDF5_INPUT', key + ' applies only to raw binary inputs; CSV and NPY carry their own layout', where + '.' + key)
        if item['format'] != 'csv' and item.get('delimiter', ',') != ',':
            fail('INVALID_HDF5_INPUT', 'delimiter applies only to CSV inputs', where + '.delimiter')
        seen[item['id']] = item
    return seen


def plan_dependencies(p, at='$'):
    seen, names = {}, set()
    for i, item in enumerate(p.get('dependencies', [])):
        where = f'{at}.dependencies[{i}]'
        identifier(item['id'], where + '.id')
        if item['id'] in seen:
            fail('DUPLICATE_HDF5_DEPENDENCY', 'dependency ids are unique', where + '.id')
        absolute_file(item['path'], where + '.path', 'INVALID_HDF5_DEPENDENCY')
        name = item.get('name', PurePosixPath(item['path']).name)
        if not FILE_NAME.fullmatch(name):
            fail('INVALID_HDF5_DEPENDENCY', 'dependent files keep a simple name ending .h5 .hdf5 .he5 .nc .bin .raw or .dat', where + '.name', value=name[:64])
        if name in names:
            fail('DUPLICATE_HDF5_DEPENDENCY', 'dependent file names are unique within the bundle', where + '.name')
        if 'sha256' in item and not HEX.fullmatch(item['sha256']):
            fail('INVALID_SHA256', 'use 64 lower-case hexadecimal digits', where + '.sha256')
        names.add(name)
        seen[item['id']] = {**item, 'name': name}
    return seen


def plan_file(f, at, dependencies):
    f = dict(f)
    name = f['name']
    if not re.fullmatch(r'[A-Za-z0-9_][A-Za-z0-9_.\-]{0,59}\.(h5|hdf5|he5)', name):
        fail('INVALID_HDF5_FILE', 'name the output with letters, digits, _ . - and the suffix .h5, .hdf5 or .he5', at + '.name')
    if name in {d['name'] for d in dependencies.values()}:
        fail('INVALID_HDF5_FILE', 'the output name collides with a dependent file name', at + '.name')
    if LIBVER.index(f['libver']) > LIBVER.index(f['libverHigh']):
        fail('INVALID_HDF5_FILE', 'libver low bound exceeds the high bound', at + '.libver')
    ub = f['userblock']
    if ub and (ub < 512 or ub & (ub - 1)):
        fail('INVALID_HDF5_FILE', 'a user block is 0 or a power of two of at least 512 bytes', at + '.userblock')
    driver = f['driver']
    if driver == 'family':
        if 'memberBytes' not in f:
            fail('INVALID_HDF5_FILE', 'the family driver declares memberBytes', at + '.memberBytes')
        if not re.fullmatch(r'[A-Za-z0-9_][A-Za-z0-9_.\-]{0,50}\.(h5|hdf5)', name):
            fail('INVALID_HDF5_FILE', 'family files are numbered from the name; use a shorter .h5 name', at + '.name')
    elif 'memberBytes' in f:
        fail('INVALID_HDF5_FILE', 'memberBytes applies only to the family driver', at + '.memberBytes')
    if f['spaceStrategy'] == 'page':
        if LIBVER.index(f['libverHigh']) < LIBVER.index('v110'):
            fail('INVALID_HDF5_FILE', 'paged file-space management needs libverHigh v110 or later', at + '.spaceStrategy')
        f.setdefault('pageBytes', 4096)
    elif 'pageBytes' in f:
        fail('INVALID_HDF5_FILE', 'pageBytes applies only to spaceStrategy page', at + '.pageBytes')
    if driver in ('family', 'split') and f['userblock']:
        fail('INVALID_HDF5_FILE', 'user blocks are supported with the sec2, stdio and core drivers', at + '.userblock')
    f['attributes'] = plan_attributes(f.get('attributes', []), at + '.attributes', {})
    return f


def output_files(f):
    """Physical members written by the driver, in a stable order."""
    name = f['name']
    stem = name.rsplit('.', 1)[0]
    if f['driver'] == 'family':
        return ['%s-%%d.h5' % stem]
    if f['driver'] == 'split':
        return [stem + '-m.h5', stem + '-r.h5']
    return [name]


# ------------------------------------------------------------------ attributes
COMPACT_ATTRIBUTE_BYTES = 64 * 1024 - 1024


def check_attribute_sizes(attributes, dense, at):
    """An attribute larger than HDF5's 64 KiB object-header message needs dense attribute storage: an object that tracks
    attribute creation order (trackOrder) or a file whose low library bound is v108 or later."""
    if dense:
        return
    for j, a in enumerate(attributes):
        if a.get('empty') or variable_size(a['type']):
            continue
        size = type_size(a['type']) * element_count(a['shape'])
        if size > COMPACT_ATTRIBUTE_BYTES:
            fail('INVALID_HDF5_ATTRIBUTE', 'an attribute of %d bytes exceeds the 64 KiB compact attribute message; set trackOrder true on '
                 'its object (dense attribute storage) or file libver v108 or later' % size, f'{at}[{j}]', bytes=size)


def plan_attributes(items, at, named, *, reserved_ok=False):
    seen = set()
    out = []
    for i, a in enumerate(items):
        where = f'{at}[{i}]'
        name = a['name']
        if '\x00' in name or '/' in name or name.strip() != name or not name:
            fail('INVALID_HDF5_ATTRIBUTE', 'attribute names are nonblank text without / or NUL', where + '.name')
        if name in seen:
            fail('DUPLICATE_HDF5_ATTRIBUTE', 'attribute names are unique on one object', where + '.name', name=name)
        if name in RESERVED_ATTRIBUTES and not reserved_ok:
            fail('INVALID_HDF5_ATTRIBUTE', name + ' is maintained by dimension scales; use scale/dimensions instead', where + '.name')
        seen.add(name)
        out.append(plan_attribute(a, where, named))
    return out


def generated_attribute(a, where, named):
    """A numeric attribute filled by a documented generator (range or linspace) over its declared shape."""
    from . import expect
    if 'value' in a or 'shape' not in a or 'type' not in a:
        fail('INVALID_HDF5_ATTRIBUTE', 'generated attribute data declares type and shape and no value', where + '.data')
    t = data_type(a['type'], where + '.type', named)
    if resolved(t)['class'] not in ('int', 'uint', 'float'):
        fail('INVALID_HDF5_ATTRIBUTE', 'generated attribute data is integer or float', where + '.type')
    shape = list(a['shape'])
    n = element_count(shape)
    if n > MAX_INLINE:
        fail('INVALID_HDF5_ATTRIBUTE', 'attributes hold at most %d elements; store bulk values in a dataset' % MAX_INLINE, where + '.shape')
    data = plan_data(dict(a['data']), t, shape, where + '.data', {'inputs': {}, 'referenceChecks': []})
    values = [check_element(v, t, f'{where}.data[{i}]') for i, v in enumerate(expect.generated(data, resolved(t), n))]
    return {'name': a['name'], 'type': t, 'shape': shape, 'values': values}


def plan_attribute(a, where, named):
    if a['empty']:
        if 'value' in a or 'shape' in a:
            fail('INVALID_HDF5_ATTRIBUTE', 'an empty (null dataspace) attribute has a type but no value or shape', where)
        t = data_type(a.get('type', {'class': 'float', 'bits': 64, 'order': 'little'}), where + '.type', named)
        return {'name': a['name'], 'type': t, 'empty': True}
    if 'data' in a:
        return generated_attribute(a, where, named)
    if 'value' not in a:
        fail('INVALID_HDF5_ATTRIBUTE', 'an attribute has a value, generated data or empty true', where + '.value')
    value = a['value']
    t = data_type(a['type'], where + '.type', named) if 'type' in a else default_type(value)
    rt = resolved(t)
    if rt['class'] in ('reference', 'vlen') and not isinstance(value, list):
        fail('INVALID_HDF5_ATTRIBUTE', 'reference and vlen attributes take an array value', where + '.value')
    if rt['class'] == 'reference':
        fail('INVALID_HDF5_ATTRIBUTE', 'reference-valued attributes are not authored here; store references in a dataset', where + '.type')
    scalar_value = not isinstance(value, list) or rt['class'] in ('complex', 'compound') and value and not isinstance(value[0], list)
    if 'shape' in a:
        shape = list(a['shape'])
    else:
        shape = [] if scalar_value else [len(value)]
    flat = [value] if scalar_value and not shape else (value if isinstance(value, list) else [value])
    if element_count(shape) != len(flat):
        fail('INVALID_HDF5_ATTRIBUTE', 'value count does not equal the product of shape', where + '.shape', values=len(flat), shape=shape)
    if len(flat) > MAX_INLINE:
        fail('INVALID_HDF5_ATTRIBUTE', 'attributes hold at most %d elements; store bulk values in a dataset' % MAX_INLINE, where + '.value')
    values = [check_element(v, t, f'{where}.value' + (f'[{i}]' if shape else '')) for i, v in enumerate(flat)]
    return {'name': a['name'], 'type': t, 'shape': shape, 'values': values}


# ------------------------------------------------------------------ data sources
def plan_data(d, t, shape, at, ctx):
    """Normalise a data record; return the host-side plan of where element values come from."""
    t0 = resolved(t)
    n = element_count(shape)
    src = d['source']
    allowed = {'values': {'values'}, 'fill': set(), 'range': {'start', 'step'}, 'linspace': {'start', 'stop'},
               'input': {'input', 'column', 'columns'}, 'references': {'targets'}, 'copy': {'dataset'}}[src]
    for key in set(d) - allowed - {'source'}:
        fail('INVALID_HDF5_DATA', key + ' does not apply to source ' + src, at + '.' + key)
    if src != 'references' and t0['class'] == 'reference':
        fail('INVALID_HDF5_DATA', 'reference datasets take data.source references', at + '.source')
    if src == 'values':
        values = d.get('values')
        if values is None:
            fail('INVALID_HDF5_DATA', 'source values lists the elements in row-major order', at + '.values')
        if len(values) != n:
            fail('INVALID_HDF5_DATA', 'value count must equal the product of shape (row-major flattening)', at + '.values', values=len(values), elements=n)
        return {'source': 'values', 'values': [check_element(v, t, f'{at}.values[{i}]') for i, v in enumerate(values)]}
    if src == 'fill':
        return {'source': 'fill'}
    if src in ('range', 'linspace'):
        if t0['class'] not in ('int', 'uint', 'float') or 'dims' in t0:
            fail('INVALID_HDF5_DATA', src + ' generates integer or float elements', at + '.source')
        if 'start' not in d or ('step' if src == 'range' else 'stop') not in d:
            fail('INVALID_HDF5_DATA', src + ' needs start and ' + ('step' if src == 'range' else 'stop'), at)
        values = [d['start'], d.get('step', d.get('stop'))]
        if not all(math.isfinite(v) for v in values):
            fail('INVALID_HDF5_DATA', 'generator parameters are finite', at)
        if t0['class'] != 'float':
            if src == 'linspace' or not all(float(v).is_integer() for v in values):
                fail('INVALID_HDF5_DATA', 'integer datasets use range with integer start and step', at)
            last = int(d['start']) + (n - 1) * int(d['step']) if n else int(d['start'])
            low, high = int_range(t0)
            if n and not (low <= int(d['start']) <= high and low <= last <= high):
                fail('INVALID_HDF5_DATA', 'generated integers leave the declared type range', at, low=low, high=high)
        if src == 'linspace' and n < 2:
            fail('INVALID_HDF5_DATA', 'linspace needs at least two elements', at)
        return {'source': src, 'start': d['start'], ('step' if src == 'range' else 'stop'): d.get('step', d.get('stop'))}
    if src == 'input':
        if 'input' not in d or d['input'] not in ctx['inputs']:
            fail('INVALID_HDF5_DATA', 'name a declared inputs[] id', at + '.input')
        item = ctx['inputs'][d['input']]
        if item['format'] == 'csv':
            if ('column' in d) == ('columns' in d):
                fail('INVALID_HDF5_DATA', 'CSV data selects exactly one of column (1-D or compound field rows) or columns (2-D)', at)
        elif 'column' in d or 'columns' in d:
            fail('INVALID_HDF5_DATA', 'column selection applies only to CSV inputs', at)
        return {'source': 'input', 'input': d['input'], **({'column': d['column']} if 'column' in d else {}),
                **({'columns': list(d['columns'])} if 'columns' in d else {})}
    if src == 'references':
        if t0['class'] != 'reference':
            fail('INVALID_HDF5_DATA', 'references fill reference-typed datasets', at + '.source')
        targets = d.get('targets') or []
        if len(targets) != n:
            fail('INVALID_HDF5_DATA', 'one target per element', at + '.targets', targets=len(targets), elements=n)
        out = []
        for i, item in enumerate(targets):
            where = f'{at}.targets[{i}]'
            path = object_path(item['path'], where + '.path')
            if t0['reference'] == 'object':
                if 'selection' in item:
                    fail('INVALID_HDF5_DATA', 'object references point at whole objects; use type reference region for selections', where + '.selection')
                out.append({'path': path})
            else:
                if 'selection' not in item:
                    fail('INVALID_HDF5_DATA', 'region references declare a selection', where + '.selection')
                out.append({'path': path, 'selection': item['selection']})
        ctx.setdefault('referenceChecks', []).append((at, out, t0['reference']))
        return {'source': 'references', 'targets': out}
    if 'dataset' not in d:
        fail('INVALID_HDF5_DATA', 'copy names an existing dataset path', at + '.dataset')
    return {'source': 'copy', 'dataset': object_path(d['dataset'], at + '.dataset')}


# ------------------------------------------------------------------ storage
def plan_storage(s, t, shape, maxshape, at, ctx, has_virtual):
    s = dict(s or {})
    t0 = resolved(t)
    chunked_needed = any(m != d for m, d in zip(maxshape, shape))
    filters = s.get('compression', 'none') != 'none' or s.get('shuffle') or s.get('fletcher32') or 'scaleOffset' in s or s.get('nbit')
    layout = s.get('layout') or ('virtual' if has_virtual else 'external' if 'external' in s else
                                 'chunked' if chunked_needed or filters or 'chunks' in s else 'contiguous')
    if has_virtual != (layout == 'virtual'):
        fail('INVALID_HDF5_STORAGE', 'virtual datasets declare a virtual record and layout virtual (or omit layout)', at + '.layout')
    if layout != 'chunked':
        for key in ('chunks', 'level', 'szipMethod', 'szipPixels', 'scaleOffset'):
            if key in s:
                fail('INVALID_HDF5_STORAGE', key + ' requires chunked layout', at + '.' + key)
        if filters:
            fail('INVALID_HDF5_STORAGE', 'filters (compression, shuffle, fletcher32, scaleOffset) require chunked layout', at)
        if chunked_needed:
            fail('INVALID_HDF5_STORAGE', 'resizable datasets (maxshape beyond shape) require chunked layout', at + '.layout')
    if layout == 'external':
        if 'external' not in s:
            fail('INVALID_HDF5_STORAGE', 'external layout lists raw segments in storage.external', at + '.external')
        if t0['class'] in ('string', 'vlen', 'reference') and ('length' not in t0):
            fail('INVALID_HDF5_STORAGE', 'external raw storage needs fixed-size elements', at + '.external')
        total = sum(seg['size'] for seg in s['external'])
        need = element_count(shape) * type_size(t0)
        if total < need:
            fail('INVALID_HDF5_STORAGE', 'external segments are smaller than the dataset', at + '.external', bytes=total, needed=need)
        for i, seg in enumerate(s['external']):
            dep = ctx['dependencies'].get(seg['file'])
            if dep is not None:
                if dep['role'] != 'rawStorage':
                    fail('INVALID_HDF5_STORAGE', 'external segments reference a rawStorage dependency or a new file name', f'{at}.external[{i}].file')
            elif not FILE_NAME.fullmatch(seg['file']):
                fail('INVALID_HDF5_STORAGE', 'a new external raw file name ends .bin, .raw or .dat', f'{at}.external[{i}].file')
        s['external'] = [{'file': seg['file'], 'offset': seg['offset'], 'size': seg['size']} for seg in s['external']]
    elif 'external' in s:
        fail('INVALID_HDF5_STORAGE', 'external segments require layout external', at + '.external')
    if layout == 'compact':
        if element_count(shape) * max(type_size(t0), 1) > 60000:
            fail('INVALID_HDF5_STORAGE', 'compact layout holds at most about 64 KiB of raw data in the object header', at + '.layout')
        if 'allocTime' in s and s['allocTime'] != 'early':
            fail('INVALID_HDF5_STORAGE', 'compact datasets are allocated early', at + '.allocTime')
    if layout == 'chunked':
        if not shape:
            fail('INVALID_HDF5_STORAGE', 'scalar datasets cannot be chunked', at + '.layout')
        chunks = s.get('chunks', 'auto')
        if chunks != 'auto':
            if len(chunks) != len(shape):
                fail('INVALID_HDF5_STORAGE', 'chunks gives one extent per axis', at + '.chunks', rank=len(shape))
            for axis, (c, d, m) in enumerate(zip(chunks, shape, maxshape)):
                if m != 'unlimited' and c > max(m, 1):
                    fail('INVALID_HDF5_STORAGE', 'a chunk extent cannot exceed the maximum axis size', f'{at}.chunks[{axis}]')
            if element_count(chunks) * max(type_size(t0), 1) > 2 ** 32 - 1:
                fail('INVALID_HDF5_STORAGE', 'a chunk must be smaller than 4 GiB', at + '.chunks')
        s['chunks'] = chunks
        comp = s.get('compression', 'none')
        if comp == 'gzip':
            s.setdefault('level', 4)
        elif 'level' in s:
            fail('INVALID_HDF5_STORAGE', 'level applies only to gzip', at + '.level')
        if comp == 'szip':
            s.setdefault('szipMethod', 'nn'); s.setdefault('szipPixels', 8)
            if s['szipPixels'] % 2:
                fail('INVALID_HDF5_STORAGE', 'szip pixels per block is even', at + '.szipPixels')
            if t0['class'] not in ('int', 'uint', 'float'):
                fail('INVALID_HDF5_STORAGE', 'szip compresses integer or float elements', at + '.compression')
        else:
            for key in ('szipMethod', 'szipPixels'):
                if key in s:
                    fail('INVALID_HDF5_STORAGE', key + ' applies only to szip', at + '.' + key)
        if s.get('nbit') and (t0['class'] not in ('int', 'uint', 'float') or 'scaleOffset' in s):
            fail('INVALID_HDF5_STORAGE', 'nbit packs integer or float elements and cannot be combined with scaleOffset', at + '.nbit')
        if 'scaleOffset' in s:
            if t0['class'] not in ('int', 'uint', 'float'):
                fail('INVALID_HDF5_STORAGE', 'scaleOffset applies to integer or float elements', at + '.scaleOffset')
            if t0['class'] == 'float' and s['scaleOffset'] == 0:
                fail('INVALID_HDF5_STORAGE', 'float scaleOffset keeps a positive number of decimal digits (lossy)', at + '.scaleOffset')
            if s.get('fletcher32'):
                pass
        if comp != 'none' and t0['class'] in ('vlen',) or comp != 'none' and t0['class'] == 'string' and 'length' not in t0:
            fail('INVALID_HDF5_STORAGE', 'compression filters apply to fixed-size elements, not variable-length data', at + '.compression')
    if 'fillValue' in s:
        if t0['class'] in ('vlen', 'reference', 'compound', 'array', 'opaque') or t0['class'] == 'string' and 'length' not in t0:
            fail('INVALID_HDF5_STORAGE', 'fillValue is supported for numeric, bool, enum and fixed-string elements', at + '.fillValue')
        s['fillValue'] = check_element(s['fillValue'], t, at + '.fillValue')
    s['layout'] = layout
    s.setdefault('compression', 'none')
    return s


def type_size(t):
    t = resolved(t)
    cls = t['class']
    dims = element_count(t.get('dims', []))
    if cls in ('int', 'uint', 'float', 'complex', 'enum', 'bitfield'):
        return t['bits'] // 8 * dims
    if cls == 'bool':
        return dims
    if cls == 'string':
        return t.get('length', 16) * dims
    if cls == 'compound':
        return sum(type_size(f['type']) for f in t['fields'])
    if cls == 'array':
        return type_size(t['base'])
    if cls == 'opaque':
        return t['size']
    if cls == 'reference':
        return 8 if t['reference'] == 'object' else 12
    return 16


def variable_size(t):
    """True when elements of this type carry out-of-line payloads (variable-length strings or sequences, references) or are of unknown size."""
    t = resolved(t)
    cls = t['class']
    if cls == 'compound':
        return any(variable_size(f['type']) for f in t['fields'])
    if cls == 'array':
        return variable_size(t['base'])
    if cls == 'string':
        return 'length' not in t
    return cls not in ('int', 'uint', 'float', 'complex', 'enum', 'bitfield', 'bool', 'opaque')


# ------------------------------------------------------------------ objects
def null_dataset(o, path, at, named):
    """A null-dataspace dataset (h5py.Empty): a type and attributes only - no shape, extent, values or storage choices."""
    for key in ('shape', 'maxshape', 'data', 'storage', 'virtual', 'scale'):
        if key in o:
            fail('INVALID_HDF5_OBJECT', 'an empty (null dataspace) dataset holds no elements; %s does not apply' % key, at + '.' + key)
    if o.get('dimensions'):
        fail('INVALID_HDF5_OBJECT', 'an empty (null dataspace) dataset has no axes to describe', at + '.dimensions')
    if 'type' not in o:
        fail('INVALID_HDF5_OBJECT', 'an empty dataset still declares its element type', at + '.type')
    t = data_type(o['type'], at + '.type', named)
    attrs = plan_attributes(o['attributes'], at + '.attributes', named)
    if 'units' in o:
        if any(a['name'] == 'units' for a in attrs):
            fail('DUPLICATE_HDF5_ATTRIBUTE', 'units is given both as a field and as an attribute', at + '.units')
        attrs.append({'name': 'units', 'type': {'class': 'string', 'encoding': 'utf-8'}, 'shape': [], 'values': [o['units']]})
    result = {'path': path, 'kind': 'dataset', 'type': t, 'empty': True, 'shape': None, 'maxshape': None, 'attributes': attrs,
              'storage': {'layout': 'contiguous'}, 'data': {'source': 'none'}, 'dimensions': []}
    if 'trackOrder' in o:
        result['trackOrder'] = o['trackOrder']
    return result


def plan_object(o, at, ctx):
    path = object_path(o['path'], at + '.path')
    kind = o['kind']
    named = ctx['named']
    if kind in ('group', 'datatype'):
        allowed = {'group': {'path', 'kind', 'attributes', 'trackOrder'}, 'datatype': {'path', 'kind', 'type', 'attributes'}}[kind]
        for key in set(o) - allowed - {'dimensions'}:
            fail('INVALID_HDF5_OBJECT', key + ' does not apply to a ' + kind, at + '.' + key)
        if o.get('dimensions'):
            fail('INVALID_HDF5_OBJECT', 'dimensions does not apply to a ' + kind, at + '.dimensions')
        result = {'path': path, 'kind': kind, 'attributes': plan_attributes(o['attributes'], at + '.attributes', named)}
        if kind == 'group':
            if 'trackOrder' in o:
                result['trackOrder'] = o['trackOrder']
        else:
            if 'type' not in o:
                fail('INVALID_HDF5_OBJECT', 'a committed datatype declares type', at + '.type')
            t = data_type(o['type'], at + '.type', named)
            if t['class'] in ('named', 'reference'):
                fail('INVALID_HDF5_OBJECT', 'commit a concrete numeric, string, enum, compound, vlen, array or opaque type', at + '.type')
            result['type'] = t
            named[path] = t
        return result
    if o.get('empty'):
        return null_dataset(o, path, at, named)
    if 'type' not in o:
        fail('INVALID_HDF5_OBJECT', 'a dataset declares its element type', at + '.type')
    t = data_type(o['type'], at + '.type', named)
    if 'shape' not in o:
        fail('INVALID_HDF5_OBJECT', 'a dataset declares shape ([] for a scalar)', at + '.shape')
    shape = list(o['shape'])
    if element_count(shape) > MAX_ELEMENTS:
        fail('HDF5_RESOURCE_LIMIT', 'a dataset holds at most %d elements in this adaptor' % MAX_ELEMENTS, at + '.shape')
    maxshape = list(o.get('maxshape', shape))
    if len(maxshape) != len(shape):
        fail('INVALID_HDF5_OBJECT', 'maxshape has one entry per axis', at + '.maxshape')
    for axis, (m, d) in enumerate(zip(maxshape, shape)):
        if m != 'unlimited' and m < d:
            fail('INVALID_HDF5_OBJECT', 'maxshape cannot be smaller than shape', f'{at}.maxshape[{axis}]')
    has_virtual = 'virtual' in o
    storage = plan_storage(o.get('storage'), t, shape, maxshape, at + '.storage', ctx, has_virtual)
    result = {'path': path, 'kind': 'dataset', 'type': t, 'shape': shape, 'maxshape': maxshape, 'storage': storage}
    if has_virtual:
        if 'data' in o:
            fail('INVALID_HDF5_OBJECT', 'virtual datasets take values from their sources, not data', at + '.data')
        result['virtual'] = plan_virtual(o['virtual'], t, shape, at + '.virtual', ctx)
    elif storage['layout'] == 'external' and 'data' not in o:
        if not all(seg['file'] in ctx['dependencies'] for seg in storage['external']):
            fail('INVALID_HDF5_STORAGE', 'external storage without data reads existing rawStorage dependencies; new raw files need data', at + '.data')
        result['data'] = {'source': 'external'}
    else:
        result['data'] = plan_data(o.get('data', {'source': 'fill'}), t, shape, at + '.data', ctx)
    if result.get('data', {}).get('source') == 'fill' and 'fillValue' not in storage and resolved(t)['class'] in ('vlen', 'reference'):
        pass
    ctx['elements'] += element_count(shape)
    if ctx['elements'] > MAX_TOTAL_ELEMENTS:
        fail('HDF5_RESOURCE_LIMIT', 'datasets together hold at most %d elements' % MAX_TOTAL_ELEMENTS, at + '.shape')
    attrs = plan_attributes(o['attributes'], at + '.attributes', named)
    if 'units' in o:
        if any(a['name'] == 'units' for a in attrs):
            fail('DUPLICATE_HDF5_ATTRIBUTE', 'units is given both as a field and as an attribute', at + '.units')
        attrs.append({'name': 'units', 'type': {'class': 'string', 'encoding': 'utf-8'}, 'shape': [], 'values': [o['units']]})
    result['attributes'] = attrs
    if 'trackOrder' in o:
        if 'virtual' in o:
            fail('INVALID_HDF5_OBJECT', 'virtual datasets are created without attribute creation order tracking', at + '.trackOrder')
        result['trackOrder'] = o['trackOrder']
    if 'scale' in o:
        if len(shape) != 1:
            fail('INVALID_HDF5_OBJECT', 'dimension scales in this adaptor are one-dimensional coordinate datasets', at + '.scale')
        result['scale'] = o['scale']
    dims = []
    seen_axes = set()
    for i, dim in enumerate(o['dimensions']):
        where = f'{at}.dimensions[{i}]'
        if dim['axis'] >= len(shape) or dim['axis'] in seen_axes:
            fail('INVALID_HDF5_DIMENSION', 'each axis is described once and exists in shape', where + '.axis', rank=len(shape))
        seen_axes.add(dim['axis'])
        scales = [object_path(s, f'{where}.scales[{j}]') for j, s in enumerate(dim['scales'])]
        dims.append({'axis': dim['axis'], **({'label': dim['label']} if 'label' in dim else {}), 'scales': scales})
        ctx['scaleChecks'].append((where, path, dim['axis'], shape[dim['axis']], scales))
    result['dimensions'] = dims
    return result


def plan_virtual(v, t, shape, at, ctx):
    sources = []
    for i, s in enumerate(v['sources']):
        where = f'{at}.sources[{i}]'
        file_id = s['file']
        if file_id != '.':
            dep = ctx['dependencies'].get(file_id)
            if dep is None or dep['role'] != 'virtualSource':
                fail('INVALID_HDF5_VIRTUAL', 'file is . (this file) or a virtualSource dependency id', where + '.file')
        at_sel, target_shape, count = selection(s.get('at'), shape, where + '.at')
        if at_sel['kind'] == 'points':
            fail('INVALID_HDF5_VIRTUAL', 'virtual mappings use all, slices or hyperslab selections', where + '.at')
        select = s.get('select')
        if select is not None and select['kind'] == 'points':
            fail('INVALID_HDF5_VIRTUAL', 'virtual mappings use all, slices or hyperslab selections', where + '.select')
        sources.append({'file': file_id, 'dataset': object_path(s['dataset'], where + '.dataset'),
                        'select': selection_unknown_shape(select, where + '.select'), 'at': at_sel, 'count': count, 'targetShape': target_shape})
    result = {'sources': sources}
    if 'fill' in v:
        result['fill'] = check_element(v['fill'], t, at + '.fill')
    ctx['virtualChecks'].append((at, sources))
    return result


def plan_link(link, at, ctx):
    path = object_path(link['path'], at + '.path')
    kind = link['kind']
    if kind == 'external':
        if 'file' not in link:
            fail('INVALID_HDF5_LINK', 'external links name the target file (a dependency id or a relative file name)', at + '.file')
        dep = ctx['dependencies'].get(link['file'])
        if dep is not None:
            if dep['role'] != 'externalLink':
                fail('INVALID_HDF5_LINK', 'external links use an externalLink dependency', at + '.file')
            target_file = dep['name']
        elif FILE_NAME.fullmatch(link['file']):
            target_file = link['file']
        else:
            fail('INVALID_HDF5_LINK', 'name an externalLink dependency id or a simple relative .h5 file name', at + '.file')
        target = object_path(link['target'], at + '.target', root=True)
        return {'path': path, 'kind': 'external', 'file': target_file, 'target': target, 'dependency': dep['id'] if dep else None}
    if 'file' in link:
        fail('INVALID_HDF5_LINK', 'file applies only to external links', at + '.file')
    target = link['target']
    if kind == 'hard':
        target = object_path(target, at + '.target')
    elif not target or '\x00' in target or len(target) > 1024:
        fail('INVALID_HDF5_LINK', 'a soft link stores a nonempty target path', at + '.target')
    return {'path': path, 'kind': kind, 'target': target}


def context(p):
    return {'inputs': plan_inputs(p), 'dependencies': plan_dependencies(p), 'named': {}, 'elements': 0,
            'scaleChecks': [], 'virtualChecks': [], 'referenceChecks': []}


def finish_tree(objects, links, ctx, at='$'):
    """Cross-object checks: unique paths, implicit parents, scales, references and virtual sources."""
    kinds = {'/': 'group'}
    shapes = {}
    for i, o in enumerate(objects):
        where = f'{at}.objects[{i}].path'
        path = o['path']
        if path in kinds:
            fail('DUPLICATE_HDF5_PATH', 'each path is declared once', where, path=path)
        for anc in ancestors(path):
            if kinds.get(anc, 'group') != 'group':
                fail('INVALID_HDF5_PATH', 'a parent path is a dataset or datatype, not a group', where, parent=anc)
            kinds.setdefault(anc, 'group')
        kinds[path] = o['kind']
        if o['kind'] == 'dataset':
            shapes[path] = o
    for i, link in enumerate(links):
        where = f'{at}.links[{i}].path'
        if link['path'] in kinds:
            fail('DUPLICATE_HDF5_PATH', 'a link path collides with a declared object', where, path=link['path'])
        for anc in ancestors(link['path']):
            if kinds.get(anc, 'group') != 'group':
                fail('INVALID_HDF5_PATH', 'a link parent is not a group', where, parent=anc)
            kinds.setdefault(anc, 'group')
        if link['kind'] == 'hard' and link['target'] not in kinds:
            fail('INVALID_HDF5_LINK', 'hard links target a declared object', f'{at}.links[{i}].target')
        kinds[link['path']] = link['kind'] + 'Link'
    for where, path, axis, size, scales in ctx['scaleChecks']:
        for j, s in enumerate(scales):
            target = shapes.get(s)
            if target is None or 'scale' not in target:
                fail('INVALID_HDF5_DIMENSION', 'attach a declared dataset that has scale set', f'{where}.scales[{j}]', scale=s)
            if target['shape'] != [size]:
                fail('INVALID_HDF5_DIMENSION', 'a scale has exactly the length of the axis it describes', f'{where}.scales[{j}]', axis=axis, size=size, scaleShape=target['shape'])
            if s == path:
                fail('INVALID_HDF5_DIMENSION', 'a dataset cannot be its own dimension scale', f'{where}.scales[{j}]')
    for where, targets, kind in ctx['referenceChecks']:
        for j, item in enumerate(targets):
            if item['path'] not in kinds or kinds[item['path']].endswith('Link'):
                fail('INVALID_HDF5_REFERENCE', 'references point at declared objects in this file', f'{where}.targets[{j}].path')
            if kind == 'region':
                target = shapes.get(item['path'])
                if target is None:
                    fail('INVALID_HDF5_REFERENCE', 'region references point at datasets', f'{where}.targets[{j}].path')
                item['selection'], _, _ = selection(item['selection'], target['shape'], f'{where}.targets[{j}].selection')
    for where, sources in ctx['virtualChecks']:
        for j, s in enumerate(sources):
            if s['file'] == '.':
                target = shapes.get(s['dataset'])
                if target is None or 'virtual' in target:
                    fail('INVALID_HDF5_VIRTUAL', 'same-file sources name a declared non-virtual dataset', f'{where}.sources[{j}].dataset')
                sel, sshape, count = selection(s['select'] if s['select']['kind'] != 'all' else None, target['shape'], f'{where}.sources[{j}].select') if s['select']['kind'] != 'slices' or s['select']['slices'] else ({'kind': 'all'}, target['shape'], element_count(target['shape']))
                if s['select']['kind'] == 'slices' and s['select']['slices']:
                    raw = {'kind': 'slices', 'slices': [{k: v for k, v in zip(('start', 'stop', 'step'), item) if v is not None} for item in s['select']['slices']]}
                    sel, sshape, count = selection(raw, target['shape'], f'{where}.sources[{j}].select')
                if count != s['count']:
                    fail('INVALID_HDF5_VIRTUAL', 'source and target selections select the same number of elements', f'{where}.sources[{j}]', source=count, target=s['count'])
                s['select'] = sel
    for o in objects:
        if o['kind'] == 'dataset' and o.get('data', {}).get('source') == 'copy':
            src = shapes.get(o['data']['dataset'])
            if src is None or src['path'] == o['path'] or src['shape'] != o['shape']:
                fail('INVALID_HDF5_DATA', 'copy names another declared dataset with the same shape', o['path'])
    return kinds
