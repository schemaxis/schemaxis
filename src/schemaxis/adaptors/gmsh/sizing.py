"""Host checks for app-owned named-boundary sizing readback."""
from .mesh import check


def verify(built, settings):
    rules = settings['nearBoundaries']
    saved = built.get('sizing', {})
    check(set(saved) == {'rules', 'minimum', 'maximum', 'combinedType', 'combinedFields'}, 'sizing evidence differs')
    check(saved['minimum'] == min([settings['size']]+[r['size'] for r in rules])
          and saved['maximum'] == settings['size'], 'native global sizing bounds differ')
    check(saved['combinedType'] == ('Min' if rules else None)
          and saved['combinedFields'] == [2*i+2 for i in range(len(rules))], 'native sizing combination differs')
    check(len(saved['rules']) == len(rules), 'native sizing rules differ')
    names = {settings['boundaryName']: 2, **{g['name']: i+3 for i,g in enumerate(settings['faceGroups'])}}
    for index, (actual, rule) in enumerate(zip(saved['rules'], rules)):
        entities = actual.get('entities')
        check(isinstance(entities, list) and entities and all(type(v) is int and v > 0 for v in entities)
              and len(set(entities)) == len(entities), 'native sizing boundary entities are invalid')
        expected = {'boundary': rule['boundary'], 'physicalTag': names[rule['boundary']],
                    'entities': entities, 'distanceSurfaces': entities, 'distanceType': 'Distance',
                    'thresholdType': 'Threshold', 'sampling': 20,
                    'threshold': {'InField': 2*index+1, 'SizeMin': rule['size'], 'SizeMax': settings['size'],
                                  'DistMin': 0, 'DistMax': rule['distance'], 'StopAtDistMax': 0}}
        check(actual == expected, 'native boundary field readback differs from sizing intent')
