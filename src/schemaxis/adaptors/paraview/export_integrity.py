"""Host-side checks of retained ParaView export evidence and exported array values.

Nothing here imports a native application. The receipt checks decide whether the
retained export directory still matches what the native run reported and whether the
reported verification evidence is well formed. They do not re-read scientific values
from the file and do not establish that the exported numbers are scientifically
correct: that remains the native comparison recorded in the receipt.
"""
import math
import re
from pathlib import Path
from schemaxis.artifacts import file_digest
from schemaxis.errors import fail

DIGEST = re.compile(r'[0-9a-f]{64}')
CSV_ASSOCIATIONS = ('Point Data', 'Cell Data', 'Row Data')


def require_finite(array, association, location='$', readback=False):
    """Fault when a floating-point array holds NaN or an infinity.

    A nonfinite value cannot be compared for equality or tolerance, so a verified
    export refuses it explicitly instead of reporting an unexplained value mismatch.
    """
    if array is None or array.GetDataType() == 13:  # VTK_STRING
        return
    if array.GetDataTypeAsString() not in ('float', 'double'):
        return
    components = array.GetNumberOfComponents()
    for tuple_index in range(array.GetNumberOfTuples()):
        for component in range(components):
            if not math.isfinite(array.GetComponent(tuple_index, component)):
                count = sum(1 for i in range(tuple_index, array.GetNumberOfTuples()) for c in range(components)
                            if not math.isfinite(array.GetComponent(i, c)))
                if readback:
                    fail('NONFINITE_ARTIFACT_DATA', 'the written file reads back NaN or infinite values',
                         location, array=array.GetName() or 'array', association=association, tuple=tuple_index,
                         component=component, recovery='treat the artifact as corrupt and export again in a new directory')
                fail('NONFINITE_DATA', 'the exported data contains NaN or infinite values, which no tolerance can verify',
                     location, array=array.GetName() or 'array', association=association, tuple=tuple_index,
                     component=component, nonfiniteValuesFromFirst=count,
                     recovery='replace or remove invalid values upstream, for example with pvCalculator '
                              'ReplaceInvalidResults, or export a node that omits the array')


def require_finite_points(data, location='$', readback=False):
    points = data.GetPoints() if hasattr(data, 'GetPoints') else None
    if points is not None:
        require_finite(points.GetData(), 'Points', location, readback)


def require_finite_fields(data, location='$', readback=False):
    """Point coordinates plus point and cell arrays of one dataset leaf."""
    require_finite_points(data, location, readback)
    for association, arrays in (('Point Data', data.GetPointData()), ('Cell Data', data.GetCellData())):
        for index in range(arrays.GetNumberOfArrays()):
            require_finite(arrays.GetAbstractArray(index), association, location, readback)


def require_finite_text(text, row, column, location='$'):
    """Fault when exported text parses as a nonfinite number."""
    try:
        value = float(text)
    except ValueError:
        return
    if not math.isfinite(value):
        fail('NONFINITE_ARTIFACT_DATA', 'the written file holds a nonfinite value', location,
             row=row, column=column, text=text[:32],
             recovery='remove nonfinite values from the exported node and export again in a new directory')


def _scan(value, location, found):
    if isinstance(value, float) and not math.isfinite(value):
        found.append(location)
    elif isinstance(value, dict):
        for key, item in value.items():
            _scan(item, f'{location}.{key}', found)
    elif isinstance(value, (list, tuple)):
        for index, item in enumerate(value):
            _scan(item, f'{location}[{index}]', found)


def _is_count(value, minimum=0):
    return type(value) is int and value >= minimum


def _is_number(value):
    return type(value) in (int, float) and math.isfinite(value)


def _strings(value, minimum=0, unique=True):
    return (isinstance(value, list) and len(value) >= minimum and all(isinstance(v, str) for v in value)
            and (not unique or len(set(value)) == len(value)))


