"""Device clock model of the time workflows (host-only, standard library, exact rationals).

Items are grouped by the device that recorded them (or by the author's declaration), references and simultaneity assertions give each group's clock error
(*skew*: recorded minus true, in seconds), and the result is a typed report with an explicit state for every group and item. Nothing is averaged away:
inconsistent evidence makes a group ``conflicting`` and lists every residual. A declared reference or assumption is labelled as declared; it is never
verified. There is no time zone, daylight-saving or leap-second knowledge.

An *item record* is ``{'id', 'wall' (ns | None), 'offset' (minutes | None), 'gpsUtc' (ns | None), 'device': {field: {'state', 'value'}},
'timeConflict': bool, 'subSecondConflict': bool}``; ``wall`` is the concordant recorded local time with its fraction, ``offset`` the recorded offset.
"""
from fractions import Fraction
import re

from schemaxis.adaptors.exiftool import timecalc as tc

IDENTIFIER = re.compile(r'[A-Za-z][A-Za-z0-9_]{0,31}')
RESERVED = re.compile(r'dev[0-9]+')
DEFAULT_KEYS = ('cameraMake', 'cameraModel', 'bodySerialNumber')
UNRESOLVED = ('ambiguous', 'unreadable')
MAX_REFERENCES, MAX_SIMULTANEOUS = 256, 256


class ClockProblem(ValueError):
    """An authored-document fault of the clock model with a stable code and an exact ``$`` location."""

    def __init__(self, code, message, location='$', **observed):
        super().__init__(message)
        self.code, self.message, self.location, self.observed = code, message, location, observed


def secs(ns):
    return Fraction(ns, tc.NS)


def text(value):
    """Exact decimal seconds of a Fraction (cut at 9 decimals, marked with a trailing ``~`` when not exact)."""
    out, exact = tc.decimal_text(value, 9)
    return out if exact else out + '~'


# ---------------------------------------------------------------- grouping
def device_key(item, keys):
    parts, unresolved = [], False
    for name in keys:
        field = item['device'].get(name) or {'state': 'absent'}
        unresolved = unresolved or field['state'] in UNRESOLVED
        parts.append([name, field['state'], field.get('value') if field['state'] == 'present' else None])
    return parts, unresolved


