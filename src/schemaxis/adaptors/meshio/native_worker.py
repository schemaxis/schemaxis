# Copyright (C) 2026 David L F Gaden
"""Trusted isolated meshio worker; never imported by the host runtime."""
import hashlib
import json
import os
from pathlib import Path
import resource
import stat
import sys

resource.setrlimit(resource.RLIMIT_AS, (2*1024**3, 2*1024**3))
resource.setrlimit(resource.RLIMIT_FSIZE, (32*1024**2, 32*1024**2))
resource.setrlimit(resource.RLIMIT_CPU, (60, 60))


def bounded(name):
    fd = os.open(name, os.O_RDONLY | os.O_NONBLOCK | os.O_NOFOLLOW)
    with os.fdopen(fd, 'rb') as stream:
        info = os.fstat(stream.fileno())
        if not stat.S_ISREG(info.st_mode) or info.st_size > 32*1024**2:
            raise ValueError('MESH_INPUT_LIMIT')
        return stream.read(32*1024**2+1)


def canonical(mesh):
    import numpy as np
    if mesh.field_data or mesh.point_sets or mesh.cell_sets or mesh.gmsh_periodic:
        raise ValueError('MESH_UNSUPPORTED_METADATA')
    if mesh.points.shape[1:] != (3,) or not 1 <= len(mesh.points) <= 100000:
        raise ValueError('MESH_POINTS_INVALID')
    cells = []
    for block in mesh.cells:
        if block.type not in ('triangle', 'tetra', 'hexahedron'):
            raise ValueError('MESH_UNSUPPORTED_CELL')
        for row in block.data.tolist(): cells.append([block.type, row])
    if not 1 <= len(cells) <= 100000: raise ValueError('MESH_CELL_LIMIT')
    def fields(mapping, count):
        result = {}
        if len(mapping) > 16: raise ValueError('MESH_DATA_LIMIT')
        for name, values in mapping.items():
            values = np.asarray(values)
            if values.shape == (count,): values = values[:, None]
            if values.shape not in ((count, 1), (count, 3)) or values.dtype.kind not in 'iuf' or not np.all(np.isfinite(values)):
                raise ValueError('MESH_DATA_INVALID')
            result[name] = values.tolist()
        return result
    return {'points': mesh.points.tolist(), 'cells': cells, 'pointData': fields(mesh.point_data, len(mesh.points)), 'cellData': fields({k: np.concatenate(v) for k, v in mesh.cell_data.items()}, len(cells))}


def main():
    import meshio
    import numpy as np
    if meshio.__version__ != '5.3.5': raise ValueError('UNSUPPORTED_MESHIO_RUNTIME')
    stage = sys.argv[1]
    config = json.loads(bounded('native-config.json'))
    name = 'source.'+config['sourceFormat'] if stage == 'convert' else 'mesh.'+config['targetFormat']
    data = bounded(name)
    consumed = {p: hashlib.sha256(bounded(p)).hexdigest() for p in (name, 'native-config.json', 'native-worker.py')}
    Path(stage+'-inputs.json').write_text(json.dumps(consumed, sort_keys=True))
    mesh = meshio.read(name, file_format=config['sourceFormat'] if stage == 'convert' else config['targetFormat'])
    before = canonical(mesh)
    if stage == 'convert':
        mesh.points = np.asarray(mesh.points, dtype=np.float64)*config['factor']
        canonical(mesh)
        meshio.write('mesh.'+config['targetFormat'], mesh, file_format='vtk42' if config['targetFormat'] == 'vtk' else 'vtu', binary=False)
    print(json.dumps({'runtime': meshio.__version__, 'numpy': np.__version__, 'mesh': before}, allow_nan=False, sort_keys=True))


if __name__ == '__main__': main()
