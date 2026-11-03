# Copyright (C) 2026 David L F Gaden
"""Host-safe streaming hashes and closed parallel VTK XML artifact manifests."""
import hashlib
from pathlib import Path
import xml.etree.ElementTree as ET
from schemaxis.errors import fail

METADATA = {'.pvtp', '.pvtu', '.vtm', '.vtpc', '.vtpd', '.pvti', '.pvtr', '.pvts'}


from schemaxis.artifacts import file_digest


def members(path):
    """Follow every metadata reference, rejecting missing/escaping members."""
    root = Path(path).resolve()
    base = root.parent
    pending, seen = [root], set()
    while pending:
        current = pending.pop()
        if current in seen:
            continue
        if not current.is_relative_to(base) or not current.is_file():
            fail('VERIFICATION_FAILED', 'parallel output member is absent or escapes output directory', str(current))
        seen.add(current)
        if current.suffix in METADATA:
            try:
                for _, element in ET.iterparse(current, events=('end',)):
                    for key in ('Source', 'file'):
                        if key in element.attrib:
                            reference = Path(element.attrib[key])
                            if reference.is_absolute():
                                fail('VERIFICATION_FAILED', 'parallel output contains an absolute reference', str(current))
                            pending.append((current.parent/reference).resolve())
                    element.clear()
            except ET.ParseError as error:
                fail('VERIFICATION_FAILED', 'parallel metadata is invalid XML', str(current), reason=str(error))
    return sorted(seen)


def manifest(path):
    return [{'file': str(member), 'sha256': file_digest(member)} for member in members(path)]


def verify_manifest(artifact):
    if artifact.get('files') != manifest(artifact['file']):
        fail('VERIFICATION_FAILED', 'parallel artifact manifest differs from referenced files', artifact['file'])


def canonical(records):
    import json
    return sorted(json.dumps(record['data'], sort_keys=True) for record in records if 'data' in record)


def validate_ranks(records, ranks):
    if (not isinstance(records, list) or len(records) != ranks
            or any(not isinstance(record, dict) for record in records)
            or [record.get('rank') for record in records] != list(range(ranks))
            or any(type(record.get('rank')) is not int or type(record.get('size')) is not int
                   or record['size'] != ranks or 'error' in record for record in records)):
        fail('VERIFICATION_FAILED', 'rank evidence is missing or invalid')


def verify_piece_evidence(artifact, ranks):
    import json
    evidence = artifact.get('verification', {})
    before, after = evidence.get('before', []), evidence.get('after', [])
    validate_ranks(before, ranks)
    validate_ranks(after, ranks)
    if (evidence.get('method') != 'exact-per-piece-v1' or evidence.get('gatheredGeometry') is not False
            or any(not isinstance(record.get('data'), dict) and record.get('empty') is not True for record in before+after)
            or not canonical(before) or canonical(before) != canonical(after)
            or hashlib.sha256(json.dumps(canonical(before)).encode()).hexdigest() != artifact.get('dataDigest')):
        fail('VERIFICATION_FAILED', 'distributed geometry verification differs')


def verify_reduction_evidence(artifact, ranks):
    import csv
    records = artifact.get('reductionEvidence', [])
    validate_ranks(records, ranks)
    populated = [record for record in records if 'values' in record]
    if len(populated) != 1 or artifact.get('gatheredGeometry') is not False:
        fail('VERIFICATION_FAILED', 'global reduction evidence differs')
    headers = ['index', *populated[0]['headers']]
    rows = [[0, *populated[0]['values']]]
    if artifact.get('columns') != headers or artifact.get('values') != rows or artifact.get('rows') != 1:
        fail('VERIFICATION_FAILED', 'reduced measurement differs from native result')
    with Path(artifact['file']).open(newline='') as stream:
        reader = csv.reader(stream)
        if next(reader, None) != headers or [[float(value) for value in row] for row in reader] != rows:
            fail('VERIFICATION_FAILED', 'reduced measurement differs from its CSV')
