"""Per-item plan of ``correctTime`` (host-only, standard library): which time sources of a captured file are rewritten, to what, and what must read back.

A correction moves each touched time field (captured, digitized, modified) of an item by one exact duration and/or relabels its recorded offset. Every
*present* source of the field is rewritten (EXIF, XMP, IPTC), so the result stays concordant; absent sources are never created, except offset carriers when
the author sets an offset. A source that exists but cannot be read is never overwritten, conflicting sources are refused unless the author names a family
to prefer, and nothing is rounded: a fraction keeps its digit count when that is exact, is extended when it must be, and is dropped only where a carrier
cannot hold it (IPTC), as a declared loss. All arithmetic is exact integer nanoseconds from ``timecalc``; there is no time zone, daylight-saving or
leap-second knowledge.

A *target* is one native assignment (or an IPTC date/time pair) with the catalogued components it carries: ``{'kind': 'local'|'offset'|'subSecond',
'field', 'family', 'location', 'before', 'after'}``. An XMP date string carries all three components, so one XMP target holds up to three components.
"""
from schemaxis.adaptors.exiftool import e3writes, edits, timecalc as tc

DEFAULT_GROUPS = ('captured', 'digitized')


def source(record, family, location):
    return next((s for s in record['sources'] if s['family'] == family and s['location'] == location), None)


def exif_location(spec, key):
    ifd = spec['exif']['ifd'] if key == 'local' else 'ExifIFD'
    return '%s:%s' % (ifd, spec['exif'][key]['tag'])


def iptc_location(spec, key):
    return '%d:%d' % (spec['iptc'][key]['record'], spec['iptc'][key]['dataset'])


def present(s): return s is not None and s['state'] == 'present'


def refuse(code, message, at, **observed):
    raise edits.Refusal(code, message, at, **observed)


def check_readable(spec, fields, group, at):
    """No source of the group may exist but be unreadable, unsupported or repeated (E3 never overwrites what it cannot read)."""
    for key in ('local', 'offset', 'subSecond'):
        for s in fields[spec[key]]['sources']:
            if s['state'] in ('unreadable', 'unsupported'):
                refuse('TIME_SOURCE_UNREADABLE', 'a source of this time field exists but cannot be read, so it is not overwritten', at, field=group, source=s['family'] + ':' + s['location'], cause=s.get('code'))
            if s['state'] == 'ambiguous':
                refuse('TIME_SOURCES_CONFLICT', 'a source of this time field is repeated, so no single value is its starting point', at, field=group, source=s['family'] + ':' + s['location'], cause=s.get('code'))


def chosen(record, key, group, at, policies, code):
    """The single starting value of a time component: the concordant canonical value, or the preferred family's when the author chose one."""
    if record['state'] == 'absent':
        return None
    if record['state'] == 'present':
        return record['canonical']
    live = [(s['family'], s['location'], s['canonical']) for s in record['sources'] if s['state'] == 'present']
    prefer = policies.get('preferFamily') if policies.get('sourceConflicts') == 'preferFamily' else None
    if prefer:
        found = [v for f, _, v in live if f == prefer]
        if found:
            return found[0]
    refuse(code, 'the sources of this time field disagree' + ('; the preferred family has no value' if prefer else ' and no family is preferred'), at, field=group, component=key,
           values=[{'family': f, 'location': l, 'value': v} for f, l, v in live][:8])


def exif_ifd_exists(payloads):
    state = payloads.exif
    return state[0] == 'ok' and state[1]['ifds'].get('ExifIFD', ('absent',))[0] == 'ok'


def native_exif_date(local): return local[:10].replace('-', ':') + ' ' + local[11:]
def iptc_date_text(local): return local[:10].replace('-', '')
def iptc_time_text(local, offset): return local[11:].replace(':', '') + ('' if offset is None else tc.offset_text(offset).replace(':', ''))


def component(kind, spec, family, location, before, after):
    return {'kind': kind, 'field': spec[{'local': 'local', 'offset': 'offset', 'subSecond': 'subSecond'}[kind]], 'family': family, 'location': location, 'before': before, 'after': after}


def target(family, location, components, writes, **extra):
    """One native write: ``writes`` is a list of ``(native name, value text)``; it is needed when any component changes."""
    return {'family': family, 'location': location, 'components': components, 'writes': writes, 'changes': any(c['before'] != c['after'] for c in components), **extra}


def absolute_target(absolute, group, at):
    """The exact captured value an absolute set intent names: ``(wall + fraction ns, fraction digits, offset minutes or None)``. The intent is
    ``{'local': 'YYYY-MM-DDTHH:MM:SS', 'fraction': digits or '', 'offset': '+HH:MM' or None}``; it is internal (no authored request builds it)."""
    try:
        wall, _ = tc.parse_local(absolute['local'], group)
        digits = absolute.get('fraction') or ''
        if digits and not (digits.isascii() and digits.isdigit() and len(digits) <= 9):
            refuse('TIME_VALUE_INVALID', 'a time fraction is one to nine digits', at, field=group)
        offset = tc.parse_offset(absolute['offset']) if absolute.get('offset') is not None else None
    except tc.TimeProblem as error:
        refuse(error.code, error.message, at, field=group, **error.observed)
    return wall + (int(digits.ljust(9, '0')) if digits else 0), digits, offset


