"""Trusted QGIS worker. Run only with the configured native Python interpreter."""
import json
import math
import os
from pathlib import Path
import sys


def main(directory, stage):
    from qgis.core import (Qgis, QgsApplication, QgsCoordinateReferenceSystem, QgsCoordinateTransform,
        QgsFeature, QgsGeometry, QgsMapSettings, QgsMapRendererSequentialJob, QgsProject,
        QgsProviderRegistry, QgsRectangle, QgsUnitTypes, QgsVectorFileWriter, QgsVectorLayer, QgsWkbTypes)
    from qgis.PyQt.QtCore import QSize, QVariant
    from qgis.PyQt.QtGui import QColor
    app=QgsApplication([],False)
    app.initQgis()
    project=QgsProject.instance()
    plan=json.loads((directory/'plan.json').read_text())
    sources=json.loads((directory/'sources.json').read_text())
    def check(condition,message):
        if not condition:raise ValueError(message)
    def snapshot(layer):
        check(layer.isValid() and layer.crs().isValid(),'invalid vector layer or CRS')
        check(layer.crs().authid().startswith('EPSG:'),'only EPSG coordinate systems are supported')
        check(0<layer.featureCount()<=plan['limits']['features'],'empty or excessive feature count')
        names=[f.name() for f in layer.fields() if f.name()!='fid']
        rows=[];vertices=0
        bounds=[math.inf,math.inf,-math.inf,-math.inf]
        for f in layer.getFeatures():
            g=f.geometry()
            check(not g.isNull() and not g.isEmpty() and g.isGeosValid(),'null, empty or invalid geometry')
            check(not QgsWkbTypes.hasZ(g.wkbType()) and not QgsWkbTypes.hasM(g.wkbType()),'only 2D geometry is supported')
            for point in g.vertices():
                vertices+=1
                check(vertices<=plan['limits']['vertices'],'vertex budget exceeded')
                check(math.isfinite(point.x()) and math.isfinite(point.y()),'nonfinite geometry coordinate')
                bounds=[min(bounds[0],point.x()),min(bounds[1],point.y()),
                        max(bounds[2],point.x()),max(bounds[3],point.y())]
            attrs={}
            for name in names:
                value=f[name]
                if value is None or (isinstance(value,QVariant) and value.isNull()):value=None
                check(value is None or type(value)in (bool,int,float,str),'unsupported attribute type')
                check(not isinstance(value,float) or math.isfinite(value),'nonfinite attribute')
                attrs[name]=value
            rows.append({'geometry':bytes(g.asWkb()).hex(),'attributes':attrs,
                         'area':g.area(),'length':g.length()})
        rows.sort(key=lambda x:json.dumps(x,sort_keys=True))
        # Measure vertices: provider cached extents may be rounded in GPKG metadata.
        return {'crs':layer.crs().authid(),'count':len(rows),'fields':names,'features':rows,
                'bounds':bounds}
    def transform_layer(layer,operation,options):
        crs=layer.crs()
        transform=None
        if operation=='reproject':
            target=QgsCoordinateReferenceSystem(options['crs'])
            check(target.isValid(),'invalid target EPSG CRS')
            transform=QgsCoordinateTransform(crs,target,project)
            # No silently degraded grid transformations.
            transform.setBallparkTransformsAreAppropriate(False)
            transform.setAllowFallbackTransforms(False)
            crs=target
        if operation=='buffer':
            check(not crs.isGeographic() and crs.mapUnits()==QgsUnitTypes.DistanceMeters,
                  'buffer requires a projected CRS in metres; reproject explicitly first')
        if operation=='centroid':
            check(not crs.isGeographic(),'centroid requires a projected CRS; reproject explicitly first')
            check(layer.geometryType()==QgsWkbTypes.PolygonGeometry,
                  'centroid requires polygon or multipolygon features')
        features=[]
        for source in layer.getFeatures():
            geom=QgsGeometry(source.geometry())
            if operation=='reproject':
                check(geom.transform(transform)==0,'coordinate transformation failed')
            elif operation=='buffer':geom=geom.buffer(options['distance'],options['segments'])
            elif operation=='centroid':geom=geom.centroid()
            else:geom=geom.intersection(QgsGeometry.fromRect(QgsRectangle(*options['bounds'])))
            if geom.isEmpty():continue
            check(not geom.isNull() and geom.isGeosValid(),'operation produced invalid geometry')
            feature=QgsFeature(layer.fields());feature.setAttributes(source.attributes());feature.setGeometry(geom)
            features.append(feature)
        check(bool(features),'operation produced an empty output')
        kind=QgsWkbTypes.displayString(features[0].geometry().wkbType())
        check(all(f.geometry().wkbType()==features[0].geometry().wkbType() for f in features),'mixed output geometry types are unsupported')
        output=QgsVectorLayer(kind+'?crs='+crs.authid(),operation,'memory')
        provider=output.dataProvider();check(provider.addAttributes(list(layer.fields())),'cannot copy fields');output.updateFields()
        check(provider.addFeatures(features)[0],'cannot populate transformed features');output.updateExtents()
        return output
    if stage=='build':
        layers={}
        for node in plan['nodes']:
            op=node['filter'];options=node['options']
            if op=='readVector':
                path=str(directory/sources[node['id']]['retained'])
                details=QgsProviderRegistry.instance().querySublayers(path)
                check(len(details)==1,'input must contain exactly one vector layer')
                layer=QgsVectorLayer(path,node['id'],'ogr')
                # GeoPackage's storage id is not a semantic field in this contract.
            else:layer=transform_layer(layers[node['inputs']['input']],op,options)
            snapshot(layer)
            layers[node['id']]=layer
        layer=layers[plan['output']]
        measured=snapshot(layer)
        options=QgsVectorFileWriter.SaveVectorOptions()
        options.driverName='GPKG';options.layerName='result';options.fileEncoding='UTF-8'
        # Regenerate storage ids rather than letting a clipped/buffered source own them.
        options.attributes=[i for i,f in enumerate(layer.fields()) if f.name()!='fid']
        saved=QgsVectorFileWriter.writeAsVectorFormatV3(layer,str(directory/'result.gpkg'),project.transformContext(),options)
        check(saved[0]==QgsVectorFileWriter.NoError,'GeoPackage export failed: '+str(saved))
        reopened=QgsVectorLayer(str(directory/'result.gpkg')+'|layername=result','result','ogr')
        exported=snapshot(reopened)
        (directory/'export-comparison.json').write_text(json.dumps({'before':measured,'after':exported},indent=2))
        check(exported==measured,'GeoPackage export changed vector geometry or attributes')
        project.addMapLayer(reopened);project.setCrs(reopened.crs())
        project.setFileName(str(directory/'project.qgz'))
        check(project.write(),'project save failed')
        if plan['preview']:
            settings=QgsMapSettings();settings.setLayers([reopened]);settings.setDestinationCrs(reopened.crs())
            extent=reopened.extent()
            if extent.width()==0 or extent.height()==0:
                centre=extent.center();extent=QgsRectangle(centre.x()-1,centre.y()-1,centre.x()+1,centre.y()+1)
            extent.scale(1.1);settings.setExtent(extent);settings.setOutputSize(QSize(640,480));settings.setBackgroundColor(QColor('white'))
            job=QgsMapRendererSequentialJob(settings);job.start();job.waitForFinished()
            check(not job.errors(),'map rendering reported errors')
            check(job.renderedImage().save(str(directory/'preview.png')),'map image save failed')
        receipt={'snapshot':measured}
        if plan['preview']:
            viewport=settings.visibleExtent()
            receipt['previewSpatial']={'state':'known','frame':'CRS','crs':reopened.crs().authid(),
                'dimensions':2,'extentOrder':['xmin','ymin','xmax','ymax'],'extent':[viewport.xMinimum(),viewport.yMinimum(),viewport.xMaximum(),viewport.yMaximum()],
                'corners2D':[[viewport.xMinimum(),viewport.yMaximum()],[viewport.xMaximum(),viewport.yMaximum()],
                             [viewport.xMaximum(),viewport.yMinimum()],[viewport.xMinimum(),viewport.yMinimum()]],
                'pixelOrigin':'top-left','rowDirection':'down',
                'cornerOrder':['top-left','top-right','bottom-right','bottom-left'],
                'scope':'native map viewport; no Cartesian 3D transform asserted','units':'CRS-defined'}
    else:
        check(stage=='reopen','unknown native stage')
        check(project.read(str(directory/'project.qgz')),'native project reopen failed')
        layers=list(project.mapLayers().values());check(len(layers)==1,'project layer membership differs')
        receipt={'snapshot':snapshot(layers[0]),'projectReopened':True}
    receipt.update(stage=stage,pid=os.getpid(),plan=plan,runtime=Qgis.QGIS_VERSION)
    (directory/('built.json' if stage=='build' else 'reopened.json')).write_text(json.dumps(receipt,indent=2,allow_nan=False))
    # All provider objects must die before exitQgis; process teardown releases them.


if __name__=='__main__':
    directory=Path(sys.argv[1]);stage=sys.argv[2]
    try:main(directory,stage)
    except Exception as error:
        (directory/'native-fault.json').write_text(json.dumps({'code':'NATIVE_EXECUTION_FAILED','message':str(error)}))
        raise
