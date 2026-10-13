"""Retain file-only native mesh sources without importing Blender on the host."""
import json
import shutil
from pathlib import Path
from schemaxis.artifacts import atomic_json
from schemaxis.errors import fail
from schemaxis.artifacts import file_digest
READERS={'readGltf','readSTL','readPLY','curveFromCSV'}


def capture(master,selection,directory):
    sources={}
    for identity in selection.order:
        node=master.nodes[identity]
        if node['filter'] not in READERS:continue
        source=Path(node['options']['file']).absolute()
        if not source.is_file():fail('RESOURCE_NOT_FOUND','mesh source is absent',str(source))
        extension={'readGltf':'.gltf','readSTL':'.stl','readPLY':'.ply','curveFromCSV':'.csv'}[node['filter']]
        local=directory/('source-'+str(len(sources))+extension)
        shutil.copyfile(source,local)
        digest=file_digest(local)
        if file_digest(source)!=digest:fail('INPUT_CHANGED','mesh input changed during capture',identity)
        sources[identity]={'file':str(source),'retained':str(local),'sha256':digest}
    atomic_json(directory/'sources.json',sources)


def verify(master,selection,directory):
    # Older receipts predate input capture; their native snapshots remain valid.
    if not (directory/'sources.json').exists():return
    sources=json.loads((directory/'sources.json').read_text())
    readers=[identity for identity in selection.order if master.nodes[identity]['filter'] in READERS]
    if set(sources)!=set(readers):fail('VERIFICATION_FAILED','mesh source membership differs')
    for identity in readers:
        source=sources[identity];original=Path(master.nodes[identity]['options']['file']).absolute()
        local=Path(source['retained']).resolve()
        if source['file']!=str(original) or local.parent!=directory.resolve():fail('VERIFICATION_FAILED','mesh source path differs',identity)
        if file_digest(local)!=source['sha256'] or file_digest(original)!=source['sha256']:fail('INPUT_CHANGED','mesh source or retained copy changed',identity)
