# Copyright (C) 2026 David L F Gaden
"""Host-safe ParaView execution capabilities and qualification boundaries."""
from schemaxis.errors import fail

MPI_OPERATIONS = frozenset({'sphere', 'slice', 'foam', 'merge', 'calculator',
                            'surface', 'outline', 'integrate',
                            'readParallelPolyData', 'readParallelUnstructuredGrid'})
CAPABILITIES = {'modes': ['serial', 'mpi'], 'mpiDriver': 'normal pvbatch (one Python driver)',
                'geometry': 'native parallel XML writers and distributed exact piece verification',
                'mpiOperations': sorted(MPI_OPERATIONS),
                'measurements': 'bounded native integrate reductions',
                'clusterQualification': False}


def validate_mpi(document):
    from .job import plan
    from schemaxis.pipeline import markers
    provisional = dict(document)
    if isinstance(provisional.get('times'), dict):
        provisional['times'] = [0.0]  # Source-time metadata is inspected by the native reader at execution.
    master, scenes, _ = plan(provisional)
    active = {node for scene in scenes for node in scene['selection']['order']}
    unsupported = {master.nodes[node]['filter'] for node in active} - MPI_OPERATIONS
    if unsupported:
        fail('UNSUPPORTED_MPI_PIPELINE', 'operations have not been qualified for MPI', unsupported=sorted(unsupported))
    if any(scene['gltf'] or scene.get('exports') for scene in scenes):
        fail('UNSUPPORTED_MPI_PUBLICATION', 'MPI supports native distributed geometry and images; custom exports/glTF remain serial')
    if any(master.nodes[item['node']]['filter'] != 'integrate' for scene in scenes for item in scene['measurements']):
        fail('UNSUPPORTED_MPI_MEASUREMENT', 'reduce with integrate before measuring; full fields belong in distributed geometry outputs')
    if any('$sample' in marker for marker in markers(master.document)):
        fail('UNSUPPORTED_MPI_SAMPLE', 'global tuple sampling is undefined across partitions; use native reductions or observations')
    return CAPABILITIES
