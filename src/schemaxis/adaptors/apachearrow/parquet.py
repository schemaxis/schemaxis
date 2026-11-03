# Copyright (C) 2026 David L F Gaden
"""Independent reader for this adaptor's closed Parquet output encoding.

This is not a general Parquet reader. No Arrow, Thrift or external parser imports.
The physical layout follows apache/parquet-format and Apache Compact Thrift specs.
All metadata retains wire types until checked; unknown fields are rejected.
"""
import math
import struct

MAX_FILE = 32 * 1024**2
MAX_ROWS = 10000
MAX_CELLS = 200000
PHYSICAL = {'bool': 0, 'int32': 1, 'int64': 2, 'float64': 5, 'utf8': 6, 'timestamp_us_utc': 2}


def require(condition, message):
    if not condition:
        raise ValueError('closed Parquet: ' + message)


class Reader:
    """Bounded byte cursor and Compact Thrift subset preserving scalar wire types."""
    def __init__(self, data):
        self.data, self.pos, self.items = memoryview(data), 0, 0

    def take(self, count):
        require(0 <= count <= len(self.data) - self.pos, 'truncated or excessive length')
        value = self.data[self.pos:self.pos + count]
        self.pos += count
        return value

    def byte(self):
        return self.take(1)[0]

    def uint(self, bits=64):
        result = 0
        for i in range((bits + 6) // 7):
            byte = self.byte()
            result |= (byte & 127) << (7 * i)
            if not byte & 128:
                require(result < 1 << bits and (i == 0 or byte != 0), 'noncanonical/overflow varint')
                return result
        raise ValueError('closed Parquet: overlong varint')

    def sint(self, bits):
        value = self.uint(bits)
        return (value >> 1) ^ -(value & 1)

    def value(self, kind, depth=0):
        self.items += 1
        require(depth <= 12 and self.items <= 100000, 'metadata nesting/item budget')
        if kind in (1, 2):
            return kind == 1
        if kind in (4, 5, 6):
            return self.sint({4: 16, 5: 32, 6: 64}[kind])
        if kind == 8:
            return bytes(self.take(self.uint(32)))
        if kind == 9:
            header = self.byte()
            count, element = header >> 4, header & 15
            if count == 15:
                count = self.uint(32)
                require(count >= 15, 'noncanonical extended list size')
            require(count <= 20000 and element in (5, 6, 8, 12), 'unsupported list or length')
            return (element, [self.value(element, depth + 1) for _ in range(count)])
        if kind == 12:
            fields, previous = {}, 0
            while True:
                header = self.byte()
                if header == 0:
                    return fields
                identifier = previous + (header >> 4) if header >> 4 else self.sint(16)
                require(0 < identifier <= 32 and identifier not in fields and len(fields) < 20,
                        'duplicate/invalid/excessive metadata field')
                fields[identifier] = (header & 15, self.value(header & 15, depth + 1))
                previous = identifier
        raise ValueError('closed Parquet: unsupported Compact Thrift wire type')


def fields(node, required, optional=None):
    optional = optional or {}
    require(set(required) <= set(node) <= set(required) | set(optional), 'metadata field membership')
    result = {}
    for key, (kind, value) in node.items():
        require(kind == (required | optional)[key], 'metadata wire type')
        result[key] = value
    return result


def sequence(value, element, maximum):
    require(value[0] == element and len(value[1]) <= maximum, 'metadata list type/length')
    return value[1]


def expected_leaf(column):
    leaf = {1: (5, PHYSICAL[column['type']]), 3: (5, int(column['nullable'])),
            4: (8, column['name'].encode('ascii'))}
    if column['type'] == 'utf8':
        leaf.update({6: (5, 0), 10: (12, {1: (12, {})})})
    if column['type'] == 'timestamp_us_utc':
        leaf.update({6: (5, 10), 10: (12, {8: (12, {1: (1, True), 2: (12, {2: (12, {})})})})})
    return leaf


def definitions(reader, count, optional):
    if not optional:
        return [1] * count
    length = struct.unpack('<I', reader.take(4))[0]
    levels = Reader(reader.take(length))
    result = []
    while levels.pos < len(levels.data):
        run = levels.uint(32)
        require(run > 0 and len(result) < count, 'empty or excess definition run')
        if run & 1:
            groups = run >> 1
            require(groups > 0 and len(result) + groups * 8 <= count + 7, 'definition bitpack length')
            values = [(byte >> bit) & 1 for byte in levels.take(groups) for bit in range(8)]
            remaining = count - len(result)
            if len(values) > remaining:
                require(not any(values[remaining:]) and levels.pos == len(levels.data), 'definition padding')
            result.extend(values[:remaining])
        else:
            length, value = run >> 1, levels.byte()
            require(value in (0, 1) and length <= count - len(result), 'definition RLE value/length')
            result.extend([value] * length)
    require(len(result) == count, 'definition count differs')
    return result


def plain(reader, physical, count):
    if physical in (1, 2, 5):
        fmt, width = {1: ('i', 4), 2: ('q', 8), 5: ('d', 8)}[physical]
        values = [struct.unpack('<' + fmt, reader.take(width))[0] for _ in range(count)]
        require(physical != 5 or all(math.isfinite(v) for v in values), 'nonfinite DOUBLE')
        return values
    if physical == 0:
        bits = reader.take((count + 7) // 8)
        if count % 8:
            require(bits[-1] >> (count % 8) == 0, 'BOOLEAN padding')
        return [bool((bits[i // 8] >> (i % 8)) & 1) for i in range(count)]
    if physical == 6:
        values = []
        for _ in range(count):
            length = struct.unpack('<I', reader.take(4))[0]
            require(length <= 4096, 'text cell budget')
            value = bytes(reader.take(length)).decode('utf-8')
            require('\x00' not in value, 'NUL text')
            values.append(value)
        return values
    raise ValueError('closed Parquet: unsupported physical type')


def pages(data, column, row_count):
    reader, values, number = Reader(data), [], 0
    while reader.pos < len(reader.data):
        header_reader = Reader(reader.data[reader.pos:reader.pos + 4096])
        header = fields(header_reader.value(12), {1: 5, 2: 5, 3: 5, 5: 12})
        require(header[1] == 0 and 0 <= header[2] == header[3] <= MAX_FILE, 'page type/compression/size')
        page = fields(header[5], {1: 5, 2: 5, 3: 5, 4: 5}, {5: 12})
        require(page.get(5, {}) == {}, 'value statistics are disabled')
        require(0 < page[1] <= row_count - len(values), 'page value count')
        require((page[2], page[3], page[4]) == (0, 3, 3), 'page encoding')
        reader.take(header_reader.pos)
        payload = Reader(reader.take(header[3]))
        mask = definitions(payload, page[1], column['nullable'])
        cells = iter(plain(payload, PHYSICAL[column['type']], sum(mask)))
        values.extend(next(cells) if present else None for present in mask)
        require(payload.pos == len(payload.data), 'unused page payload')
        number += 1
        require(number <= 20000, 'page budget')
    require(len(values) == row_count, 'chunk row count')
    return values, number


def check_sizes(node, column, values):
    """Arrow writes size histograms even when value statistics are disabled."""
    nullable, text = column['nullable'], column['type'] == 'utf8'
    if not values or not (nullable or text):
        require(node is None, 'unexpected size statistics')
        return
    require(node is not None, 'missing size statistics')
    stats = fields(node, {2: 9, 3: 9} | ({1: 6} if text else {}))
    require(sequence(stats[2], 6, 0) == [], 'repetition histogram')
    nulls = values.count(None)
    require(sequence(stats[3], 6, 2) == ([nulls, len(values) - nulls] if nullable else []), 'definition histogram')
    if text:
        require(stats[1] == sum(len(v.encode('utf-8')) for v in values if v is not None), 'text byte statistics')


def read(data, columns):
    """Return all physical rows after checking schema and exact owned file regions."""
    require(12 <= len(data) <= MAX_FILE and data[:4] == data[-4:] == b'PAR1', 'file framing/size')
    footer_size = struct.unpack('<I', data[-8:-4])[0]
    start = len(data) - 8 - footer_size
    require(0 < footer_size <= 1024**2 and start >= 4, 'footer range')
    reader = Reader(data[start:-8])
    footer = fields(reader.value(12), {1: 5, 2: 9, 3: 6, 4: 9, 6: 8, 7: 9})
    require(reader.pos == footer_size, 'trailing footer bytes')
    require(footer[1] == 2 and footer[6] == b'parquet-cpp-arrow version 26.0.0', 'writer/version identity')
    require(1 <= len(columns) <= 32, 'column count')
    leaves = sequence(footer[2], 12, 33)
    require(leaves == [{3: (5, 0), 4: (8, b'schema'), 5: (5, len(columns))}]
            + [expected_leaf(c) for c in columns], 'physical/logical column schema differs')
    orders = sequence(footer[7], 12, 32)
    require(orders == [{1: (12, {})}] * len(columns), 'column ordering metadata')
    total = footer[3]
    require(0 <= total <= MAX_ROWS and total * len(columns) <= MAX_CELLS, 'row/cell budget')
    groups = sequence(footer[4], 12, 16)
    require(len(groups) == max(1, (total + 1023) // 1024), 'row-group count')
    decoded, cursor, row_cursor, page_total = [], 4, 0, 0
    for raw_group in groups:
        group = fields(raw_group, {1: 9, 2: 6, 3: 6, 5: 6, 6: 6})
        count = min(1024, total - row_cursor)
        require(group[3] == count and group[5] == (cursor if count else 0), 'row-group rows/offset')
        chunks = sequence(group[1], 12, 32)
        require(len(chunks) == len(columns), 'column-chunk count')
        group_start, arrays = cursor, []
        for raw_chunk, column in zip(chunks, columns):
            chunk = fields(raw_chunk, {2: 6, 3: 12})  # file_path intentionally excluded
            require(chunk[2] == 0, 'column-chunk legacy offset')
            meta = fields(chunk[3], {1: 5, 2: 9, 3: 9, 4: 5, 5: 6, 6: 6, 7: 6, 9: 6, 13: 9}, {16: 12})
            require(meta[1] == PHYSICAL[column['type']] and meta[4] == 0, 'physical type/codec')
            require(sequence(meta[2], 5, 2) == ([3, 0] if count else [3]), 'chunk encodings')
            require(sequence(meta[3], 8, 1) == [column['name'].encode('ascii')], 'column path')
            size = meta[7]
            require(meta[5] == count and 0 <= size == meta[6] <= start - cursor, 'chunk count/size')
            require(meta[9] == (cursor if count else 0), 'noncontiguous/overlapping chunk region')
            if count:
                values, number = pages(memoryview(data)[cursor:cursor + size], column, count)
            else:
                require(size == 0, 'empty table payload')
                values, number = [], 0
            stats = sequence(meta[13], 12, 1)
            require(stats == ([{1: (5, 0), 2: (5, 0), 3: (5, number)}] if count else []), 'page encoding statistics')
            check_sizes(meta.get(16), column, values)
            arrays.append(values)
            cursor += size
            page_total += number
            require(page_total <= 20000, 'total page budget')
        require(group[2] == group[6] == cursor - group_start, 'row-group byte size')
        decoded.extend([list(row) for row in zip(*arrays)])
        row_cursor += count
    require(cursor == start and row_cursor == total, 'unowned bytes or row count')
    require(sum(len(v.encode('utf-8')) for row in decoded for v in row if isinstance(v, str)) <= 8 * 1024**2,
            'aggregate text budget')
    return decoded