def group_items(items, spec, faulted=()):
    """Groups ``[{'id', 'key', 'declared', 'members'}]`` plus ``ungroupable`` ids and findings. ``spec`` is the planned ``groups`` member (or ``None``)."""
    spec = spec or {'by': 'recordedDevice'}
    ids = [i['id'] for i in items]
    faulted = set(faulted)
    overrides = {}
    for index, entry in enumerate(spec.get('itemOverrides', [])):
        at = '$.itemOverrides[%d]' % index
        if entry['item'] in faulted:
            continue
        if entry['item'] not in ids:
            raise ClockProblem('UNKNOWN_ITEM', 'itemOverrides names an item that is not in the media set', at + '.item', value=entry['item'][:64])
        if entry['item'] in overrides:
            raise ClockProblem('GROUP_MEMBERSHIP_INVALID', 'an item has more than one override', at + '.item', value=entry['item'])
        if not IDENTIFIER.fullmatch(entry['group']):
            raise ClockProblem('GROUP_MEMBERSHIP_INVALID', 'a group id is an ASCII letter followed by up to 31 letters, digits or underscores', at + '.group', value=entry['group'][:64])
        overrides[entry['item']] = entry['group']
    groups, order, findings, ungroupable = {}, [], [], []
    if spec['by'] == 'declared':
        owner = {}
        for gi, member in enumerate(spec['members']):
            at = '$.groups.members[%d]' % gi
            if not IDENTIFIER.fullmatch(member['group']) or member['group'] in groups:
                raise ClockProblem('GROUP_MEMBERSHIP_INVALID', 'declared group ids are unique identifiers', at + '.group', value=member['group'][:64])
            groups[member['group']] = {'id': member['group'], 'key': None, 'declared': True, 'members': []}
            order.append(member['group'])
            for item_id in [i for i in member['items'] if i not in faulted]:
                if item_id in owner:
                    raise ClockProblem('GROUP_MEMBERSHIP_INVALID', 'an item belongs to two declared groups', at + '.items', value=item_id[:64], groups=[owner[item_id], member['group']])
                owner[item_id] = member['group']
        unknown = sorted(set(owner) - set(ids))
        missing = [i for i in ids if i not in owner]
        if unknown or missing:
            raise ClockProblem('GROUP_MEMBERSHIP_INVALID', 'every media item must belong to exactly one declared group and every named item must exist', '$.groups.members', unknown=unknown[:20], uncovered=missing[:20])
        for item in items:
            groups[owner[item['id']]]['members'].append(item['id'])
        for gid in order:
            keys = {tuple(map(tuple, device_key(next(i for i in items if i['id'] == m), DEFAULT_KEYS)[0])) for m in groups[gid]['members']}
            if len(keys) > 1:
                findings.append({'code': 'declaredGroupMixesRecordedDevices', 'group': gid, 'devices': len(keys)})
            groups[gid]['recordedKeys'] = [list(map(list, k)) for k in sorted(keys, key=str)]
    else:
        keys_named = list(spec.get('keys', DEFAULT_KEYS))
        by_key = {}
        for item in items:
            if item['id'] in overrides:
                continue
            key, unresolved = device_key(item, keys_named)
            if unresolved:
                ungroupable.append(item['id'])
                continue
            marker = repr(key)
            if marker not in by_key:
                gid = 'dev%d' % (len(by_key) + 1)
                by_key[marker] = gid
                groups[gid] = {'id': gid, 'key': key, 'declared': False, 'members': []}
                order.append(gid)
            groups[by_key[marker]]['members'].append(item['id'])
        for item_id, gid in overrides.items():
            if gid not in groups:
                if RESERVED.fullmatch(gid):
                    raise ClockProblem('GROUP_MEMBERSHIP_INVALID', 'dev1, dev2, ... name the groups of recorded devices; this media set has no such device, so give an override group another id',
                                       '$.groups.itemOverrides', value=gid[:64], devices=[g for g in order if RESERVED.fullmatch(g)][:20])
                groups[gid] = {'id': gid, 'key': None, 'declared': True, 'override': True, 'members': []}
                order.append(gid)
            elif groups[gid]['key'] is not None:
                findings.append({'code': 'overrideJoinsRecordedDevice', 'item': item_id, 'group': gid})        # an explicit author decision, published
            groups[gid]['members'].append(item_id)
        for gid in order:
            g = groups[gid]
            g['members'] = [i for i in ids if i in set(g['members'])]
            if g['key'] is not None:
                serial = next((p for p in g['key'] if p[0] == 'bodySerialNumber'), None)
                g['mayMergeBodies'] = serial is None or serial[1] != 'present'
    return [groups[g] for g in order], ungroupable, findings


# ---------------------------------------------------------------- recorded instants
def recorded_instant(item, assumed):
    """``(instant_ns | None, basis, assumed_differs)`` of an item: its recorded offset, else its group's assumed offset, else wall-clock only."""
    if item['wall'] is None:
        return None, 'unreadable', False
    if item.get('offsetState') in ('unreadable', 'unsupported', 'ambiguous'):
        return None, 'offsetUnresolved', False         # a recorded offset exists but cannot be resolved: it is not absent, so no assumed offset replaces it
    if item['offset'] is not None:
        return tc.instant(item['wall'], item['offset']), 'recordedOffset', assumed is not None and assumed != item['offset']
    if assumed is not None:
        return tc.instant(item['wall'], assumed), 'assumedOffset', False
    return None, 'wallOnly', False


