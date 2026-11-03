# Copyright (C) 2026 David L F Gaden
"""Human-readable names for verified workflow outputs, as a post-verification view.

Native publication names stay unchanged because receipts and digests depend on
them. After a run verifies, ``apply`` creates ``named/`` beside the evidence,
with hard links (or copies across filesystems) named by a pattern, and
``named/naming.json`` mapping each name to its verified source and sha256.
Naming never overwrites a file; a collision fails the naming step only.
"""
from collections import Counter
import errno
import hashlib
import json
import math
import os
from pathlib import Path
import re
import shutil

from .errors import fail
from . import storage

VERSION = 'schemaxis.output-naming/1'
DEFAULT_PATTERN = '{index}-{operation}-{output}{ext}'
DEFAULT_WIDTH = 6
_TOKEN = re.compile(r'\{([^{}]*)\}')
_SIMPLE = ('index', 'operation', 'output', 'artifact', 'ext')
_PARAMETER = r'param:[A-Za-z][A-Za-z0-9_.-]*'
_AXIS = r'axis:[A-Za-z0-9_.-]+'
_LITERAL = r'[A-Za-z0-9_.+=,@-]*'
_MAX_PATTERN = 256
_MAX_NAME = 255
_MANIFEST = 'naming.json'


def validate_width(width, location='$.indexWidth'):
    if type(width) is not int or not 1 <= width <= 12:
        fail('INVALID_NAMING', 'index width must be an integer from 1 to 12', location)
    return width


def validate_pattern(pattern, location='$.pattern'):
    """Return the tokens of a safe single-component file name pattern."""
    if not isinstance(pattern, str) or not pattern or len(pattern) > _MAX_PATTERN:
        fail('INVALID_NAMING', 'pattern must be a nonempty string of at most 256 characters', location)
    tokens, position = [], 0
    for match in _TOKEN.finditer(pattern):
        literal = pattern[position:match.start()]
        if not re.fullmatch(_LITERAL, literal):
            fail('INVALID_NAMING', 'literal text may contain letters, digits and _ . + = , @ - only', location,
                 literal=literal)
        token = match.group(1)
        if token not in _SIMPLE and not re.fullmatch(_PARAMETER, token) and not re.fullmatch(_AXIS, token):
            fail('INVALID_NAMING', 'unknown token; use {index}, {operation}, {output}, {param:ID}, {axis:NAME}, '
                 '{artifact} or {ext}', location, token=token)
        tokens.append(token)
        position = match.end()
    if not re.fullmatch(_LITERAL, pattern[position:]):
        fail('INVALID_NAMING', 'literal text may contain letters, digits and _ . + = , @ - only', location,
             literal=pattern[position:])
    if not tokens:
        fail('INVALID_NAMING', 'pattern needs at least one token, such as {index}', location)
    if pattern.startswith('.'):
        fail('INVALID_NAMING', 'names must not start with a dot', location)
    return tokens


def _number(value):
    if type(value) is int:
        text = str(value)
    else:
        if not math.isfinite(value):
            fail('INVALID_NAMING', 'cannot name a nonfinite number')
        text = '{:.12g}'.format(value)
        if 'e' not in text and '.' in text:
            text = text.rstrip('0').rstrip('.')
    return text.replace('+', '').replace('-', 'm').replace('.', 'p')


def sanitise(value):
    """Render one token value as a portable file name fragment.

    Numbers are compact (``0.5`` -> ``0p5``, ``-2`` -> ``m2``); booleans are
    ``yes``/``no``; in text, ``.`` becomes ``p`` and anything outside letters,
    digits, ``_`` and ``-`` becomes ``_``. Numeric vectors join with ``_``.
    """
    if type(value) is bool:
        return 'yes' if value else 'no'
    if type(value) in (int, float):
        return _number(value)
    if value is None:
        return 'none'
    if isinstance(value, str):
        text = re.sub(r'[^A-Za-z0-9_-]', '_', value.replace('.', 'p'))
        return text or '_'
    if isinstance(value, list) and value and all(type(item) in (bool, int, float, str) for item in value):
        return '_'.join(sanitise(item) for item in value)
    fail('INVALID_NAMING', 'only scalars and flat lists can appear in a name', kind=type(value).__name__)


