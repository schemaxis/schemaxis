"""Typed per-item metadata records from located payloads and the catalogue (standard library only, no native process).

Every requested field gets exactly one state:
present, absent (the family was understood and has no such value), unreadable (present but malformed), unsupported (outside the reader),
ambiguous (duplicate locations or conflicting sources) or, for derived fields, the strongest state of their inputs. Each source of a field
keeps its own state and location. Concordance between sources is the literal equality of their canonical values: no source is
preferred and no normative reconciliation standard is claimed.
"""
from fractions import Fraction

from schemaxis.adaptors.exiftool import catalogue, codecs, containers, iptc as iptc_reader, tiff, xmp as xmp_reader

PROOF = 'independent'
STRENGTH = ('ambiguous', 'unreadable', 'unsupported', 'absent')
UNASSESSED = ('unreadable', 'unsupported')


class Payloads:
    """Decoded payload state of one file: each family is ('ok', data), ('absent',), ('notApplicable',), ('ambiguous', code, message) or ('error', state, code, message)."""

    def __init__(self, located, sidecar=None):
        supported = containers.CAPABILITIES[located['container']]
        self.container, self.frame, self.notes = located['container'], located['frame'], list(located['notes'])
        self.exif = self.family('exif', supported, located['exif'], self.read_exif)
        self.xmp = self.family('xmp', supported, located['xmp'], self.read_xmp)
        self.iptc = self.family('iptc', supported, located['iptc'], self.read_iptc)
        self.frame_state = ('notApplicable',) if 'container' not in supported else ('ok', self.frame) if self.frame else ('absent',)
        self.sidecar = None if sidecar is None else self.family('xmp', ('xmp',), sidecar['xmp'], self.read_xmp)

    @staticmethod
    def family(name, supported, payloads, reader):
        if name not in supported:
            return ('notApplicable',)
        if not payloads:
            return ('absent',)
        if len(payloads) > 1:
            return ('ambiguous', name.upper() + '_SEGMENT_REPEATED', 'the file carries %d %s payloads, so no single one is authoritative' % (len(payloads), name.upper()))
        return reader(payloads[0])

    @staticmethod
    def read_exif(payload):
        try:
            return ('ok', tiff.walk(payload))
        except tiff.Damaged as error:
            return ('error', 'unreadable', error.code, error.message)

    @staticmethod
    def read_xmp(payload):
        try:
            return ('ok', xmp_reader.parse(payload))
        except xmp_reader.Problem as error:
            return ('error', 'unsupported' if error.code == 'XMP_ENCODING_UNSUPPORTED' else 'unreadable', error.code, error.message)

    @staticmethod
    def read_iptc(app13):
        try:
            blocks = [data for ident, data in iptc_reader.resources(app13) if ident == 0x0404]
            if not blocks:
                return ('absent',)
            if len(blocks) > 1:
                return ('ambiguous', 'IPTC_RESOURCE_REPEATED', 'the APP13 segment holds more than one IPTC-NAA resource')
            return ('ok', iptc_reader.datasets(blocks[0]))
        except iptc_reader.Problem as error:
            return ('error', 'unsupported' if error.code in ('IPTC_CONTAINER_UNSUPPORTED', 'IPTC_EXTENDED_UNSUPPORTED') else 'unreadable', error.code, error.message)


def source(spec, state, value=None, code=None, message=None, **extra):
    record = {'family': spec['family'], 'location': location(spec), 'state': state}
    if value is not None:
        record['canonical'] = value
    if code:
        record['code'] = code
        record['message'] = message
    record.update(extra)
    return record


def location(spec):
    if spec['family'] == 'exif':
        return '%s:%s' % (spec['ifd'], spec['tag'])
    if spec['family'] == 'xmp':
        return spec['property']
    if spec['family'] == 'iptc':
        return '%d:%d' % (spec['record'], spec['dataset'])
    return 'frame.' + spec['property']


def companion_value(entry):
    """What one companion entry reads as (text or integer), or None when this copy is itself unreadable (only the copy count is then anchored)."""
    try:
        return codecs.exif_text(entry) if entry.kind == 2 else codecs.exif_integer(entry)
    except codecs.ValueProblem:
        return None