def read_reference(entry, index):
    at = '$.references[%d]' % index
    if ('trueUtc' in entry) == ('trueLocal' in entry):
        raise ClockProblem('REFERENCE_INVALID', 'give either trueUtc or trueLocal with trueOffset', at)
    try:
        if 'trueUtc' in entry:
            instant = tc.parse_utc(entry['trueUtc'], at + '.trueUtc')
            return {'item': entry['item'], 'trueInstant': instant, 'trueWall': None, 'trueOffset': None, 'note': entry.get('note'), 'at': at}
        if 'trueOffset' not in entry:
            raise ClockProblem('REFERENCE_INVALID', 'trueLocal needs trueOffset', at + '.trueOffset')
        wall, _ = tc.parse_local(entry['trueLocal'], at + '.trueLocal')
        offset = tc.parse_offset(entry['trueOffset'], at + '.trueOffset')
    except tc.TimeProblem as problem:
        code = 'LEAP_SECOND_UNSUPPORTED' if problem.code == 'LEAP_SECOND_UNSUPPORTED' else 'REFERENCE_INVALID'
        raise ClockProblem(code, problem.message, at, **problem.observed)
    return {'item': entry['item'], 'trueInstant': tc.instant(wall, offset), 'trueWall': wall, 'trueOffset': offset, 'note': entry.get('note'), 'at': at}


# ---------------------------------------------------------------- the report
def reconcile(items, spec, faulted=()):
    """The typed time report (see ``reconcile_exact``, which also returns the exact numbers a correction needs)."""
    return reconcile_exact(items, spec, faulted)[0]


