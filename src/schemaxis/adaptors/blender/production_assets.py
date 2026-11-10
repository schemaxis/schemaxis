"""Reusable self-contained scene assets; public input has no executable paths."""
import json
import struct
from schemaxis.core.declarations import validate_arguments
from schemaxis.schema import arguments_schema
from schemaxis.errors import fail
from .node_catalogue import vector,choice,boolean
from .production import NAME,array,record

ASSET=record({'id':NAME,'file':{**NAME,'maxLength':4096},'format':choice('glb',['glb','gltf','blend','stl','ply','obj','usd']),
 'sourceUnits':choice('metres',['metres','millimetres','centimetres','inches','feet']),
 'collection':{'type':'string','default':'','maxLength':128},'location':vector(),'rotation':vector(),'scale':vector((1,1,1)),
 'includeLights':boolean(),'scene':{'type':'string','default':'','maxLength':128},'viewLayer':{'type':'string','default':'','maxLength':128}},['id','file'])


def asset_schema_property():return arguments_schema({'assets':array(ASSET,128)})['properties']['assets']


def require_embedded_gltf(path,format):
    """Check dependencies before a native importer can dereference source URIs."""
    from pathlib import Path
    source=Path(path)
    try:
        if format=='glb':
            with source.open('rb') as stream:
                header=stream.read(20)
                if len(header)!=20:raise ValueError('truncated GLB header')
                magic,version,total,length,kind=struct.unpack('<5I',header)
                if magic!=0x46546c67 or version!=2 or total!=source.stat().st_size or kind!=0x4e4f534a or length>64*1024*1024 or length>total-20:
                    raise ValueError('invalid or unbounded GLB JSON chunk')
                document=json.loads(stream.read(length))
        else:
            if source.stat().st_size>64*1024*1024:raise ValueError('unbounded glTF JSON')
            document=json.loads(source.read_text())
        if not isinstance(document,dict) or document.get('asset',{}).get('version')!='2.0':raise ValueError('glTF2 required')
        resources=[*document.get('buffers',[]),*document.get('images',[])]
        if any(not isinstance(r,dict) or ('uri' in r and (not isinstance(r['uri'],str) or not r['uri'].startswith('data:'))) for r in resources):
            fail('UNSUPPORTED_ASSET_DEPENDENCY','glTF resources must be embedded before asset reuse',str(source))
        return document
    except (OSError,ValueError,TypeError,AttributeError,struct.error) as error:
        fail('INVALID_ASSET','invalid bounded self-contained glTF source',str(source),reason=str(error))


def validate_assets(raw,where):
    assets=validate_arguments({'assets':array(ASSET,128)},{'assets':raw},location=where)['assets']
    names=set()
    from schemaxis.pipeline import name
    for i,a in enumerate(assets):
        at=f'{where}.assets[{i}]';name(a['id'],at+'.id')
        if a['id'] in names:fail('DUPLICATE_ID','asset identities must be distinct',at+'.id')
        names.add(a['id'])
        if a['format'] in ('glb','gltf','usd') and a['sourceUnits']!='metres':fail('INVALID_ASSET','glTF and supported baked USD physical coordinates are metres',at+'.sourceUnits')
        if a['format']!='blend' and (a['scene'] or a['viewLayer']):fail('UNSUPPORTED_OPTION','scene and view-layer selectors require native blend assets',at)
        if min(a['scale'])<=0:fail('INVALID_TRANSFORM','asset scale must be positive',at+'.scale')
    return assets


def verify_selection(spec,selection):
    """Bind explicit selectors to observations; inferred names remain observable."""
    if spec['format']!='blend':
        if selection is not None:fail('VERIFICATION_FAILED','exchange asset has native scene selection',spec['id'])
        return
    if not isinstance(selection,dict) or selection.get('mode') not in ('scene','objectLibrary'):
        fail('VERIFICATION_FAILED','native asset selection is absent or invalid',spec['id'])
    for key in ('scene','viewLayer'):
        value=selection.get(key)
        if not isinstance(value,str) or (selection['mode']=='scene' and not value) or (selection['mode']=='objectLibrary' and value) or spec[key] and value!=spec[key]:
            fail('VERIFICATION_FAILED','native asset selection differs',spec['id']+'.'+key)
    if selection['mode']=='scene':
        import math
        fps=selection.get('sourceFps');frames=selection.get('sourceFrameRange')
        if type(fps) not in (int,float) or not math.isfinite(fps) or fps<=0 or not isinstance(frames,list) or len(frames)!=2 or any(type(f) is not int for f in frames) or frames[0]>frames[1]:
            fail('VERIFICATION_FAILED','native source timing metadata is invalid',spec['id'])
        for key in ('excluded','projections'):
            if not isinstance(selection.get(key),list):fail('VERIFICATION_FAILED','native source projection metadata is invalid',spec['id'])
