"""The single host-side map between authored boundary names and physical tags.

Tag 1 is the volume and tag 2 the remainder. Planar groups take tags 3.. in
declared order and cylinder groups follow them. The remainder may be absent only
when cylinder groups are declared; its tag is then reserved but unused.
"""

VOLUME_TAG = 1
REMAINDER_TAG = 2


def planes(settings):
    return settings['faceGroups']


def cylinders(settings):
    return settings.get('cylinderGroups', [])


def plane_tag(index):
    return REMAINDER_TAG + 1 + index


def cylinder_tag(settings, index):
    return REMAINDER_TAG + 1 + len(planes(settings)) + index


def tags(settings, remainder=True):
    """Boundary name to physical tag; the remainder is omitted when absent."""
    result = {settings['boundaryName']: REMAINDER_TAG} if remainder else {}
    result.update({g['name']: plane_tag(i) for i, g in enumerate(planes(settings))})
    result.update({g['name']: cylinder_tag(settings, i) for i, g in enumerate(cylinders(settings))})
    return result


def declared_names(settings):
    """Every name a sizing or requirement may reference, remainder included."""
    return set(tags(settings))


def expected(settings, remainder=True):
    """Physical groups, sorted as the MSH reader reports them."""
    groups = [{'dimension': 2, 'tag': tag, 'name': name} for name, tag in tags(settings, remainder).items()]
    groups.append({'dimension': 3, 'tag': VOLUME_TAG, 'name': settings['volumeName']})
    return sorted(groups, key=lambda g: (g['dimension'], g['tag']))
