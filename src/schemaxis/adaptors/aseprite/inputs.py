# Copyright (C) 2026 David L F Gaden
"""Captured PNG assets: original paths never cross the native boundary."""
import hashlib
import os
from pathlib import Path
import stat

from schemaxis.artifacts import atomic_json
from schemaxis.errors import fail
from .png import MAX_BYTES, decode


def source_bytes(path):
    try:
        if Path(path).is_symlink(): fail('INVALID_RESOURCE', 'PNG source may not be a symbolic link', str(path))
        descriptor = os.open(path, os.O_RDONLY | getattr(os, 'O_NONBLOCK', 0) | getattr(os, 'O_NOFOLLOW', 0))
        with os.fdopen(descriptor, 'rb') as stream:
            info = os.fstat(stream.fileno())
            if not stat.S_ISREG(info.st_mode):
                fail('INVALID_RESOURCE', 'PNG source must be a regular file, not a directory/device/pipe', str(path))
            if info.st_size > MAX_BYTES: fail('RESOURCE_LIMIT', 'PNG source exceeds 2 MiB', str(path))
            data = stream.read(MAX_BYTES+1)
        if len(data) > MAX_BYTES: fail('RESOURCE_LIMIT', 'PNG source exceeds 2 MiB', str(path))
        return data
    except OSError as error:
        fail('INVALID_RESOURCE', 'cannot read regular PNG source: '+str(error), str(path))


def records(prepared):
    return [(index, node) for index, node in enumerate(prepared['nodes']) if node['filter'] == 'importImage']


def inspect(prepared, directory=None):
    """Read originals before capture, or validate only retained copies offline."""
    if directory is not None and (Path(directory)/"inputs").is_symlink():
        fail("VERIFICATION_FAILED", "captured input directory may not be a symlink", "inputs")
    images, manifest, total = {}, [], 0
    for index, node in records(prepared):
        o = node['options']
        retained = f'inputs/source-{index:03d}.png'
        path = Path(o['source']) if directory is None else Path(directory)/retained
        data = source_bytes(path)
        total += len(data)
        if total > 16*1024*1024: fail('RESOURCE_LIMIT', 'imported PNG files exceed 16 MiB in total', '$.nodes')
        image = decode(data, location=f'$.nodes[{index}].options.source')
        if (image['width'], image['height']) != (o['width'], o['height']):
            fail('IMAGE_DIMENSIONS', 'PNG dimensions must equal declared width/height; no scaling or clipping',
                 f'$.nodes[{index}].options', actualWidth=image['width'], actualHeight=image['height'])
        images[node['id']] = image
        manifest.append({'node': node['id'], 'source': o['source'], 'retained': retained,
                         'width': image['width'], 'height': image['height'],
                         'sha256': hashlib.sha256(data).hexdigest()})
    return images, manifest


def capture(prepared, directory):
    # Read once and validate these same bytes; source changes after capture have no
    # influence on native execution or retained offline verification.
    directory = Path(directory)
    manifest, images, total = [], {}, 0
    for index, node in records(prepared):
        o = node['options']
        data = source_bytes(o['source'])
        total += len(data)
        if total > 16*1024*1024: fail('RESOURCE_LIMIT', 'imported PNG files exceed 16 MiB in total', '$.nodes')
        image = decode(data, location=f'$.nodes[{index}].options.source')
        if (image['width'], image['height']) != (o['width'], o['height']):
            fail('IMAGE_DIMENSIONS', 'PNG dimensions must equal declared width/height; no scaling or clipping',
                 f'$.nodes[{index}].options', actualWidth=image['width'], actualHeight=image['height'])
        target = directory/f'inputs/source-{index:03d}.png'
        target.parent.mkdir(exist_ok=True)
        target.write_bytes(data)
        images[node['id']] = image
        manifest.append({'node': node['id'], 'source': o['source'], 'retained': target.relative_to(directory).as_posix(),
                         'width': image['width'], 'height': image['height'], 'sha256': hashlib.sha256(data).hexdigest()})
    atomic_json(directory/'input-manifest.json', {'version': 'schemaxis.aseprite.inputs/1', 'images': manifest})
    return images, manifest
