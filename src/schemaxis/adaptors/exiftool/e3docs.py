"""Publications of the time and location write operations: plan documents, write-report extras, residual reports and track reports (host-only).

Every document is derived from the plan, the item outcomes and the retained inputs, so verification rebuilds and compares each one byte for byte. A plan
document records the validated authored inputs and the normalised block they produce, so a later run can recompute both and refuse an edited plan; it also
records, per item, the capture hash it was made for and the exact native arguments it would use.
"""
from fractions import Fraction

from schemaxis.adaptors.exiftool import e3place, e3proofs, e3read, e3reports, e3track, e3write, locations, timecalc as tc

RESIDUAL_LIMITS = {
    'correctTime': [
        'Only the catalogued time sources of the selected fields (EXIF, XMP, IPTC) were changed. GPS time stamps are the receiver\'s clock and are never shifted; maker-note times, embedded preview or thumbnail Exif, XMP edit-history times (xmpMM:History), QuickTime or sidecar times, file-system times and file names are not interpreted and not changed.',
        'A fraction of a second that IPTC cannot hold is truncated toward the earlier second and listed per item (iptcFractionDropped); no other value is rounded. No time zone, daylight-saving rule or leap second is known.',
        'A reference time, an assumed offset and an assumed-correct group are the author\'s declarations: the write does not verify them, and a correct-looking result is not proof the camera clock was right.'],
    'setLocation': [
        'Only the catalogued GPS values were written, removed or kept as declared. Place names (IPTC city, region, country, XMP location structures) are not updated and nothing is geocoded; maker-note positions, embedded preview or thumbnail Exif and sidecar positions are not interpreted and not changed.',
        'The stored coordinate precision is a serialisation bound (2e-10 degrees), not GPS accuracy. An altitude is written only with the reference the author declared and only where the file\'s metadata edition can express it; no vertical datum is converted and no ExifVersion is promoted.',
        'Readers older than Exif 3.0 print altitude references 0 and 1 as above or below sea level; the published reference is the author\'s declaration and legacy readers may not recognise a sea-level reference of 2 or 3.'],
    'geotagFromTrack': [
        'Positions were interpolated by great-circle slerp between consecutive fixes of the captured tracks (or taken exactly on a fix, or snapped to a nearby segment endpoint when the author allowed it); the path between fixes is unknown and no accuracy, confidence or error radius is claimed. The native geotag feature is not used and not compared.',
        'The photo instant is the recorded capture wall time minus the recorded (or declared) offset, moved by a declared clock correction that is applied to the photo instant only; the image\'s own time fields are not rewritten. There is no system time zone, and a wrong camera clock gives a wrong position.',
        'Place names are not updated, nothing is geocoded, and maker-note positions, preview Exif and sidecar positions are not interpreted. The stored coordinate precision is a serialisation bound, not GPS accuracy.']}
PLACE_DATASETS = {(2, 90): 'City', (2, 92): 'Sublocation', (2, 95): 'Province-State', (2, 100): 'Country-PrimaryLocationCode', (2, 101): 'Country-PrimaryLocationName'}


def names(p):
    """The report documents of an operation, in published order (they follow the item slots in a write run; a plan-only run has no slots)."""
    op = p['operation']
    if p.get('apply') == 'plan':
        return {'correctTime': ['time-correction-plan.json', 'time-report.json', 'manifest.json'], 'setLocation': ['location-plan.json', 'manifest.json'],
                'geotagFromTrack': ['geotag-plan.json', 'track-report.json', 'manifest.json']}[op]
    return {'correctTime': ['time-correction-plan.json', 'time-report.json', 'write-report.json', 'residual.json', 'manifest.json'],
            'setLocation': ['location-plan.json', 'write-report.json', 'residual.json', 'manifest.json'],
            'geotagFromTrack': ['track-report.json', 'geotag-plan.json', 'write-report.json', 'residual.json', 'manifest.json']}[op]


