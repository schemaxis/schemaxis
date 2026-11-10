"""Checked frozen CAD solid inputs shared by drawing and analysis workflows.

The host extracts an explicitly selected stored BREP from FCStd without restoring
its project, scripts or feature proxies. Geometry is measured in its stored shape
frame; assembly parent transforms and App::Link instances are not reconstructed.
"""
import hashlib
import math
from pathlib import Path
from zipfile import ZipFile
from schemaxis.errors import fail, keys
from schemaxis.core.faults import SchemaxisError
from .document_xml import Document, read_member

def number(value, location, low=-100000, high=100000, *, code='INVALID_CAD_SOURCE'):
    if type(value) not in (int,float) or not math.isfinite(value) or not low <= value <= high:
        fail(code, 'Provide a finite number within the declared bounds', location)
    return value


def vector(value, count, location, *, code='INVALID_CAD_SOURCE'):
    if not isinstance(value,list) or len(value)!=count:
        fail(code,'Wrong coordinate count',location)
    return [number(x,location,code=code) for x in value]


def text(value,location,limit=200, *, code='INVALID_CAD_SOURCE'):
    if not isinstance(value,str) or not value.strip() or len(value)>limit or any(ord(x)<32 for x in value):
        fail(code,'Provide nonempty printable text within the length limit',location)
    return value


def digest(data): return hashlib.sha256(data).hexdigest()


def source_record(source, *, captured=None, unread=False):
    keys(source,('file','object','units','expect'),'$.source')
    file=source.get('file')
    if not isinstance(file,str) or not file or len(file)>4096:
        fail('INVALID_CAD_SOURCE','source.file must name STEP or FCStd geometry','$.source.file')
    path=Path(file).absolute()
    if source.get('units') not in ('mm','cm','m','inch'):
        fail('UNSUPPORTED_UNITS','Assert source length unit: mm, cm, m or inch; expected geometry is always mm','$.source.units')
    expect=source.get('expect');keys(expect,('volume','bounds','centreOfMass'),'$.source.expect')
    volume=number(expect.get('volume'),'$.source.expect.volume',1e-9,1e18)
    bounds=vector(expect.get('bounds'),6,'$.source.expect.bounds')
    centre=vector(expect.get('centreOfMass'),3,'$.source.expect.centreOfMass')
    if any(bounds[i]>=bounds[i+1] for i in (0,2,4)):
        fail('INVALID_CAD_SOURCE','Expected solid bounds must increase on each axis','$.source.expect.bounds')
    if unread:return {'file':str(path),'volume':volume,'bounds':bounds,'centreOfMass':centre,'units':'mm'}
    actual=Path(captured) if captured else path
    if actual.is_symlink() or not actual.is_file():
        fail('RESOURCE_NOT_FOUND','Provide a regular CAD source file',str(actual))
    if actual.stat().st_size>64*1024*1024:fail('RESOURCE_LIMIT','CAD source exceeds the64MiB input limit',str(actual))
    data=actual.read_bytes();kind=path.suffix.lower()
    result={'file':str(path),'sha256':digest(data),'bytes':len(data),'volume':volume,'bounds':bounds,'centreOfMass':centre,'units':'mm','sourceUnits':source['units']}
    if kind in ('.step','.stp'):
        if 'object' in source:fail('INVALID_CAD_SOURCE','STEP source contains one solid; omit object','$.source.object')
        from .step_source import admit
        facts=admit(data,str(path))
        if facts['unit']!=source['units']:fail('UNIT_MISMATCH','STEP assigns a different length unit than declared',str(path))
        result.update(format='STEP',capture='source.step')
    elif kind=='.fcstd':
        if source['units']!='mm':fail('UNIT_MISMATCH','FCStd native geometry is always in mm',str(path))
        object_name=source.get('object')
        if not isinstance(object_name,str) or not object_name.strip() or any(ord(x)<32 for x in object_name) or len(object_name)>128:
            fail('INVALID_CAD_SOURCE','FCStd source needs an explicit internal shape object name','$.source.object')
        from .assembly_sources import check_archive
        check_archive(actual,str(path))
        try:
            saved=Document(actual)
            matches=[n for n in saved.types if n==object_name or saved.string(n,'Label')==object_name]
            if len(matches)!=1:raise ValueError('source object name/label is absent or ambiguous')
            selector=object_name;object_name=matches[0]
            container=saved.properties[object_name]['Shape']
            if container.get('type')!='Part::PropertyPartShape' or len(container.findall('Part'))!=1:raise ValueError('not one typed native shape')
            prop=container.find('Part')
            member=prop.get('file')
            if not member or '/' in member or '\\' in member:raise ValueError('invalid shape payload name')
            with ZipFile(actual) as archive:brep=read_member(archive,member,32*1024*1024)
            if not brep.startswith((b'\nCASCADE Topology',b'CASCADE Topology')):raise ValueError('not a textual OCCT BREP')
        except Exception as error:
            if isinstance(error,SchemaxisError):raise
            fail('UNSUPPORTED_SOURCE','Named FCStd object has no readable bounded BREP shape',str(path),detail=str(error))
        result.update(format='FCStd',capture='source.FCStd',object=object_name,selector=selector,member=member,brepSha256=digest(brep))
    else:fail('UNSUPPORTED_SOURCE','CAD input must be plain STEP or geometry extracted from FCStd',str(path))
    return result



def capture_source(record,directory):
    """Capture exactly planned bytes and selected BREP before native execution."""
    directory=Path(directory);data=Path(record['file']).read_bytes()
    if digest(data)!=record['sha256']:fail('INPUT_CHANGED','CAD source changed after planning',record['file'])
    (directory/record['capture']).write_bytes(data)
    if record['format']=='FCStd':
        with ZipFile(directory/record['capture']) as archive:brep=read_member(archive,record['member'],32*1024*1024)
        if digest(brep)!=record['brepSha256']:fail('INPUT_CHANGED','Selected CAD shape changed after planning',record['file'])
        (directory/'source.brep').write_bytes(brep)
    return directory/('source.brep' if record['format']=='FCStd' else 'source.step')