def decode_exif(spec, payloads):
    state = payloads.exif
    if state[0] != 'ok':
        return from_family_state(spec, state)
    group = state[1]['ifds'].get(spec['ifd'])
    if group is None:
        return source(spec, 'absent')
    if group[0] == 'error':
        return source(spec, 'unreadable', code=group[1], message=group[2])
    tag = int(spec['tag'], 16)
    entries = [e for e in group[1] if e.tag == tag]
    if not entries:
        return source(spec, 'absent')
    if len(entries) > 1:
        return source(spec, 'ambiguous', code='EXIF_TAG_REPEATED', message='the tag is repeated %d times in %s' % (len(entries), spec['ifd']), instances=len(entries))

    def companion(name):
        found = [e for e in group[1] if e.tag == int(spec['companion'][name], 16)]
        if len(found) > 1:
            raise codecs.Repeated('EXIF_COMPANION_REPEATED', 'the reference tag is repeated %d times in %s' % (len(found), spec['ifd']), name, len(found),
                                  [companion_value(e) for e in found])
        return found[0] if found else None
    decoder = codecs.CODECS[spec['codec']][1]
    try:
        value = decoder(entries[0], companion, spec['values']) if spec['codec'] == 'exifEnum' else decoder(entries[0], companion)
        companions = {name: None if companion(name) is None else codecs.exif_text(companion(name)) if companion(name).kind == 2 else codecs.exif_integer(companion(name))
                      for name in spec.get('companionNative', {})}
    except codecs.ValueProblem as problem:
        return from_problem(spec, problem)
    return source(spec, 'present', value, _companions=companions)


def decode_xmp(spec, payloads, sidecar=False):
    state = payloads.sidecar if sidecar else payloads.xmp
    result = decode_xmp_state(spec, state)
    if sidecar:
        result['family'] = 'xmp-sidecar'
    return result


def decode_xmp_state(spec, state):
    if state[0] != 'ok':
        return from_family_state(spec, state)
    found = state[1].get(spec['property'])
    if not found:
        return source(spec, 'absent')
    if len(found) > 1:
        return source(spec, 'ambiguous', code='XMP_PROPERTY_REPEATED', message='the property occurs %d times' % len(found), instances=len(found))
    try:
        value = codecs.CODECS[spec['codec']][1](found[0])
    except codecs.ValueProblem as problem:
        return from_problem(spec, problem)
    return source(spec, 'present', value)


def decode_iptc(spec, payloads):
    state = payloads.iptc
    if state[0] != 'ok':
        return from_family_state(spec, state)
    sets = state[1]['datasets']
    values = sets.get((spec['record'], spec['dataset']))
    if not values:
        return source(spec, 'absent')

    def companion(name):
        return sets.get(tuple(spec['companion'][name]))
    try:
        value = codecs.CODECS[spec['codec']][1](values, state[1]['charset'], companion)
    except codecs.ValueProblem as problem:
        return from_problem(spec, problem)
    return source(spec, 'present', value, charset=state[1]['charset'])


def decode_container(spec, payloads):
    state = payloads.frame_state
    if state[0] in ('notApplicable', 'absent'):
        return source(spec, state[0])
    return source(spec, 'present', codecs.CODECS[spec['codec']][1](state[1]))


def from_family_state(spec, state):
    kind = state[0]
    if kind in ('absent', 'notApplicable'):
        return source(spec, kind)
    if kind == 'ambiguous':
        return source(spec, 'ambiguous', code=state[1], message=state[2])
    return source(spec, state[1], code=state[2], message=state[3])


def from_problem(spec, problem):
    state = 'ambiguous' if isinstance(problem, codecs.Ambiguous) else 'absent' if isinstance(problem, codecs.Missing) else 'unsupported' if isinstance(problem, codecs.Unsupported) else 'unreadable'
    extra = {'companion': problem.companion, 'instances': problem.instances, '_repeatedValues': problem.values} if isinstance(problem, codecs.Repeated) else {}
    return source(spec, state, code=problem.code, message=problem.message, **extra)


DECODERS = {'exif': decode_exif, 'xmp': decode_xmp, 'iptc': decode_iptc, 'container': decode_container}