def plan_group(group, fields, payloads, delta_ns, set_offset, assumed, policies, at, absolute=None):
    """The plan of one time group of one item, or ``None`` when no source of the group is present. ``delta_ns`` moves the wall clock exactly.

    ``absolute`` (internal) *sets* the group to an exact captured value instead of moving it: every present source takes the value, offset and fraction carriers are
    added as for a set offset, and a group with no local time at all receives it in the one carrier that can hold it without creating a block the native writer fills
    with mandatory values: ExifIFD:DateTimeOriginal (with the offset and fraction tags) in an existing ExifIFD, otherwise XMP-exif:DateTimeOriginal. An offset that a
    destination records and the intent lacks is never removed here, and a recorded fraction keeps its digit count.
    """
    spec = e3writes.time_groups()[group]
    check_readable(spec, fields, group, at)
    local_rec, offset_rec, sub_rec = (fields[spec[k]] for k in ('local', 'offset', 'subSecond'))
    local = chosen(local_rec, 'local', group, at, policies, 'TIME_SOURCES_CONFLICT')
    creating = absolute is not None and local is None
    if local is None and not creating:
        return None
    offset_text = chosen(offset_rec, 'offset', group, at, policies, 'TIME_SOURCES_CONFLICT')
    digits = chosen(sub_rec, 'subSecond', group, at, policies, 'TIME_SUBSECOND_CONFLICT') or ''
    old_offset = tc.parse_offset(offset_text) if offset_text is not None else None
    if absolute is not None:
        target_ns, target_digits, target_offset = absolute_target(absolute, group, at)
        if target_offset is None and old_offset is not None:
            refuse('TIME_OFFSET_REMOVAL', 'the destination records a UTC offset that the set value lacks, and an offset is never removed by a set', at, field=group)
        if digits:
            written, _ = tc.fraction_after(digits, target_ns % tc.NS)
            if written != target_digits:
                refuse('TIME_FRACTION_PRECISION', 'the destination field would record the fraction with another digit count than the set value, so the typed values would differ', at, field=group, recorded=digits, set=target_digits, written=written)
        if target_offset is not None and target_offset != old_offset:
            set_offset = {'minutes': target_offset, 'keep': 'wallClock'}
        new_offset = target_offset if target_offset is not None else old_offset
        moved = target_ns
        total = 0
        if local is not None:
            wall, _ = tc.parse_local(local, group)
            total = moved - (wall + (int(digits.ljust(9, '0')) if digits else 0))
        digits_set = target_digits
    else:
        wall, _ = tc.parse_local(local, group)
        fraction = int(digits.ljust(9, '0')) if digits else 0
        total, new_offset = delta_ns, old_offset
        if set_offset is not None:
            new_offset = set_offset['minutes']
            if set_offset['keep'] == 'instant':
                basis = old_offset if old_offset is not None else assumed
                if basis is None:
                    refuse('OFFSET_UNKNOWN', 'keeping the instant while changing the offset needs a recorded or assumed offset for this field', at, field=group)
                total += (new_offset - basis) * 60 * tc.NS
        try:
            moved = tc.shifted(wall + fraction, total) if total else wall + fraction
            tc.parts(moved)
        except tc.TimeProblem as error:
            refuse(error.code, error.message, at, field=group, **error.observed)
        digits_set = None
    new_fraction = moved % tc.NS
    new_local = tc.local_text(moved - new_fraction, 0)
    if digits_set is not None:
        new_digits, extended = digits_set, False
    else:
        new_digits, extended = tc.fraction_after(digits, new_fraction)
    new_offset_text = None if new_offset is None else tc.offset_text(new_offset)
    recorded_any = bool(digits)
    exif_local = source(local_rec, 'exif', exif_location(spec, 'local'))
    xmp_locals = {x['property']: source(local_rec, 'xmp', x['property']) for x in spec['xmp']}
    create_exif = creating and exif_ifd_exists(payloads)
    create_xmp = creating and not create_exif
    add_fraction = False
    if not recorded_any and (bool(new_digits) if digits_set is not None else new_fraction):
        if policies.get('subSecond', 'addIfNeeded') == 'refuse':
            refuse('TIME_SUBSECOND_REQUIRED', 'the correction has a fractional second and this field records none (subSecond policy: refuse)', at, field=group)
        add_fraction = True
        if not ((present(exif_local) and exif_ifd_exists(payloads)) or create_exif or create_xmp or any(present(s) for s in xmp_locals.values())):
            refuse('TIME_SUBSECOND_REQUIRED', 'the correction has a fractional second and no source of this field can hold one (IPTC cannot)', at, field=group)
    targets, losses = [], []
    if present(exif_local) or create_exif:
        targets.append(target('exif', exif_location(spec, 'local'), [component('local', spec, 'exif', exif_location(spec, 'local'), exif_local['canonical'] if present(exif_local) else None, new_local)],
                              [(spec['exif']['local']['write'], native_exif_date(new_local))]))
        offset_source = source(offset_rec, 'exif', exif_location(spec, 'offset'))
        if present(offset_source) or (set_offset is not None and exif_ifd_exists(payloads)):
            loc = exif_location(spec, 'offset')
            targets.append(target('exif', loc, [component('offset', spec, 'exif', loc, offset_source['canonical'] if present(offset_source) else None, new_offset_text)],
                                  [(spec['exif']['offset']['write'], new_offset_text)]))
        sub_source = source(sub_rec, 'exif', exif_location(spec, 'subSecond'))
        if present(sub_source) or (add_fraction and exif_ifd_exists(payloads)):
            loc = exif_location(spec, 'subSecond')
            targets.append(target('exif', loc, [component('subSecond', spec, 'exif', loc, sub_source['canonical'] if present(sub_source) else None, new_digits or None)],
                                  [(spec['exif']['subSecond']['write'], new_digits)]))
    for entry in spec['xmp']:
        prop = entry['property']
        local_source = xmp_locals[prop]
        created = create_xmp and prop == 'exif:DateTimeOriginal'
        if not present(local_source) and not created:
            continue
        offset_source, sub_source = source(offset_rec, 'xmp', prop), source(sub_rec, 'xmp', prop)
        has_offset = (present(offset_source) or set_offset is not None) and new_offset_text is not None
        has_fraction = (present(sub_source) or add_fraction) and bool(new_digits)
        text = new_local + ('.' + new_digits if has_fraction else '') + (new_offset_text if has_offset else '')
        parts = [component('local', spec, 'xmp', prop, local_source['canonical'] if present(local_source) else None, new_local)]
        if has_offset:
            parts.append(component('offset', spec, 'xmp', prop, offset_source['canonical'] if present(offset_source) else None, new_offset_text))
        if has_fraction:
            parts.append(component('subSecond', spec, 'xmp', prop, sub_source['canonical'] if present(sub_source) else None, new_digits))
        targets.append(target('xmp', prop, parts, [(entry['write'], text)]))
    if 'iptc' in spec:
        date_location, time_location = iptc_location(spec, 'date'), iptc_location(spec, 'time')
        iptc_local = source(local_rec, 'iptc', date_location)
        if present(iptc_local):
            offset_source = source(offset_rec, 'iptc', time_location)
            has_offset = (present(offset_source) or set_offset is not None) and new_offset_text is not None
            before_offset = tc.parse_offset(offset_source['canonical']) if present(offset_source) else None
            parts = [component('local', spec, 'iptc', date_location, iptc_local['canonical'], new_local)]
            if has_offset:
                parts.append(component('offset', spec, 'iptc', time_location, offset_source['canonical'] if present(offset_source) else None, new_offset_text))
            writes = []
            if iptc_date_text(iptc_local['canonical']) != iptc_date_text(new_local):
                writes.append((spec['iptc']['date']['write'], iptc_date_text(new_local)))
            if iptc_time_text(iptc_local['canonical'], before_offset) != iptc_time_text(new_local, new_offset if has_offset else None):
                writes.append((spec['iptc']['time']['write'], iptc_time_text(new_local, new_offset if has_offset else None)))
            targets.append(target('iptc', date_location, parts, writes, forced=bool(writes)))
            if new_fraction:
                losses.append({'key': spec['iptc']['time']['write'], 'reason': 'iptcFractionDropped', 'fraction': new_digits, 'treatment': 'truncatedToTheEarlierSecond'})
    if creating:
        losses.append({'key': 'captureTime', 'reason': 'timeCreatedInXmpOnly' if create_xmp else 'timeCreatedInExifOnly', 'treatment': 'oneCarrierCreated'})
    infos = ['subSecondDigitsExtended'] if extended else []
    return {'group': group, 'before': {'local': local, 'offset': offset_text, 'fraction': digits or None}, 'after': {'local': new_local, 'offset': new_offset_text, 'fraction': new_digits or None},
            'deltaNanoseconds': total, 'changed': any(t['changes'] or t.get('forced') for t in targets), 'targets': targets, 'losses': losses if any(t['changes'] for t in targets) else [], 'infos': infos}


def assignments(group_plans):
    """The ordered native argument list of the changed targets of all groups: ``-n`` (raw forms) and one ``-NAME=value`` per write."""
    args, seen = ['-n'], set()
    for plan in group_plans:
        for t in plan['targets']:
            if not (t['changes'] or t.get('forced')):
                continue
            for name, value in t['writes']:
                if name not in seen:
                    seen.add(name)
                    args.append('-%s=%s' % (name, value))
    return args


def expectations(group_plans):
    """``{(field, family, location): canonical}`` that every written component must read back as (components that did not change are included)."""
    return {(c['field'], c['family'], c['location']): c['after'] for plan in group_plans for t in plan['targets'] for c in t['components']}