def reconcile_exact(items, spec, faulted=()):
    """``(report, exact)``: the typed time report and, per item id, the exact (Fraction) skew and basis a correction applies.

    ``spec`` keys: ``groups``, ``references``, ``simultaneous``, ``assumeCorrect``, ``assumedOffsets``, ``model``,
    ``toleranceSeconds``, ``maxDriftRate``, ``maxDriftExtrapolationSeconds``, ``gpsToleranceSeconds`` (planned, defaults filled)."""
    by_id = {i['id']: i for i in items}
    faulted = set(faulted)
    tolerance = Fraction(spec.get('toleranceSeconds', '2'))
    groups, ungroupable, findings = group_items(items, spec.get('groups'), faulted)
    owner = {m: g['id'] for g in groups for m in g['members']}
    assumed = {}
    for index, entry in enumerate(spec.get('assumedOffsets', [])):
        at = '$.assumedOffsets[%d]' % index
        if entry['group'] not in {g['id'] for g in groups}:
            raise ClockProblem('GROUP_MEMBERSHIP_INVALID', 'assumedOffsets names a group that does not exist', at + '.group', value=entry['group'][:64])
        try:
            assumed[entry['group']] = tc.parse_offset(entry['offset'], at + '.offset')
        except tc.TimeProblem as problem:
            raise ClockProblem('INVALID_ARGUMENT', problem.message, at + '.offset')
    for gid in spec.get('assumeCorrect', []):
        if gid not in {g['id'] for g in groups}:
            raise ClockProblem('GROUP_MEMBERSHIP_INVALID', 'assumeCorrect names a group that does not exist', '$.assumeCorrect', value=str(gid)[:64])
    rows = {}
    for item in items:
        gid = owner.get(item['id'])
        instant, basis, differs = recorded_instant(item, assumed.get(gid))
        rows[item['id']] = {'id': item['id'], 'group': gid, 'basis': basis, 'recordedInstant': instant, 'wall': item['wall'], 'offset': item['offset'], 'findings': [],
                            'assumedOffsetDiffers': differs}
        if basis == 'offsetUnresolved':
            rows[item['id']]['findings'].append('offsetConflict' if item.get('offsetState') == 'ambiguous' else 'offsetUnreadable')
        if item['id'] in ungroupable:
            rows[item['id']]['findings'].append('DEVICE_IDENTITY_UNRESOLVED')
        if differs:
            rows[item['id']]['findings'].append('assumedOffsetDiffers')
        if item.get('timeState') in ('unreadable', 'unsupported'):
            rows[item['id']]['findings'].append('TIME_SOURCE_UNREADABLE')
        elif item.get('timeState') == 'absent':
            rows[item['id']]['findings'].append('captureTimeAbsent')
        if item['timeConflict']:
            rows[item['id']]['findings'].append('timeSourcesConflict')
        if item['subSecondConflict']:
            rows[item['id']]['findings'].append('subSecondConflict')
    # references
    refs, seen = [], set()
    if len(spec.get('references', [])) > MAX_REFERENCES:
        raise ClockProblem('INVALID_ARGUMENT', 'at most %d references' % MAX_REFERENCES, '$.references')
    for index, entry in enumerate(spec.get('references', [])):
        if entry['item'] in faulted:
            raise ClockProblem('REFERENCE_INVALID', 'the referenced item could not be captured or read, so it cannot anchor a clock', '$.references[%d].item' % index, value=entry['item'][:64])
        if entry['item'] not in by_id:
            raise ClockProblem('UNKNOWN_ITEM', 'a reference names an item that is not in the media set', '$.references[%d].item' % index, value=entry['item'][:64])
        if entry['item'] in seen:
            raise ClockProblem('DUPLICATE_REFERENCE', 'an item has more than one reference', '$.references[%d].item' % index, value=entry['item'])
        seen.add(entry['item'])
        ref = read_reference(entry, index)
        item, row = by_id[entry['item']], rows[entry['item']]
        if item['wall'] is None:
            raise ClockProblem('REFERENCE_INVALID', 'the referenced item has no readable recorded capture time', ref['at'] + '.item', value=entry['item'])
        ref['group'] = row['group']
        ref['instantSkew'] = None if row['recordedInstant'] is None else secs(row['recordedInstant'] - ref['trueInstant'])
        ref['wallSkew'] = None if ref['trueWall'] is None else secs(item['wall'] - ref['trueWall'])
        ref['offsetError'] = None if item['offset'] is None or ref['trueOffset'] is None else Fraction((item['offset'] - ref['trueOffset']) * 60)
        ref['recordedInstant'] = row['recordedInstant']
        refs.append(ref)
        if ref['offsetError']:
            row['findings'].append('offsetErrorDetected')
    # per-group estimates
    result_groups = {}
    for g in groups:
        result_groups[g['id']] = estimate_group(g, [r for r in refs if r['group'] == g['id']], spec, tolerance)
    # simultaneity
    edges = []
    if len(spec.get('simultaneous', [])) > MAX_SIMULTANEOUS:
        raise ClockProblem('INVALID_ARGUMENT', 'at most %d simultaneity assertions' % MAX_SIMULTANEOUS, '$.simultaneous')
    for index, entry in enumerate(spec.get('simultaneous', [])):
        at = '$.simultaneous[%d]' % index
        tol = Fraction(entry.get('toleranceSeconds', '1'))
        members = []
        for item_id in entry['items']:
            if item_id in faulted:
                raise ClockProblem('REFERENCE_INVALID', 'a simultaneity assertion names an item that could not be captured or read', at + '.items', value=item_id[:64])
            if item_id not in by_id:
                raise ClockProblem('UNKNOWN_ITEM', 'a simultaneity assertion names an item that is not in the media set', at + '.items', value=item_id[:64])
            members.append(rows[item_id])
        for row in members:
            if row['recordedInstant'] is None:
                rows[row['id']]['findings'].append('OFFSET_UNKNOWN')
        usable = [m for m in members if m['recordedInstant'] is not None and m['group'] is not None]
        if len(usable) < len(members):
            ungrouped = [m['id'] for m in members if m['group'] is None]
            edges.append({'assertion': index, 'state': 'unusable', 'code': 'DEVICE_IDENTITY_UNRESOLVED' if ungrouped else 'OFFSET_UNKNOWN',
                          'items': ungrouped or [m['id'] for m in members if m['recordedInstant'] is None]})
            continue
        base = usable[0]
        for other in usable[1:]:
            d = secs(other['recordedInstant'] - base['recordedInstant'])
            if other['group'] == base['group']:
                edges.append({'assertion': index, 'state': 'consistent' if abs(d) <= tol else 'conflicting', 'sameGroup': True, 'items': [base['id'], other['id']],
                              'differenceSeconds': text(d), 'toleranceSeconds': text(tol)})
                if abs(d) > tol:
                    result_groups[base['group']]['state'] = 'conflicting'
                    result_groups[base['group']].setdefault('conflicts', []).append({'assertion': index, 'differenceSeconds': text(d)})
            else:
                edges.append({'assertion': index, 'state': 'edge', 'a': base['group'], 'b': other['group'], 'items': [base['id'], other['id']], 'd': d, 'tolerance': tol,
                              'ta': base['recordedInstant'], 'tb': other['recordedInstant']})
    cycles = propagate(result_groups, edges, spec, tolerance, {g['id']: [r for r in refs if r['group'] == g['id']] for g in groups})
    # per item
    gps_tol = Fraction(spec.get('gpsToleranceSeconds', 120))
    out_items, exact = [], {}
    for item in items:
        row = rows[item['id']]
        gid = row['group']
        group = result_groups.get(gid)
        record = {'id': item['id'], 'group': gid, 'groupState': group['state'] if group else 'ungroupable', 'basis': row['basis'], 'findings': row['findings'],
                  'recordedLocal': None if item['wall'] is None else tc.local_text(item['wall'], len(item['digits']) if item.get('digits') is not None else None), 'recordedOffset': None if item['offset'] is None else tc.offset_text(item['offset']),
                  'skewSeconds': None, 'proposedLocal': None, 'proposedOffset': None, 'proposedInstant': None}
        skew, outside = (None, False) if not group or row['recordedInstant'] is None else skew_at(group, row['recordedInstant'])      # an instant skew belongs to an instant: a wall-only item has only a wall skew
        exact[item['id']] = {'group': gid, 'groupState': group['state'] if group else 'ungroupable', 'skew': skew, 'wallSkew': None if not group else group.get('wallSkew'), 'basis': row['basis'],
                             'recordedInstant': row['recordedInstant'], 'assumedOffset': assumed.get(gid), 'outside': outside, 'code': None if not group else group.get('code'),
                             'model': None if not group else group.get('model')}
        if outside:
            record['groupState'] = 'outsideReferenceSpan'
            record['findings'] = record['findings'] + ['outsideReferenceSpan']
        if skew is not None and row['recordedInstant'] is not None and group['state'] == 'anchored':
            record['skewSeconds'] = text(skew)
            true_instant = row['recordedInstant'] - round_ns(skew)
            offset = item['offset'] if item['offset'] is not None else assumed.get(gid)
            try:
                record['proposedInstant'] = tc.unbounded_text(true_instant)
                record['proposedLocal'] = tc.local_text(true_instant + offset * 60 * tc.NS)
                record['proposedOffset'] = tc.offset_text(offset)
            except tc.TimeProblem as error:
                record['proposedLocal'] = record['proposedOffset'] = None
                record['findings'].append(error.code)
            if item['gpsUtc'] is not None and abs(secs(true_instant - item['gpsUtc'])) > gps_tol:
                record['findings'].append('gpsStampDisagrees')
        elif group and group['state'] == 'anchored' and row['basis'] == 'wallOnly' and group.get('wallSkew') is not None and group.get('model') != 'linearDrift':
            record['skewSeconds'] = text(group['wallSkew'])
            try:
                record['proposedLocal'] = tc.local_text(item['wall'] - round_ns(group['wallSkew']))
            except tc.TimeProblem as error:
                record['findings'].append(error.code)
        out_items.append(record)
    report_groups = []
    for g in groups:
        r = result_groups[g['id']]
        report_groups.append({'id': g['id'], 'key': g['key'], 'declared': g['declared'], 'members': g['members'], 'state': r['state'], 'anchoredBy': r.get('anchoredBy'),
                              'model': r.get('model'), 'skewSeconds': None if r.get('skew') is None else text(r['skew']), 'spreadSeconds': r.get('spread'), 'residuals': r.get('residuals', []),
                              'code': r.get('code'), 'reason': r.get('reason'), 'drift': r.get('drift'), 'conflicts': r.get('conflicts', []), 'mayMergeBodies': g.get('mayMergeBodies'), 'recordedKeys': g.get('recordedKeys'),
                              'assumedOffset': None if g['id'] not in assumed else tc.offset_text(assumed[g['id']])})
    public_edges = [{k: (text(v) if isinstance(v, Fraction) else v) for k, v in e.items() if k not in ('d', 'tolerance', 'ta', 'tb')} | ({'differenceSeconds': text(e['d']), 'toleranceSeconds': text(e['tolerance'])} if 'd' in e else {}) for e in edges]
    report = {'groups': report_groups, 'ungroupable': ungroupable, 'findings': findings, 'edges': public_edges, 'cycles': cycles, 'items': out_items,
            'references': [{'item': r['item'], 'group': r['group'], 'instantSkewSeconds': None if r['instantSkew'] is None else text(r['instantSkew']),
                            'wallSkewSeconds': None if r['wallSkew'] is None else text(r['wallSkew']),
                            'offsetErrorSeconds': None if r['offsetError'] is None else text(r['offsetError']), 'note': r['note'], 'declared': True} for r in refs],
            'declared': {'assumeCorrect': list(spec.get('assumeCorrect', [])), 'assumedOffsets': {k: tc.offset_text(v) for k, v in sorted(assumed.items())}}}
    return report, exact


