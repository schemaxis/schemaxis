"""Trusted native GDAL subprocess; authored documents cannot supply Python."""
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


def main():
    # Isolated environments may need their own PROJ/GDAL data directory.
    for key, folder in (('PROJ_DATA','proj'),('GDAL_DATA','gdal')):
        candidate=Path(sys.prefix)/'share'/folder
        if candidate.is_dir(): os.environ[key]=str(candidate)
    from osgeo import gdal
    gdal.UseExceptions()
    if gdal.VersionInfo('RELEASE_NAME')!='3.13.3': raise ValueError('UNSUPPORTED_GDAL_RUNTIME')
    stage=sys.argv[1];config=json.loads(bounded('native-config.json'))
    name='source.tif' if stage=='window' else 'raster.tif'
    Path(stage+'-inputs.json').write_text(json.dumps({p:hashlib.sha256(bounded(p)).hexdigest() for p in (name,'native-config.json','native-worker.py')},sort_keys=True))
    ds=gdal.OpenEx(name,gdal.OF_RASTER|gdal.OF_READONLY,allowed_drivers=['GTiff'])
    before=snapshot(ds,gdal)
    if stage=='window':
        result=gdal.Translate('raster.tif',ds,format='GTiff',srcWin=[config[k] for k in ('x','y','width','height')],width=config['outputWidth'],height=config['outputHeight'],resampleAlg='nearest',creationOptions=['COMPRESS=NONE','TILED=NO','BIGTIFF=NO'],errorIfWindowOutsideSource=True)
        result.GetRasterBand(1).SetUnitType(before['units'])
        result.Close()
    ds.Close()
    print(json.dumps({'runtime':gdal.VersionInfo('RELEASE_NAME'),'raster':before},sort_keys=True,allow_nan=False))


if __name__=='__main__':main()
