# Copyright (C) 2026 David L F Gaden
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
    production=master.document['scenes'][0].get('production',{})
    image_bytes=0
    for image in [*production.get('images',[]),*production.get('assets',[])]:
        identity=('asset:' if 'format' in image else 'production:')+image['id'];source=Path(image['file']).absolute()
        local=directory/('source-'+str(len(sources))+source.suffix.lower())
        if 'format' not in image:
            from .image_assets import admit_file,capture_file
            before=image_bytes;image_bytes=admit_file(source,identity,image_bytes)
            digest=capture_file(source,local,image_bytes-before,identity)
        else:
            if not source.is_file():fail('RESOURCE_NOT_FOUND','asset source is absent',str(source))
            shutil.copyfile(source,local);digest=file_digest(local)
            if file_digest(source)!=digest:fail('INPUT_CHANGED','asset input changed during capture',identity)
        sources[identity]={'file':str(source),'retained':str(local),'sha256':digest}
    atomic_json(directory/'sources.json',sources)


def verify(master,selection,directory):
    # Older receipts predate input capture; their native snapshots remain valid.
    if not (directory/'sources.json').exists():return
    sources=json.loads((directory/'sources.json').read_text())
    readers=[identity for identity in selection.order if master.nodes[identity]['filter'] in READERS]
    image_inputs={'production:'+i['id']:i['file'] for i in master.document['scenes'][0].get('production',{}).get('images',[])}
    production_inputs=dict(image_inputs)
    production_inputs.update({'asset:'+a['id']:a['file'] for a in master.document['scenes'][0].get('production',{}).get('assets',[])})
    readers.extend(production_inputs)
    if set(sources)!=set(readers):fail('VERIFICATION_FAILED','mesh source membership differs')
    image_bytes=[0,0]
    for identity in readers:
        source=sources[identity];original=Path(production_inputs[identity] if identity in production_inputs else master.nodes[identity]['options']['file']).absolute()
        local=Path(source['retained']).resolve()
        if source['file']!=str(original) or local.parent!=directory.resolve():fail('VERIFICATION_FAILED','mesh source path differs',identity)
        if identity in image_inputs:
            from .image_assets import admit_file,digest_file
            for index,path in enumerate((original,local)):image_bytes[index]=admit_file(path,identity,image_bytes[index])
            digest=lambda path:digest_file(path,identity)
        else:digest=file_digest
        if digest(local)!=source['sha256'] or digest(original)!=source['sha256']:fail('INPUT_CHANGED','mesh source or retained copy changed',identity)