def round_ns(skew):
    """A skew (Fraction seconds) in whole nanoseconds, rounded half-even; the published skew text keeps the exact value."""
    return round(skew * tc.NS)


def estimate_group(group, refs, spec, tolerance):
    model = spec.get('model', 'constant')
    out = {'state': 'insufficient', 'model': None, 'members': group['members']}
    usable = [r for r in refs if r['instantSkew'] is not None]
    if not usable:
        wall = [r for r in refs if r['wallSkew'] is not None]
        if wall:
            out.update(state='anchored', anchoredBy='references', model='constant', wallSkew=tc.median([r['wallSkew'] for r in wall]),
                       basis='wallOnly', spread=text(max(r['wallSkew'] for r in wall) - min(r['wallSkew'] for r in wall)))
            if max(r['wallSkew'] for r in wall) - min(r['wallSkew'] for r in wall) > tolerance:
                out['state'] = 'conflicting'
        return out
    skews = [r['instantSkew'] for r in usable]
    spread = max(skews) - min(skews)
    wall = [r['wallSkew'] for r in usable if r['wallSkew'] is not None]
    if model == 'linearDrift':
        return drift_estimate(out, usable, tolerance, spec)
    estimate = tc.median(skews)
    out.update(model='constant', skew=estimate, spread=text(spread), residuals=[{'item': r['item'], 'residualSeconds': text(r['instantSkew'] - estimate)} for r in usable],
               wallSkew=tc.median(wall) if wall else None, anchoredBy='references')
    out['state'] = 'anchored' if spread <= tolerance else 'conflicting'
    return out


