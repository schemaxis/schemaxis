"""Generalised preservation proof P over two files of one container (standard library only).

``preserve(before, after, allow=())`` states what a rewrite did to everything that is not an editable metadata slot, without comparing any
offset, so a writer may relocate strips, tiles, chunks and HEIF items. It is independent of the native writer: both files are located by the
E5 locators and the fingerprints are compared row by row. Nothing here decodes pixels, and the proof says nothing about authenticity.

The result is ``{'ok': bool, 'container': str, 'faults': [{'code', 'path', 'message'}]}``:

* ``PRESERVATION_MISMATCH``: a protected row changed, was dropped, added or reordered; ``path`` names the role and key. Rows a plan declares
  changeable (planned targets, closed native side effects) are passed in ``allow`` as ``(role, key)`` pairs or bare roles.
* the container changed (a TIFF written back as DNG, say) or the output cannot be located: ``PRESERVATION_MISMATCH`` or the locator's code;
* the output has a structural refusal the input did not have (for example a HEIF ``iref`` the native writer left inconsistent): that code;
* WebP: the AM-16R layout proof replaces the plain VP8X row comparison, because VP8X may be created or removed as predicted.

JPEG keeps ``jpegwrite.preservation``; passing a JPEG here is an error, never a silent pass.
"""
from schemaxis.adaptors.exiftool import e5common as common, e5locate, e5riff


def fault(code, path, message):
    return {'code': code, 'path': path, 'message': message}


def preserve(before, after, *, allow=()):
    """Proof P for two file contents; ``before`` must be a file the locators admit (the caller refused anything else before the write)."""
    first = e5locate.locate(before)
    if first['protected'] is None:
        raise ValueError('JPEG files are proved by jpegwrite.preservation, not by the E5 fingerprint')
    container = first['container']
    faults = []
    try:
        second = e5locate.locate(after)
    except common.Refused as error:
        return {'ok': False, 'container': container, 'faults': [fault(error.code, 'output', error.message)]}
    if second['container'] != container:
        faults.append(fault('PRESERVATION_MISMATCH', 'container', 'the output is %s but the input was %s' % (second['container'], container)))
    known = {r['code'] for r in first['write']['refusals']}
    for refusal in second['write']['refusals']:
        if refusal['code'] not in known:
            faults.append(fault(refusal['code'], 'output', refusal['message']))
    exempt = tuple(allow) + (('riff/vp8x',) if container == 'webp' else ())
    for row in common.compare(first['protected'], second['protected'], allow=exempt):
        faults.append(fault('PRESERVATION_MISMATCH', row['path'], 'a protected %s row was %s' % (row['role'], row['kind'])))
    if container == 'webp':
        for row in e5riff.prove_layout(before, after):
            if row['code'] != 'PRESERVATION_MISMATCH' or not any(f['code'] == 'PRESERVATION_MISMATCH' for f in faults):
                faults.append(fault(row['code'], 'riff/layout', row['message']))
    effects = []
    if container in ('tiff', 'dng'):
        faults, effects = maker_note_relocation(before, after, faults)
    return {'ok': not faults, 'container': container, 'faults': faults, **({'effects': effects} if effects else {})}


MAKER_NOTE_PATH = 'tiff/entry[IFD0/Exif:0x927c]'


def maker_note_relocation(before, after, faults):
    """D-3: a maker note whose bytes changed because the native writer moved it is compared by the independent relocation-aware check of the JPEG proof (a plain IFD whose entries keep tag, type, count,
    value bytes and relative position; only its own offset fields move by one delta). A rebuilt note that this check cannot show equal stays a ``MAKERNOTE_CHANGED`` fault: never a verified write."""
    noted = [f for f in faults if f['path'] == MAKER_NOTE_PATH and f['message'].endswith('was changed')]
    if not noted:
        return faults, []
    from schemaxis.adaptors.exiftool import proofs
    found, effect = proofs.maker_note_check(before, after, 'image')
    rest = [f for f in faults if f not in noted]
    if found:
        return rest + [fault('MAKERNOTE_CHANGED', noted[0]['path'], p['message']) for p in found], []
    return rest, [effect] if effect else [{'rule': 'S8-makerNoteRelocated', 'entry': 'ExifIFD:0x927C'}]