def _render(pattern, entry, index, width):
    def token(match):
        key = match.group(1)
        if key == 'index':
            return str(index).zfill(width)
        if key == 'ext':
            return entry.get('ext', '')
        if key == 'artifact':
            return str(entry['artifact'])
        if key in ('operation', 'output'):
            return sanitise(entry.get(key) or entry.get('stem') or 'output')
        group, _, identity = key.partition(':')
        values = entry.get('parameters' if group == 'param' else 'axes', {})
        if identity not in values:
            fail('INVALID_NAMING', ('parameter ' if group == 'param' else 'axis ') + identity
                 + ' has no value for this output', '$.pattern', token=key, operation=entry.get('operation'))
        return sanitise(values[identity])
    name = _TOKEN.sub(token, pattern)
    if len(name.encode('utf-8')) > _MAX_NAME or name in ('.', '..') or name == _MANIFEST:
        fail('INVALID_NAMING', 'pattern produced an unusable file name', '$.pattern', name=name[:300])
    return name


def preview(pattern, entries, index_width=DEFAULT_WIDTH):
    """Names for a UI preview; entries carry operation, output, artifact, ext and values.

    Each entry may contain ``operation``, ``output``, ``artifact`` (default 0),
    ``ext`` (with its dot), ``parameters`` and ``axes``. The index is the 1-based
    position in ``entries``. Collisions are reported, not raised.
    """
    validate_pattern(pattern)
    validate_width(index_width)
    if not isinstance(entries, list) or len(entries) > 100000:
        fail('INVALID_NAMING', 'entries must be a list of at most 100000 objects', '$.entries')
    names, seen, collisions = [], set(), []
    for index, entry in enumerate(entries, start=1):
        if not isinstance(entry, dict):
            fail('INVALID_NAMING', 'each entry must be an object', '$.entries/' + str(index - 1))
        value = _render(pattern, {'artifact': 0, **entry}, index, index_width)
        if value in seen:
            collisions.append(value)
        seen.add(value)
        names.append(value)
    return {'names': names, 'collisions': sorted(set(collisions))}


def _load(path):
    try:
        return json.loads(Path(path).read_text(encoding='utf-8'))
    except (OSError, ValueError) as error:
        fail('VERIFICATION_FAILED', 'missing or malformed run evidence: ' + str(error), str(path))


def _axis_values(directory, indices):
    """Named study axes with their selected values (positions when not scalar)."""
    from .adaptor_runtime import InputProgram
    program = InputProgram(_load(directory / 'authored.json'), workflow=True)
    result = {}
    for group, position in indices.items():
        if '/axis:' not in group:
            continue
        axis = group.rsplit('/axis:', 1)[1]
        items = program.explicit.get(group, ([],))[0]
        value = items[position] if 0 <= position < len(items) else position
        scalar = type(value) in (bool, int, float, str) or (
            isinstance(value, list) and all(type(item) in (int, float) for item in value))
        result.setdefault(axis, value if scalar else position)
    return result


def _collect(directory, axes):
    """Verified artifacts in deterministic order: states, operations, artifacts."""
    from .adaptor_runtime import is_common
    saved = _load(directory / 'result.json')
    if is_common(directory):
        for state in saved.get('states', []):
            values = {**axes, **_axis_values(directory, state.get('indices', {}))}
            yield from _collect(directory / state['directory'], values)
        return
    if saved.get('executionVersion') == 2:
        receipts = [(job['operation'], Path(job['directory'])) for job in saved['jobs']]
    else:
        receipts = [(item['id'], directory / item['id']) for item in saved['operations']]
    counters = {}
    for operation, target in receipts:
        for artifact in _load(target / 'verification.json')['artifacts']:
            index = counters.get(operation, 0)
            counters[operation] = index + 1
            yield {'operation': operation, 'artifact': index, 'record': artifact, 'axes': dict(axes)}


def _sha256(path):
    digest = hashlib.sha256()
    with open(path, 'rb') as stream:
        for block in iter(lambda: stream.read(1048576), b''):
            digest.update(block)
    return digest.hexdigest()