def check_verification(evidence, expected, location):
    """Shape and consistency of the recorded native verification for one export."""
    def malformed(reason, **detail):
        fail('MALFORMED_EXPORT_EVIDENCE', 'recorded export verification evidence is malformed', location,
             reason=reason, **detail)
    if not isinstance(evidence, dict):
        malformed('verification is not an object')
    comparison = expected['comparison']
    if evidence.get('comparison') != comparison:
        malformed('verification comparison differs from the authored comparison',
                  recorded=evidence.get('comparison'), authored=comparison)
    tolerance = expected['tolerance']
    if comparison == 'table':
        if not _is_count(evidence.get('rows')):
            malformed('rows is not a count')
        if not _strings(evidence.get('verifiedColumns'), 1):
            malformed('no uniquely named verified columns')
        if not _strings(evidence.get('additionalColumns'), unique=False) or set(evidence['additionalColumns']) & set(evidence['verifiedColumns']):
            malformed('additional columns are malformed or overlap the verified columns')
        if evidence.get('association') not in CSV_ASSOCIATIONS:
            malformed('association is not a verified CSV association', association=evidence.get('association'))
        if not isinstance(evidence.get('delimiter'), str) or len(evidence['delimiter']) != 1:
            malformed('delimiter is not one character')
    elif comparison == 'exact':
        if not isinstance(evidence.get('data'), dict) or not evidence['data']:
            malformed('exact snapshot is absent')
    elif comparison == 'semantic':
        associations = evidence.get('associations')
        if (not isinstance(associations, dict) or set(associations) != {'point', 'cell'}
                or any(not isinstance(item, dict) or not _is_count(item.get('records')) or not _strings(item.get('fields'), unique=False)
                       for item in associations.values())):
            malformed('semantic point and cell record counts are absent')
        if evidence.get('tolerance') != tolerance:
            malformed('verification tolerance differs from the authored tolerance', recorded=evidence.get('tolerance'))
    elif comparison == 'geometry':
        if not _is_count(evidence.get('surfaceCells'), 1):
            malformed('geometry comparison recorded no surface cells')
        if evidence.get('tolerance') != tolerance:
            malformed('verification tolerance differs from the authored tolerance', recorded=evidence.get('tolerance'))
    elif comparison == 'pixels':
        if evidence.get('format') == 'vtk-json-image':
            if not _strings(evidence.get('fields'), 1):
                malformed('JSON image verified no arrays')
            if evidence.get('tolerance') != tolerance:
                malformed('verification tolerance differs from the authored tolerance', recorded=evidence.get('tolerance'))
        else:
            maximum = evidence.get('maximumError')
            if not _is_number(maximum) or maximum < 0 or maximum > tolerance:
                malformed('maximum pixel error is absent, negative or beyond the authored tolerance',
                          maximumError=maximum, tolerance=tolerance)
            dimensions = evidence.get('dimensions')
            if not isinstance(dimensions, list) or len(dimensions) != 3 or any(not _is_count(v, 1) for v in dimensions):
                malformed('image dimensions are absent')


def verify_export_evidence(directory, artifact, expected, native, location, *, basename='data'):
    """Check one retained export artifact against its authored settings.

    `directory` is the run directory, `expected` the planned export settings and
    `native` the writer's native class name. Faults are structured and name the member.
    """
    directory = Path(directory).resolve()
    found = []
    _scan(artifact, 'artifact', found)
    if found:
        fail('NONFINITE_EVIDENCE', 'retained export evidence holds NaN or infinite numbers', location, at=found[:8])
    check_verification(artifact.get('verification'), expected, location)
    main = Path(artifact['file'])
    export_directory = main.parent.resolve()
    if export_directory == directory or not export_directory.is_relative_to(directory):
        fail('VERIFICATION_FAILED', 'export file is not inside its own output directory', str(main))
    suffix = expected['extension']
    names = {f'{basename}.{suffix}'} | ({f'{basename}.0.case'} if native == 'EnSightWriter' else set())
    if main.name not in names:
        fail('VERIFICATION_FAILED', 'export file name differs from the managed name', str(main), expected=sorted(names))
    members = artifact.get('files')
    if not isinstance(members, list) or not members or any(
            not isinstance(m, dict) or set(m) != {'file', 'sha256'} or not isinstance(m['file'], str)
            or not isinstance(m['sha256'], str) or not DIGEST.fullmatch(m['sha256']) for m in members):
        fail('MALFORMED_EXPORT_EVIDENCE', 'export member list is absent or malformed', location)
    listed = [Path(m['file']).resolve() for m in members]
    if len(set(listed)) != len(listed) or main.resolve() not in listed:
        fail('MALFORMED_EXPORT_EVIDENCE', 'export members repeat or omit the export file', location)
    if any(path.parent != export_directory and not path.is_relative_to(export_directory) for path in listed):
        fail('VERIFICATION_FAILED', 'export member lies outside the export directory', location)
    recorded = {Path(m['file']).resolve(): m['sha256'] for m in members}
    if recorded[main.resolve()] != artifact.get('sha256'):
        fail('VERIFICATION_FAILED', 'export file digest differs from its member record', str(main))
    present = []
    for path in sorted(export_directory.rglob('*')):
        if path.is_symlink():
            fail('VERIFICATION_FAILED', 'export directory holds a symbolic link', str(path))
        if path.is_file():
            present.append(path.resolve())
        elif not path.is_dir():
            fail('VERIFICATION_FAILED', 'export directory holds a special file', str(path))
    # The publication layer adds one '<member>.metadata.json' description beside each member after the
    # run; it is not part of the native record, so only that exact name next to a listed member is allowed.
    sidecars = {p.with_name(p.name + '.metadata.json') for p in listed}
    missing = [str(p) for p in listed if p not in present]
    unlisted = [str(p) for p in present if p not in recorded and p not in sidecars]
    if missing or unlisted:
        fail('VERIFICATION_FAILED', 'export directory membership differs from the retained record', str(export_directory),
             missing=missing[:8], unlisted=unlisted[:8])
    for path, digest in recorded.items():
        if file_digest(path) != digest:
            fail('VERIFICATION_FAILED', 'artifact member digest differs', str(path))
