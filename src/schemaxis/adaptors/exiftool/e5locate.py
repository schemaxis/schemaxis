"""One entry point over every E5 container locator (standard library only).

``locate(data, name=None)`` detects the container by signature alone, applies the profile's size bound, runs the container locator and returns
its result (see ``e5common``). JPEG keeps its existing locator and preservation proof untouched; its result only gains the common ``slots``
view. A file name is used for one purpose: a suffix that disagrees with the detected container adds the note ``EXTENSION_MISMATCH``.
"""
from pathlib import Path

from schemaxis.adaptors.exiftool import containers, e5common as common, e5heif, e5png, e5profiles, e5riff, e5tiff

LOCATORS = {'tiff': e5tiff.locate, 'png': e5png.locate, 'webp': e5riff.locate, 'heif': e5heif.locate}
LEGACY_SUFFIXES = {'.jpg': 'jpeg', '.jpeg': 'jpeg', '.jpe': 'jpeg', '.xmp': 'xmp'}


def jpeg_view(found):
    """The existing locator result with the common ``slots`` view added; JPEG protection stays with ``jpegwrite.preservation``."""
    found = dict(found)
    found['slots'] = [common.slot(f, 'present' if found[f] else 'absent', count=len(found[f])) for f in common.FAMILIES]
    found['protected'] = None
    found['write'] = None
    return found


def has_maker_note(payload):
    """Whether an Exif TIFF stream has a maker note entry (ExifIFD 0x927C), read by the shared bounded walker; an unreadable stream has none."""
    from schemaxis.adaptors.exiftool import tiff
    try:
        group = tiff.walk(payload)['ifds'].get('ExifIFD')
    except tiff.Damaged:
        return False
    return bool(group and group[0] == 'ok' and any(e.tag == 0x927C for e in group[1]))


def locate(data, name=None):
    kind = e5profiles.detect(data)
    if kind is None:
        found = containers.locate(data)
        found = jpeg_view(found)
        container = found['container']
    else:
        limit = e5profiles.profile(kind)['maxBytes']
        if len(data) > limit:
            raise common.Refused('PHOTO_RESOURCE_LIMIT', 'the file exceeds %d bytes' % limit, bytes=len(data))
        found = LOCATORS[kind](data)
        container = found['container']
    if container != 'jpeg' and 'makerNoteMayIdentifyDevice' not in found.get('limitations', ()) and any(has_maker_note(payload) for payload in found.get('exif', ())):
        found.setdefault('limitations', []).append('makerNoteMayIdentifyDevice')      # a kept maker note may still identify the device, in any container that holds one
    if name is not None:
        suffix = Path(str(name)).suffix.lower()
        expected = [LEGACY_SUFFIXES[suffix]] if suffix in LEGACY_SUFFIXES else e5profiles.by_suffix(name)
        if expected and container not in expected:
            found['notes'].append('EXTENSION_MISMATCH')
            found['extension'] = {'suffix': suffix, 'detected': container}
    return found