def drift_estimate(out, usable, tolerance, spec):
    """Ordinary least squares of skew against recorded instant, exactly in rationals (exact for two references)."""
    points = sorted(((secs(r['recordedInstant']), r['instantSkew'], r['item']) for r in usable))
    out.update(model='linearDrift', anchoredBy='references')
    if len(points) < 2 or points[-1][0] - points[0][0] < 60:
        out.update(state='insufficient', reason='linearDrift needs at least two references at least 60 s apart')
        return out
    t0 = points[0][0]
    xs = [t - t0 for t, _, _ in points]
    ys = [y for _, y, _ in points]
    n = len(points)
    mean_x, mean_y = sum(xs) / n, sum(ys) / n
    sxx = sum((x - mean_x) ** 2 for x in xs)
    slope = sum((x - mean_x) * (y - mean_y) for x, y in zip(xs, ys)) / sxx
    intercept = mean_y - slope * mean_x
    residuals = [{'item': item, 'residualSeconds': text(y - (intercept + slope * x))} for x, y, (_, _, item) in zip(xs, ys, points)]
    max_rate = Fraction(str(spec.get('maxDriftRate', '0.001')))
    out.update(drift={'t0': tc.unbounded_text(round(t0 * tc.NS)), 'interceptSeconds': text(intercept), 'ratePerSecond': text(slope), 'rateSecondsPerDay': text(slope * 86400)},
               residuals=residuals, spread=text(max(abs(y - (intercept + slope * x)) for x, y in zip(xs, ys))), skew=intercept, slope=slope, t0=t0,
               span=(points[0][0], points[-1][0]))
    if max(abs(y - (intercept + slope * x)) for x, y in zip(xs, ys)) > tolerance:
        out['state'] = 'conflicting'
    elif abs(slope) > max_rate:
        out.update(state='conflicting', code='DRIFT_IMPLAUSIBLE', reason='the fitted drift rate exceeds the declared plausibility bound maxDriftRate')
    else:
        out['state'] = 'anchored'
    out['maxRate'] = max_rate
    extra = Fraction(spec.get('maxDriftExtrapolationSeconds', 0))
    out['extrapolation'] = extra
    return out


