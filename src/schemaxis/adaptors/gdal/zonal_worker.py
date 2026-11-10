"""Trusted native GDAL zonal-stats subprocess; authored documents cannot supply Python or native flags."""
import hashlib
import json
import os
from pathlib import Path
import resource
import stat
import struct
import sys

resource.setrlimit(resource.RLIMIT_AS,(2*1024**3,2*1024**3))
resource.setrlimit(resource.RLIMIT_FSIZE,(16*1024**2,16*1024**2))
resource.setrlimit(resource.RLIMIT_CPU,(60,60))
STATS=['count','min','max','sum','mean']


def bounded(name):
    fd=os.open(name,os.O_RDONLY|os.O_NONBLOCK|os.O_NOFOLLOW)
    with os.fdopen(fd,'rb') as stream:
        info=os.fstat(stream.fileno())
        if not stat.S_ISREG(info.st_mode) or info.st_size>8*1024**2: raise ValueError('RASTER_FILE_LIMIT')
        data=stream.read(8*1024**2+1)
    if len(data)>8*1024**2: raise ValueError('RASTER_FILE_LIMIT')
    return data


def snapshot(ds,gdal):
    w,h=ds.RasterXSize,ds.RasterYSize
    if ds.RasterCount!=1 or w*h>262144: raise ValueError('RASTER_SHAPE')
    band=ds.GetRasterBand(1);dtype=gdal.GetDataTypeName(band.DataType)
    fmt={'UInt16':'H','Int16':'h','Float32':'f'}[dtype]
    crs=ds.GetSpatialRef()
    return {'width':w,'height':h,'dtype':dtype,'epsg':int(crs.GetAuthorityCode(None)),'geotransform':list(ds.GetGeoTransform()),'pixelInterpretation': 'area' if ds.GetMetadataItem('AREA_OR_POINT')=='Area' else 'point','band':1,'units':band.GetUnitType(),'nodata':band.GetNoDataValue(),'pixels':list(struct.unpack('='+str(w*h)+fmt,band.ReadRaster()))}


def vector_view(path,gdal):
    """Fresh OGR reading of a GeoJSON file: properties by field, geometry as exterior ring coordinates."""
    ds=gdal.OpenEx(path,gdal.OF_VECTOR|gdal.OF_READONLY,allowed_drivers=['GeoJSON'])
    layer=ds.GetLayer(0);names=[layer.GetLayerDefn().GetFieldDefn(i).GetName() for i in range(layer.GetLayerDefn().GetFieldCount())]
    rows=[]
    for feature in layer:
        geometry=feature.GetGeometryRef()
        ring=[list(geometry.GetGeometryRef(0).GetPoint_2D(i)) for i in range(geometry.GetGeometryRef(0).GetPointCount())] if geometry is not None else None
        rows.append({'properties':{n:(feature.GetField(n) if feature.IsFieldSetAndNotNull(n) else None) for n in names},'ring':ring})
    ds.Close()
    return {'fields':names,'features':rows}


def main():
    for key, folder in (('PROJ_DATA','proj'),('GDAL_DATA','gdal')):
        candidate=Path(sys.prefix)/'share'/folder
        if candidate.is_dir(): os.environ[key]=str(candidate)
    from osgeo import gdal
    gdal.UseExceptions()
    if gdal.VersionInfo('RELEASE_NAME')!='3.13.3': raise ValueError('UNSUPPORTED_GDAL_RUNTIME')
    stage=sys.argv[1]
    bounded('native-config.json')
    consumed=('source.tif','zones.geojson','native-config.json','zonal_worker.py') if stage=='zonal' else ('summary.geojson','zones.geojson','native-config.json','zonal_worker.py')
    Path(stage+'-inputs.json').write_text(json.dumps({p:hashlib.sha256(bounded(p)).hexdigest() for p in consumed},sort_keys=True))
    if stage=='zonal':
        ds=gdal.OpenEx('source.tif',gdal.OF_RASTER|gdal.OF_READONLY,allowed_drivers=['GTiff'])
        before=snapshot(ds,gdal)
        ds.Close()
        gdal.Run('raster','zonal-stats',input='source.tif',zones='zones.geojson',stat=STATS,pixels='default',include_field=['zone'],output='summary.geojson',output_format='GeoJSON')
        print(json.dumps({'runtime':gdal.VersionInfo('RELEASE_NAME'),'algorithm':'raster zonal-stats','raster':before},sort_keys=True,allow_nan=False))
    elif stage=='zonal-readback':
        print(json.dumps({'runtime':gdal.VersionInfo('RELEASE_NAME'),'summary':vector_view('summary.geojson',gdal),'zones':vector_view('zones.geojson',gdal)},sort_keys=True,allow_nan=False))
    else: raise ValueError('unknown stage')


if __name__=='__main__':main()
