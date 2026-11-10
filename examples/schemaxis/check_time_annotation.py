"""Independent checks for the paraview-time-annotation.json acceptance example.

The sphere is static, so labelled images may differ between times only through
the drawn time label, while the plain scene must render identical pixels.
"""
import argparse
import json
from pathlib import Path

JUSTIFICATION = {'Left': 'Left', 'Center': 'Centered', 'Right': 'Right'}


def check(result):
    verification = json.loads((Path(result) / 'verification.json').read_text())
    assert verification['status'] == 'succeeded' and verification['verified'] is True
    times = sorted({state['visit']['time'] for state in verification['states']})
    assert len(times) == 2, times
    images = [a for a in verification['artifacts'] if a['identity']['kind'] == 'image']
    labelled = [a for a in images if a['identity']['scene'] == 'labelled']
    plain = [a for a in images if a['identity']['scene'] == 'plain']
    assert len(labelled) == 4 and len(plain) == 2
    for artifact in images:
        assert artifact['verified'] is True and artifact['dimensions'][:2] == [320, 240]
        assert artifact['viewTime'] == times[artifact['identity']['timeIndex']]
    for artifact in labelled:
        time = times[artifact['identity']['timeIndex']]
        drawn, authored = artifact['annotations']['label'], artifact['effectiveAppearance']['label']
        assert drawn['text'] == f't = {time:.3f}', drawn['text']
        assert drawn['viewTime'] == time
        assert drawn['justification'] == JUSTIFICATION[authored['justification']]
        assert all(abs(a - b) < 1e-12 for a, b in zip(drawn['colour'], authored['colour']))
        assert all(drawn[k] == authored[k] for k in ('fontSize', 'bold', 'italic'))
        receipt = artifact['appearance']['label']
        assert receipt['kind'] == 'text' and receipt['position'] == authored['position']
    for appearance in (0, 1):
        pair = sorted((a for a in labelled if a['identity']['appearance'] == appearance),
                      key=lambda a: a['identity']['timeIndex'])
        assert pair[0]['annotations']['label']['text'] != pair[1]['annotations']['label']['text']
        assert pair[0]['pixelSha256'] != pair[1]['pixelSha256'], 'time label did not change the drawn image'
    styles = {a['identity']['appearance']: a['annotations']['label'] for a in labelled}
    assert (styles[0]['fontSize'], styles[0]['bold'], styles[0]['italic']) == (28, True, False)
    assert (styles[1]['fontSize'], styles[1]['bold'], styles[1]['italic']) == (16, False, True)
    assert all('annotations' not in a and 'label' not in a['appearance'] for a in plain)
    assert plain[0]['pixelSha256'] == plain[1]['pixelSha256'], 'plain scene retained time-dependent text'
    return {'verified': True, 'times': times,
            'labels': sorted({a['annotations']['label']['text'] for a in labelled}),
            'checks': ['drawn label matches each selected view time', 'labels and pixels differ between times',
                       'drawn font, colour and justification match each appearance',
                       'plain scene has no text and identical pixels at both times']}


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('result', help='output directory of the example run')
    print(json.dumps(check(parser.parse_args().result), indent=2))