def skew_at(group, recorded):
    """``(skew, outside)``: the group's estimated skew (Fraction seconds) at a recorded instant (drift-adjusted), and whether the instant lies outside the
    reference span of a drift model by more than the declared extrapolation allowance (then there is no skew)."""
    if group.get('skew') is None:
        return None, False
    if group.get('model') == 'linearDrift' and group['state'] == 'anchored':
        if recorded is None:
            return None, False          # a drift skew is a function of the instant: an item with no recorded instant has none (never the intercept)
        t = secs(recorded)
        lo, hi = group['span']
        if t < lo - group['extrapolation'] or t > hi + group['extrapolation']:
            return None, True
        return group['skew'] + group['slope'] * (t - group['t0']), False
    return group['skew'], False


def propagate(groups, edges, spec, tolerance, refs_by_group=None):
    """Anchor groups through simultaneity edges; publishes each cycle's residual. Mutates the group estimates and returns the cycle list.

    An edge says that two items were taken at the same true moment, so ``skew_b(tb) = skew_a(ta) + d`` for the recorded instants ``ta`` and ``tb`` of its two
    items: each endpoint's skew is evaluated at *its own* edge instant (a drift group's skew is a function of time, never its intercept), an edge whose
    instant lies outside a drift group's reference span (plus the declared allowance) is unusable, and a group anchored through a path gets the constant skew
    measured at the asserted instant. A group declared correct is an anchor only where its own references do not contradict that declaration.
    """
    refs_by_group = refs_by_group or {}
    tol = tolerance
    for gid in spec.get('assumeCorrect', []):
        g = groups.get(gid)
        if g is None:
            continue
        refs = [r for r in refs_by_group.get(gid, []) if r['instantSkew'] is not None or r['wallSkew'] is not None]
        raw = [r['instantSkew'] if r['instantSkew'] is not None else r['wallSkew'] for r in refs]
        residuals = [{'item': r['item'], 'residualSeconds': text(v)} for r, v in zip(refs, raw)]
        if refs and (g['state'] == 'conflicting' or any(abs(v) > tol for v in raw)):
            g.update(state='conflicting', code='ASSUMPTION_CONTRADICTED', assumed=True, residuals=residuals, skew=None, wallSkew=None, anchoredBy=None, spread=text(max(raw) - min(raw)),
                     reason='the references of this group contradict the declaration that its clock is correct; nothing is assumed or averaged away')
        else:
            g.update(state='anchored', anchoredBy='assumeCorrect', skew=Fraction(0), wallSkew=Fraction(0), model='constant', spread=text(max(raw) - min(raw)) if raw else '0', residuals=residuals, assumed=True)
    for e in edges:
        if e.get('state') == 'edge' and 'conflicting' in (groups[e['a']]['state'], groups[e['b']]['state']):
            e.update(state='unusable', code='GROUP_CONFLICTING')       # a conflicting group anchors nothing and is anchored by nothing
    graph = {}
    for e in edges:
        if e.get('state') == 'edge':
            graph.setdefault(e['a'], []).append((e['b'], e))
            graph.setdefault(e['b'], []).append((e['a'], e))
    cycles, visited = [], set()

    def constant(value):
        return lambda t: (value, False)

    def drifting(group):
        return lambda t: skew_at(group, t)
    for gid in sorted(graph):
        if gid in visited:
            continue
        component, queue = [gid], [gid]
        visited.add(gid)
        while queue:
            node = queue.pop(0)
            for neighbour, edge in graph[node]:
                if neighbour not in visited:
                    visited.add(neighbour)
                    component.append(neighbour)
                    queue.append(neighbour)
        component.sort()
        members = {id(e): e for n in component for _, e in graph[n]}
        limit = max([e['tolerance'] for e in members.values()] or [tolerance])
        anchors = [n for n in component if groups[n]['state'] == 'anchored' and groups[n].get('skew') is not None]
        relative = not anchors
        solve = {n: drifting(groups[n]) for n in anchors}
        derived = {}
        if relative:
            solve[component[0]] = constant(Fraction(0))
            derived[component[0]] = Fraction(0)
        order, used, conflict = sorted(solve), set(), False
        position = 0
        while position < len(order):
            x = order[position]
            position += 1
            for y, e in sorted(graph[x], key=lambda item: (item[0], item[1]['assertion'])):
                if id(e) in used:
                    continue
                used.add(id(e))
                tx, ty = (e['ta'], e['tb']) if x == e['a'] else (e['tb'], e['ta'])
                sx, outside = solve[x](tx)
                if outside:
                    e.update(state='unusable', code='outsideReferenceSpan')
                    continue
                implied = sx + e['d'] if x == e['a'] else sx - e['d']
                if y not in solve:
                    solve[y] = constant(implied)
                    derived[y] = implied
                    order.append(y)
                    continue
                sy, outside_y = solve[y](ty)
                if outside_y:
                    e.update(state='unusable', code='outsideReferenceSpan')
                    continue
                residual = implied - sy
                state = 'consistent' if abs(residual) <= limit else 'conflicting'
                cycles.append({'groups': sorted({x, y}), 'assertion': e['assertion'], 'residualSeconds': text(residual), 'toleranceSeconds': text(limit), 'state': state})
                conflict = conflict or state == 'conflicting'
        for n in component:
            g = groups[n]
            if conflict:
                g['state'] = 'conflicting'
                g.setdefault('conflicts', []).append({'component': component})
            elif n in derived:
                if relative:
                    g.update(state='unanchored', relativeSkew=derived[n], skew=None)
                else:
                    own = [r for r in refs_by_group.get(n, []) if r['instantSkew'] is not None or r['wallSkew'] is not None]
                    residuals = [{'item': r['item'], 'residualSeconds': text((r['instantSkew'] if r['instantSkew'] is not None else r['wallSkew']) - derived[n])} for r in own]
                    contradicted = any(abs((r['instantSkew'] if r['instantSkew'] is not None else r['wallSkew']) - derived[n]) > limit for r in own)
                    if contradicted:       # the group's own declared references contradict the skew the simultaneity path gives it: nothing is overwritten or averaged away
                        g.update(state='conflicting', code='REFERENCE_CONTRADICTED', anchoredBy=None, model='constant', skew=None, wallSkew=None, residuals=residuals,
                                 reason='the declared references of this group contradict the skew that its simultaneity assertions give it', spread=None)
                        g.setdefault('conflicts', []).append({'component': component, 'pathSkewSeconds': text(derived[n])})
                    else:
                        g.update(state='anchored', anchoredBy='path', model='constant', skew=derived[n], spread=None, residuals=residuals)
                        g.pop('reason', None)           # a stale insufficient-evidence reason does not describe an anchored group
            elif relative:
                g.update(state='unanchored', relativeSkew=Fraction(0), skew=None)
    for g in groups.values():
        if g['state'] == 'unanchored' and g.get('relativeSkew') is not None:
            g['relativeSkewText'] = text(g['relativeSkew'])
    return cycles
