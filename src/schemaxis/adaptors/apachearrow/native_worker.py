"""Trusted isolated PyArrow worker; copied to the owned run and never host-imported."""
import hashlib
import json
import os
from pathlib import Path
import resource
import stat
import struct
import sys

resource.setrlimit(resource.RLIMIT_AS, (2 * 1024**3, 2 * 1024**3))
resource.setrlimit(resource.RLIMIT_FSIZE, (32 * 1024**2, 32 * 1024**2))
resource.setrlimit(resource.RLIMIT_CPU, (30, 30))


def bounded(name):
    fd = os.open(name, os.O_RDONLY | os.O_NONBLOCK | os.O_NOFOLLOW)
    with os.fdopen(fd, 'rb') as stream:
        info = os.fstat(stream.fileno())
        if not stat.S_ISREG(info.st_mode) or info.st_size > 32 * 1024**2:
            raise ValueError('ARROW_NATIVE_INPUT_LIMIT')
        data = stream.read(32 * 1024**2 + 1)
    if len(data) > 32 * 1024**2:
        raise ValueError('ARROW_NATIVE_INPUT_LIMIT')
    return data


def main():
    import pyarrow as pa
    import pyarrow.compute as pc
    import pyarrow.csv as csv
    import pyarrow.parquet as pq
    if pa.__version__ != '26.0.0' or pa.cpp_version != '26.0.0':
        raise ValueError('UNSUPPORTED_ARROW_RUNTIME: require PyArrow and C++ 26.0.0')
    pa.set_cpu_count(1)
    pa.set_io_thread_count(1)
    types = {'bool': pa.bool_(), 'int32': pa.int32(), 'int64': pa.int64(), 'float64': pa.float64(),
             'utf8': pa.string(), 'timestamp_us_utc': pa.timestamp('us', 'UTC')}
    stage = sys.argv[1]
    if stage not in ('convert', 'readback'):
        raise ValueError('INVALID_ARROW_STAGE')
    config_bytes = bounded('native-config.json')
    config = json.loads(config_bytes)
    input_name = 'source.csv' if stage == 'convert' else 'table.parquet'
    data = bounded(input_name)
    inputs = {input_name: hashlib.sha256(data).hexdigest(),
              'native-config.json': hashlib.sha256(config_bytes).hexdigest(),
              'native-worker.py': hashlib.sha256(bounded('native-worker.py')).hexdigest()}
    Path(stage + '-inputs.json').write_text(json.dumps(inputs, sort_keys=True))

    def schema(columns):
        return pa.schema([pa.field(c['name'], types[c['type']], nullable=c['nullable']) for c in columns])

    def snapshot(table, columns):
        if not table.schema.equals(schema(columns), check_metadata=True):
            raise ValueError('ARROW_SCHEMA_READBACK_DIFFERS')
        arrays = []
        for c in columns:
            array = table[c['name']]
            if c['type'] == 'timestamp_us_utc':
                array = pc.cast(array, pa.int64(), safe=True)
            values = array.to_pylist()
            arrays.append([None if v is None else struct.pack('<d', v).hex() if c['type'] == 'float64'
                           else str(v) if c['type'] in ('int64', 'timestamp_us_utc') else v for v in values])
        return {'columns': columns, 'rows': [list(row) for row in zip(*arrays)]}

    if stage == 'convert':
        table = csv.read_csv(pa.BufferReader(data),
            read_options=csv.ReadOptions(use_threads=False),
            parse_options=csv.ParseOptions(newlines_in_values=True, ignore_empty_lines=False),
            convert_options=csv.ConvertOptions(column_types={c['name']: types[c['type']] for c in config['columns']},
                null_values=['\\N'], strings_can_be_null=True, quoted_strings_can_be_null=True,
                true_values=['true'], false_values=['false']))
        table = table.cast(schema(config['columns']), safe=True)
        observed = snapshot(table, config['columns'])
        for predicate in config['where']:
            column = table[predicate['column']]
            operation = predicate['test']
            if operation == 'isNull':
                mask = pc.is_null(column)
            elif operation == 'isValid':
                mask = pc.is_valid(column)
            else:
                value = pa.scalar(predicate['value']).cast(column.type, safe=True)
                kernel = {'eq': pc.equal, 'ne': pc.not_equal, 'lt': pc.less, 'le': pc.less_equal,
                          'gt': pc.greater, 'ge': pc.greater_equal}[operation]
                mask = pc.fill_null(kernel(column, value), False)
            table = table.filter(mask, null_selection_behavior='drop')
        arrays = []
        for item, output in zip(config['select'], config['outputColumns']):
            array = table[item['column']]
            if 'cast' in item:
                array = pc.cast(array, types[item['cast']], safe=True)
            if 'fillNull' in item:
                array = pc.fill_null(array, pa.scalar(item['fillNull']).cast(array.type, safe=True))
            arrays.append(array)
        table = pa.Table.from_arrays(arrays, schema=schema(config['outputColumns']))
        snapshot(table, config['outputColumns'])
        pq.write_table(table, 'table.parquet', version='2.6', data_page_version='1.0',
            compression='NONE', use_dictionary=False, column_encoding='PLAIN',
            use_byte_stream_split=False, write_statistics=False, write_page_index=False,
            write_page_checksum=False, use_deprecated_int96_timestamps=False,
            allow_truncated_timestamps=False, store_schema=False, row_group_size=1024,
            data_page_size=65536, write_batch_size=256, use_content_defined_chunking=False)
    else:
        table = pq.read_table(pa.BufferReader(data), use_threads=False)
        observed = snapshot(table, config['outputColumns'])
    print(json.dumps({'runtime': pa.__version__, 'cpp': pa.cpp_version, 'table': observed},
                     allow_nan=False, sort_keys=True))


if __name__ == '__main__':
    main()
