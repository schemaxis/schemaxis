"""Install only compiled included geometry properties in fresh trusted graphs."""
from pathlib import Path
from schemaxis.errors import fail
from .source_assets import descriptors,admit
from .step_source import read_bounded


def attach(directory,doc,prepared,sources):
    for name,item in descriptors(prepared).items():
        data=read_bounded(sources[item['id']]['retained'],item['id']);admit(data,item,item['id'])
        target=Path(directory)/item['member'];target.write_bytes(data)
        obj=doc.getObject(name);obj.addProperty('App::PropertyFileIncluded','SourceAsset','Schemaxis')
        obj.SourceAsset=str(target)


def observe(doc,prepared):
    for name,item in descriptors(prepared).items():
        obj=doc.getObject(name)
        if obj.getTypeIdOfProperty('SourceAsset')!='App::PropertyFileIncluded':
            fail('VERIFICATION_FAILED','Included source native property type differs',item['id'])
        admit(read_bounded(obj.SourceAsset,item['id']),item,item['id'])


def stage_copies(directory,path,part,index):
    """Stage admitted archive bytes before native extraction/copy can alias paths."""
    from .source_assets import copied_assets,verify_members
    assets=copied_assets(part,index)
    if not assets:return
    from .source_envelope import read_members
    from .document_xml import Document
    members=read_members(path,str(path),'VERIFICATION_FAILED')
    verify_members(members,Document(path).root,assets,str(path))
    for item in assets.values():
        (Path(directory)/item['copiedMember']).write_bytes(members[item['member']])


def attach_copies(directory,doc,part,index,mapping):
    """Assign staged originals, never the copied temporary FileIncluded path."""
    from .source_assets import copied_assets
    for name,item in copied_assets(part,index).items():
        obj=doc.getObject(mapping[name])
        if obj.getTypeIdOfProperty('SourceAsset')!='App::PropertyFileIncluded':
            fail('VERIFICATION_FAILED','Copied source asset property type differs',item['id'])
        target=Path(directory)/item['copiedMember']
        admit(read_bounded(target,item['id']),item,item['id'])
        # PropertyFileIncluded's (filePath,newFileName) API changes its retained
        # basename; plain path assignment preserves the old copied basename.
        obj.SourceAsset=(str(target),item['copiedMember'])
