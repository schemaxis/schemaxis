"""Independent checks for the paraview-image-background.json acceptance example.

Each PNG is decoded on the host. Corners must show the requested background (or
zero alpha), the model's centre pixel must not depend on the background, and the
native background-pixel counts must match an independent recount.
"""
import argparse
import json
from pathlib import Path
from schemaxis.png import read

EXPECTED = {'white': ((255, 255, 255), False), 'slate': ((51, 102, 153), False), 'clear': (None, True)}


def check(result):
    verification = json.loads((Path(result) / 'verification.json').read_text())
    assert verification['status'] == 'succeeded' and verification['verified'] is True
    assert verification['backgroundVersion'] == 1
    images = {a['identity']['writer']: a for a in verification['artifacts'] if a['identity']['kind'] == 'image'}
    assert sorted(images) == sorted(EXPECTED), sorted(images)
    centres, counts = {}, {}
    for writer, (colour, transparent) in EXPECTED.items():
        artifact = images[writer]
        width, height, pixels = read(artifact['file'])
        assert (width, height) == (320, 240)
        pixel = lambda x, y: tuple(pixels[4 * (y * width + x):4 * (y * width + x) + 4])
        corners = [pixel(x, y) for x in (0, width - 1) for y in (0, height - 1)]
        if transparent:
            assert all(c[3] == 0 for c in corners), corners
            count = sum(1 for i in range(3, len(pixels), 4) if pixels[i] == 0)
            assert artifact['background']['channels'] == 4
        else:
            assert all(c == (*colour, 255) for c in corners), corners
            count = sum(1 for i in range(0, len(pixels), 4)
                        if all(abs(pixels[i + k] - colour[k]) <= 1 for k in range(3)))
        assert artifact['background']['transparent'] is transparent
        assert artifact['background']['backgroundPixels'] == count, (writer, count)
        assert 0 < count < width * height
        centres[writer] = pixel(width // 2, height // 2)
        counts[writer] = count
    assert centres['clear'][3] == 255
    assert len(set(centres.values())) == 1, centres
    return {'verified': True, 'centrePixel': centres['white'], 'backgroundPixels': counts,
            'checks': ['corners show the requested opaque colour or zero alpha',
                       'model centre pixel is identical for every background',
                       'native background-pixel counts match an independent host recount']}


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('result', help='output directory of the example run')
    print(json.dumps(check(parser.parse_args().result), indent=2))