def request_doc(request):
    """The published form of a normalised position request (signed decimals as text, exactly as written)."""
    out = {}
    for axis in ('latitude', 'longitude'):
        r = request[axis]
        out[axis] = {'decimal': format(r['value'], 'f') if r['value'] != 0 else '0', 'reference': r['ref'], 'signedZeroNormalised': r['signedZeroNormalised']}
    if request['altitude'] is not None:
        a = request['altitude']
        out['altitude'] = {'meters': a['meters'], 'reference': a['reference']}
    if request['datum'] is not None:
        out['datum'] = request['datum']
    if request['horizontalError'] is not None:
        out['horizontalErrorMeters'] = request['horizontalError']['magnitude']
    if request['gpsUtc'] is not None:
        out['gpsUtc'] = request['gpsUtc']['text']
    return out


def group_doc(gp):
    return {'group': gp['group'], 'before': gp['before'], 'after': gp['after'], 'deltaNanoseconds': gp['deltaNanoseconds'], 'shiftSeconds': tc.seconds_text(gp['deltaNanoseconds']), 'changed': gp['changed'],
            'targets': [{'family': t['family'], 'location': t['location'], 'changes': t['changes'], 'writes': [{'name': n, 'value': v} for n, v in t['writes']],
                         'components': [{k: c[k] for k in ('kind', 'field', 'before', 'after')} for c in t['components']]} for t in gp['targets']],
            'losses': gp['losses'], 'infos': gp['infos']}


def entry_of(p, item):
    """The plan-document entry of one item: what this operation would do (or did) with the capture, with the exact native arguments."""
    entry = {'id': item['id'], 'captureSha256': item.get('sha256'), 'arguments': []}
    plan = item.get('plan')
    if item['status'] != 'ok' or plan is None:
        entry.update(status='refused', outcome='refused', fault=item.get('fault'))
        return entry
    entry.update(status='unchanged' if plan['kind'] == 'unchanged' else 'planned', outcome=plan['outcome'], arguments=list(plan['args']))
    if plan['kind'] == 'time':
        entry.update(group=plan['group'], basis=plan['basis'], skewSeconds=plan['skewSeconds'], groups=[group_doc(gp) for gp in plan['groups']], losses=plan['losses'], infos=plan['infos'])
    elif plan['kind'] == 'location':
        entry.update(position=request_doc(plan['request']), edition=plan['edition'], altitude=plan['altitude'], writes={'exif': plan['exifActive'], 'xmp': plan['xmpActive'], 'xmpRemoved': plan['xmpRemove']},
                     creation=plan['creation'], losses=plan['losses'], infos=plan['infos'])
        for key in ('placement', 'photoInstant', 'track'):
            if key in plan:
                entry[key] = plan[key]
    else:
        entry.update(reason=plan['reason'], detail=plan['detail'])
    return entry


def plan_document(p, ctx, base, table, items):
    op = p['operation']
    block = {k: v for k, v in ctx.block.items() if k != 'planFile'}
    doc = {**base, 'version': e3write.PLAN_SCHEMAS[op], 'apply': p.get('apply', 'write'), 'inputs': block['arguments'], 'declared': e3write.json_safe(block),
           'items': [entry_of(p, item) for item in items],
           'statement': 'The native assignments each item receives, decided from the independent read of its capture before any native write; values are computed by Schemaxis and never authored as native options. A plan applies only to the captures it was made for.'}
    if ctx.plan_sha is not None:
        doc['appliedPlanSha256'] = ctx.plan_sha
    if ctx.tracks is not None:
        doc['trackSha256'] = [{'id': t['id'], 'sha256': t['data']['sha256']} for t in ctx.tracks]
    if ctx.clock_plan is not None:
        doc['clockPlanSha256'] = ctx.inputs['clockPlan']['sha256']
    return doc


def row_extra(p, item, outcome):
    """Extra keys of an item's write-report row (written items only)."""
    plan = item['plan']
    extra = {'outcome': plan['outcome'], 'losses': plan['losses'], 'infos': plan['infos']}
    if plan['kind'] == 'unchanged':
        extra.update(reason=plan['reason'])
    if item.get('readback') is not None:
        extra['readback'] = item['readback']
    return extra