class Record:
    """Lazily computed field records of one file."""

    def __init__(self, payloads, version=catalogue.VERSION):
        self.payloads, self.cache, self.version = payloads, {}, version

    def field(self, name):
        if name not in self.cache:
            spec = catalogue.fields(self.version)[name]
            self.cache[name] = self.derived(name, spec) if 'derive' in spec else self.aggregate(name, spec, self.sources(spec))
        return self.cache[name]

    def sources(self, spec):
        found = [DECODERS[s['family']](s, self.payloads) | {'_spec': s} for s in spec['sources']]
        if self.payloads.sidecar is not None:
            found += [decode_xmp(s, self.payloads, True) | {'_spec': s} for s in spec['sources'] if s['family'] == 'xmp']
        return found

    def aggregate(self, name, spec, sources):
        live = [s for s in sources if s['state'] != 'notApplicable']
        present = [s for s in live if s['state'] == 'present']
        for s in present:
            if spec['type'] == 'textList' and isinstance(s['canonical'], str):
                s['canonical'] = (s['canonical'],)
        record = {'field': name, 'type': spec['type'], 'unit': spec['unit'], 'privacy': spec['privacy'], 'proofLevel': PROOF, 'sources': sources}
        if not live:
            return {**record, 'state': 'unsupported', 'value': None, 'reconciliation': 'none', 'canonical': None}
        values = [s['canonical'] for s in present]
        if any(s['state'] == 'ambiguous' for s in live):
            return {**record, 'state': 'ambiguous', 'value': None, 'reconciliation': 'ambiguous-source', 'canonical': None}
        if present:
            if not concordant(spec, values):
                return {**record, 'state': 'ambiguous', 'value': None, 'reconciliation': 'conflicting', 'canonical': None}
            if any(s['state'] in UNASSESSED for s in live):
                # a source that exists but could not be read or is outside this reader cannot be said to agree or disagree
                reconciliation = 'partially-assessed'
            elif len(present) == 1:
                reconciliation = 'single-source'
            else:
                reconciliation = 'consistent'
            return {**record, 'state': 'present', 'canonical': values[0], 'reconciliation': reconciliation, 'value': None}
        for state in STRENGTH[1:]:
            if any(s['state'] == state for s in live):
                return {**record, 'state': state, 'value': None, 'reconciliation': 'none', 'canonical': None}
        return {**record, 'state': 'absent', 'value': None, 'reconciliation': 'none', 'canonical': None}

    def derived(self, name, spec):
        rule = spec['derive']['rule']
        inputs = [self.field(x) for x in spec['derive']['from']]
        record = {'field': name, 'type': spec['type'], 'unit': spec['unit'], 'privacy': spec['privacy'], 'proofLevel': PROOF, 'sources': [],
                  'derivedFrom': list(spec['derive']['from']), 'rule': rule, 'value': None, 'canonical': None, 'reconciliation': 'derived'}
        for state in STRENGTH:
            if any(i['state'] == state for i in inputs):
                return {**record, 'state': state, 'reconciliation': 'none' if state == 'absent' else 'derived-from-' + state + '-input'}
        a, b = inputs
        canonical = codecs.to_utc(a['canonical'], b['canonical']) if rule == 'utcFromLocalOffset' else a['canonical'] + 'T' + b['canonical'] + 'Z'
        return {**record, 'state': 'present', 'canonical': canonical}


def concordant(spec, values):
    """Literal equality of canonical values, or, for a field that declares ``concordance.within``, agreement within that exact bound (a serialisation bound)."""
    if 'concordance' in spec:
        bound = catalogue.tolerance(spec['concordance']['within'])
        return all(abs(v - values[0]) <= bound for v in values)
    return all(v == values[0] for v in values)


def publish_value(spec, canonical):
    """JSON value and optional exact text of a canonical value."""
    if canonical is None:
        return None, None
    if isinstance(canonical, Fraction):
        return codecs.number(canonical), codecs.exact_text(canonical)
    if isinstance(canonical, tuple):
        return list(canonical), None
    return canonical, None


def publish(record, version=catalogue.VERSION):
    """The JSON-safe published form of one field record (no Python-only values)."""
    spec = catalogue.fields(version)[record['field']]
    value, exact = publish_value(spec, record['canonical'])
    out = {'field': record['field'], 'state': record['state'], 'value': value, 'unit': record['unit'], 'type': record['type'], 'privacy': record['privacy'],
           'proofLevel': record['proofLevel'], 'reconciliation': record['reconciliation']}
    if exact is not None and exact != str(value):
        out['exact'] = exact
    if spec['type'] == 'code' and value is not None:
        out['label'] = spec['labels'].get(str(value))
    if 'derivedFrom' in record:
        out['derivedFrom'] = record['derivedFrom']
    out['sources'] = [publish_source(s) for s in record['sources']]
    if record['reconciliation'] == 'partially-assessed':
        out['unassessedSources'] = [{k: s[k] for k in ('family', 'location', 'state', 'code') if k in s} for s in record['sources'] if s['state'] in UNASSESSED]
    if record['reconciliation'] == 'conflicting':
        out['values'] = [{'family': s['family'], 'location': s['location'], 'value': publish_value(spec, s['canonical'])[0]} for s in record['sources'] if s['state'] == 'present']
    return out


def publish_source(s):
    out = {k: v for k, v in s.items() if k not in ('canonical', '_spec', '_companions', '_repeatedValues')}
    if 'canonical' in s:
        out['value'] = publish_value(None, s['canonical'])[0]
    return out


def build(located, names, sidecar=None, version=catalogue.VERSION):
    payloads = Payloads(located, sidecar)
    record = Record(payloads, version)
    return record, {name: record.field(name) for name in names}, payloads
