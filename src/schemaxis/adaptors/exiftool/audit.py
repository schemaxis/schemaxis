"""Audit and comparison over typed field records (pure host logic, no native process, no clock, no filesystem).

Rules form a closed set and every finding names its rule, item, field, status and the evidence that triggered it. Comparison uses the
literal equality of canonical values (exact rationals, exact text): nothing is rounded, normalised or preferred.
"""
import datetime

from schemaxis.adaptors.exiftool import catalogue, records

RULES = ('requiredFields', 'sourceConflicts', 'unreadableValues', 'timePlausibility', 'privacyInventory', 'duplicateContent')
RULE_FIELDS = {'timePlausibility': ('capturedLocal', 'capturedOffset', 'capturedUtc', 'gpsUtc', 'digitizedLocal'),
               'privacyInventory': tuple(name for name, spec in catalogue.fields().items() if spec['privacy'] != 'none')}
PRIVACY_CLASSES = ('location', 'device-identity', 'personal-identity')
OUTCOMES = ('same', 'different', 'missing-in-item', 'missing-in-baseline', 'both-absent', 'not-comparable')


def value_of(record):
    return records.publish_value(None, record['canonical'])[0]


def finding(rule, item, field, severity, status, message, **evidence):
    return {'rule': rule, 'item': item, 'field': field, 'severity': severity, 'status': status, 'message': message, 'evidence': evidence}


def parse_instant(text):
    return datetime.datetime.strptime(text, '%Y-%m-%dT%H:%M:%SZ')


def audit(items, options):
    """Findings for ok items; ``options`` is the plan's audit block (rules, require, gpsToleranceSeconds)."""
    rules, found = set(options['rules']), []
    fields = catalogue.fields()
    for item in items:
        by = item['fields']
        name = item['id']
        if 'requiredFields' in rules:
            for field in options['require']:
                state = by[field]['state']
                if state != 'present':
                    found.append(finding('requiredFields', name, field, 'warning', state, '%s is required but is %s' % (fields[field]['label'], state)))
        for field, record in by.items():
            if 'sourceConflicts' in rules and record['state'] == 'ambiguous':
                sources = [{'family': s['family'], 'location': s['location'], 'state': s['state'], 'value': records.publish_source(s).get('value')} for s in record['sources'] if s['state'] in ('present', 'ambiguous')]
                found.append(finding('sourceConflicts', name, field, 'warning', 'ambiguous', '%s has %s; no source is preferred' % (fields[field]['label'], 'conflicting sources' if record['reconciliation'] == 'conflicting' else 'duplicate or ambiguous locations'),
                                     reconciliation=record['reconciliation'], sources=sources))
            bad = [{'family': s['family'], 'location': s['location'], 'code': s.get('code'), 'message': s.get('message')} for s in record['sources'] if s['state'] == 'unreadable']
            if 'unreadableValues' in rules and (record['state'] == 'unreadable' or bad):
                # a malformed source is reported even when another source of the same field is readable (the field then stays present, partially assessed)
                message = '%s is present but malformed' if record['state'] == 'unreadable' else '%s has a malformed source, so its sources were only partially assessed'
                found.append(finding('unreadableValues', name, field, 'warning', 'unreadable', message % fields[field]['label'], sources=bad, fieldState=record['state']))
        if 'timePlausibility' in rules:
            found.extend(time_findings(name, by, options['gpsToleranceSeconds']))
        if 'privacyInventory' in rules:
            for privacy in PRIVACY_CLASSES:
                carried = [f for f, r in by.items() if r['state'] == 'present' and r['privacy'] == privacy]
                if carried:
                    found.append(finding('privacyInventory', name, None, 'info', 'present', 'the file records %s metadata' % privacy, privacy=privacy, fields=carried))
    if 'duplicateContent' in rules:
        groups = {}
        for item in items:
            groups.setdefault(item['sha256'], []).append(item['id'])
        for digest, names in sorted(groups.items(), key=lambda kv: kv[1][0]):
            if len(names) > 1:
                found.append(finding('duplicateContent', names[0], None, 'warning', 'duplicate', 'identical bytes are captured from %d distinct sources' % len(names), sha256=digest, items=names))
    order = {name: index for index, name in enumerate(item['id'] for item in items)}
    found.sort(key=lambda f: (order.get(f['item'], 0), RULES.index(f['rule']), list(fields).index(f['field']) if f['field'] else -1))
    return found


def time_findings(name, by, tolerance):
    out = []
    captured, offset, utc, gps, digitized = (by[k] for k in RULE_FIELDS['timePlausibility'][:3] + ('gpsUtc', 'digitizedLocal'))
    if utc['state'] == 'present' and gps['state'] == 'present':
        seconds = abs(int((parse_instant(utc['canonical']) - parse_instant(gps['canonical'])).total_seconds()))
        if seconds > tolerance:
            out.append(finding('timePlausibility', name, 'gpsUtc', 'warning', 'differs', 'the GPS UTC stamp differs from the capture instant by %d seconds (tolerance %d)' % (seconds, tolerance),
                               capturedUtc=utc['canonical'], gpsUtc=gps['canonical'], differenceSeconds=seconds))
    elif gps['state'] == 'present' and captured['state'] == 'present' and offset['state'] != 'present':
        out.append(finding('timePlausibility', name, 'capturedOffset', 'info', offset['state'], 'the GPS UTC stamp cannot be compared with the capture time because no UTC offset is recorded', capturedLocal=captured['canonical']))
    if captured['state'] == 'present' and digitized['state'] == 'present' and digitized['canonical'] < captured['canonical']:
        out.append(finding('timePlausibility', name, 'digitizedLocal', 'warning', 'precedes', 'the digitization time precedes the capture time',
                           capturedLocal=captured['canonical'], digitizedLocal=digitized['canonical']))
    if offset['state'] == 'present' and captured['state'] != 'present':
        out.append(finding('timePlausibility', name, 'capturedOffset', 'info', captured['state'], 'a UTC offset is recorded without a usable capture time', capturedOffset=offset['canonical']))
    return out


def compare(items, baseline, field_names):
    """Item-by-field outcomes against the named baseline item."""
    base = next(i for i in items if i['id'] == baseline)
    rows = []
    for item in items:
        if item['id'] == baseline:
            continue
        for field in field_names:
            a, b = base['fields'][field], item['fields'][field]
            pa, pb = a['state'] == 'present', b['state'] == 'present'
            if pa and pb:
                outcome = 'same' if a['canonical'] == b['canonical'] else 'different'
            elif pa:
                outcome = 'missing-in-item' if b['state'] == 'absent' else 'not-comparable'
            elif pb:
                outcome = 'missing-in-baseline' if a['state'] == 'absent' else 'not-comparable'
            elif a['state'] == 'absent' and b['state'] == 'absent':
                outcome = 'both-absent'
            else:
                outcome = 'not-comparable'
            rows.append({'item': item['id'], 'field': field, 'outcome': outcome, 'baseline': {'state': a['state'], 'value': value_of(a)}, 'other': {'state': b['state'], 'value': value_of(b)}})
    return rows