def _hard_link(source, target):
    os.link(source, target)


def _publish(source, target):
    """Hard-link, or copy across devices; never replace an existing name."""
    try:
        _hard_link(source, target)
        return 'hardlink'
    except FileExistsError:
        fail('NAMING_COLLISION', 'named output already exists; naming never overwrites', str(target))
    except OSError as error:
        if error.errno not in (errno.EXDEV, errno.EPERM, errno.EMLINK, errno.ENOTSUP):
            raise
    with open(source, 'rb') as reader, open(target, 'xb') as writer:
        shutil.copyfileobj(reader, writer)
    return 'copy'


def apply(run_directory, pattern, *, index_width=DEFAULT_WIDTH, parameters=None, outputs=None):
    """Verify a run, then publish ``named/`` links and ``named/naming.json``.

    ``parameters`` maps parameter IDs to bound values (for ``{param:ID}``);
    ``outputs`` is the template's named output aliases (for ``{output}``).
    Unaliased artifacts use their native file stem for ``{output}``. The index
    is a 1-based run-wide ordinal in deterministic evidence order.
    """
    from . import workflow
    validate_pattern(pattern)
    validate_width(index_width)
    parameters = {} if parameters is None else parameters
    outputs = {} if outputs is None else outputs
    if not isinstance(parameters, dict) or not isinstance(outputs, dict):
        fail('INVALID_NAMING', 'parameters and outputs must be objects', '$')
    directory = Path(run_directory).expanduser().resolve()
    verification = workflow.verify(directory)
    aliases = {}
    for alias, item in outputs.items():
        if isinstance(item, dict):
            aliases.setdefault((item.get('operation'), item.get('artifact')), alias)
    entries = []
    for ordinal, item in enumerate(_collect(directory, {}), start=1):
        source = Path(item['record']['file'])
        source = (source if source.is_absolute() else directory / source).resolve()
        try:
            relative = source.relative_to(directory)
        except ValueError:
            fail('VERIFICATION_FAILED', 'verified artifact lies outside the run directory', str(source))
        sha256 = _sha256(source)
        if item['record'].get('sha256') not in (None, sha256):
            fail('VERIFICATION_FAILED', 'artifact changed after verification', str(relative))
        suffix = ''.join(source.suffixes[-1:])
        entry = {'operation': item['operation'], 'artifact': item['artifact'], 'ext': suffix,
                 'output': aliases.get((item['operation'], item['artifact'])),
                 'stem': source.name[:-len(suffix)] if suffix else source.name,
                 'parameters': parameters, 'axes': item['axes']}
        entries.append((_render(pattern, entry, ordinal, index_width), relative, sha256, entry, item))
    counts = Counter(entry[0] for entry in entries)
    duplicates = sorted(value for value, count in counts.items() if count > 1)
    if duplicates:
        fail('NAMING_COLLISION', 'the pattern gives several outputs the same name; add {index} or another token',
             '$.pattern', names=duplicates[:20])
    named = directory / 'named'
    if named.is_symlink() or named.exists() and (not named.is_dir() or any(named.iterdir())):
        fail('OUTPUT_EXISTS', 'named outputs already exist; remove named/ to rename this run', str(named))
    named.mkdir(exist_ok=True)
    mapping = {}
    for value, relative, sha256, entry, item in entries:
        method = _publish(directory / relative, named / value)
        if method == 'copy' and _sha256(named / value) != sha256:
            fail('VERIFICATION_FAILED', 'copied output differs from its verified source', str(named / value))
        mapping[value] = {'source': relative.as_posix(), 'sha256': sha256, 'operation': entry['operation'],
                          'artifact': entry['artifact'], 'output': entry['output'],
                          'kind': item['record'].get('kind', item['record'].get('identity', {}).get('kind')),
                          'axes': entry['axes'], 'method': method}
    manifest = {'version': VERSION, 'pattern': pattern, 'indexWidth': index_width,
                'verification': verification, 'names': mapping}
    storage.atomic(named / _MANIFEST, (json.dumps(manifest, indent=2) + '\n').encode('utf-8'), exclusive=True)
    return {'directory': str(named), 'manifest': str(named / _MANIFEST), **manifest}