def published_readback(plan, payloads_out):
    """The independently decoded after-values of the written targets (stored rationals with their exact sum, XMP literals, typed height), never the request."""
    out = {}
    if plan['kind'] == 'location':
        if plan['exifActive']:
            for axis, short in (('latitude', 'lat'), ('longitude', 'lon')):
                triple, ref = e3read.raw_position(payloads_out, short)
                if triple is not None:
                    out[axis] = {**locations.quantisation(triple, abs(plan['exifExpect'][axis]['value'])), 'reference': ref}
            if plan['exifExpect']['altitude'] is not None:
                out['height'] = e3read.height(payloads_out)
            entry = e3proofs.raw_entry(payloads_out, 0x0000)
            out['gpsVersionId'] = None if entry is None else entry.values()
        props = e3place.xmp_properties(payloads_out)
        xmp = {}
        for axis in ('latitude', 'longitude'):
            found = props.get('exif:GPS' + axis.capitalize())
            if found and found[0].get('kind') == 'text' and plan['xmpExpect'][axis] is not None:
                xmp[axis] = found[0]['value']
        if xmp:
            out['xmp'] = xmp
    return out


def residual_row(p, item, helpers):
    payloads = item['payloads']
    row = {'id': item['id']}
    xmp = e3place.xmp_properties(payloads)
    from schemaxis.adaptors.exiftool import proofs
    datasets = proofs.datasets_of(payloads)
    row['mayContainCaptureTimeOrLocation'] = {'makerNote': helpers['maker_note_size'](payloads) is not None, 'embeddedThumbnail': helpers['thumbnail'](item['located']) is not None,
                                               'xmpEditHistory': 'xmpMM:History' in xmp, 'iptcPlaceNames': sorted(PLACE_DATASETS[k] for k in datasets if k in PLACE_DATASETS)}
    if p['operation'] == 'correctTime':
        gps = e3place.gps_entries(payloads)
        row['gpsTimeStampsPresent'] = bool({0x0007, 0x001D} & set(gps))
        selected = p['e3']['timeFields'] if 'timeFields' in p['e3'] else None
        row['modifiedNotShifted'] = selected is not None and 'modified' not in selected and 'xmp:ModifyDate' in xmp
    return row


def residual_document(p, base, table, items, helpers):
    rows = [residual_row(p, item, helpers) for r, item in zip(table, items) if r['status'] == 'written']
    return {**base, 'items': rows, 'limits': RESIDUAL_LIMITS[p['operation']]}


def track_report_document(p, ctx, base):
    index = ctx.index
    return {**base, 'conventions': {'interpolation': 'great-circle slerp between consecutive timed fixes of one segment; exact on a fix; no extrapolation; segments, tracks and gaps are never bridged',
                                    'datum': 'WGS-84 for GPX 1.1 (the schema says so); a GPX 1.0 datum only if the author declared one', 'accuracy': 'none claimed'},
            'tracks': e3track.track_report(ctx.tracks, index), 'settings': {'interpolation': ctx.block['interpolation'], 'track': ctx.block['track']}}


def documents(p, ctx, base, table, items, outcomes, encode, helpers):
    """Every E3 report document (bytes by name) except ``manifest.json`` and the per-item outcome documents, which the E2 writer publishes."""
    op = p['operation']
    files = {e3write.PLAN_FILES[op]: encode(plan_document(p, ctx, base, table, items))}
    if op == 'correctTime':
        files['time-report.json'] = e3time_report(p, ctx, base, items, encode)
    if op == 'geotagFromTrack':
        files['track-report.json'] = encode(track_report_document(p, ctx, base))
    if p.get('apply') == 'plan':
        return files
    files['write-report.json'] = encode({**base, 'items': table, 'statement': 'Per-item outcomes with the three proofs. P is about bytes, not pixels; N compares two listings of the same engine; the published after-values are decoded from the output bytes, not copied from the request.',
                                        'review': {'observedMetadataOnly': True, 'privacyCertified': False, 'humanReviewRequired': True}})
    files['residual.json'] = encode(residual_document(p, base, table, items, helpers))
    return files


def e3time_report(p, ctx, base, items, encode):
    report = getattr(ctx, 'report', None)
    document = {**base, 'version': e3reports.TIME_REPORT_VERSION, 'conventions': {'skew': 'recorded minus true, in exact decimal seconds (a trailing ~ marks a repeating decimal cut at 9 places); positive means the camera is ahead',
                                                                                  'declared': 'references, assumeCorrect and assumedOffsets are the author\'s declarations and are never verified'},
                'declared': ctx.block['time'], 'report': report}
    return encode(document)
